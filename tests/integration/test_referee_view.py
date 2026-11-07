"""heatcheck-referee-view/1: read-only projection of a ledger entry (docs/REFEREE_VIEW_FORMAT.md)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from heatcheck.ledger.evidence import EvidenceLedger
from heatcheck.ledger.referee_view import VIEW_FORMAT, referee_view

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "reports" / "max" / "logs" / "2026-11-07-dialogue-live" / "evidence_live_turn.jsonl"
FIXTURE = ROOT / "apps" / "web" / "fixtures" / "referee" / "referee_view.sample.json"
EID = "3ff5ed9fc4faf52a0f2f4dca495d85d672802fe715b9abed9bf4264e8af8b661"


def _entry(tmp_path):
    p = tmp_path / "l.jsonl"
    shutil.copy(LIVE, p)  # never open the committed ledger log for writing
    return EvidenceLedger(p).get(EID)


def test_committed_fixture_is_the_projection_of_the_committed_entry(tmp_path):
    assert referee_view(_entry(tmp_path)) == json.loads(FIXTURE.read_text("utf-8"))


def test_projection_copies_values_and_does_not_modify_the_entry(tmp_path):
    entry = _entry(tmp_path)
    before = copy.deepcopy(entry)
    v = referee_view(entry)
    assert entry == before
    i = entry["identity"]
    assert v["format"] == VIEW_FORMAT
    assert v["derived_from"] == {"evidence_id": entry["evidence_id"], "entry_hash": entry["entry_hash"],
                                 "created_at_utc": entry["created_at_utc"]}
    assert v["verdict"] == {"decision": i["decision"], "reason": i["reason"]}
    assert [a["status"] for a in v["attacks_run"]] == [r["status"] for r in i["attack_results"]]
    assert [a["p_value"] for a in v["attacks_run"]] == [r["p_value"] for r in i["attack_results"]]
    assert v["claim"]["plan_hash"] == i["claim"]["canonical_plan_hash"] and v["claim"]["revision"] is None
    assert v["roles"]["discoverer"]["display_name"] == "Heater"
    assert v["roles"]["discoverer"]["role"] == "discoverer"
    assert "PASSED" not in json.dumps(v)


def test_committed_ledger_line_unchanged(tmp_path):
    _entry(tmp_path)
    assert LIVE.read_text("utf-8").count("\n") == 1
