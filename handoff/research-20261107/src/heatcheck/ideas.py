"""Idea family: templated, strictly validated hypotheses tested on development data (docs/IDEA_GRAMMAR.md).

Pure parts (validation, views, statistics, Holm, verdicts) have no file or network side effects.
`run_family` is the only function that writes files: registration.json (write-once, before computing) and
results.json (write-once). Survivors are CANDIDATE, never SURVIVED_PROTOCOL. No code path here reads the sealed
2024-25 season or the custodian ledger.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import kernels as K
from .util import canonical_json, sha256_bytes, utc_now_iso

FORMAT = "heatcheck-idea-family/1"
MAX_IDEAS = 20
B = 999
ALPHA = 0.05
MIN_GAMES_EACH = 30
MIN_SHOTS_EACH = 200
ALTERNATIVES = ("two_sided", "greater", "less")

GAME_LEVELS = {
    "home_rest_days": ("0", "1", "2", "3+"),
    "away_rest_days": ("0", "1", "2", "3+"),
    "rest_advantage": ("home_more", "equal", "away_more"),
    "home_back_to_back": ("yes",),
    "away_back_to_back": ("yes",),
    "elo_gap": ("home_fav_100+", "home_fav_0_100", "away_fav_0_100", "away_fav_100+"),
    "month": ("10", "11", "12", "01", "02", "03"),
    "day_of_week": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
SHOT_LEVELS = {
    "after_makes": ("1", "2", "3", "4"),
    "after_misses": ("1", "2", "3", "4"),
    "shot_value": ("3",),
    "period": ("1", "2", "3", "4", "OT"),
}
TEMPLATES = {
    "GAME_HOME_WIN_SPLIT": ("feature", GAME_LEVELS),
    "SHOT_MAKE_AFTER_CONDITION": ("condition", SHOT_LEVELS),
}
MODES = ("development", "synthetic")


class IdeaRefused(ValueError):
    pass


@dataclass(frozen=True)
class Idea:
    template: str
    params: tuple  # sorted (key, value) pairs

    @property
    def p(self) -> dict:
        return dict(self.params)

    def canonical(self) -> dict:
        return {"params": self.p, "template": self.template}

    @property
    def idea_hash(self) -> str:
        return sha256_bytes(canonical_json(self.canonical()))

    @property
    def seed(self) -> int:
        return int(self.idea_hash[:8], 16)


# --------------------------------------------------------------------------- validation
def _strict_loads(text: str):
    def no_dupes(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise IdeaRefused(f"duplicate JSON keys: {sorted(k for k in keys if keys.count(k) > 1)}")
        return dict(pairs)

    def no_nan(tok):
        raise IdeaRefused(f"non-finite number {tok!r} not allowed")
    try:
        return json.loads(text, object_pairs_hook=no_dupes, parse_constant=no_nan)
    except json.JSONDecodeError as e:
        raise IdeaRefused(f"invalid JSON: {e}") from None


def _exact_keys(obj, keys: set, what: str):
    if not isinstance(obj, dict):
        raise IdeaRefused(f"{what} must be an object")
    if set(obj) != keys:
        raise IdeaRefused(f"{what} must have exactly the keys {sorted(keys)}; got {sorted(obj)}")


def _enum(value, allowed, what: str) -> str:
    if type(value) is not str or value not in allowed:
        raise IdeaRefused(f"{what} must be one of {list(allowed)}; got {value!r}")
    return value


def validate_request(obj, mode: str) -> list[Idea]:
    """Validate a whole request. `obj` is the parsed object or the raw JSON text. Refuses on any defect."""
    if mode not in MODES:
        raise IdeaRefused(f"mode must be one of {MODES}")
    if isinstance(obj, (str, bytes)):
        obj = _strict_loads(obj.decode() if isinstance(obj, bytes) else obj)
    _exact_keys(obj, {"format", "ideas"}, "request")
    if obj["format"] != FORMAT:
        raise IdeaRefused(f"format must be {FORMAT!r}")
    ideas_in = obj["ideas"]
    if not isinstance(ideas_in, list) or not 1 <= len(ideas_in) <= MAX_IDEAS:
        raise IdeaRefused(f"ideas must be a list of 1 to {MAX_IDEAS} ideas")
    out, seen = [], set()
    for i, it in enumerate(ideas_in):
        _exact_keys(it, {"template", "params"}, f"idea {i}")
        tpl = _enum(it["template"], tuple(TEMPLATES), f"idea {i} template")
        if mode == "synthetic" and tpl != "SHOT_MAKE_AFTER_CONDITION":
            raise IdeaRefused(f"idea {i}: {tpl} is not available in synthetic mode (no games in the simulator)")
        key, levels = TEMPLATES[tpl]
        _exact_keys(it["params"], {key, "level", "alternative"}, f"idea {i} params")
        k = _enum(it["params"][key], tuple(levels), f"idea {i} {key}")
        lv = _enum(it["params"]["level"], levels[k], f"idea {i} level for {key}={k}")
        alt = _enum(it["params"]["alternative"], ALTERNATIVES, f"idea {i} alternative")
        idea = Idea(tpl, tuple(sorted({key: k, "level": lv, "alternative": alt}.items())))
        if mode == "synthetic" and k == "period" and lv == "OT":
            raise IdeaRefused(f"idea {i}: synthetic leagues have no overtime period")
        if idea.idea_hash in seen:
            raise IdeaRefused(f"idea {i} duplicates an earlier idea")
        seen.add(idea.idea_hash)
        out.append(idea)
    return out


# --------------------------------------------------------------------------- views (no truth)
@dataclass(frozen=True)
class GameView:
    """One row per eligible development game: home_win plus pre-game features. No other outcome."""
    frame: pd.DataFrame  # game_id, home_win, home_rest, away_rest, home_b2b, away_b2b, elo_diff, game_date_et

    def identity(self) -> str:
        cols = ["game_id", "home_win", "home_rest", "away_rest", "home_b2b", "away_b2b", "elo_diff", "game_date_et"]
        f = self.frame[cols].sort_values("game_id")
        return sha256_bytes(f.to_csv(index=False, lineterminator="\n", float_format="%.12g").encode())


@dataclass(frozen=True)
class ShotView:
    """Eligible field-goal attempts ordered within player-game. period 5 means any overtime."""
    made: np.ndarray    # int8
    group: np.ndarray   # player-game id (contiguous blocks)
    value: np.ndarray   # 2 or 3
    period: np.ndarray  # 1..4, 5 = OT

    def identity(self) -> str:
        h = hashlib.sha256()
        for a in (self.made, self.group, self.value, self.period):
            h.update(np.ascontiguousarray(a, dtype=np.int64).tobytes())
        return h.hexdigest()


# --------------------------------------------------------------------------- statistics
def _game_group(view: GameView, feature: str, level: str) -> np.ndarray:
    f = view.frame
    if feature in ("home_rest_days", "away_rest_days"):
        r = (f.home_rest if feature == "home_rest_days" else f.away_rest).to_numpy()
        return (r >= 3) if level == "3+" else (r == int(level))
    if feature == "rest_advantage":
        d = (f.home_rest - f.away_rest).to_numpy()
        return {"home_more": d > 0, "equal": d == 0, "away_more": d < 0}[level]
    if feature == "home_back_to_back":
        return f.home_b2b.to_numpy() == 1
    if feature == "away_back_to_back":
        return f.away_b2b.to_numpy() == 1
    if feature == "elo_gap":
        e = f.elo_diff.to_numpy(float)
        return {"home_fav_100+": e >= 100, "home_fav_0_100": (e >= 0) & (e < 100),
                "away_fav_0_100": (e >= -100) & (e < 0), "away_fav_100+": e < -100}[level]
    d = pd.to_datetime(f.game_date_et)
    if feature == "month":
        return (d.dt.month == int(level)).to_numpy()
    if feature == "day_of_week":
        return (d.dt.day_name().str[:3] == level).to_numpy()
    raise IdeaRefused(f"unknown feature {feature}")


def _diff(y: np.ndarray, g: np.ndarray) -> float | None:
    a, b = y[g], y[~g]
    if len(a) == 0 or len(b) == 0:
        return None
    return float(a.mean() - b.mean())


def streak_condition(made: np.ndarray, group: np.ndarray, k: int, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """(condition, eligible): eligible = at least k earlier FGA in the same player-game; condition = those k
    were all made (kind 'makes') or all missed (kind 'misses'). Only strictly earlier shots are used."""
    made = np.asarray(made, dtype=np.int8); group = np.asarray(group); n = len(made)
    elig = np.ones(n, dtype=bool); allv = np.ones(n, dtype=bool)
    want = 1 if kind == "makes" else 0
    for j in range(1, k + 1):
        prev = np.full(n, -1, dtype=np.int8); prev[j:] = made[:-j]
        same = np.zeros(n, dtype=bool); same[j:] = group[j:] == group[:-j]
        elig &= same; allv &= prev == want
    return allv & elig, elig


def _shot_stat(view_made, view: ShotView, condition: str, level: str):
    if condition in ("after_makes", "after_misses"):
        cond, elig = streak_condition(view_made, view.group, int(level), "makes" if condition == "after_makes" else "misses")
    elif condition == "shot_value":
        cond, elig = view.value == 3, np.ones(len(view_made), dtype=bool)
    else:
        cond, elig = view.period == (5 if level == "OT" else int(level)), np.ones(len(view_made), dtype=bool)
    y = np.asarray(view_made, dtype=float)
    t = _diff(y[elig], cond[elig])
    return t, int((cond & elig).sum()), int((~cond & elig).sum()), (y[cond & elig].mean() if (cond & elig).any() else None), \
        (y[~cond & elig].mean() if (~cond & elig).any() else None)


def _strata(view: ShotView, condition: str) -> np.ndarray:
    if condition == "shot_value":
        return np.asarray(view.group)
    return np.asarray(view.group) * 2 + (np.asarray(view.value) == 3)


def p_value(t: float, null: np.ndarray, alternative: str) -> float:
    null = np.asarray(null, float)
    if alternative == "greater":
        return (1 + int(np.sum(null >= t - 1e-15))) / (len(null) + 1)
    if alternative == "less":
        return (1 + int(np.sum(null <= t + 1e-15))) / (len(null) + 1)
    c = float(null.mean())
    return (1 + int(np.sum(np.abs(null - c) >= abs(t - c) - 1e-15))) / (len(null) + 1)


def run_idea(idea: Idea, view, n_perm: int = B) -> dict:
    p = idea.p
    rng = np.random.default_rng(idea.seed)
    if idea.template == "GAME_HOME_WIN_SPLIT":
        if not isinstance(view, GameView):
            raise IdeaRefused("GAME idea needs a GameView")
        g = _game_group(view, p["feature"], p["level"])
        y = view.frame.home_win.to_numpy(float)
        n_c, n_r = int(g.sum()), int((~g).sum())
        base = {"n_condition": n_c, "n_rest": n_r,
                "rate_condition": float(y[g].mean()) if n_c else None,
                "rate_rest": float(y[~g].mean()) if n_r else None}
        if min(n_c, n_r) < MIN_GAMES_EACH:
            return {**base, "status": "INSUFFICIENT", "T": None, "null_mean": None, "p_raw": None}
        t = _diff(y, g)
        null = np.array([_diff(rng.permutation(y), g) for _ in range(n_perm)])
    else:
        if not isinstance(view, ShotView):
            raise IdeaRefused("SHOT idea needs a ShotView")
        t, n_c, n_r, rc, rr = _shot_stat(view.made, view, p["condition"], p["level"])
        base = {"n_condition": n_c, "n_rest": n_r, "rate_condition": None if rc is None else float(rc),
                "rate_rest": None if rr is None else float(rr)}
        if t is None or min(n_c, n_r) < MIN_SHOTS_EACH:
            return {**base, "status": "INSUFFICIENT", "T": t, "null_mean": None, "p_raw": None}
        strata = _strata(view, p["condition"])
        vals = []
        for _ in range(n_perm):
            tt = _shot_stat(K.permute_within(view.made, strata, rng), view, p["condition"], p["level"])[0]
            if tt is not None:
                vals.append(tt)
        null = np.array(vals)
    return {**base, "status": "EXECUTED", "T": t, "null_mean": float(null.mean()),
            "B_effective": int(len(null)), "p_raw": p_value(t, null, p["alternative"])}


def holm_verdicts(rows: list[dict]) -> list[dict]:
    """Holm across ALL ideas; an idea without a p-value enters as p = 1."""
    ps = [r["p_raw"] if r["p_raw"] is not None else 1.0 for r in rows]
    adj = K.holm(ps)
    out = []
    for r, pa in zip(rows, adj):
        if r["status"] != "EXECUTED":
            v = "INSUFFICIENT_EVIDENCE"
        elif pa < ALPHA:
            v = "CANDIDATE"
        else:
            v = "NOT_A_CANDIDATE"
        out.append({**r, "p_holm": pa if r["status"] == "EXECUTED" else None, "verdict": v})
    assert all(o["verdict"] != "SURVIVED_PROTOCOL" for o in out)
    return out


# --------------------------------------------------------------------------- family (the only file writes)
def _write_once(path: Path, text: str) -> None:
    with open(path, "x", newline="\n") as f:
        f.write(text)


def run_family(ideas: list[Idea], views: dict, out_dir: Path, *, mode: str, data_identity: dict, code_hash: str,
               n_perm: int = B) -> dict:
    """Register and freeze (registration.json) BEFORE computing, re-verify, run, Holm, write results.json.
    `views` maps template name -> GameView / ShotView."""
    missing = sorted({i.template for i in ideas} - set(views))
    if missing:
        raise IdeaRefused(f"no data view for {missing}")
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    reg = {"format": FORMAT, "mode": mode, "label": "EXPLORATORY",
           "ideas": [{"idea_hash": i.idea_hash, **i.canonical()} for i in ideas],
           "n_ideas": len(ideas), "alpha": ALPHA, "B": n_perm, "multiplicity": f"Holm across all {len(ideas)} ideas",
           "seed_rule": "int(idea_hash[:8], 16)", "data_identity": data_identity, "code_hash": code_hash,
           "data_scope": ("2023-24 development games only; spent 2023-24 final games and the sealed 2024-25 season "
                          "are never read") if mode == "development" else
                         "synthetic planted-truth league; truth withheld from the proposer and the tests",
           "created_utc": utc_now_iso()}
    reg_text = json.dumps(reg, indent=2, sort_keys=True) + "\n"
    _write_once(out_dir / "registration.json", reg_text)
    reg_hash = sha256_bytes(reg_text.encode())
    # re-read: compute only what was frozen
    frozen = (out_dir / "registration.json").read_bytes()
    if sha256_bytes(frozen) != reg_hash:
        raise IdeaRefused("registration.json changed between freezing and computing")
    frozen_ideas = json.loads(frozen)["ideas"]
    if [f["idea_hash"] for f in frozen_ideas] != [i.idea_hash for i in ideas]:
        raise IdeaRefused("registered ideas differ from the ideas to run")
    rows = []
    for i in ideas:
        rows.append({"idea_hash": i.idea_hash, "template": i.template, "params": i.p,
                     **run_idea(i, views[i.template], n_perm)})
    rows = holm_verdicts(rows)
    res = {"format": FORMAT, "mode": mode, "label": "EXPLORATORY", "registration_hash": reg_hash,
           "n_ideas": len(ideas), "alpha": ALPHA, "B": n_perm, "data_scope": reg["data_scope"],
           "results": rows,
           "verdict_meaning": "CANDIDATE = exploratory finding on development data after Holm; not SURVIVED_PROTOCOL. "
                              "It needs its own pre-registration and a sealed confirmatory test.",
           "created_utc": utc_now_iso()}
    _write_once(out_dir / "results.json", json.dumps(res, indent=2, default=float) + "\n")
    return res


# --------------------------------------------------------------------------- synthetic scoring (runner side)
def truth_for(idea: Idea, gamma_logodds: float) -> tuple[str, str | None]:
    """(EFFECT|NULL, direction) for a SHOT idea in a simulate.generate league (docs/IDEA_GRAMMAR.md §5)."""
    c = idea.p["condition"]
    if c == "period":
        return "NULL", None
    if c == "shot_value":
        return "EFFECT", "less"
    if gamma_logodds == 0:
        return "NULL", None
    up = "greater" if gamma_logodds > 0 else "less"
    return ("EFFECT", up) if c == "after_makes" else ("EFFECT", "less" if up == "greater" else "greater")


def scoreboard(results: dict, ideas: list[Idea], gamma_logodds: float) -> dict:
    rows, tally = [], {"planted_effects_found": 0, "planted_effects_missed": 0, "nulls_correctly_not_flagged": 0,
                       "false_candidates": 0}
    by_hash = {i.idea_hash: i for i in ideas}
    for r in results["results"]:
        idea = by_hash[r["idea_hash"]]
        truth, direction = truth_for(idea, gamma_logodds)
        cand = r["verdict"] == "CANDIDATE"
        observed = None if r["T"] is None else ("greater" if r["T"] > r["null_mean"] else "less") if r["null_mean"] is not None else None
        right_dir = cand and direction is not None and (
            idea.p["alternative"] == direction or (idea.p["alternative"] == "two_sided" and observed == direction))
        if truth == "EFFECT":
            outcome = "FOUND" if right_dir else ("FALSE_CANDIDATE_WRONG_DIRECTION" if cand else "MISSED")
        else:
            outcome = "FALSE_CANDIDATE" if cand else "CORRECTLY_NOT_FLAGGED"
        key = {"FOUND": "planted_effects_found", "MISSED": "planted_effects_missed",
               "CORRECTLY_NOT_FLAGGED": "nulls_correctly_not_flagged"}.get(outcome, "false_candidates")
        tally[key] += 1
        rows.append({"idea_hash": r["idea_hash"], "params": r["params"], "truth": truth, "true_direction": direction,
                     "verdict": r["verdict"], "p_holm": r["p_holm"], "outcome": outcome})
    return {"tally": tally, "per_idea": rows}
