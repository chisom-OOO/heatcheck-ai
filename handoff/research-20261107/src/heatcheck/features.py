"""Point-in-time feature builders.

Pre-tip  (DECISIONS D5/D6): features for a game on ET date D use only outcomes of games on ET dates < D.
Pre-shot (DATA_PIPELINE §3): features for shot s use only events with smaller `sequence` in the same game;
           the current shot's result, assist, block and descriptor are never inputs.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ELO_K = 20.0
ELO_HFA = 100.0
ELO_MEAN = 1505.0
ELO_CARRY = 0.75
FEATURE_VERSION_PREGAME = "pregame/1"
FEATURE_VERSION_PRESHOT = "preshot/1"


class LabelUnavailable(RuntimeError):
    """Raised when a feature needs an outcome that the caller has not been granted."""


def _elo_expect(diff: float) -> float:
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def _run_elo(games: pd.DataFrame, labels: dict[str, int], ratings: dict[int, float], *,
             emit: bool) -> tuple[dict[int, float], list[dict]]:
    """Process games grouped by ET date. Emits pre-date ratings for every game, then updates."""
    out = []
    for date, day in games.sort_values(["game_date_et", "game_id"]).groupby("game_date_et", sort=True):
        snap = dict(ratings)  # ratings as of start of this date
        for r in day.itertuples():
            h = snap.get(r.home_team_id, ELO_MEAN); a = snap.get(r.away_team_id, ELO_MEAN)
            hfa = 0.0 if r.neutral_site else ELO_HFA
            if emit:
                out.append({"game_id": r.game_id, "home_elo": h, "away_elo": a, "elo_diff": h + hfa - a})
        for r in day.itertuples():
            if r.game_id not in labels:
                raise LabelUnavailable(r.game_id)
            h = ratings.get(r.home_team_id, ELO_MEAN); a = ratings.get(r.away_team_id, ELO_MEAN)
            hfa = 0.0 if r.neutral_site else ELO_HFA
            e = _elo_expect(h + hfa - a); y = labels[r.game_id]
            ratings[r.home_team_id] = h + ELO_K * (y - e)
            ratings[r.away_team_id] = a - ELO_K * (y - e)
    return ratings, out


def seed_elo(prior_games: pd.DataFrame, prior_labels: pd.DataFrame) -> dict[int, float]:
    lab = dict(zip(prior_labels.game_id, prior_labels.home_win.astype(int)))
    pg = prior_games.copy()
    pg["neutral_site"] = pg["neutral_site"].astype(bool)
    ratings, _ = _run_elo(pg, lab, {}, emit=False)
    return {t: ELO_CARRY * r + (1 - ELO_CARRY) * ELO_MEAN for t, r in ratings.items()}


def pregame_features(games: pd.DataFrame, labels: pd.DataFrame, seed_ratings: dict[int, float],
                     target_ids: set[str] | None = None) -> pd.DataFrame:
    """Build features for `target_ids` (default: all games). Needs labels only for games dated
    strictly before the latest target date; raises LabelUnavailable otherwise."""
    g = games.copy()
    g["neutral_site"] = g["neutral_site"].astype(bool)
    targets = set(g.game_id) if target_ids is None else set(target_ids)
    last_date = g[g.game_id.isin(targets)].game_date_et.max()
    lab = dict(zip(labels.game_id, labels.home_win.astype(int)))
    # Elo: run through all dates up to last_date; labels needed only for dates < last_date
    hist = g[g.game_date_et <= last_date]
    ratings = dict(seed_ratings)
    rows = []
    for date, day in hist.sort_values(["game_date_et", "game_id"]).groupby("game_date_et", sort=True):
        snap = dict(ratings)
        for r in day.itertuples():
            h = snap.get(r.home_team_id, ELO_MEAN); a = snap.get(r.away_team_id, ELO_MEAN)
            hfa = 0.0 if r.neutral_site else ELO_HFA
            rows.append({"game_id": r.game_id, "home_elo": h, "away_elo": a, "elo_diff": h + hfa - a})
        if date == last_date:
            break
        ratings, _ = _run_elo(day, lab, ratings, emit=False)
    elo = pd.DataFrame(rows)

    # rest: days since team's previous game this season (ET dates), minus 1, capped at 3
    long = pd.concat([
        g[["game_id", "game_date_et", "home_team_id"]].rename(columns={"home_team_id": "team"}).assign(side="home"),
        g[["game_id", "game_date_et", "away_team_id"]].rename(columns={"away_team_id": "team"}).assign(side="away"),
    ])
    long["d"] = pd.to_datetime(long.game_date_et)
    long = long.sort_values(["team", "d", "game_id"])
    gap = long.groupby("team").d.diff().dt.days
    long["rest"] = (gap - 1).clip(upper=3).fillna(3).astype(int)
    rest = long.pivot(index="game_id", columns="side", values="rest")

    f = g[["game_id", "game_date_et", "tip_utc", "neutral_site"]].merge(elo, on="game_id", how="left")
    f["home_rest"] = f.game_id.map(rest["home"]); f["away_rest"] = f.game_id.map(rest["away"])
    f["rest_diff"] = f.home_rest - f.away_rest
    f["home_b2b"] = (f.home_rest == 0).astype(int); f["away_b2b"] = (f.away_rest == 0).astype(int)
    f["elo_logit"] = f.elo_diff / 400.0 * math.log(10)
    f["p_elo"] = 1.0 / (1.0 + np.exp(-f.elo_logit))
    f["cutoff_utc"] = pd.to_datetime(f.game_date_et).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    f["feature_version"] = FEATURE_VERSION_PREGAME
    f["target_id"] = "GAME:" + f.game_id
    f = f[f.game_id.isin(targets)].sort_values(["game_date_et", "game_id"]).reset_index(drop=True)
    return f[["target_id", "game_id", "game_date_et", "cutoff_utc", "neutral_site", "home_elo", "away_elo",
              "elo_diff", "elo_logit", "p_elo", "home_rest", "away_rest", "rest_diff", "home_b2b", "away_b2b",
              "feature_version"]]


# --------------------------------------------------------------------------- pre-shot
BANNED_SHOT_INPUTS = {"shot_result", "descriptor", "assist_person_id", "block_person_id"}


def preshot_features(events: pd.DataFrame, streak_k: int = 3) -> pd.DataFrame:
    """One row per field-goal attempt. Ordering-dependent features are set missing for shots in a
    (game, period) that contains a clock-regression step (DECISIONS D3)."""
    e = events.sort_values(["game_id", "sequence"], kind="mergesort").reset_index(drop=True)
    g = e.groupby("game_id", sort=False)
    e["home_pre"] = g.score_home_after.shift(1).fillna(0).astype(int)
    e["away_pre"] = g.score_away_after.shift(1).fillna(0).astype(int)
    bad_gp = set(map(tuple, e.loc[e.clock_regress.astype(bool), ["game_id", "period"]].values))

    s = e[e.is_field_goal == 1].copy()
    # home/away side of shooter, derived from team_id vs game's scoring sides — passed via events' team ids
    s["made_tmp"] = (s.shot_result == "Made").astype(int)  # used ONLY via shift (prior shots)
    pg = s.groupby(["game_id", "person_id"], sort=False)
    s["prior_fga"] = pg.cumcount()
    s["prior_makes"] = pg.made_tmp.cumsum() - s.made_tmp
    prev = [pg.made_tmp.shift(i) for i in range(1, streak_k + 1)]
    allmade = np.logical_and.reduce([p == 1 for p in prev])
    allmiss = np.logical_and.reduce([p == 0 for p in prev])
    s[f"prev{streak_k}_all_made"] = np.where(s.prior_fga >= streak_k, allmade.astype(int), np.nan)
    s[f"prev{streak_k}_all_missed"] = np.where(s.prior_fga >= streak_k, allmiss.astype(int), np.nan)
    s["prev_shot_made"] = pg.made_tmp.shift(1)
    s = s.drop(columns=["made_tmp"])
    s["shot_value"] = np.where(s.action_type == "3pt", 3, 2)
    q = s.qualifiers.str.split(", ")
    for tag in ["fromturnover", "2ndchance", "fastbreak", "pointsinthepaint"]:
        s[f"q_{tag}"] = q.apply(lambda l, t=tag: int(t in l))
    s["ordering_unresolved"] = [(gid, p) in bad_gp for gid, p in zip(s.game_id, s.period)]
    dep = ["prior_fga", "prior_makes", f"prev{streak_k}_all_made", f"prev{streak_k}_all_missed",
           "prev_shot_made", "home_pre", "away_pre"]
    s.loc[s.ordering_unresolved, dep] = np.nan
    s["target_id"] = "SHOT:" + s.game_id + ":" + s.sequence.astype(str)
    s["feature_version"] = FEATURE_VERSION_PRESHOT
    cols = ["target_id", "game_id", "sequence", "period", "clock_sec_left", "elapsed_sec", "person_id",
            "team_id", "shot_value", "shot_distance", "area", "x", "y", "sub_type",
            "q_fromturnover", "q_2ndchance", "q_fastbreak", "q_pointsinthepaint",
            "home_pre", "away_pre"] + dep[:5] + ["ordering_unresolved", "feature_version"]
    out = s[list(dict.fromkeys(cols))].reset_index(drop=True)
    assert not (set(out.columns) & BANNED_SHOT_INPUTS)
    return out


def add_shooter_margin(feat: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    m = feat.merge(games[["game_id", "home_team_id"]], on="game_id", how="left")
    is_home = m.team_id == m.home_team_id
    m["margin_pre"] = np.where(is_home, m.home_pre - m.away_pre, m.away_pre - m.home_pre)
    return m.drop(columns=["home_team_id"])


def feature_bytes(df: pd.DataFrame) -> bytes:
    """Byte-stable serialisation used by the future-perturbation test."""
    d = df[sorted(df.columns)].copy()
    for c in d.columns:
        if isinstance(d[c].dtype, pd.DatetimeTZDtype):
            d[c] = d[c].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return d.to_csv(index=False, lineterminator="\n", float_format="%.17g", na_rep="\\N").encode()
