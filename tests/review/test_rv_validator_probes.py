"""Reviewer probes of the shared validator (heatcheck/contracts, M-001).

Each test states the behaviour the spec (docs/DATA_FORMAT.md, docs/team/*, DATA_PIPELINE.md,
ACCEPTANCE.json) implies. A failing test here is a reviewer FINDING against the validator,
not a test bug: it means a malformed bundle in that category is reported PASS. Do not mark
these xfail to make the run green; record the outcome instead.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from heatcheck.contracts.bundle import BundleError, build_manifest, load_bundle, write_bundle
from heatcheck.contracts.records import RecordError, record_hash, validate_record
from tests.review.review_support import first, of_type, reference_raw, reference_records

REJECT = (BundleError, RecordError, ValueError)


def bundle_result(tmp_path: Path, recs: list[dict], created_utc: str = "2026-11-07T12:00:00Z"):
    """Write ``recs`` as a bundle and load it. Returns None on PASS, else the error."""
    try:
        manifest, body = build_manifest(
            recs, bundle_id="rv", created_by_role="MAX", created_utc=created_utc,
            producer={"tool": "tests/review", "version": "1"},
        )
        write_bundle(tmp_path / "b", manifest, body, reference_raw())
        load_bundle(tmp_path / "b")
    except REJECT as exc:
        return exc
    return None


def assert_rejected(tmp_path: Path, recs: list[dict], why: str) -> None:
    err = bundle_result(tmp_path, recs)
    assert err is not None, f"EXPECTED REJECT, ACTUAL PASS: {why}"


@pytest.fixture()
def recs() -> list[dict]:
    return reference_records()


def shot(recs: list[dict], peid: str) -> dict:
    return next(r for r in of_type(recs, "EVENT") if r["body"]["provider_event_id"] == peid)


def test_control_reference_bundle_passes(tmp_path, recs):
    assert bundle_result(tmp_path, recs) is None


# =========================================================================== pre-shot leakage


def test_rv_l1_max_input_sequence_equal_to_cutoff_rejected(recs):
    fr = first(recs, "FEATURE_ROW")
    fr["body"]["max_input_sequence"] = fr["body"]["cutoff"]["before_sequence"]
    with pytest.raises(RecordError):
        validate_record(fr)


def test_rv_l2_utc_cutoff_fractional_second_leak_rejected(recs):
    fr = first(recs, "FEATURE_ROW")
    fr["body"]["cutoff"] = {"kind": "UTC", "utc": "2024-01-01T00:30:00Z",
                            "game_id": None, "before_sequence": None}
    fr["body"]["max_input_available_utc"] = "2024-01-01T00:30:00.5Z"
    with pytest.raises(RecordError):
        validate_record(fr)


def test_rv_l3_cutoff_after_target_shot_rejected(tmp_path, recs):
    """Row for shot e3 (sequence 3) declares cutoff 4 and inputs up to 3: e3 itself is input."""
    fr = first(recs, "FEATURE_ROW")
    assert fr["body"]["target_id"].endswith(":e3")
    fr["body"]["cutoff"]["before_sequence"] = 4
    fr["body"]["max_input_sequence"] = 3
    assert_rejected(tmp_path, recs, "PRE_SHOT_MAKE cutoff is later than its own shot")


def test_rv_l4_source_hashes_include_target_shot_rejected(tmp_path, recs):
    fr = first(recs, "FEATURE_ROW")
    e3 = shot(recs, "e3")
    fr["body"]["source_record_hashes"] = sorted(
        {*fr["body"]["source_record_hashes"], record_hash(e3)})
    assert_rejected(tmp_path, recs, "feature inputs list the target shot's own EVENT hash")


def test_rv_l5_target_id_resolves_to_no_event_rejected(tmp_path, recs):
    fr = first(recs, "FEATURE_ROW")
    fr["body"]["target_id"] = "syn:G0001:shot:e999"
    assert_rejected(tmp_path, recs, "PRE_SHOT_MAKE target_id names no shot in the bundle")


def test_rv_l6_source_hashes_reference_unknown_records_rejected(tmp_path, recs):
    fr = first(recs, "FEATURE_ROW")
    fr["body"]["source_record_hashes"] = ["f" * 64]
    assert_rejected(tmp_path, recs, "source_record_hashes names a record not in the bundle")


def test_rv_l7_reference_fixture_inputs_precede_cutoff(recs):
    """Control on Max's own fixture: every declared input hash is an earlier EVENT."""
    fr = first(recs, "FEATURE_ROW")
    by_hash = {record_hash(r): r for r in recs}
    for h in fr["body"]["source_record_hashes"]:
        assert h in by_hash, f"fixture input {h} is not a record in the bundle"
        assert by_hash[h]["body"]["sequence"] < fr["body"]["cutoff"]["before_sequence"]


