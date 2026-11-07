"""live_forecast.forecast(): logic on a SYNTHETIC test schedule in the scheduleLeagueV2 shape (test fixture,
never data). Checks: payload hash binding, D5 date rule, required games, cutoff before every tip, output
fields. Real-schedule parsing is verified on Max's raw file when it arrives."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_forecast_cli", ROOT / "scripts/live_forecast.py")
LF = importlib.util.module_from_spec(spec); spec.loader.exec_module(LF)


def _g(gid, utc, status, home, away, hs=None, as_=None, neutral=False):
    return {"gameId": gid, "gameStatus": status, "gameDateTimeUTC": utc, "isNeutral": neutral,
            "homeTeam": {"teamId": home, "teamCity": "Home", "teamName": str(home), "score": hs},
            "awayTeam": {"teamId": away, "teamCity": "Away", "teamName": str(away), "score": as_}}


def _setup(tmp_path, extra=(), drop=None):
    games = [_g("0022600100", "2026-11-06T00:00:00Z", 3, 1610612738, 1610612752, 110, 100),   # Nov 5 ET: used
             _g("0022600150", "2026-11-07T17:00:00Z", 3, 1610612743, 1610612747, 90, 99)]     # Nov 7 ET: not used
    games += [_g(gid, "2026-11-08T00:30:00Z", 1, 1610612737 + i, 1610612750 + i)
              for i, gid in enumerate(LF.REQUIRED_IDS) if gid != drop]
    games += list(extra)
    raw = json.dumps({"leagueSchedule": {"gameDates": [{"games": games}]}}).encode()
    (tmp_path / "sched.json").write_bytes(raw)
    st = {"ratings_2026_27_start": {str(t): 1505.0 for t in range(1610612737, 1610612767)},
          "backtest_2024_25": {"log_loss": 0.63, "brier": 0.22, "games": 1230},
          "last_completed_game_utc": "2026-04-13T03:05:51Z"}
    (tmp_path / "elo_state.json").write_text(json.dumps(st))
    return hashlib.sha256(raw).hexdigest()


def test_forecast_shape_cutoff_and_date_rule(tmp_path):
    sha = _setup(tmp_path)
    LF.forecast(tmp_path, tmp_path / "sched.json", tmp_path / "f.json", sha, "2026-11-07T23:10:00Z", "TEST")
    f = json.loads((tmp_path / "f.json").read_text())
    assert f["label"] == "DESCRIPTIVE FORECAST" and f["source"]["sha256"] == sha and len(f["games"]) == 7
    assert f["data_cutoff_utc"] == "2026-11-06T04:00:00Z"            # last used tip + 4 h bound
    assert all(g["tip_utc"] > f["data_cutoff_utc"] for g in f["games"])
    g = f["games"][0]
    assert set(g) == {"game_id", "tip_utc", "home_team_id", "away_team_id", "home_team", "away_team",
                      "p_home_win", "elo_home", "elo_away"} and g["game_id"].startswith("nba:")
    assert 0 < g["p_home_win"] < 1


def test_same_day_results_not_used_and_hash_and_required_ids(tmp_path):
    sha = _setup(tmp_path)
    with pytest.raises(SystemExit, match="sha256"):
        LF.forecast(tmp_path, tmp_path / "sched.json", tmp_path / "f.json", "0" * 64, "x", "TEST")
    sha2 = _setup(tmp_path, drop="0022600189")
    with pytest.raises(SystemExit, match="0022600189"):
        LF.forecast(tmp_path, tmp_path / "sched.json", tmp_path / "f.json", sha2, "x", "TEST")


def test_home_court_and_neutral():
    assert LF.p_home(1505, 1505) == pytest.approx(1 / (1 + 10 ** (-100 / 400)))
    assert LF.p_home(1505, 1505, neutral=True) == pytest.approx(0.5)
