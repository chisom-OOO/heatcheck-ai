"""E-001 A1, A2, A6: the committed bundle validates, replays offline byte-identically,
and is labelled for what was actually done."""

from __future__ import annotations

import socket

import pytest
from conftest import BUNDLE

from heatcheck.contracts import bundle
from heatcheck.contracts.records import canonical_bytes, loads_strict
from heatcheck.markets.adapters.replay import replay_bundle

DERIVED_TYPES = ("VENUE_MARKET", "VENUE_MAPPING", "QUOTE")


def committed_lines(types: tuple[str, ...]) -> list[bytes]:
    lines = (BUNDLE / "records.jsonl").read_bytes().splitlines()
    return [ln for ln in lines if loads_strict(ln.decode("utf-8"))["record_type"] in types]


def test_a1_validator_cli_passes(capsys):
    assert bundle.main([str(BUNDLE)]) == 0
    assert capsys.readouterr().out.startswith("PASS ")


def test_a2_replay_offline_is_byte_identical(no_network):
    with pytest.raises(AssertionError, match="network access attempted"):
        socket.socket()
    derived = replay_bundle(BUNDLE)
    got = sorted(canonical_bytes(r) for r in derived)
    assert got == sorted(committed_lines(DERIVED_TYPES))
    counts = {t: sum(r["record_type"] == t for r in derived) for t in DERIVED_TYPES}
    assert counts == {"VENUE_MARKET": 2, "VENUE_MAPPING": 2, "QUOTE": 2}


def test_generator_reproduces_committed_bundle(builder):
    manifest, body, raw = builder.build()
    assert (BUNDLE / "records.jsonl").read_bytes() == body
    on_disk, _ = bundle.load_bundle(BUNDLE)
    assert on_disk == manifest
    for rel, data in raw.items():
        assert (BUNDLE / rel).read_bytes() == data


def test_a6_labelled_as_synthetic():
    manifest, records = bundle.load_bundle(BUNDLE)
    assert manifest["data_modes"] == ["SYNTHETIC"]
    assert manifest["created_by_role"] == "EXPERIENCE"
    assert "SYNTHETIC FALLBACK" in manifest["notes"]
    assert "no original capture time" in manifest["notes"].lower()
    assert "G12 stays NOT_RUN" in manifest["notes"]
    assert {r["data_mode"] for r in records} == {"SYNTHETIC"}
    for r in records:
        if r["record_type"] == "RAW_SNAPSHOT":
            assert r["body"]["rights_note"].startswith("SYNTHETIC")
        if r["record_type"] == "QUOTE":
            assert {lv["derivation"] for lv in r["body"]["levels"]} == {"DIRECT"}
        if r["record_type"] == "VENUE_MAPPING":
            assert r["body"]["status"] == "PROPOSED"


def test_bundle_is_small():
    total = sum(p.stat().st_size for p in BUNDLE.rglob("*") if p.is_file())
    assert total < 1_000_000
