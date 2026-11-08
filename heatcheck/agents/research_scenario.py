"""Adapter from Research's scenario functions (research/scenario-effects) to Max's EffectsProvider.

Research's code: handoff/research-20261107/src/heatcheck/scenario.py, loaded by file path under the
name ``research_scenario`` (its package is also called ``heatcheck``). Tables:
data/scenario/player_absence_effects.json and data/scenario/schedule_effects.json, re-read when the
files change, so pulling Research's updated tables (e.g. with shrinkage) needs no code change.

Every number comes from Research's ``scenario_probability`` with one change against the game's
forecast baseline. Its log-odds result converts exactly to the forecast's Elo units
(Elo = log-odds x 400 / ln 10), so Max's what-if arithmetic and Research's combiner agree.

What is shown by default:
- the estimate Research's combiner uses (``effect_log_odds``: the shrunk estimate once Research
  adds shrinkage). Any raw value Research supplies goes only to ``evidence`` (the evidence drawer);
- players are hidden when Research flags them "not shown by default", when they are
  low-involvement (Research: "their estimates should not be used"), when they have no name, or when
  they missed fewer than 5 games (the combiner refuses those).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_CODE = ROOT / "handoff" / "research-20261107" / "src" / "heatcheck" / "scenario.py"
ABSENCE = ROOT / "data" / "scenario" / "player_absence_effects.json"
SCHEDULE = ROOT / "data" / "scenario" / "schedule_effects.json"
ELO_PER_LOGIT = 400.0 / math.log(10.0)
LEVEL = 0.95
MIN_MISSED = 5
PLAYERS_PER_TEAM = 2
LOW_INVOLVEMENT = "low_involvement_outcome_dependent_appearance"
FLAG_TEXT = {
    "absences_mix_rest_injury_suspension_and_coach_decisions":
        "absences mix rest, injury, suspension, illness and coach decisions",
    "elo_partly_absorbs_long_absences": "Elo partly absorbs long absences, shrinking the estimate toward zero",
    "team_change_in_window": "he played for more than one team in a season; the estimate mixes contexts",
    "small_n": "fewer than 5 games missed; the interval is wide and unstable",
    LOW_INVOLVEMENT: "low involvement: appearances depend on the score, so the estimate is biased",
}
REST_WORDS = {"back_to_back": re.compile(r"back[- ]to[- ]back|\bb2b\b", re.I),
              "three_in_four": re.compile(r"3[- ]in[- ]4|three[- ]in[- ]four|third game in four", re.I)}


def _load_research():
    if "research_scenario" in sys.modules:
        return sys.modules["research_scenario"]
    spec = importlib.util.spec_from_file_location("research_scenario", RESEARCH_CODE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["research_scenario"] = mod
    spec.loader.exec_module(mod)
    return mod


def shown_by_default(row: dict) -> tuple[bool, str]:
    flags = [str(f) for f in row.get("flags") or []]
    if row.get("shown_by_default") is False or any("not_shown_by_default" in f or "not shown by default" in f
                                                    for f in flags):
        return False, "Research marks this estimate not shown by default"
    if LOW_INVOLVEMENT in flags:
        return False, FLAG_TEXT[LOW_INVOLVEMENT]
    if not row.get("player_name"):
        return False, "no player name in the data"
    if int(row.get("n_games_missed") or 0) < MIN_MISSED:
        return False, f"only {row.get('n_games_missed')} games missed (under {MIN_MISSED})"
    return True, ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower().replace(".", " ")).split()


def name_matches(typed: str, data_name: str) -> bool:
    """'Jarrett Allen' or 'Allen' matches Research's 'J. Allen' (first initial + last name)."""
    t, d = _norm(typed), _norm(data_name)
    if not t or not d or t[-1] != d[-1]:
        return False
    return len(t) == 1 or len(d) == 1 or t[0][0] == d[0][0]


