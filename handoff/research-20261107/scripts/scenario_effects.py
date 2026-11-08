"""Build scenario-effect ESTIMATES (not claims) from data we already have: player absence and schedule effects.

Usage: python -I scripts/scenario_effects.py <data_2023-24> <data_2024-25> <cdnnba_2025.csv> <out_dir> \
           <raw_csv_2023> <raw_csv_2024>

Seasons 2023-24, 2024-25 (Research builds from pinned nba_data@46488f0f archives) and 2025-26 (cdnnba_2025.csv
from the same pinned commit). Elo expectation: frozen B1 Elo (features.py) with its seeds rolled season to season
by the frozen carry rule, exactly as scripts/live_forecast.py. Writes player_absence_effects.json and
schedule_effects.json. The 2023-24 final and 2024-25 sealed epochs are already spent; this reads them for
description only and runs no registered test.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from heatcheck import canonical, scenario as SC, store  # noqa: E402
from heatcheck import features as F  # noqa: E402
from heatcheck.util import sha256_file, utc_now_iso  # noqa: E402


def carry(r: dict) -> dict:
    return {t: F.ELO_CARRY * v + (1 - F.ELO_CARRY) * F.ELO_MEAN for t, v in r.items()}


def _sqlite_season(data: Path, games_tbl="games", labels_tbl="game_labels"):
    g = store.read(data / "public.sqlite", games_tbl); g["neutral_site"] = g.neutral_site.astype(bool)
    lab = store.read(data / "restricted_labels.sqlite", labels_tbl)
    return g, lab


def _sqlite_events(data: Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{data / 'public.sqlite'}?mode=ro", uri=True)
    ev = pd.read_sql("SELECT game_id, team_id, person_id FROM events WHERE person_id IS NOT NULL "
                     "AND team_id IS NOT NULL", con)
    con.close()
    return ev


def _season_games(g, lab, seed, season):
    feat = F.pregame_features(g, lab, seed, set(g.game_id)).merge(lab[["game_id", "home_win"]], on="game_id")
    feat = feat.merge(g[["game_id", "home_team_id", "away_team_id"]], on="game_id")
    feat["season"] = season
    return feat.rename(columns={"p_elo": "p_home"})[["game_id", "season", "game_date_et", "home_team_id",
                                                      "away_team_id", "p_home", "home_win", "home_rest", "away_rest"]]


def _names(csvs: list[Path]) -> dict:
    out = {}
    for p in csvs:
        d = pd.read_csv(p, usecols=["personId", "playerName", "playerNameI"], low_memory=False).dropna(subset=["personId"])
        d = d[d.personId > 0]
        d["name"] = d.playerNameI.fillna(d.playerName)      # "A. Davis": less ambiguous than the family name
        out.update({int(k): v for k, v in d.dropna(subset=["name"]).groupby("personId").name.last().items()})
    return out


def main(d23: Path, d24: Path, csv25: Path, out: Path, raw23: Path, raw24: Path):
    out.mkdir(parents=True, exist_ok=True)
    g22, l22 = _sqlite_season(d23, "games_2022", "game_labels_2022")
    g23, l23 = _sqlite_season(d23)
    g24, l24 = _sqlite_season(d24)
    b25 = canonical.build_canonical(csv25, "2025-26", neutral_sites=set())
    g25 = b25.games.copy(); g25["neutral_site"] = g25.neutral_site.astype(bool); l25 = b25.game_labels

    s23 = F.seed_elo(g22, l22)
    games = [_season_games(g23, l23, s23, "2023-24")]
    r, _ = F._run_elo(g23, dict(zip(l23.game_id, l23.home_win.astype(int))), dict(s23), emit=False)
    s24 = carry(r); games.append(_season_games(g24, l24, s24, "2024-25"))
    r, _ = F._run_elo(g24, dict(zip(l24.game_id, l24.home_win.astype(int))), dict(s24), emit=False)
    s25 = carry(r); games.append(_season_games(g25, l25, s25, "2025-26"))
    games = pd.concat(games, ignore_index=True)

    rows = SC.team_rows(games)
    rows["three_in_four"] = SC.three_in_four(rows)

    ev = pd.concat([_sqlite_events(d23), _sqlite_events(d24),
                    b25.events[["game_id", "team_id", "person_id"]].dropna()], ignore_index=True)
    ev = ev[ev.person_id.astype("int64") > 0]
    full = pd.DataFrame({"game_id": ev.game_id, "team_id": ev.team_id.astype("int64"),
                         "player_id": ev.person_id.astype("int64")})
    involvement = full.groupby(["player_id", "team_id", "game_id"]).size().groupby(["player_id", "team_id"]).median()
    app = full.drop_duplicates()
    names = _names([raw23, raw24, csv25])
    tri = {}
    for g in (g23, g24, g25):
        tri.update(dict(zip(g.home_team_id, g.home_tricode))); tri.update(dict(zip(g.away_team_id, g.away_tricode)))

    absence = SC.absence_effects(rows, app, names, tri, involvement={k: float(v) for k, v in involvement.items()})
    absence, shrink = SC.apply_eb_shrinkage(absence)
    sched = SC.schedule_effects(rows)
    n_missed = np.array([a["n_games_missed"] for a in absence])
    coverage = {"player_team_keys": int(len(absence)), "with_ge_5_games_missed": int((n_missed >= 5).sum()),
                "with_ge_10_games_missed": int((n_missed >= 10).sum()),
                "with_ge_20_games_missed": int((n_missed >= 20).sum()),
                "distinct_players": int(len({a["player_id"] for a in absence})),
                "games": int(len(games)), "team_games": int(len(rows))}
    sources = {"seasons": ["2023-24", "2024-25", "2025-26"],
               "upstream": "shufinskiy/nba_data@46488f0f (cdnnba play-by-play)",
               "data_2023_24_tables": store.logical_table_hashes(d23),
               "data_2024_25_tables": store.logical_table_hashes(d24, store.SEASON_TABLES),
               "cdnnba_2025_csv_sha256": sha256_file(csv25)}
    method = ("Residual = team result minus the frozen B1 Elo pre-game win probability (home court unless neutral). "
              "Effect = mean residual with the condition minus without, on the win-probability scale; log-odds "
              "effect by the delta method. Absence: games of the team between the player's first and last "
              "appearance for it in a season, absent = no play-by-play event for him; seasons pooled per "
              "player-team; bootstrap resamples absent and present games separately (B=2000). Schedule: "
              "bootstrap resamples whole games (B=2000).")
    common = {"label": "ESTIMATE", "not_a_claim": True, "method": method, "data_sources": sources,
              "created_utc": utc_now_iso()}
    coverage["shown_by_default"] = int(sum(a["shown_by_default"] for a in absence))
    pa = {**common, "format": "heatcheck-scenario-absence/1", "coverage": coverage, "shrinkage": shrink,
          "assumptions_and_flags": [
              "absences mix rest, injury, suspension, illness and coach decisions; the data cannot tell them apart",
              "small_n: fewer than 5 games missed; intervals are wide and unstable",
              "team_change_in_window: the player appeared for more than one team in a season",
              "Elo partly absorbs long absences (ratings drift while a player is out), shrinking estimates toward 0",
              "end-of-tenure absences (after the last appearance) are not counted",
              "low_involvement_outcome_dependent_appearance: median play-by-play events per game below 8; such "
              "players often appear only when a game is decided (garbage time), so appearance depends on the "
              "outcome and the estimate is biased",
              "estimate (default) is empirical-Bayes shrunk toward 0; raw_estimate and raw intervals are unshrunk; "
              "shown_by_default is false for any risk flag or fewer than 5 games missed",
              "raw intervals have no multiplicity adjustment: about 5% exclude 0 by chance alone across this many keys",
              "2025-26 neutral-site games are not flagged (home court applied)"],
          "effects": {a["key"]: a for a in absence}}
    se = {**common, "format": "heatcheck-scenario-schedule/1",
          "assumptions": ["rest days from the frozen feature code: days since previous game minus 1, capped at 3; "
                          "season openers count as 3",
                          "schedule conditions are confounded with travel, opponent and late-season rest decisions",
                          "registered_verdict, where present, is the pre-registered result: the UI must say the "
                          "effect is unproven"],
          "effects": sched}
    (out / "player_absence_effects.json").write_text(json.dumps(pa, indent=1, default=float) + "\n", newline="\n")
    (out / "schedule_effects.json").write_text(json.dumps(se, indent=1, default=float) + "\n", newline="\n")
    print(json.dumps({"coverage": coverage,
                      "schedule": {k: (v["effect_win_prob"] if "effect_win_prob" in v else
                                       {kk: vv["effect_win_prob"] for kk, vv in v["by_value"].items()})
                                   for k, v in sched.items()}}, indent=1, default=float))


if __name__ == "__main__":
    a = sys.argv
    main(Path(a[1]), Path(a[2]), Path(a[3]), Path(a[4]), Path(a[5]), Path(a[6]))
