"""Research's recorded GAME_PREDICTION final (receipt 3e238d2d) in Max's evidence ledger.

Nothing is recomputed: the tests check that decisions and numbers are copied verbatim, that
every source is bound by the hash of its exact bytes, that tampered sources are refused, and
that the dialogue answers GP-REST / GP-ELO from the recorded entries without writing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pytest

from heatcheck.agents import recorded as R
from heatcheck.agents.dialogue import (
    Dialogue,
    mappable_ids,
    ref_facts,
    ref_guard,
    ref_template,
)
from heatcheck.api.display_titles import DISPLAY_TITLES, display_title
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "evidence" / "evidence.jsonl"
LOOP_LOG = ROOT / "reports" / "max" / "logs" / "2026-11-07-al-fixes" / "evidence_real_game_v2.jsonl"
RESULT = json.loads((R.EVIDENCE / R.GP_RESULT).read_text(encoding="utf-8"))


def _copy_evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "evidence"
    ev.mkdir()
    for f in (R.GP_RESULT, R.GP_PLAN, R.GP_AMENDMENT, R.GP_REPLAY, "custodian_ledger.jsonl"):
        shutil.copyfile(R.EVIDENCE / f, ev / f)
    return ev


def test_recording_copies_decisions_verbatim_and_binds_sources(tmp_path):
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    out = R.record(R.game_prediction_source(), ledger)
    assert set(out) == {"GP-REST", "GP-ELO"}
    for cid, hid in (("GP-REST", "H1"), ("GP-ELO", "H2")):
        i = out[cid]["identity"]
        d = RESULT["decisions"][hid]
        assert i["decision"] == d["decision"] and i["reason"] == d["reason"]
        assert i["result"] == {k: v for k, v in d.items() if k not in ("decision", "reason")}
        assert i["claim"]["research_hypothesis_id"] == hid
        assert i["source"] == "RECORDED_RESEARCH_RESULT" and i["phase"] == "FINAL"
        assert i["lane"] == "DEVELOPMENT" and i["custodian"]["receipt_id"].startswith("3e238d2d")
        for ref in i["files"]:
            assert ref["sha256"] == hashlib.sha256((R.EVIDENCE / ref["path"]).read_bytes()).hexdigest()
        raw = (R.EVIDENCE / "custodian_ledger.jsonl").read_bytes().split(b"\n")
        for line in i["custodian"]["ledger_lines"]:
            assert line["sha256"] == hashlib.sha256(raw[line["line"] - 1]).hexdigest()
        assert [x["type"] for x in i["custodian"]["ledger_lines"]] == ["reserve", "spend", "replay"]
    assert out["GP-REST"]["identity"]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert out["GP-ELO"]["identity"]["decision"] == "SURVIVED_PROTOCOL"
    again = R.record(R.game_prediction_source(), ledger)          # idempotent
    assert len(ledger.all()) == 2
    assert {k: v["evidence_id"] for k, v in again.items()} == {k: v["evidence_id"] for k, v in out.items()}


def test_committed_ledger_holds_loop_entries_then_recorded_finals():
    led = EvidenceLedger.open_readonly(COMMITTED)
    entries = led.all()  # verifies every hash and the chain
    loop = LOOP_LOG.read_bytes()
    assert COMMITTED.read_bytes()[:len(loop)] == loop   # the earlier log, byte for byte
    assert [(e["identity"]["claim"]["claim_id"], e["identity"]["decision"]) for e in entries] == [
        ("HH-K3", "INSUFFICIENT_EVIDENCE"), ("HH-K2", "NOT_SUPPORTED"), ("GP-REST", "BLOCKED"),
        ("GP-REST", "INSUFFICIENT_EVIDENCE"), ("GP-ELO", "SURVIVED_PROTOCOL"),
        # 2024-25 confirmatory final (receipt 5cbb3222), appended 7 November by record_final_done.
        ("CONF-HA", "SURVIVED_PROTOCOL"), ("CONF-MOM", "INSUFFICIENT_EVIDENCE"),
        ("CONF-HH", "INSUFFICIENT_EVIDENCE")]
    assert {e["identity"]["custodian"]["receipt_id"] for e in entries[5:]} == {
        "5cbb3222-181d-439d-9202-02a8d8030e4e"}
    assert R.find_recorded(led, "GP-REST")["evidence_id"] == entries[3]["evidence_id"]


@pytest.mark.parametrize("tamper,match", [
    ("replay", "does not reproduce"),
    ("plan", "canonical_plan_hash"),
    ("spend", "never spent"),
    ("reserve_plan", "different plan hash"),
])
def test_tampered_sources_are_refused(tmp_path, monkeypatch, tamper, match):
    ev = _copy_evidence(tmp_path)
    if tamper == "replay":
        d = json.loads((ev / R.GP_REPLAY).read_text())
        d["decisions"]["H1"]["decision"] = "SURVIVED_PROTOCOL"
        (ev / R.GP_REPLAY).write_text(json.dumps(d))
    elif tamper == "plan":
        d = json.loads((ev / R.GP_PLAN).read_text())
        d["practical_effect_floor"] = 0.07
        (ev / R.GP_PLAN).write_text(json.dumps(d))
    else:
        lines = (ev / "custodian_ledger.jsonl").read_text().splitlines()
        out = []
        for line in lines:
            e = json.loads(line)
            if e.get("receipt_id") == R.GP_RECEIPT and e["type"] == "spend" and tamper == "spend":
                continue
            if e.get("receipt_id") == R.GP_RECEIPT and e["type"] == "reserve" and tamper == "reserve_plan":
                e["plan_hash"] = "0" * 64
                line = json.dumps(e)
            out.append(line)
        (ev / "custodian_ledger.jsonl").write_text("\n".join(out) + "\n")
    ledger = EvidenceLedger(tmp_path / "l.jsonl")
    with pytest.raises(R.RecordRefused, match=match):
        R.record(R.game_prediction_source(ev), ledger, ev)
    assert ledger.all() == []


# --------------------------------------------------------------------------- dialogue


def _dialogue(tmp_path) -> tuple[Dialogue, EvidenceLedger]:
    path = tmp_path / "copy.jsonl"
    shutil.copyfile(COMMITTED, path)
    ledger = EvidenceLedger(path)
    return Dialogue(view=None, ledger=ledger, llm=None, view_identity={"bundle": "none"}), ledger


def test_gp_rest_answers_from_the_recorded_final_not_blocked(tmp_path):
    d, ledger = _dialogue(tmp_path)
    before = ledger.path.read_bytes()
    out = d.turn("Do back-to-backs and rest days change who wins?")
    assert out["claim_id"] == "GP-REST" and out["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert out["evidence_source"] == "RECORDED_RESEARCH_RESULT" and out["phase"] == "FINAL"
    assert out["custodian_receipt_id"] == R.GP_RECEIPT
    assert out["evidence_record_id"] == R.find_recorded(ledger, "GP-REST")["evidence_id"]
    assert ledger.path.read_bytes() == before                     # nothing run, nothing written
    assert "300 unseen 2023-24 games" in out["ref_text"]
    assert out["claim_title"] == "Rest and back-to-backs on top of Elo"


def test_gp_elo_answers_survived_from_the_recorded_final(tmp_path):
    d, _ = _dialogue(tmp_path)
    out = d.turn("Does Elo beat the home-win base rate?")
    assert out["claim_id"] == "GP-ELO" and out["verdict"] == "SURVIVED_PROTOCOL"


def test_recorded_only_claim_without_record_gives_no_verdict(tmp_path):
    ledger = EvidenceLedger(tmp_path / "empty.jsonl")
    out = Dialogue(view=None, ledger=ledger, llm=None).turn("Does Elo beat a coin flip?")
    assert out["claim_id"] == "GP-ELO" and out["verdict"] is None
    assert out["evidence_record_id"] is None and ledger.all() == []


def test_ref_template_passes_the_guard_for_every_committed_entry():
    for e in EvidenceLedger.open_readonly(COMMITTED).all():
        facts = ref_facts(e)
        assert ref_guard(ref_template(facts), facts) == [], e["identity"]["claim"]["claim_id"]


def test_heater_guard_rejects_invented_number_against_recorded_entry():
    e = R.find_recorded(EvidenceLedger.open_readonly(COMMITTED), "GP-ELO")
    from heatcheck.agents.dialogue import number_violations
    assert number_violations("Elo won on 300 games, FOLKS!", ref_facts(e)) == []
    assert number_violations("Elo won on 412 games, FOLKS!", ref_facts(e)) == ["412"]


# --------------------------------------------------------------------------- display titles


def test_every_mappable_claim_has_a_display_title_outside_the_evidence():
    assert mappable_ids() | {"NONE"} <= set(DISPLAY_TITLES)
    assert display_title("HH-K2") == "Hot hand: two makes in a row"
    assert display_title("UNKNOWN-ID") == "UNKNOWN-ID"
    text = COMMITTED.read_text(encoding="utf-8")
    for title in DISPLAY_TITLES.values():
        assert title not in text                                  # never part of an identity


def test_display_titles_endpoint():
    from heatcheck.api.dialogue_server import serve
    srv = serve(object(), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/display-titles"
        with urllib.request.urlopen(url) as r:
            assert json.loads(r.read()) == {"display_titles": DISPLAY_TITLES}
    finally:
        srv.shutdown()
