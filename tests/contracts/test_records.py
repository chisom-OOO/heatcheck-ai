"""Format/validator tests for heatcheck-records/1. These are contract checks, not NBA gates."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from heatcheck.contracts.bundle import BundleError, build_manifest, load_bundle, write_bundle
from heatcheck.contracts.records import (
    RecordError,
    canonical_bytes,
    encode_records,
    loads_strict,
    validate_record,
)

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "tests" / "fixtures" / "contracts" / "syn_reference_bundle"


@pytest.fixture()
def records() -> list[dict]:
    _, recs = load_bundle(REF)
    return copy.deepcopy(recs)


def first(recs: list[dict], rtype: str) -> dict:
    return next(r for r in recs if r["record_type"] == rtype)


def test_reference_bundle_loads_and_is_reproducible():
    manifest, recs = load_bundle(REF)
    assert manifest["data_modes"] == ["SYNTHETIC"]
    assert {r["record_type"] for r in recs} >= {"GAME", "EVENT", "QUOTE", "VENUE_MAPPING"}
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "make_reference_bundle.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_canonical_bytes_are_order_independent_and_reject_nonfinite():
    assert canonical_bytes({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
    with pytest.raises(RecordError):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(ValueError):
        loads_strict('{"x": NaN}')
    with pytest.raises(ValueError):
        loads_strict('{"x": 1, "x": 2}')


@pytest.mark.parametrize(
    ("rtype", "mutate", "fragment"),
    [
        ("GAME", lambda b: b.update(extra=1), "unknown fields"),
        ("GAME", lambda b: b.update(game_id="nba:0022300001"), "namespace"),
        ("GAME", lambda b: b.update(away_team_id=b["home_team_id"]), "must differ"),
        ("GAME", lambda b: b.update(season="2023-25"), "season"),
        ("GAME", lambda b: b.update(scheduled_tip_utc="2024-01-01 00:30"), "UTC"),
        ("GAME", lambda b: b.update(scheduled_tip_utc="2024-02-30T00:00:00Z"), "calendar"),
        ("EVENT", lambda b: b.update(shot=None, action="SHOT"), "shot object"),
        ("EVENT", lambda b: b.update(revision=0), ">= 1"),
        ("EVENT", lambda b: b.update(sequence=True), "integer"),
        ("FEATURE_ROW", lambda b: b.update(max_input_sequence=3), "strictly before"),
        (
            "FEATURE_ROW",
            lambda b: b["features"].update(assisted_rate={"value": 1, "missing_reason": None}),
            "post-outcome",
        ),
        (
            "FEATURE_ROW",
            lambda b: b["features"].update(x={"value": None, "missing_reason": None}),
            "exactly one",
        ),
        ("RESTRICTED_LABEL", lambda b: b["value"].update(made=True), "needs exactly"),
        ("QUOTE", lambda b: b["levels"][0].update(price="1.2"), "<= 1"),
        ("QUOTE", lambda b: b["levels"][0].update(price=0.52), "decimal string"),
        ("QUOTE", lambda b: b["levels"][0].update(price="52"), "<= 1"),
        ("QUOTE", lambda b: b["levels"][0].update(price="0.60"), "crossed"),
        ("QUOTE", lambda b: b.update(levels=[]), "use EMPTY"),
        ("QUOTE", lambda b: b.update(status="STALE"), "needs a reason"),
        ("QUOTE", lambda b: b.update(received_utc="2023-12-31T23:59:59Z"), "before fetch"),
        ("VENUE_MAPPING", lambda b: b.update(status="VERIFIED"), "overtime"),
    ],
)
def test_invalid_records_are_rejected(records, rtype, mutate, fragment):
    rec = first(records, rtype)
    validate_record(rec)
    mutate(rec["body"])
    with pytest.raises(RecordError, match=fragment):
        validate_record(rec)


def test_quote_subsecond_receive_after_fetch_is_valid(records):
    # Regression: lexical comparison put "...00.250Z" before "...00Z".
    rec = first(records, "QUOTE")
    assert rec["body"]["received_utc"].endswith(".250Z")
    validate_record(rec)


def test_envelope_checks(records):
    rec = first(records, "EVENT")  # EVENT forbids market data modes; GAME allows them
    for key, value, fragment in [
        ("protocol_version", "heatcheck-nba/2", "protocol_version"),
        ("data_mode", "LIVE_MARKET", "allows"),
        ("record_type", "SCAN", "record_type"),
    ]:
        bad = copy.deepcopy(rec)
        bad[key] = value
        with pytest.raises(RecordError, match=fragment):
            validate_record(bad)


def _copy_ref(tmp_path: Path) -> Path:
    dst = tmp_path / "bundle"
    shutil.copytree(REF, dst)
    return dst


def test_tampered_raw_payload_fails(tmp_path):
    b = _copy_ref(tmp_path)
    raw = next((b / "raw").iterdir())
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(BundleError, match="hash mismatch"):
        load_bundle(b)


def test_tampered_records_fail(tmp_path):
    b = _copy_ref(tmp_path)
    lines = (b / "records.jsonl").read_bytes().splitlines(keepends=True)
    (b / "records.jsonl").write_bytes(b"".join(reversed(lines)))
    with pytest.raises(BundleError, match="sha256"):
        load_bundle(b)


def test_crlf_conversion_is_detected(tmp_path):
    b = _copy_ref(tmp_path)
    p = b / "records.jsonl"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(BundleError):
        load_bundle(b)


def _rewrite(tmp_path: Path, recs: list[dict]) -> Path:
    manifest, _ = load_bundle(REF)
    new_manifest, body = build_manifest(
        recs,
        bundle_id=manifest["bundle_id"],
        created_by_role="MAX",
        created_utc=manifest["created_utc"],
        producer=manifest["producer"],
        notes=manifest["notes"],
    )
    out = tmp_path / "rewritten"
    shutil.copytree(REF / "raw", out / "raw")
    write_bundle(out, new_manifest, body, {})
    return out


def test_dangling_references_fail(records, tmp_path):
    mapping = first(records, "VENUE_MAPPING")
    mapping["body"]["contract_id"] = "NOT-AN-OUTCOME"
    with pytest.raises(BundleError, match="not an outcome"):
        load_bundle(_rewrite(tmp_path, records))


def test_mapping_team_must_be_participant(records, tmp_path):
    first(records, "VENUE_MAPPING")["body"]["team_id"] = "syn-team:OTHER"
    with pytest.raises(BundleError, match="participant"):
        load_bundle(_rewrite(tmp_path, records))


def test_unsafe_raw_path_fails(records, tmp_path):
    snap = first(records, "RAW_SNAPSHOT")
    snap["body"]["bundle_path"] = "../outside.json"
    with pytest.raises(BundleError, match="unsafe"):
        load_bundle(_rewrite(tmp_path, records))


def test_encoding_is_stable_under_input_order(records):
    assert encode_records(records) == encode_records(list(reversed(records)))
    assert encode_records(records) == (REF / "records.jsonl").read_bytes()


def test_cli_reports_pass_and_fail(tmp_path):
    ok = subprocess.run(
        [sys.executable, "-m", "heatcheck.contracts.bundle", str(REF)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert ok.returncode == 0 and ok.stdout.startswith("PASS"), ok.stdout + ok.stderr
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text(json.dumps({"x": 1}))
    fail = subprocess.run(
        [sys.executable, "-m", "heatcheck.contracts.bundle", str(bad)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert fail.returncode == 1 and fail.stdout.startswith("FAIL")


def _as_real(records: list[dict], market_only: bool) -> list[dict]:
    """Rewrite the synthetic reference into real-namespace shapes, for FORMAT tests only.

    The values stay invented and live only in a temp directory; nothing here is NBA or
    market evidence.
    """
    text = json.dumps(records)
    for a, b in [("syn-team:", "nba-team:"), ("syn-player:", "nba-player:"), ("syn:", "nba:")]:
        text = text.replace(a, b)
    out = []
    market_types = {"VENUE_MARKET", "VENUE_MAPPING", "QUOTE"}
    for r in json.loads(text):
        if market_only and r["record_type"] in {"EVENT", "FEATURE_ROW", "RESTRICTED_LABEL"}:
            continue
        if not market_only and r["record_type"] in market_types:
            continue
        r["data_mode"] = "RECORDED_MARKET" if market_only else "REAL_NBA_RETROSPECTIVE"
        out.append(r)
    return out


def test_experience_shape_recorded_market_bundle_validates(records, tmp_path):
    recs = _as_real(records, market_only=True)
    manifest, _ = load_bundle(_rewrite(tmp_path, recs))
    assert manifest["data_modes"] == ["RECORDED_MARKET"]


def test_research_shape_real_nba_bundle_validates(records, tmp_path):
    recs = _as_real(records, market_only=False)
    manifest, _ = load_bundle(_rewrite(tmp_path, recs))
    assert manifest["data_modes"] == ["REAL_NBA_RETROSPECTIVE"]


def test_events_cannot_attach_to_market_mode_game(records, tmp_path):
    recs = _as_real(records, market_only=False)
    first(recs, "GAME")["data_mode"] = "RECORDED_MARKET"
    with pytest.raises(BundleError, match="share its game's data_mode"):
        load_bundle(_rewrite(tmp_path, recs))


def test_real_record_cannot_reference_synthetic_game(records, tmp_path):
    first(records, "VENUE_MAPPING")["data_mode"] = "RECORDED_MARKET"
    with pytest.raises(RecordError, match="namespace"):
        load_bundle(_rewrite(tmp_path, records))


def test_game_tip_times_scheduled_or_observed(records):
    game = first(records, "GAME")
    game["body"].update(scheduled_tip_utc=None, observed_tip_utc="2024-01-01T00:35:55.7Z")
    validate_record(game)  # observed only (Research's cdnnba data has no published schedule)
    game["body"]["observed_tip_utc"] = None
    with pytest.raises(RecordError, match="scheduled_tip_utc or observed_tip_utc"):
        validate_record(game)
    game["body"]["observed_tip_utc"] = "not a time"
    with pytest.raises(RecordError, match="UTC"):
        validate_record(game)
