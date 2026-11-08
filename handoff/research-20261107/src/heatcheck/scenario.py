"""Scenario effect ESTIMATES (not claims): player absence and schedule effects on win probability relative to
the registered B1 Elo expectation, and a pure scenario combiner.

Everything here is pure: frames and arrays in, dicts out. No file, network or database side effects.

Residual: for a team in a game, r = (1 if the team won else 0) - p_team, where p_team is the frozen B1 Elo
pre-game win probability for that team (home court included unless neutral). An effect is a difference of mean
residuals between games with and without a condition, so it is "change in win probability beyond what Elo
expected". Log-odds effects use the delta method: delta = effect / (pbar * (1 - pbar)), pbar = mean Elo
probability over the games behind the estimate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LABEL = "ESTIMATE"
B_DEFAULT = 2000
Z80, Z95 = 1.2815515655446004, 1.959963984540054
REST_FAMILY = ("back_to_back", "three_in_four", "rest_diff")


# --------------------------------------------------------------------------- residuals
def team_rows(games: pd.DataFrame) -> pd.DataFrame:
    """games: game_id, season, game_date_et, home_team_id, away_team_id, p_home (Elo), home_win,
    home_rest, away_rest. Returns one row per team per game with p_team, y, resid, rest, opp_rest."""
    g = games.reset_index(drop=True)
    home = pd.DataFrame({"game_id": g.game_id, "season": g.season, "date": g.game_date_et, "team_id": g.home_team_id,
                         "opp_id": g.away_team_id, "side": "home", "p_team": g.p_home, "y": g.home_win,
                         "rest": g.home_rest, "opp_rest": g.away_rest})
    away = pd.DataFrame({"game_id": g.game_id, "season": g.season, "date": g.game_date_et, "team_id": g.away_team_id,
                         "opp_id": g.home_team_id, "side": "away", "p_team": 1 - g.p_home, "y": 1 - g.home_win,
                         "rest": g.away_rest, "opp_rest": g.home_rest})
    t = pd.concat([home, away], ignore_index=True)
    t["resid"] = t.y.astype(float) - t.p_team.astype(float)
    return t


def three_in_four(rows: pd.DataFrame) -> np.ndarray:
    """True when this is the team's 3rd (or later) game within a 4-day window ending on this date."""
    d = pd.to_datetime(rows.date)
    out = np.zeros(len(rows), dtype=bool)
    for (_, _), idx in rows.groupby(["team_id", "season"]).groups.items():
        dd = d.loc[idx].sort_values()
        vals = dd.to_numpy()
        for i, (ix, day) in enumerate(zip(dd.index, vals)):
            lo = day - np.timedelta64(3, "D")
            out[rows.index.get_loc(ix)] = int(((vals >= lo) & (vals <= day)).sum()) >= 3
    return out


# --------------------------------------------------------------------------- bootstrap helpers
def _interval(draws: np.ndarray) -> dict:
    d = draws[np.isfinite(draws)]
    if len(d) == 0:
        return {"ci80": None, "ci95": None}
    q = np.percentile(d, [10, 90, 2.5, 97.5])
    return {"ci80": [float(q[0]), float(q[1])], "ci95": [float(q[2]), float(q[3])]}


def _logit_scale(est: float | None, iv: dict, pbar: float | None) -> dict:
    if est is None or pbar is None:
        return {"estimate": None, "ci80": None, "ci95": None, "pbar": None, "method": "no games with this condition"}
    f = 1.0 / (pbar * (1 - pbar))
    return {"estimate": est * f,
            "ci80": None if iv["ci80"] is None else [v * f for v in iv["ci80"]],
            "ci95": None if iv["ci95"] is None else [v * f for v in iv["ci95"]],
            "pbar": pbar, "method": "delta method: win-probability effect / (pbar*(1-pbar))"}