# =========================================================================== games and teams


def test_rv_g1_event_team_not_in_game_rejected(tmp_path, recs):
    shot(recs, "e2")["body"]["team_id"] = "syn-team:OTHER"
    assert_rejected(tmp_path, recs, "EVENT team_id is not home or away of its game")


def test_rv_g2_feature_row_target_from_other_game_rejected(tmp_path, recs):
    g2 = copy.deepcopy(first(recs, "GAME"))
    g2["record_id"] = g2["body"]["game_id"] = "syn:G0002"
    recs.append(g2)
    fr = first(recs, "FEATURE_ROW")
    fr["body"]["game_id"] = fr["body"]["cutoff"]["game_id"] = "syn:G0002"
    # target_id still names syn:G0001's shot e3
    assert_rejected(tmp_path, recs, "FEATURE_ROW for game G0002 targets a G0001 shot")


def test_rv_g3_team_win_label_team_not_in_game_rejected(tmp_path, recs):
    lab = copy.deepcopy(first(recs, "RESTRICTED_LABEL"))
    lab["record_id"] = "syn:G0001:team_win:r1"
    lab["body"].update(target_id="syn:G0001:team_win", label_kind="TEAM_WIN",
                       value={"team_id": "syn-team:OTHER", "won": True})
    recs.append(lab)
    assert_rejected(tmp_path, recs, "TEAM_WIN label for a team not in the game")


def test_rv_g4_mapping_team_not_in_game_rejected(tmp_path, recs):
    first(recs, "VENUE_MAPPING")["body"]["team_id"] = "syn-team:OTHER"
    assert_rejected(tmp_path, recs, "mapping team not a participant")


def test_rv_g5_quote_contract_not_mapping_contract_rejected(tmp_path, recs):
    first(recs, "QUOTE")["body"]["contract_id"] = "M1-NO"
    assert_rejected(tmp_path, recs, "quote contract differs from its mapping")


def test_rv_g6_real_id_in_synthetic_record_rejected(recs):
    g = first(recs, "GAME")
    g["body"]["home_team_id"] = "nba-team:1610612747"
    with pytest.raises(RecordError):
        validate_record(g)


def test_rv_g7_mapping_game_mismatch_with_shot_game_rejected(tmp_path, recs):
    """Mapping points at a second game with the same teams on another date."""
    g2 = copy.deepcopy(first(recs, "GAME"))
    g2["record_id"] = g2["body"]["game_id"] = "syn:G0002"
    g2["body"]["scheduled_tip_utc"] = "2024-02-01T00:30:00Z"
    recs.append(g2)
    first(recs, "VENUE_MAPPING")["body"]["game_id"] = "syn:G0002"
    # Nothing in the format binds a market to a date, so this is expected to PASS the
    # validator; it is documented as a candidate-level check (test_rv_experience_*).
    assert bundle_result(tmp_path, recs) is None


# =========================================================================== reversed outcomes


