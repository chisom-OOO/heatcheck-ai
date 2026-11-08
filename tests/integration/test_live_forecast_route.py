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
