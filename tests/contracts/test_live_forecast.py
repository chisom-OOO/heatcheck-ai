"""heatcheck-live-forecast/1 validator tests (format scope only; the fixture is a hand-made SAMPLE)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from heatcheck.contracts.live_forecast import (
    LiveForecastError,
    parse_live_forecast,
    validate_live_forecast,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "live_forecast" / "forecasts.SAMPLE.json"
REAL_SHA = "a" * 64


@pytest.fixture()
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def as_real(doc: dict) -> dict:
    """Same shape with non-sample provenance (values still invented; for format tests only)."""
    doc = copy.deepcopy(doc)
    doc["model"] = "B1 Elo, fixed constants"
    doc["source"] = {"results": "cdn.nba.com schedule JSON", "fetched_utc": "2026-11-07T21:59:00Z",
                     "sha256": REAL_SHA, "cross_check": "NOT_RUN"}
    return doc


def test_sample_fixture_is_valid_and_flagged_sample():
    lf = parse_live_forecast(FIXTURE.read_bytes())
    assert lf.is_sample is True
    assert len(lf.doc["games"]) == 2


def test_non_sample_shape_is_valid_and_not_flagged(sample):
    assert validate_live_forecast(as_real(sample)).is_sample is False


def test_empty_games_list_is_valid(sample):
    sample["games"] = []
    assert validate_live_forecast(sample).is_sample is True


def _set(path: list, value):
    def mutate(doc):
        obj = doc
        for k in path[:-1]:
            obj = obj[k]
        obj[path[-1]] = value
    return mutate


def _delete(path: list):
    def mutate(doc):
        obj = doc
        for k in path[:-1]:
            obj = obj[k]
        del obj[path[-1]]
    return mutate


INVALID = [
    ("wrong format", _set(["format"], "heatcheck-live-forecast/2"), "$.format"),
    ("wrong label", _set(["label"], "PREDICTION"), "$.label"),
    ("unknown top field", _set(["edge"], 0.1), "unknown fields ['edge']"),
    ("missing games", _delete(["games"]), "$.games: required field missing"),
    ("empty inputs", _set(["inputs_used"], []), "$.inputs_used"),
    ("duplicate input", _set(["inputs_used"], ["home_court", "home_court"]), "unique"),
    ("cutoff without Z", _set(["data_cutoff_utc"], "2026-11-07T22:00:00+00:00"), "$.data_cutoff_utc"),
    ("cutoff equals tip", _set(["data_cutoff_utc"], "2026-11-08T00:30:00Z"), "strictly before every tip_utc"),
    ("cutoff after tip", _set(["games", 1, "tip_utc"], "2026-11-07T21:00:00Z"), "$.games[1].tip_utc"),
    ("p above 1", _set(["games", 0, "p_home_win"], 1.2), "$.games[0].p_home_win: expected <= 1.0"),
    ("p negative", _set(["games", 0, "p_home_win"], -0.1), "expected >= 0.0"),
    ("p as percent string", _set(["games", 0, "p_home_win"], "60%"), "expected finite number"),
    ("p boolean", _set(["games", 0, "p_home_win"], True), "expected finite number"),
    ("bad game id namespace", _set(["games", 0, "game_id"], "syn:0022600901"), "$.games[0].game_id"),
    ("short game id", _set(["games", 0, "game_id"], "nba:226009"), "10-digit"),
    ("duplicate game id", _set(["games", 1, "game_id"], "nba:0022600901"), "duplicate game_id"),
    ("bad team id", _set(["games", 0, "home_team_id"], "BOS"), "$.games[0].home_team_id"),
    ("same teams", _set(["games", 0, "away_team_id"], "nba-team:1610612738"), "same"),
    ("unknown game field", _set(["games", 0, "edge_vs_market"], 0.05), "unknown fields"),
    ("brier above 1", _set(["backtest_2024_25", "brier"], 1.5), "$.backtest_2024_25.brier"),
    ("fractional games", _set(["backtest_2024_25", "games"], 1.5), "$.backtest_2024_25.games"),
    ("bad cross_check", _set(["source", "cross_check"], "PASS"), "$.source.cross_check"),
    ("sample hash not hex", _set(["source", "sha256"], "abc"), "$.source.sha256"),
]


@pytest.mark.parametrize("name,mutate,expected", INVALID, ids=[c[0] for c in INVALID])
def test_invalid_cases_are_refused(sample, name, mutate, expected):
    validate_live_forecast(copy.deepcopy(sample))  # unmutated base is valid
    mutate(sample)
    with pytest.raises(LiveForecastError) as exc:
        validate_live_forecast(sample)
    assert expected in str(exc.value)


def test_real_file_may_not_use_sample_placeholders(sample):
    doc = as_real(sample)
    doc["source"]["sha256"] = "SAMPLE"
    with pytest.raises(LiveForecastError, match="contains SAMPLE"):
        validate_live_forecast(doc)


def test_real_file_needs_real_fetch_time(sample):
    doc = as_real(sample)
    doc["source"]["fetched_utc"] = "today"
    with pytest.raises(LiveForecastError, match=r"\$\.source\.fetched_utc"):
        validate_live_forecast(doc)


def test_sample_marker_must_lead_results(sample):
    """A file that only mentions SAMPLE mid-string is neither a clean sample nor a clean real file."""
    sample["source"]["results"] = "cdn.nba.com (SAMPLE copy)"
    with pytest.raises(LiveForecastError, match="contains SAMPLE"):
        validate_live_forecast(sample)


@pytest.mark.parametrize("raw", [b'{"format": NaN}', b'{"a": 1, "a": 2}', b"\xff\xfe", b"[1,"])
def test_non_strict_json_is_refused(raw):
    with pytest.raises(LiveForecastError, match="strict UTF-8 JSON"):
        parse_live_forecast(raw)