def test_rv_o1_final_score_swapped_against_events_rejected(tmp_path, recs):
    lab = first(recs, "RESTRICTED_LABEL")
    assert lab["body"]["value"] == {"away_points": 0, "home_points": 2}
    lab["body"]["value"] = {"away_points": 2, "home_points": 0}
    assert_rejected(tmp_path, recs, "GAME_FINAL_SCORE home/away reversed vs EVENT points")


def test_rv_o2_shot_made_label_contradicts_event_rejected(tmp_path, recs):
    lab = copy.deepcopy(first(recs, "RESTRICTED_LABEL"))
    lab["record_id"] = "syn:G0001:shot:e2:r1"
    lab["body"].update(target_id="syn:G0001:shot:e2", label_kind="SHOT_MADE",
                       value={"made": False})  # EVENT e2 says made=True
    recs.append(lab)
    assert_rejected(tmp_path, recs, "SHOT_MADE label contradicts EVENT.shot.made")


def test_rv_o3_team_win_contradicts_final_score_rejected(tmp_path, recs):
    lab = copy.deepcopy(first(recs, "RESTRICTED_LABEL"))
    lab["record_id"] = "syn:G0001:team_win:r1"
    lab["body"].update(target_id="syn:G0001:team_win", label_kind="TEAM_WIN",
                       value={"team_id": "syn-team:AWAY", "won": True})  # away scored 0
    recs.append(lab)
    assert_rejected(tmp_path, recs, "TEAM_WIN says the losing team won")


def test_rv_o4_final_tie_rejected(tmp_path, recs):
    first(recs, "RESTRICTED_LABEL")["body"]["value"] = {"away_points": 2, "home_points": 2}
    assert_rejected(tmp_path, recs, "FINAL NBA game cannot end tied")


def test_rv_o5_quote_level_derived_complement_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["levels"][1]["derivation"] = "DERIVED_COMPLEMENT"
    with pytest.raises(RecordError):
        validate_record(q)  # DATA_FORMAT: QUOTE levels are stored as the venue gave them


def test_rv_o6_bid_ask_swapped_ok_rejected(recs):
    q = first(recs, "QUOTE")
    for lv in q["body"]["levels"]:
        lv["side"] = "ASK" if lv["side"] == "BID" else "BID"
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_o7_both_outcomes_mapped_to_same_team_win_rejected(tmp_path, recs):
    m2 = copy.deepcopy(first(recs, "VENUE_MAPPING"))
    m2["record_id"] = m2["body"]["mapping_id"] = "map:syn:G0001:M1-NO"
    m2["body"]["contract_id"] = "M1-NO"  # label AWAY, but team_id still HOME
    recs.append(m2)
    assert_rejected(tmp_path, recs, "YES and NO of one market both mapped to HOME TEAM_WINS")


# =========================================================================== units and timestamps


def test_rv_u1_cents_price_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["levels"][0]["price"] = "53"
    with pytest.raises(RecordError):
        validate_record(q)


@pytest.mark.parametrize("price", ["0.537", "0.0053", "0.005"])
def test_rv_u2_off_tick_price_rejected(tmp_path, recs, price):
    """Market tick_size is 0.01; '0.0053' is a cents value divided by 100 twice."""
    first(recs, "QUOTE")["body"]["levels"][0]["price"] = price
    assert_rejected(tmp_path, recs, f"price {price} is off the market's 0.01 tick grid")


def test_rv_u3_zero_size_level_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["levels"][0]["size"] = "0"
    with pytest.raises(RecordError):
        validate_record(q)


