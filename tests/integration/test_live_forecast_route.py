"""GET /api/live-forecast payload: re-validated per request, invalid files never leak values."""

from __future__ import annotations

import json
from pathlib import Path

from heatcheck.api.dialogue_server import live_forecast_payload

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "live_forecast" / "forecasts.SAMPLE.json"


def test_sample_file_is_served_flagged_sample():
    out = live_forecast_payload(FIXTURE)
    assert out["status"] == "OK" and out["is_sample"] is True
    assert out["forecast"]["games"][0]["game_id"] == "nba:0022600901"


def test_unconfigured_and_missing_are_unavailable(tmp_path):
    assert live_forecast_payload(None)["status"] == "UNAVAILABLE"
    assert live_forecast_payload(tmp_path / "forecasts.json")["status"] == "UNAVAILABLE"


def test_invalid_file_returns_reason_only(tmp_path):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["games"][0]["p_home_win"] = 1.7
    bad = tmp_path / "forecasts.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    out = live_forecast_payload(bad)
    assert out["status"] == "DATA_INVALID" and "p_home_win" in out["reason"]
    assert "forecast" not in out


def test_board_hides_games_that_have_tipped_off_but_keeps_the_file(tmp_path):
    """User, 8 Nov: the board lists only games still to tip; earlier ones are counted, not shown as cards."""
    from datetime import UTC, datetime

    from heatcheck.api.dialogue_server import board_forecast_payload
    from heatcheck.contracts.records import parse_utc
    full = live_forecast_payload(FIXTURE)
    tips = sorted(parse_utc(g["tip_utc"]) for g in full["forecast"]["games"])
    before = FIXTURE.read_bytes()
    # before every tip: nothing hidden
    out = board_forecast_payload(FIXTURE, now=datetime(2000, 1, 1, tzinfo=UTC))
    assert out["forecast"]["games"] == full["forecast"]["games"] and out["earlier"]["count"] == 0
    # exactly at the first tip: that game (and any at the same time) moves to "earlier"
    out = board_forecast_payload(FIXTURE, now=tips[0])
    n_first = sum(1 for t in tips if t <= tips[0])
    assert out["earlier"]["count"] == n_first and len(out["forecast"]["games"]) == len(tips) - n_first
    assert all(parse_utc(g["tip_utc"]) > tips[0] for g in out["forecast"]["games"])
    assert set(out["earlier"]["games"][0]) == {"game_id", "away_team", "home_team", "tip_utc"}
    # after the last tip: no cards, all counted; file untouched, hash is of the whole file
    out = board_forecast_payload(FIXTURE, now=tips[-1])
    assert out["forecast"]["games"] == [] and out["earlier"]["count"] == len(tips)
    assert FIXTURE.read_bytes() == before and out["file_sha256"] == full["file_sha256"]
    # invalid / missing files pass through unchanged
    assert board_forecast_payload(None)["status"] == "UNAVAILABLE"
