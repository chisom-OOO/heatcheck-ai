"""E-001 on the RECORDED capture (nba:0022600189, captured 2026-11-07T16:21:17Z):
A1 validates, A2 replays offline byte-identically, A3 detects a changed byte,
A6 is labelled RECORDED_MARKET with the original capture time."""

from __future__ import annotations

import shutil

import pytest
from conftest import ROOT

from heatcheck.contracts import bundle
from heatcheck.contracts.records import canonical_bytes, loads_strict
from heatcheck.markets.adapters import capture
from heatcheck.markets.adapters.common import AdapterError
from heatcheck.markets.adapters.replay import replay_bundle

REC = ROOT / "tests" / "fixtures" / "quotes" / "e001-recorded-0022600189"
RAW_FILES = sorted(p.name for p in (REC / "raw").iterdir())


def test_a1_recorded_bundle_validates(capsys):
    assert bundle.main([str(REC)]) == 0
    assert "modes=['RECORDED_MARKET']" in capsys.readouterr().out


def test_a2_recorded_replay_offline_is_byte_identical(no_network):
    derived = sorted(canonical_bytes(r) for r in replay_bundle(REC))
    committed = sorted(
        ln for ln in (REC / "records.jsonl").read_bytes().splitlines()
        if loads_strict(ln.decode())["record_type"] in ("VENUE_MARKET", "VENUE_MAPPING", "QUOTE")
    )
    assert derived == committed


def test_recorded_build_is_reproducible(no_network):
    meta = loads_strict((REC.parent / f"{REC.name}.build.json").read_text(encoding="utf-8"))
    manifest, body, raw = capture.build(REC, meta["rights_note"], meta["notes"],
                                        meta["created_utc"])
    assert (REC / "records.jsonl").read_bytes() == body
    assert bundle.load_bundle(REC)[0] == manifest
    assert all((REC / rel).read_bytes() == data for rel, data in raw.items())


@pytest.mark.parametrize("name", RAW_FILES)
def test_a3_recorded_changed_byte_fails(tmp_path, name, no_network):
    copy = tmp_path / REC.name
    shutil.copytree(REC, copy)
    target = copy / "raw" / name
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(bundle.BundleError, match="hash mismatch"):
        bundle.load_bundle(copy)
    with pytest.raises(AdapterError, match="does not match its sha256"):
        replay_bundle(copy)


def test_a6_recorded_labelling_and_identity():
    manifest, records = bundle.load_bundle(REC)
    assert manifest["data_modes"] == ["RECORDED_MARKET"]
    assert manifest["created_by_role"] == "EXPERIENCE"
    assert "Original capture time" in manifest["notes"]
    assert "2026-11-07T16:21:17.463932Z" in manifest["notes"]
    by_type: dict[str, list[dict]] = {}
    for r in records:
        by_type.setdefault(r["record_type"], []).append(r)
    (game,) = by_type["GAME"]
    assert game["record_id"] == "nba:0022600189"
    assert game["body"]["home_team_id"] == "nba-team:1610612754"
    quotes = {q["body"]["venue"]: q["body"] for q in by_type["QUOTE"]}
    assert set(quotes) == {"POLYMARKET", "KALSHI"}
    for q in quotes.values():
        assert q["status"] == "OK"
        assert {lv["derivation"] for lv in q["levels"]} == {"DIRECT"}
    assert {lv["side"] for lv in quotes["KALSHI"]["levels"]} == {"BID"}
    maps = {m["body"]["contract_id"]: m["body"] for m in by_type["VENUE_MAPPING"]}
    assert maps["KXNBAGAME-26NOV07DENIND-IND:yes"]["overtime_convention"] == "UNKNOWN"
    assert {m["status"] for m in maps.values()} == {"PROPOSED"}
    for snap in by_type["RAW_SNAPSHOT"]:
        if snap["body"]["provider"] in ("polymarket", "kalshi"):
            assert snap["body"]["source"].startswith("GET https://")