def stratified_diff_bootstrap(r_cond: np.ndarray, r_rest: np.ndarray, B: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap of mean(r_cond) - mean(r_rest), resampling each group separately (games are the units)."""
    a = r_cond[rng.integers(0, len(r_cond), size=(B, len(r_cond)))].mean(1)
    b = r_rest[rng.integers(0, len(r_rest), size=(B, len(r_rest)))].mean(1)
    return a - b


# --------------------------------------------------------------------------- player absence
LOW_INVOLVEMENT_EVENTS = 8


def absence_effects(rows: pd.DataFrame, appearances: pd.DataFrame, names: dict, tricodes: dict,
                    B: int = B_DEFAULT, seed: int = 20261108, involvement: dict | None = None) -> list[dict]:
    """rows: team_rows output. appearances: unique (game_id, team_id, player_id) for players who appeared.
    For each player, team and season, games 'missed' are that team's games between the player's first and last
    appearance for the team that season (tenure window) in which he did not appear. Seasons for the same
    player and team are pooled."""
    rng = np.random.default_rng(seed)
    r = rows[["game_id", "season", "date", "team_id", "resid", "p_team"]]
    app = appearances.merge(r[["game_id", "team_id", "date", "season"]], on=["game_id", "team_id"], how="inner")
    teams_per_season = app.groupby(["player_id", "season"]).team_id.nunique()
    moved = set(teams_per_season[teams_per_season > 1].index.get_level_values(0))
    tenure = app.groupby(["player_id", "team_id", "season"]).date.agg(["min", "max"]).reset_index()
    played = set(zip(app.player_id, app.team_id, app.game_id))
    out = []
    for (pid, tid), ten in tenure.groupby(["player_id", "team_id"]):
        pres, absn, pall, seasons = [], [], [], []
        for t in ten.itertuples():
            tg = r[(r.team_id == tid) & (r.season == t.season) & (r.date >= t.min) & (r.date <= t.max)]
            mask = np.array([(pid, tid, g) in played for g in tg.game_id])
            pres.append(tg.resid.to_numpy()[mask]); absn.append(tg.resid.to_numpy()[~mask])
            pall.append(tg.p_team.to_numpy()); seasons.append(t.season)
        pres, absn, pall = np.concatenate(pres), np.concatenate(absn), np.concatenate(pall)
        if len(absn) == 0 or len(pres) == 0:
            continue
        est = float(absn.mean() - pres.mean())
        iv = _interval(stratified_diff_bootstrap(absn, pres, B, rng))
        pbar = float(pall.mean())
        flags = ["absences_mix_rest_injury_suspension_and_coach_decisions",
                 "elo_partly_absorbs_long_absences"]
        if len(absn) < 5:
            flags.append("small_n")
        if pid in moved:
            flags.append("team_change_in_window")
        inv = (involvement or {}).get((pid, tid))
        if inv is not None and inv < LOW_INVOLVEMENT_EVENTS:
            flags.append("low_involvement_outcome_dependent_appearance")
        out.append({"key": f"nba-player:{pid}|nba-team:{tid}", "player_id": f"nba-player:{pid}",
                    "player_name": names.get(pid), "team_id": f"nba-team:{tid}", "team": tricodes.get(tid),
                    "seasons": sorted(set(seasons)), "n_games_missed": int(len(absn)),
                    "n_games_played": int(len(pres)), "median_events_per_game": inv, "label": LABEL,
                    "effect_win_prob": {"estimate": est, **iv},
                    "effect_log_odds": _logit_scale(est, iv, pbar), "flags": flags})
    return out


# --------------------------------------------------------------------------- schedule
def game_clustered_effect(rows: pd.DataFrame, cond: np.ndarray, B: int, rng: np.random.Generator,
                          base: np.ndarray | None = None) -> tuple[float, dict, float, int, int]:
    """Effect = mean resid (cond rows) - mean resid (base rows; default: not cond). Bootstrap resamples GAMES,
    so both team rows of a game move together."""
    base = ~cond if base is None else base
    if cond.sum() == 0 or base.sum() == 0:
        return None, {"ci80": None, "ci95": None}, None, int(cond.sum()), int(base.sum())
    gidx, games = pd.factorize(rows.game_id)
    w = rng.multinomial(len(games), np.full(len(games), 1 / len(games)), size=B)[:, gidx].astype(float)
    rv = rows.resid.to_numpy(float)
    def mean_w(m):
        num = (w[:, m] * rv[m]).sum(1); den = w[:, m].sum(1)
        return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    draws = mean_w(cond) - mean_w(base)
    est = float(rv[cond].mean() - rv[base].mean())
    return est, _interval(draws), float(rows.p_team.to_numpy(float)[cond].mean()), int(cond.sum()), int(base.sum())


REGISTERED_REST = {"claim": "GP-REST", "verdict": "INSUFFICIENT_EVIDENCE",
                   "receipt": "3e238d2d-030e-45b4-aae7-db0787ecb873",
                   "meaning": "the pre-registered 2023-24 final test could not establish that rest difference and "
                              "back-to-backs add to Elo; the effect is unproven"}


def schedule_effects(rows: pd.DataFrame, B: int = B_DEFAULT, seed: int = 20261109) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    b2b = (rows.rest.to_numpy() == 0)
    est, iv, pbar, n1, n0 = game_clustered_effect(rows, b2b, B, rng)
    out["back_to_back"] = {"definition": "team played the previous day (rest days = 0), vs the team not on a back-to-back",
                           "applies_to": "team", "n_condition": n1, "n_rest": n0, "label": LABEL,
                           "effect_win_prob": {"estimate": est, **iv}, "effect_log_odds": _logit_scale(est, iv, pbar),
                           "registered_verdict": REGISTERED_REST}
    t34 = rows["three_in_four"].to_numpy(bool)
    est, iv, pbar, n1, n0 = game_clustered_effect(rows, t34, B, rng)
    out["three_in_four"] = {"definition": "team's 3rd game within 4 days, vs not", "applies_to": "team",
                            "n_condition": n1, "n_rest": n0, "label": LABEL,
                            "effect_win_prob": {"estimate": est, **iv}, "effect_log_odds": _logit_scale(est, iv, pbar),
                            "registered_verdict": None, "registered_note": "no registered test covers 3-in-4"}
    home = rows[rows.side == "home"].reset_index(drop=True)
    diff = (home.rest - home.opp_rest).clip(-3, 3).to_numpy()
    by = {}
    for k in (-3, -2, -1, 1, 2, 3):
        est, iv, pbar, n1, n0 = game_clustered_effect(home, diff == k, B, rng, base=(diff == 0))
        by[str(k)] = {"n_condition": n1, "n_reference": n0, "effect_win_prob": {"estimate": est, **iv},
                      "effect_log_odds": _logit_scale(est, iv, pbar)}
    out["rest_diff"] = {"definition": "home rest days minus away rest days (each capped at 3, diff clipped to +-3), "
                                      "effect on the HOME team vs games with equal rest", "applies_to": "home",
                        "label": LABEL, "by_value": by, "registered_verdict": REGISTERED_REST}
    return out


# --------------------------------------------------------------------------- scenario combiner (pure)
class ScenarioRefused(ValueError):
    pass


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _expit(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def scenario_probability(baseline_p_home: float, home_team_id: str, away_team_id: str, changes: list[dict],
                         absence: dict, schedule: dict, *, baseline_includes: tuple = (), min_n_missed: int = 5) -> dict:
    """Combine ESTIMATED effects with a baseline home-win probability on the log-odds scale.

    changes: list of
      {"type": "player_absence", "key": "nba-player:<id>|nba-team:<id>", "side": "home"|"away"}
      {"type": "schedule", "effect": "back_to_back"|"three_in_four", "side": "home"|"away"}
      {"type": "schedule", "effect": "rest_diff", "value": -3..3}          (home minus away rest days)
    absence: {key: row} from absence_effects; schedule: schedule_effects output.
    baseline_includes: factors already reflected in the baseline (e.g. ("rest",) for a model with rest terms).

    Assumption: effects are independent and additive on the log-odds scale; interval uses a normal approximation
    of each effect's 95% bootstrap interval, combined in quadrature. The baseline is treated as fixed.
    Refuses (never repairs): unknown fields or effects, the same player twice, a player on the wrong side, more
    than one rest-family change per team, rest_diff together with any team-level rest change, any rest change
    when the baseline already includes rest, and absence effects with fewer than min_n_missed games."""
    if not (isinstance(baseline_p_home, (int, float)) and 0 < baseline_p_home < 1):
        raise ScenarioRefused("baseline_p_home must be a number strictly between 0 and 1")
    if not isinstance(changes, list):
        raise ScenarioRefused("changes must be a list")
    z = _logit(float(baseline_p_home)); var = 0.0
    applied, seen_players, rest_teams, rest_diff_used = [], set(), set(), False
    sides = {"home": home_team_id, "away": away_team_id}
    for i, c in enumerate(changes):
        if not isinstance(c, dict) or c.get("type") not in ("player_absence", "schedule"):
            raise ScenarioRefused(f"change {i}: type must be player_absence or schedule")
        if c["type"] == "player_absence":
            if set(c) != {"type", "key", "side"} or c["side"] not in sides:
                raise ScenarioRefused(f"change {i}: player_absence needs exactly type, key, side (home|away)")
            row = absence.get(c["key"])
            if row is None:
                raise ScenarioRefused(f"change {i}: no estimate for {c['key']}")
            if row["player_id"] in seen_players:
                raise ScenarioRefused(f"change {i}: {row['player_id']} counted twice")
            if row["team_id"] != sides[c["side"]]:
                raise ScenarioRefused(f"change {i}: {row['player_id']}'s estimate is for {row['team_id']}, "
                                      f"not the {c['side']} team {sides[c['side']]}")
            if row["n_games_missed"] < min_n_missed:
                raise ScenarioRefused(f"change {i}: only {row['n_games_missed']} games missed (< {min_n_missed})")
            seen_players.add(row["player_id"]); eff = row["effect_log_odds"]
            sign = 1 if c["side"] == "home" else -1
        else:
            eff_name = c.get("effect")
            if eff_name not in REST_FAMILY:
                raise ScenarioRefused(f"change {i}: unknown schedule effect {eff_name!r}")
            if "rest" in baseline_includes:
                raise ScenarioRefused(f"change {i}: baseline already reflects rest; {eff_name} would double count")
            if eff_name == "rest_diff":
                if set(c) != {"type", "effect", "value"} or type(c["value"]) is not int or not -3 <= c["value"] <= 3:
                    raise ScenarioRefused(f"change {i}: rest_diff needs an integer value in -3..3 and no side")
                if rest_diff_used or rest_teams:
                    raise ScenarioRefused(f"change {i}: rest_diff overlaps another rest change (double counting)")
                rest_diff_used = True
                if c["value"] == 0:
                    applied.append({"change": c, "log_odds": 0.0, "se": 0.0}); continue
                eff = schedule["rest_diff"]["by_value"][str(c["value"])]["effect_log_odds"]; sign = 1
            else:
                if set(c) != {"type", "effect", "side"} or c["side"] not in sides:
                    raise ScenarioRefused(f"change {i}: {eff_name} needs exactly type, effect, side (home|away)")
                if rest_diff_used or c["side"] in rest_teams:
                    raise ScenarioRefused(f"change {i}: {eff_name} overlaps another rest change for the "
                                          f"{c['side']} team (double counting)")
                rest_teams.add(c["side"]); eff = schedule[eff_name]["effect_log_odds"]
                sign = 1 if c["side"] == "home" else -1
        if eff["estimate"] is None or eff["ci95"] is None:
            raise ScenarioRefused(f"change {i}: no estimate (no games with this condition)")
        se = (eff["ci95"][1] - eff["ci95"][0]) / (2 * Z95)
        z += sign * eff["estimate"]; var += se * se
        applied.append({"change": c, "log_odds": sign * eff["estimate"], "se": se})
    sd = math.sqrt(var)
    return {"label": LABEL, "baseline_p_home": float(baseline_p_home), "scenario_p_home": _expit(z),
            "ci80": [_expit(z - Z80 * sd), _expit(z + Z80 * sd)], "ci95": [_expit(z - Z95 * sd), _expit(z + Z95 * sd)],
            "applied": applied,
            "assumptions": ["effects are independent and additive on the log-odds scale",
                            "each effect's 95% bootstrap interval is approximated as normal; combined in quadrature",
                            "the baseline probability is treated as fixed (no baseline uncertainty)",
                            "estimates, not claims: absences mix rest and injury; schedule effects are unproven "
                            "where the registered verdict says so"]}
