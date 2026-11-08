"""DESCRIPTIVE FORECAST (not a registered claim): roll the registered B1 Elo forward and price upcoming games.

Usage:
  python -I scripts/live_forecast.py ratings <data_2023-24> <data_2024-25> <cdnnba_2025.csv> <out_dir>
  python -I scripts/live_forecast.py forecast <out_dir> <schedule.json> <forecasts.json>

Model: features.py Elo exactly as in the 2023-24 final run (receipt 3e238d2d): K=20, home court 100 Elo points,
no margin term, ratings updated once per US/Eastern date, between-season regression
carry = 0.75 * rating + 0.25 * 1505 (features.seed_elo; applied at every season boundary).
Seasons used: 2022-23 (seed) -> 2023-24 -> 2024-25 -> 2025-26 -> carried into 2026-27.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from heatcheck import canonical, store  # noqa: E402
from heatcheck import features as F  # noqa: E402
from heatcheck import kernels as K  # noqa: E402
from heatcheck.util import sha256_file, utc_now_iso  # noqa: E402

EPS = 1e-6   # same clip as the final run


def carry(r: dict) -> dict:
    return {t: F.ELO_CARRY * v + (1 - F.ELO_CARRY) * F.ELO_MEAN for t, v in r.items()}


def _season(data: Path, games_tbl="games", labels_tbl="game_labels"):
    g = store.read(data / "public.sqlite", games_tbl)
    g["neutral_site"] = g.neutral_site.astype(bool)
    lab = store.read(data / "restricted_labels.sqlite", labels_tbl)
    return g, lab


def ratings(data23: Path, data24: Path, csv25: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    g22, l22 = _season(data23, "games_2022", "game_labels_2022")
    g23, l23 = _season(data23)
    g24, l24 = _season(data24)
    b25 = canonical.build_canonical(csv25, "2025-26", neutral_sites=set())   # assumption: no neutral flags
    g25 = b25.games.copy(); g25["neutral_site"] = g25.neutral_site.astype(bool); l25 = b25.game_labels

    r = F.seed_elo(g22, l22)                                                  # carried into 2023-24
    r, _ = F._run_elo(g23, dict(zip(l23.game_id, l23.home_win.astype(int))), r, emit=False)
    r24_start = carry(r)
    # backtest 2024-25: pre-game probabilities from the frozen feature builder, scored like the final run
    feat = F.pregame_features(g24, l24, r24_start, set(g24.game_id)).merge(l24[["game_id", "home_win"]], on="game_id")
    y = feat.home_win.to_numpy(float); p = feat.p_elo.to_numpy(float)
    backtest = {"log_loss": float(K.log_loss_per(y, p, EPS).mean()), "brier": float(K.brier_per(y, p).mean()),
                "games": int(len(feat))}
    r, _ = F._run_elo(g24, dict(zip(l24.game_id, l24.home_win.astype(int))), r24_start, emit=False)
    r, _ = F._run_elo(g25, dict(zip(l25.game_id, l25.home_win.astype(int))), carry(r), emit=False)
    r27 = carry(r)
    last = pd.to_datetime(l25.finalization_utc, utc=True).max()
    teams = (pd.concat([g25[["home_team_id", "home_tricode"]].set_axis(["team_id", "tricode"], axis=1),
                        g25[["away_team_id", "away_tricode"]].set_axis(["team_id", "tricode"], axis=1)])
             .drop_duplicates().set_index("team_id").tricode.to_dict())
    state = {"ratings_2026_27_start": {str(k): v for k, v in sorted(r27.items())},
             "tricodes": {str(k): v for k, v in sorted(teams.items())},
             "backtest_2024_25": backtest,
             "last_completed_game_utc": last.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "games_used": {"2023-24": int(len(g23)), "2024-25": int(len(g24)), "2025-26": int(len(g25))},
             "results_2026_27_used": 0,
             "inputs": {"cdnnba_2025_csv_sha256": sha256_file(csv25),
                        "data_2023_24_tables": store.logical_table_hashes(data23),
                        "data_2024_25_tables": store.logical_table_hashes(data24, store.SEASON_TABLES)},
             "assumptions": ["2025-26 neutral-site games not flagged: home court applied to every game",
                             "no 2026-27 results available: ratings are the 2025-26 end ratings carried once"],
             "created_utc": utc_now_iso()}
    (out / "elo_state.json").write_text(json.dumps(state, indent=2) + "\n", newline="\n")
    print(json.dumps({k: state[k] for k in ("backtest_2024_25", "last_completed_game_utc", "games_used")}, indent=2))


def p_home(elo_h: float, elo_a: float, neutral: bool = False) -> float:
    return 1.0 / (1.0 + 10 ** (-((elo_h + (0.0 if neutral else F.ELO_HFA)) - elo_a) / 400.0))


REQUIRED_IDS = ["0022600189", "0022600190", "0022600191", "0022600192", "0022600193", "0022600194", "0022600195"]
FORECAST_DATES_ET = ("2026-11-07", "2026-11-08")
GAME_END_BOUND_H = 4   # upper bound on game length; the schedule JSON has tip times, not end times


def _sched_games(raw: bytes) -> pd.DataFrame:
    d = json.loads(raw)
    rows = []
    for day in d["leagueSchedule"]["gameDates"]:
        for g in day["games"]:
            h, a = g["homeTeam"], g["awayTeam"]
            rows.append({"game_id": g["gameId"], "status": int(g["gameStatus"]),
                         "tip_utc": pd.Timestamp(g["gameDateTimeUTC"]).tz_convert("UTC") if pd.Timestamp(g["gameDateTimeUTC"]).tzinfo
                         else pd.Timestamp(g["gameDateTimeUTC"], tz="UTC"),
                         "neutral_site": bool(g.get("isNeutral", False)),
                         "home_team_id": int(h["teamId"]), "away_team_id": int(a["teamId"]),
                         "home_team": f"{h['teamCity']} {h['teamName']}", "away_team": f"{a['teamCity']} {a['teamName']}",
                         "home_score": h.get("score"), "away_score": a.get("score")})
    df = pd.DataFrame(rows)
    df["game_date_et"] = df.tip_utc.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    return df


def forecast(out: Path, schedule: Path, dest: Path, expected_sha: str, fetched_utc: str, provenance: str):
    raw = schedule.read_bytes()
    sha = __import__("hashlib").sha256(raw).hexdigest()
    if sha != expected_sha:
        raise SystemExit(f"REFUSED: schedule sha256 {sha} != expected {expected_sha}")
    st = json.loads((out / "elo_state.json").read_text())
    r = {int(k): v for k, v in st["ratings_2026_27_start"].items()}
    df = _sched_games(raw)
    reg = df[df.game_id.str.fullmatch(r"00226[0-9]{5}")]                   # 2026-27 regular season only
    first_date = min(FORECAST_DATES_ET)
    done = reg[(reg.status == 3) & (reg.game_date_et < first_date)].copy()  # D5: strictly earlier ET dates
    if done[["home_score", "away_score"]].isna().any().any() or (done.home_score == done.away_score).any():
        raise SystemExit("REFUSED: a completed game lacks a decisive score")
    lab = dict(zip(done.game_id, (done.home_score.astype(int) > done.away_score.astype(int)).astype(int)))
    if len(done):
        r, _ = F._run_elo(done, lab, r, emit=False)
    up = reg[reg.game_date_et.isin(FORECAST_DATES_ET) & (reg.status != 3)].sort_values(["tip_utc", "game_id"])
    missing = sorted(set(REQUIRED_IDS) - set(up.game_id))
    if missing:
        raise SystemExit(f"REFUSED: required games missing or already final in the schedule: {missing}")
    last_tip = done.tip_utc.max() if len(done) else pd.Timestamp(st["last_completed_game_utc"])
    cutoff = (last_tip + pd.Timedelta(hours=GAME_END_BOUND_H)) if len(done) else last_tip
    if not cutoff < up.tip_utc.min():
        raise SystemExit(f"REFUSED: data cutoff {cutoff} is not before the first tip {up.tip_utc.min()}")
    z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    games = []
    for g in up.itertuples():
        eh, ea = r.get(g.home_team_id, F.ELO_MEAN), r.get(g.away_team_id, F.ELO_MEAN)
        games.append({"game_id": "nba:" + g.game_id, "tip_utc": z(g.tip_utc),
                      "home_team_id": f"nba-team:{g.home_team_id}", "away_team_id": f"nba-team:{g.away_team_id}",
                      "home_team": g.home_team, "away_team": g.away_team,
                      "p_home_win": round(p_home(eh, ea, g.neutral_site), 6), "elo_home": round(eh, 3),
                      "elo_away": round(ea, 3)})
    doc = {"format": "heatcheck-live-forecast/1", "label": "DESCRIPTIVE FORECAST",
           "model": ("B1 Elo, fixed constants (same code as final run receipt 3e238d2d): K 20, home court 100, "
                     "between-season carry 0.75*r+0.25*1505; ratings rolled 2022-23 to 2026-27 from "
                     "shufinskiy/nba_data@46488f0f (2023-24 to 2025-26) and cdn.nba.com schedule results (2026-27)"),
           "inputs_used": ["elo_rating_home", "elo_rating_away", "home_court"],
           "data_cutoff_utc": z(cutoff),
           "source": {"results": f"cdn.nba.com schedule JSON (scheduleLeagueV2.json; {provenance})",
                      "fetched_utc": fetched_utc, "sha256": sha, "cross_check": "NOT_RUN"},
           "backtest_2024_25": st["backtest_2024_25"], "games": games}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2) + "\n", newline="\n")
    print(json.dumps({"completed_2026_27_used": len(done), "last_used_tip": z(last_tip), "data_cutoff_utc": z(cutoff),
                      "n_forecast": len(games), "first_tip": games[0]["tip_utc"]}, indent=2))


def fallback(out: Path, gamelist: Path, dest: Path, results_archive: Path, fetched_utc: str):
    """FALLBACK forecast: 2025-26 end ratings carried once into 2026-27; NO 2026-27 results; hand-copied game list."""
    st = json.loads((out / "elo_state.json").read_text())
    r = {int(k): v for k, v in st["ratings_2026_27_start"].items()}
    gl = json.loads(gamelist.read_text())["games"]
    ids = [g["game_id"] for g in gl]
    if len(ids) != len(set(ids)) or sorted("nba:" + i for i in REQUIRED_IDS) != sorted(ids):
        raise SystemExit(f"REFUSED: game list must be exactly the required games {REQUIRED_IDS}")
    cutoff = st["last_completed_game_utc"]
    games = []
    for g in sorted(gl, key=lambda g: (g["tip_utc"], g["game_id"])):
        h, a = int(g["home_team_id"].split(":")[1]), int(g["away_team_id"].split(":")[1])
        if str(h) not in st["tricodes"] or str(a) not in st["tricodes"]:
            raise SystemExit(f"REFUSED: unknown team in {g['game_id']}")
        if not cutoff < g["tip_utc"]:
            raise SystemExit("REFUSED: cutoff not before tip")
        eh, ea = r[h], r[a]
        games.append({"game_id": g["game_id"], "tip_utc": g["tip_utc"], "home_team_id": g["home_team_id"],
                      "away_team_id": g["away_team_id"], "home_team": g["home_team"], "away_team": g["away_team"],
                      "p_home_win": round(p_home(eh, ea, False), 6), "elo_home": round(eh, 3), "elo_away": round(ea, 3)})
    doc = {"format": "heatcheck-live-forecast/1", "label": "DESCRIPTIVE FORECAST",
           "model": ("FALLBACK: B1 Elo, fixed constants (same code as final run receipt 3e238d2d): K 20, home court 100, "
                     "between-season carry 0.75*r+0.25*1505. Ratings are the 2025-26 end ratings carried once into "
                     "2026-27; NO 2026-27 results were used (cdn.nba.com refused every machine tried). Game list "
                     "hand-copied from NBA.com, not fetched. All seven games assumed not at a neutral site."),
           "inputs_used": ["elo_rating_home", "elo_rating_away", "home_court"],
           "data_cutoff_utc": cutoff,
           "source": {"results": ("shufinskiy/nba_data@46488f0f datasets/cdnnba_2025.tar.xz (2025-26 regular-season "
                                  "results; earlier seasons from the same repository). No 2026-27 results. Game list "
                                  "hand-copied from the NBA.com schedule page (data/live/raw/gamelist_handcopied_20261107.json)"),
                      "fetched_utc": fetched_utc, "sha256": sha256_file(results_archive), "cross_check": "NOT_RUN"},
           "backtest_2024_25": st["backtest_2024_25"], "games": games}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2) + "\n", newline="\n")
    print(json.dumps({"n_forecast": len(games), "data_cutoff_utc": cutoff,
                      "games": [(g["game_id"], g["away_team"], "@", g["home_team"], g["p_home_win"]) for g in games]}, indent=2))


def _bdl_games(raw_files: list[Path]) -> pd.DataFrame:
    rows = []
    for f in raw_files:
        for g in json.loads(f.read_bytes())["data"]:
            rows.append({"bdl_id": g["id"], "date_et": str(g["date"])[:10], "datetime": g.get("datetime"),
                         "season": g["season"], "status": str(g["status"]), "postseason": bool(g.get("postseason")),
                         "home": g["home_team"]["abbreviation"], "away": g["visitor_team"]["abbreviation"],
                         "home_score": g.get("home_team_score"), "away_score": g.get("visitor_team_score")})
    df = pd.DataFrame(rows).drop_duplicates("bdl_id")
    if df.empty:
        raise SystemExit("REFUSED: no games in the balldontlie payload")
    return df


def forecast_bdl(out: Path, raw_dir: Path, gamelist: Path, dest: Path, fetched_utc: str, provenance: str):
    """Full forecast from Max's raw balldontlie /v1/games pages (2026-27 results to date) + hand-copied game list.
    Elo update uses completed regular-season 2026-27 games on US/Eastern dates strictly before 2026-11-07 (D5)."""
    files = sorted(raw_dir.glob("[0-9][0-9]-*.json"))   # numbered raw pages only (manifest.json excluded)
    if not files:
        raise SystemExit(f"REFUSED: no raw JSON files in {raw_dir}")
    per_file = [{"file": f.name, "sha256": sha256_file(f)} for f in files]
    sha = (per_file[0]["sha256"] if len(per_file) == 1 else
           __import__("hashlib").sha256("".join(f"{x['sha256']}  {x['file']}\n" for x in per_file).encode()).hexdigest())
    st = json.loads((out / "elo_state.json").read_text())
    r = {int(k): v for k, v in st["ratings_2026_27_start"].items()}
    tri = {v: int(k) for k, v in st["tricodes"].items()}
    df = _bdl_games(files)
    df = df[(df.season == 2026) & (~df.postseason)]
    unknown = sorted((set(df.home) | set(df.away)) - set(tri))
    if unknown:
        raise SystemExit(f"REFUSED: balldontlie abbreviations without an NBA team id: {unknown}")
    first_date = min(FORECAST_DATES_ET)
    done = df[(df.status == "Final") & (df.date_et < first_date)].copy()
    if done[["home_score", "away_score"]].isna().any().any() or (done.home_score == done.away_score).any():
        raise SystemExit("REFUSED: a completed game lacks a decisive score")
    done["game_id"] = "bdl:" + done.bdl_id.astype(str)
    done["home_team_id"] = done.home.map(tri); done["away_team_id"] = done.away.map(tri)
    done["game_date_et"] = done.date_et; done["neutral_site"] = False      # assumption: no neutral flags
    lab = dict(zip(done.game_id, (done.home_score.astype(int) > done.away_score.astype(int)).astype(int)))
    if len(done):
        r, _ = F._run_elo(done, lab, r, emit=False)
    tips = pd.to_datetime(done.datetime, utc=True, errors="coerce")
    if tips.isna().any():
        raise SystemExit("REFUSED: a completed game has no datetime; cannot bound the data cutoff")
    cutoff = tips.max() + pd.Timedelta(hours=GAME_END_BOUND_H)
    gl = json.loads(gamelist.read_text())["games"]
    z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    inv = {v: k for k, v in tri.items()}
    allg = _bdl_games(files)
    games = []
    for g in sorted(gl, key=lambda g: (g["tip_utc"], g["game_id"])):
        h, a = int(g["home_team_id"].split(":")[1]), int(g["away_team_id"].split(":")[1])
        tip = pd.Timestamp(g["tip_utc"])
        hit = allg[(allg.home == inv[h]) & (allg.away == inv[a]) &
                   (pd.to_datetime(allg.datetime, utc=True, errors="coerce") == tip)]
        if len(hit) != 1:
            raise SystemExit(f"REFUSED: {g['game_id']} ({inv[a]} @ {inv[h]} {g['tip_utc']}) not matched in balldontlie")
        if not z(cutoff) < g["tip_utc"]:
            raise SystemExit(f"REFUSED: cutoff {z(cutoff)} not before tip of {g['game_id']}")
        eh, ea = r[h], r[a]
        games.append({"game_id": g["game_id"], "tip_utc": g["tip_utc"], "home_team_id": g["home_team_id"],
                      "away_team_id": g["away_team_id"], "home_team": g["home_team"], "away_team": g["away_team"],
                      "p_home_win": round(p_home(eh, ea, bool(g.get("neutral_site", False))), 6),
                      "elo_home": round(eh, 3), "elo_away": round(ea, 3)})
    doc = {"format": "heatcheck-live-forecast/1", "label": "DESCRIPTIVE FORECAST",
           "model": ("B1 Elo, fixed constants (same code as final run receipt 3e238d2d): K 20, home court 100, "
                     "carry 0.75*r+0.25*1505 between seasons. Ratings use results through 2026-11-06 ET (balldontlie "
                     "for 2026-27); the same ratings price Saturday and Sunday. Game 189 DEN vs IND is at a neutral "
                     "site (Arena CDMX, NBA schedule PDF): no home court."),
           "inputs_used": ["elo_rating_home", "elo_rating_away", "home_court"],
           "data_cutoff_utc": z(cutoff),
           "source": {"results": (f"balldontlie /v1/games raw pages ({provenance}; {len(files)} file(s); sha256 is "
                                  + ("the file's hash" if len(files) == 1 else "over the per-file hash list")
                                  + "), plus shufinskiy/nba_data@46488f0f for 2023-24 to 2025-26. Game list: "
                                  "data/live/raw/gamelist_20261107_08.json (2026-11-07 hand-copied from NBA.com; "
                                  "2026-11-08 ids from cdn.nba.com 2026-27-NBA-Regular-Season-Schedule-By-Date.pdf, "
                                  "sha256 5e82e37e...3570); every game matched in balldontlie"),
                      "fetched_utc": fetched_utc, "sha256": sha, "cross_check": "NOT_RUN"},
           "backtest_2024_25": st["backtest_2024_25"], "games": games}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2) + "\n", newline="\n")
    print(json.dumps({"completed_2026_27_used": int(len(done)), "files": per_file, "data_cutoff_utc": z(cutoff),
                      "games": [(g["game_id"], g["away_team"], "@", g["home_team"], g["p_home_win"]) for g in games]},
                     indent=2))


if __name__ == "__main__":
    if sys.argv[1] == "balldontlie":
        a = sys.argv
        forecast_bdl(Path(a[2]), Path(a[3]), Path(a[4]), Path(a[5]), a[6], a[7])
        sys.exit(0)
    if sys.argv[1] == "fallback":
        a = sys.argv
        fallback(Path(a[2]), Path(a[3]), Path(a[4]), Path(a[5]), a[6])
        sys.exit(0)
    if sys.argv[1] == "ratings":
        ratings(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    elif sys.argv[1] == "forecast":
        a = sys.argv
        forecast(Path(a[2]), Path(a[3]), Path(a[4]), a[a.index("--sha256") + 1], a[a.index("--fetched-utc") + 1],
                 a[a.index("--provenance") + 1])
    else:
        raise SystemExit(f"unknown command {sys.argv[1]}")
