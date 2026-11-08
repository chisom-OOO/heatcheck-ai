"""M-002 mapping verification against stored rules text (Polymarket), on Experience's recorded
bundles (bytes unchanged; mutations are applied to in-memory copies)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from heatcheck.contracts.bundle import load_bundle
from heatcheck.contracts.mapping_verification import (
    NBA_TEAMS,
    apply_verifications,
    et_phrase,
    verification_doc,
    verify_polymarket_mapping,
)

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "data" / "experience" / "quotes" / "20261107T222950Z" / "0022600190-pm-2229"
E001 = ROOT / "tests" / "fixtures" / "quotes" / "e001-recorded-0022600189"


def parts(bundle=BUNDLE):
    manifest, recs = load_bundle(bundle)
    by_id = {r["record_id"]: r for r in recs}
    m = next(r for r in recs if r["record_type"] == "VENUE_MAPPING" and ":POLYMARKET:" in r["record_id"])
    market = by_id[m["body"]["venue_market_record_id"]]
    game = by_id[m["body"]["game_id"]]
    raw = (bundle / by_id[market["body"]["source_snapshot_ids"][0]]["body"]["bundle_path"]).read_bytes()
    return manifest["records_sha256"], recs, m, market, game, json.loads(raw), hashlib.sha256(raw).hexdigest()


def failed(checks):
    return {c["check"] for c in checks if c["status"] != "PASS"}


def test_et_phrase_handles_dst():
    assert et_phrase("2026-11-08T00:30:00Z") == "Saturday, November 7, 2026 at 7:30 PM ET"  # EST
    assert et_phrase("2026-10-31T23:30:00Z") == "Saturday, October 31, 2026 at 7:30 PM ET"  # EDT


def test_team_table_has_thirty_distinct_teams():
    assert len(NBA_TEAMS) == 30 and len({v[0] for v in NBA_TEAMS.values()}) == 30


@pytest.mark.parametrize("bundle", [BUNDLE, E001])
def test_recorded_polymarket_mapping_verifies(bundle):
    _, _, m, market, game, payload, sha = parts(bundle)
    assert failed(verify_polymarket_mapping(m, market, game, payload, sha)) == set()


def _rules_edit(old, new):
    def f(m, market, game, payload):
        payload["description"] = payload["description"].replace(old, new)
        market["body"]["rules_text_sha256"] = hashlib.sha256(payload["description"].encode()).hexdigest()
    return f


MUTATIONS = [
    ("rules hash differs", lambda m, mk, g, p: p.__setitem__("description", p["description"] + " "),
     "rules_text_hash"),
    ("overtime sentence removed", _rules_edit(" including any overtime periods", ""), "overtime_rule"),
    ("other team in rules", _rules_edit("Nets", "Knicks"), "rules_teams"),
    ("resolution not the winner", _rules_edit('If the Hawks win, the market will resolve to "Hawks"',
                                              'If the Hawks lose, the market will resolve to "Hawks"'),
     "rules_template"),
    ("scheduled time differs", _rules_edit("7:30 PM", "8:00 PM"), "rules_scheduled_time"),
    ("cancel rule changed", _rules_edit("resolve 50-50", "resolve to Nets"), "cancel_rule"),
    ("game start time differs", lambda m, mk, g, p: p.__setitem__("gameStartTime", "2026-11-08 01:00:00+00"),
     "game_start_time"),
    ("not moneyline", lambda m, mk, g, p: p.__setitem__("sportsMarketType", "spreads"), "moneyline"),
    ("contract is the away token", lambda m, mk, g, p: m["body"].__setitem__(
        "contract_id", json.loads(p["clobTokenIds"])[0]), "contract_is_team"),
    ("mapping says regulation only", lambda m, mk, g, p: m["body"].__setitem__(
        "overtime_convention", "REGULATION_ONLY"), "overtime_rule"),
    ("market closed", lambda m, mk, g, p: p.__setitem__("closed", True), "active"),
    ("payload not bound", lambda m, mk, g, p: mk["body"].__setitem__("source_snapshot_ids", ["0" * 64]),
     "payload_bound"),
]


@pytest.mark.parametrize("name,mutate,check", MUTATIONS, ids=[x[0] for x in MUTATIONS])
def test_each_mismatch_leaves_mapping_proposed(name, mutate, check):
    sha_b, _, m, market, game, payload, sha = parts()
    m, market, game, payload = map(copy.deepcopy, (m, market, game, payload))
    mutate(m, market, game, payload)
    try:
        doc = verification_doc(m, market, game, payload, sha, sha_b, "2026-11-07T23:00:00Z")
    except ValueError:
        return  # the mutated record is itself invalid heatcheck-records/1: also not verified
    assert check in failed(doc["checks"]), doc["checks"]
    assert doc["outcome"] == "LEFT_PROPOSED" and doc["record"] is None


def test_apply_swaps_in_verified_record_only_when_bound():
    sha_b, recs, m, market, game, payload, sha = parts()
    doc = verification_doc(m, market, game, payload, sha, sha_b, "2026-11-07T23:00:00Z")
    out, notes = apply_verifications(recs, sha_b, [doc])
    got = next(r for r in out if r["record_id"] == m["record_id"])
    assert got["body"]["status"] == "VERIFIED" and notes == []
    assert m["body"]["status"] == "PROPOSED"  # input untouched
    # Another bundle's hash: ignored.
    out, _ = apply_verifications(recs, "f" * 64, [doc])
    assert next(r for r in out if r["record_id"] == m["record_id"])["body"]["status"] == "PROPOSED"
    # The proposal changed after verification: refused.
    recs2 = copy.deepcopy(recs)
    next(r for r in recs2 if r["record_id"] == m["record_id"])["body"]["team_id"] = game["body"]["away_team_id"]
    out, notes = apply_verifications(recs2, sha_b, [doc])
    assert next(r for r in out if r["record_id"] == m["record_id"])["body"]["status"] == "PROPOSED"
    assert "changed since verification" in notes[0]
    # A forged verified record that changes the contract: refused.
    forged = copy.deepcopy(doc)
    forged["record"]["body"]["contract_id"] = json.loads(payload["clobTokenIds"])[0]
    out, notes = apply_verifications(recs, sha_b, [forged])
    assert "differs from the proposal" in notes[0]


def test_committed_verification_documents_bind_current_bundles():
    vdir = ROOT / "data" / "max" / "mapping_verifications"
    docs = sorted(vdir.glob("*.json"))
    # The first 7 (E-001 recorded + 22:29Z capture) stay; later live captures add more. Every one is checked.
    names = {f.stem for f in docs}
    assert {"e001-recorded-0022600189", *(f"0022600{n}-pm-2229" for n in range(190, 196))} <= names
    assert len(docs) >= 7
    for f in docs:
        d = json.loads(f.read_text(encoding="utf-8"))
        manifest, recs = load_bundle(ROOT / d["bundle_dir"])
        out, notes = apply_verifications(recs, manifest["records_sha256"], d["verifications"])
        assert notes == []
        status = {r["body"]["venue_market_record_id"].split(":")[0]: r["body"]["status"]
                  for r in out if r["record_type"] == "VENUE_MAPPING"}
        assert status["POLYMARKET"] == "VERIFIED"
        assert status.get("KALSHI", "PROPOSED") == "PROPOSED"  # Kalshi overtime UNKNOWN