class ResearchScenario:
    """EffectsProvider over Research's tables and combiner."""

    def __init__(self, absence_path: Path = ABSENCE, schedule_path: Path = SCHEDULE):
        self.absence_path, self.schedule_path = absence_path, schedule_path
        self._cache_key = None
        self.mod = _load_research()
        self._load()

    # tables: re-read when Research pushes new ones
    def _load(self):
        key = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in (self.absence_path, self.schedule_path))
        if key == self._cache_key:
            return
        ab, sc = self.absence_path.read_bytes(), self.schedule_path.read_bytes()
        self.absence_doc, self.schedule_doc = json.loads(ab), json.loads(sc)
        self.absence = self.absence_doc["effects"]
        self.schedule = self.schedule_doc["effects"]
        self.tables_sha256 = {"absence": hashlib.sha256(ab).hexdigest(), "schedule": hashlib.sha256(sc).hexdigest()}
        code_sha = hashlib.sha256(RESEARCH_CODE.read_bytes()).hexdigest()
        self.identity = {"name": "research-scenario-effects", "version": self.absence_doc.get("format", "?"),
                         "code_sha256": code_sha, "tables_sha256": self.tables_sha256,
                         "tables_created_utc": [self.absence_doc.get("created_utc"),
                                                self.schedule_doc.get("created_utc")]}
        self._cache_key = key

    def points_to_elo(self) -> float | None:
        return None  # Research has not supplied one

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _side(game: dict, team: str | None) -> str | None:
        if team == game["home_team"]:
            return "home"
        if team == game["away_team"]:
            return "away"
        return None

    def _combine(self, game: dict, change: dict) -> dict:
        return self.mod.scenario_probability(float(game["p_home_win"]), game["home_team_id"], game["away_team_id"],
                                             [change], self.absence, self.schedule)

    def _result(self, game: dict, side: str, rc: dict, n: int, n_unit: str, verdict: str, caveats: list[str],
                evidence: dict, method: str) -> dict:
        logit = lambda p: math.log(p / (1 - p))  # noqa: E731
        b = logit(rc["baseline_p_home"])
        sgn = 1.0 if side == "home" else -1.0  # Elo shift for the changed team
        shift = (logit(rc["scenario_p_home"]) - b) * ELO_PER_LOGIT * sgn
        lo, hi = ((logit(x) - b) * ELO_PER_LOGIT * sgn for x in rc["ci95"])
        return {"status": "ESTIMATE", "elo_shift": shift, "elo_shift_range": sorted([lo, hi]), "level": LEVEL,
                "interval": "95% (Research's bootstrap, normal approximation)", "n": int(n), "n_unit": n_unit,
                "verdict": verdict, "caveats": caveats,
                "method": method, "evidence": evidence, "research_result": rc}

    # ------------------------------------------------------------------ EffectsProvider
    def estimate(self, change: dict, ctx: dict) -> dict:
        self._load()
        game = ctx["game"]
        if change["kind"] == "REST":
            side = self._side(game, change.get("team"))
            eff = next((k for k, rx in REST_WORDS.items() if rx.search(change.get("detail") or "")), None)
            if eff is None:
                return {"status": "NOT_AVAILABLE", "reason": "Research has team-level estimates only for a "
                        "back-to-back and a third game in four days; rest differences need both teams' rest days"}
            if side is None:
                return {"status": "NOT_AVAILABLE", "reason": "say which team is on the back-to-back"}
            row = self.schedule[eff]
            try:
                rc = self._combine(game, {"type": "schedule", "effect": eff, "side": side})
            except self.mod.ScenarioRefused as e:
                return {"status": "NOT_AVAILABLE", "reason": f"Research's combiner refused: {e}"}
            rv = row.get("registered_verdict") or {}
            cav = [*(self.schedule_doc.get("assumptions") or [])[1:2]]
            if rv:
                cav.insert(0, f"unproven: the registered test ({rv.get('claim')}) found "
                              f"{rv.get('verdict')}")
            return self._result(game, side, rc, row["n_condition"], "games on the condition",
                                rv.get("verdict") or "NOT_TESTED", cav or ["schedule effects are confounded"],
                                {"effect_win_prob": row["effect_win_prob"], "effect_log_odds": row["effect_log_odds"],
                                 "registered_verdict": rv or None}, row.get("definition", ""))
        if change["kind"] == "PLAYER_OUT":
            teams = [change["team"]] if change.get("team") else [game["home_team"], game["away_team"]]
            ids = {game["home_team"]: game["home_team_id"], game["away_team"]: game["away_team_id"]}
            key = change.get("key")
            rows = ([self.absence[key]] if key in self.absence else
                    [r for r in self.absence.values() if r["team_id"] in {ids.get(t) for t in teams}
                     and r.get("player_name") and name_matches(change.get("player", ""), r["player_name"])])
            if not rows:
                return {"status": "NO_DATA", "reason": f"no absence estimate for {change.get('player')} with "
                        f"{' or '.join(teams)} in 2023-24 to 2025-26"}
            if len(rows) > 1:
                return {"status": "NOT_AVAILABLE", "reason": "more than one player matches: "
                        + ", ".join(sorted(r["player_name"] for r in rows))}
            row = rows[0]
            ok, why = shown_by_default(row)
            if not ok:
                return {"status": "NO_DATA" if "games missed" in why or "no player name" in why else "NOT_AVAILABLE",
                        "reason": f"{row.get('player_name') or row['player_id']}: {why}"}
            side = "home" if row["team_id"] == game["home_team_id"] else "away"
            try:
                rc = self._combine(game, {"type": "player_absence", "key": row["key"], "side": side})
            except self.mod.ScenarioRefused as e:
                return {"status": "NOT_AVAILABLE", "reason": f"Research's combiner refused: {e}"}
            cav = [FLAG_TEXT.get(f, f.replace("_", " ")) for f in row.get("flags") or []]
            cav.append(f"from {', '.join(row.get('seasons') or [])} data; not checked against tonight's roster")
            raw = {k: row[k] for k in row if "raw" in k}  # raw (unshrunk) values, if Research supplies them
            return self._result(game, side, rc, row["n_games_missed"], "games missed", "NOT_TESTED",
                                cav or ["absence estimates are descriptive"],
                                {"player": row["player_name"], "key": row["key"], "seasons": row.get("seasons"),
                                 "n_games_played": row.get("n_games_played"),
                                 "effect_win_prob": row.get("effect_win_prob"),
                                 "effect_log_odds": row.get("effect_log_odds"), **({"raw": raw} if raw else {})},
                                "absence: mean Elo residual with vs without him (Research)")
        return {"status": "NOT_AVAILABLE", "reason": f"no Research estimate for {change['kind']}"}

    def menu(self, ctx: dict) -> list[dict] | None:
        self._load()
        game = ctx["game"]
        out = []
        for team, tid in ((game["away_team"], game["away_team_id"]), (game["home_team"], game["home_team_id"])):
            out.append({"kind": "REST", "team": team, "detail": "back-to-back",
                        "text": f"The {team} are on the second night of a back-to-back"})
            out.append({"kind": "REST", "team": team, "detail": "3-in-4",
                        "text": f"The {team} play their third game in four days"})
            rows = [r for r in self.absence.values() if r["team_id"] == tid and "2025-26" in (r.get("seasons") or [])
                    and shown_by_default(r)[0]]
            rows.sort(key=lambda r: (-int(r.get("n_games_played") or 0), r["key"]))
            for r in rows[:PLAYERS_PER_TEAM]:
                out.append({"kind": "PLAYER_OUT", "team": team, "player": r["player_name"], "key": r["key"],
                            "text": f"The {team} are without {r['player_name']}"})
        return out