@pytest.mark.parametrize("ts", [
    "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00", "2024-01-01 00:00:00Z",
    "1704067200", "2024-01-01T00:00:00.1234567Z", "2024-02-30T00:00:00Z",
])
def test_rv_u4_non_canonical_timestamps_rejected(recs, ts):
    q = first(recs, "QUOTE")
    q["body"]["received_utc"] = ts
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_u5_epoch_millis_integer_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["received_utc"] = 1704067200000
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_u6_received_before_fetch_fractional_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["fetch_start_utc"] = "2024-01-01T00:00:00.5Z"
    q["body"]["received_utc"] = "2024-01-01T00:00:00Z"
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_u7_provider_time_after_received_rejected(recs):
    """Provider stamp 5 h after receipt: the signature of local time mislabelled as UTC."""
    q = first(recs, "QUOTE")
    q["body"]["provider_time_utc"] = "2024-01-01T05:00:01Z"
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_u8_raw_snapshot_time_outside_fetch_window_rejected(tmp_path, recs):
    """Quote fetched 2024-01-01T00:00; its raw book snapshot says retrieved 2026-11-07."""
    q = first(recs, "QUOTE")
    snap = next(r for r in recs if r["record_id"] == q["body"]["raw_snapshot_id"])
    assert snap["body"]["retrieved_utc"] == "2026-11-07T12:00:00Z"
    assert_rejected(tmp_path, recs, "raw snapshot retrieved_utc outside quote fetch window")


def test_rv_u9_manifest_created_utc_is_validated(tmp_path, recs):
    err = bundle_result(tmp_path, recs, created_utc="yesterday afternoon")
    assert err is not None, "EXPECTED REJECT, ACTUAL PASS: manifest created_utc not a UTC stamp"


# =========================================================================== stale quotes


def test_rv_s1_ok_quote_with_two_hour_old_provider_time_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["provider_time_utc"] = "2023-12-31T22:00:00Z"  # received 2024-01-01T00:00:00Z
    with pytest.raises(RecordError):
        validate_record(q)  # needs STALE or a configured freshness threshold


def test_rv_s2_ok_quote_with_one_day_fetch_window_rejected(recs):
    q = first(recs, "QUOTE")
    q["body"]["fetch_start_utc"] = "2023-12-31T00:00:00Z"
    with pytest.raises(RecordError):
        validate_record(q)


def test_rv_s3_stale_quote_requires_reason(recs):
    q = first(recs, "QUOTE")
    q["body"]["status"] = "STALE"
    q["body"]["status_reason"] = None
    with pytest.raises(RecordError):
        validate_record(q)


# =========================================================================== overtime rules


def _verified(recs: list[dict], **changes: str) -> None:
    m = first(recs, "VENUE_MAPPING")["body"]
    market = first(recs, "VENUE_MARKET")["body"]
    market["rules_text_sha256"] = "a" * 64
    m.update(status="VERIFIED", overtime_convention="INCLUDES_OVERTIME",
             cancel_postpone_convention="VOID_ON_POSTPONEMENT_PAST_48H")
    m.update(changes)


def test_rv_t0_control_verified_includes_overtime_passes(tmp_path, recs):
    _verified(recs)
    assert bundle_result(tmp_path, recs) is None


def test_rv_t1_verified_unknown_overtime_rejected(recs):
    _verified(recs, overtime_convention="UNKNOWN")
    with pytest.raises(RecordError):
        validate_record(first(recs, "VENUE_MAPPING"))


def test_rv_t2_verified_regulation_only_for_team_wins_rejected(recs):
    """Research §143: a full-game TEAM_WINS target and a regulation-only contract differ."""
    _verified(recs, overtime_convention="REGULATION_ONLY")
    with pytest.raises(RecordError):
        validate_record(first(recs, "VENUE_MAPPING"))


def test_rv_t3_verified_unknown_cancel_postpone_rejected(recs):
    """ACCEPTANCE G10: 'regulation/overtime/cancel mapping; unknowns block'."""
    _verified(recs, cancel_postpone_convention="UNKNOWN")
    with pytest.raises(RecordError):
        validate_record(first(recs, "VENUE_MAPPING"))


def test_rv_t4_verified_without_rules_hash_rejected(tmp_path, recs):
    _verified(recs)
    first(recs, "VENUE_MARKET")["body"]["rules_text_sha256"] = None
    assert_rejected(tmp_path, recs, "VERIFIED mapping whose market has no rules hash")
