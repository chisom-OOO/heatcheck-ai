"""M-002 quote eligibility tests on the SYNTHETIC reference bundle (format scope only)."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path

import pytest

from heatcheck.contracts.bundle import load_bundle
from heatcheck.contracts.eligibility import select_quote_for_cutoff

REF = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "contracts" / "syn_reference_bundle"
MIN = timedelta(minutes=5)


@pytest.fixture()
def parts():
    _, recs = load_bundle(REF)
    mapping = copy.deepcopy(next(r for r in recs if r["record_type"] == "VENUE_MAPPING"))
    quote = copy.deepcopy(next(r for r in recs if r["record_type"] == "QUOTE"))
    mapping["body"].update(status="VERIFIED", overtime_convention="INCLUDES_OVERTIME")
    return mapping, quote  # quote received 2024-01-01T00:00:00.250Z


def test_eligible_when_received_before_cutoff(parts):
    mapping, quote = parts
    sel = select_quote_for_cutoff(mapping, [quote], "2024-01-01T00:01:00Z", MIN)
    assert sel.status == "ELIGIBLE" and sel.quote_record_id == quote["record_id"]
    assert sel.age_seconds == pytest.approx(59.75)


def test_quote_received_after_cutoff_is_ineligible(parts):
    mapping, quote = parts
    # 0.250 s after the quote was fetched-started but before it was received
    sel = select_quote_for_cutoff(mapping, [quote], "2024-01-01T00:00:00.100Z", MIN)
    assert sel.status == "NO_QUOTE_BY_CUTOFF" and sel.quote_record_id is None


def test_latest_of_several_eligible_is_selected(parts):
    mapping, early = parts
    late = copy.deepcopy(early)
    late["record_id"] = early["record_id"] + "-late"
    late["body"].update(fetch_start_utc="2024-01-01T00:00:30Z", received_utc="2024-01-01T00:00:31Z")
    future = copy.deepcopy(early)
    future["record_id"] = early["record_id"] + "-future"
    future["body"].update(fetch_start_utc="2024-01-01T00:02:00Z", received_utc="2024-01-01T00:02:01Z")
    sel = select_quote_for_cutoff(mapping, [future, early, late], "2024-01-01T00:01:00Z", MIN)
    assert sel.status == "ELIGIBLE" and sel.quote_record_id == late["record_id"]


def test_stale_quote(parts):
    mapping, quote = parts
    sel = select_quote_for_cutoff(mapping, [quote], "2024-01-01T00:10:00Z", MIN)
    assert sel.status == "STALE"


def test_unverified_mapping_blocks(parts):
    mapping, quote = parts
    mapping["body"]["status"] = "BLOCKED_RULES_UNVERIFIED"
    sel = select_quote_for_cutoff(mapping, [quote], "2024-01-01T00:01:00Z", MIN)
    assert sel.status == "MAPPING_NOT_VERIFIED"


def test_latest_non_ok_quote_is_not_skipped(parts):
    mapping, quote = parts
    empty = copy.deepcopy(quote)
    empty["record_id"] += "-empty"
    empty["body"].update(
        levels=[], status="EMPTY", status_reason="no depth",
        fetch_start_utc="2024-01-01T00:00:40Z", received_utc="2024-01-01T00:00:41Z",
    )
    sel = select_quote_for_cutoff(mapping, [quote, empty], "2024-01-01T00:01:00Z", MIN)
    assert sel.status == "QUOTE_NOT_OK" and sel.quote_record_id == empty["record_id"]


def test_freshness_threshold_must_be_configured(parts):
    mapping, quote = parts
    with pytest.raises(ValueError):
        select_quote_for_cutoff(mapping, [quote], "2024-01-01T00:01:00Z", timedelta(0))
