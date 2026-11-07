"""Prove each candidate-level semantic check fires on a known-bad input (and not on a
known-good one), so a clean result on a candidate bundle means something."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from heatcheck.contracts.bundle import build_manifest, load_bundle, write_bundle
from heatcheck.contracts.records import record_hash
from tests.review.review_checks import experience_problems, research_problems
from tests.review.review_support import (
    GAME_ID,
    HOME,
    SYN_SNAPSHOT,
    envelope,
    first,
    of_type,
    reference_builder,
    reference_raw,
    reference_records,
    synthetic_game,
    synthetic_game_header,
)

# --------------------------------------------------------------------------- research


def clean_research() -> tuple[dict, list[dict]]:
    events = synthetic_game()
    snap = envelope("RAW_SNAPSHOT", SYN_SNAPSHOT, "SYNTHETIC", {
        "snapshot_sha256": SYN_SNAPSHOT, "provider": "synthetic", "source": "tests/review",
        "redacted_params": {}, "retrieved_utc": "2026-11-07T12:00:00Z", "byte_count": 0,
        "media_type": "application/json", "schema_version": "x",
        "rights_note": "Invented.", "bundle_path": None})
    labels = [envelope("RESTRICTED_LABEL", f"{GAME_ID}:final:r1", "SYNTHETIC", {
        "target_id": f"{GAME_ID}:final", "label_kind": "GAME_FINAL_SCORE", "game_id": GAME_ID,
        "value": {"home_points": 10, "away_points": 8}, "first_observed_utc": None,
        "revision": 1, "reconciliation": "UNVERIFIED", "source_snapshot_ids": [SYN_SNAPSHOT]})]
    for e in events:
        b = e["body"]
        if b["action"] == "SHOT":
            labels.append(envelope("RESTRICTED_LABEL", f"{GAME_ID}:shot:{b['provider_event_id']}:r1",
                                   "SYNTHETIC", {
                "target_id": f"{GAME_ID}:shot:{b['provider_event_id']}", "label_kind": "SHOT_MADE",
                "game_id": GAME_ID, "value": {"made": b["shot"]["made"]},
                "first_observed_utc": None, "revision": 1, "reconciliation": "UNVERIFIED",
                "source_snapshot_ids": [SYN_SNAPSHOT]}))
    recs = [snap, synthetic_game_header(), *events, *reference_builder(events), *labels]
    manifest, _ = build_manifest(recs, bundle_id="rv", created_by_role="RESEARCH",
                                 created_utc="2026-11-07T12:00:00Z", producer={"tool": "rv"})
    return manifest, recs


def test_research_clean_has_no_problems():
    m, recs = clean_research()
    assert research_problems(m, recs, real=False) == []


def test_research_real_mode_requirements_fire():
    m, recs = clean_research()
    probs = research_problems(m, recs, real=True)
    assert any("REAL_NBA_RETROSPECTIVE" in x for x in probs)
    assert any("2023-24 regular-season" in x for x in probs)
    assert any("A3 not met" in x for x in probs)


def _label(recs, kind, suffix=""):
    return next(r for r in recs if r["body"].get("label_kind") == kind
                and r["body"]["target_id"].endswith(suffix))


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: _label(r, "GAME_FINAL_SCORE")["body"].update(
        value={"home_points": 8, "away_points": 10}), "HOME/AWAY REVERSED"),
    (lambda r: _label(r, "GAME_FINAL_SCORE")["body"].update(
        value={"home_points": 9, "away_points": 9}), "tied"),
    (lambda r: _label(r, "SHOT_MADE", ":e2")["body"].update(value={"made": False}), "REVERSED"),
    (lambda r: next(e for e in r if e["record_id"].endswith(":e2:r1"))["body"].update(
        team_id="syn-team:OTHER"), "not in game"),
    (lambda r: next(f for f in r if f["record_type"] == "FEATURE_ROW"
                    and f["body"]["target_id"].endswith(":e5"))["body"]["cutoff"].update(
        before_sequence=6), "LEAK"),
    (lambda r: next(f for f in r if f["record_type"] == "FEATURE_ROW"
                    and f["body"]["target_id"].endswith(":e5"))["body"]["features"].update(
        shot_made_flag={"value": 1, "missing_reason": None}), "suggests outcome"),
    (lambda r: next(f for f in r if f["record_type"] == "FEATURE_ROW"
                    and f["body"]["target_id"].endswith(":e5"))["body"]["features"]
     ["player_prior_makes_in_game"].update(value=2), "reviewer recomputed"),
    (lambda r: r.remove(next(f for f in r if f["record_type"] == "FEATURE_ROW"
                             and f["body"]["target_id"].endswith(":e5"))), "no PRE_SHOT_MAKE row"),
    (lambda r: next(e for e in r if e["record_id"].endswith(":e17:r1"))["body"].update(
        clock_seconds_remaining="400.0"), "overtime period"),
])
def test_research_check_fires(mutate, needle):
    m, recs = clean_research()
    recs = copy.deepcopy(recs)
    mutate(recs)
    probs = research_problems(m, recs, real=False)
    assert any(needle in x for x in probs), probs


def test_research_leak_via_label_input_fires():
    m, recs = clean_research()
    lab = _label(recs, "SHOT_MADE", ":e5")
    row = next(f for f in recs if f["record_type"] == "FEATURE_ROW"
               and f["body"]["target_id"].endswith(":e5"))
    row["body"]["source_record_hashes"] = sorted(
        {*row["body"]["source_record_hashes"], record_hash(lab)})
    assert any("RESTRICTED_LABEL (LEAK)" in x for x in research_problems(m, recs, real=False))


# --------------------------------------------------------------------------- experience


def clean_experience(tmp: Path, mutate=None) -> tuple[Path, dict, list[dict]]:
    recs = [r for r in reference_records()
            if r["record_type"] in ("RAW_SNAPSHOT", "GAME", "VENUE_MARKET", "VENUE_MAPPING", "QUOTE")]
    q = first(recs, "QUOTE")["body"]
    q.update(fetch_start_utc="2026-11-07T11:59:59Z", received_utc="2026-11-07T12:00:00.2Z",
             provider_time_utc="2026-11-07T11:59:58Z")
    for s in of_type(recs, "RAW_SNAPSHOT"):
        s["body"]["retrieved_utc"] = "2026-11-07T12:00:00Z"
    first(recs, "GAME")["body"].update(status="SCHEDULED", scheduled_tip_utc="2026-11-08T00:30:00Z")
    mk = first(recs, "VENUE_MARKET")["body"]
    mk["outcomes"] = [{"contract_id": "M1-YES", "label": "Synthetic Home Team"},
                      {"contract_id": "M1-NO", "label": "Synthetic Away Team"}]
    first(recs, "VENUE_MAPPING")["body"]["status"] = "PROPOSED"
    if mutate:
        mutate(recs)
    manifest, body = build_manifest(recs, bundle_id="rv-e", created_by_role="EXPERIENCE",
                                    created_utc="2026-11-07T12:05:00Z",
                                    producer={"tool": "rv"}, notes="Invented fixture.")
    write_bundle(tmp, manifest, body, reference_raw())
    m, loaded = load_bundle(tmp)
    return tmp, m, loaded


def test_experience_clean_has_no_problems(tmp_path):
    d, m, recs = clean_experience(tmp_path / "b")
    assert experience_problems(d, m, recs, stale_s=60) == []


def _q(recs):
    return first(recs, "QUOTE")["body"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: _q(r)["levels"][0].update(price="0.0052"), "off tick"),
    (lambda r: _q(r)["levels"][0].update(price="0.53"), "not traceable"),
    (lambda r: _q(r)["levels"][0].update(derivation="DERIVED_COMPLEMENT"), "DIRECT only"),
    (lambda r: _q(r)["levels"][0].update(size="0"), "not positive"),
    (lambda r: _q(r).update(provider_time_utc="2026-11-07T10:00:00Z"), "STALE"),
    (lambda r: _q(r).update(provider_time_utc="2026-11-07T17:00:00Z"), "after received"),
    (lambda r: _q(r).update(provider_time_utc=None), "freshness unprovable"),
    (lambda r: _q(r).update(fetch_start_utc="2026-11-07T11:00:00Z"), "fetch took"),
    (lambda r: [s["body"].update(retrieved_utc="2024-01-01T00:00:00Z")
                for s in of_type(r, "RAW_SNAPSHOT")], "outside fetch"),
    (lambda r: first(r, "GAME")["body"].update(scheduled_tip_utc="2026-11-07T11:00:00Z"),
     "not a pre-tip"),
    (lambda r: first(r, "GAME")["body"].update(status="POSTPONED"), "status POSTPONED"),
    (lambda r: first(r, "VENUE_MAPPING")["body"].update(overtime_convention="REGULATION_ONLY"),
     "not comparable"),
    (lambda r: first(r, "VENUE_MAPPING")["body"].update(overtime_convention="INCLUDES_OVERTIME"),
     "without a rules_text_sha256"),
    (lambda r: first(r, "VENUE_MAPPING")["body"].update(status="VERIFIED",
                                                         overtime_convention="INCLUDES_OVERTIME"),
     "requires PROPOSED"),
    (lambda r: first(r, "VENUE_MARKET")["body"]["outcomes"][0].update(label="NO"),
     "manual confirmation"),
])
def test_experience_check_fires(tmp_path, mutate, needle):
    d, m, recs = clean_experience(tmp_path / "b", mutate)
    probs = experience_problems(d, m, recs, stale_s=60)
    assert any(needle in x for x in probs), probs


def test_experience_double_mapping_fires(tmp_path):
    def add(r):
        m2 = copy.deepcopy(first(r, "VENUE_MAPPING"))
        m2["record_id"] = m2["body"]["mapping_id"] = "map:2"
        m2["body"]["contract_id"] = "M1-NO"
        assert m2["body"]["team_id"] == "syn-team:HOME" and HOME  # same team, opposite contract
        r.append(m2)
    d, m, recs = clean_experience(tmp_path / "b", add)
    assert any("REVERSED?" in x for x in experience_problems(d, m, recs, stale_s=60))
