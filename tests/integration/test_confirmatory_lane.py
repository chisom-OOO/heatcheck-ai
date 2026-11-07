"""CONFIRMATORY lane: dry run against Research's frozen family, and the recording path.

Research's real ``scripts/confirmatory.py final`` is never run here (user instruction: it runs
once, recorded, after the reviewer verifies the seal). The final-mode tests inject a runner
that writes a SYNTHETIC result file, to test only Max's verification and recording code.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from heatcheck.agents import confirmatory as C
from heatcheck.agents.dialogue import (
    Dialogue,
    map_schema,
    parse_mapping,
    ref_guard_allows,
)
from heatcheck.agents.loop import run_once
from heatcheck.ledger.evidence import EvidenceLedger

FAMILY = json.loads((C.EVIDENCE / C.SUBDIR / "family.json").read_text(encoding="utf-8"))
SEALED = FAMILY["sealed_data_hashes"]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _copy_handoff(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the code files and the confirmatory evidence (not the whole handoff)."""
    h = tmp_path / "handoff"
    for f in FAMILY["code_files"]:
        (h / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(C.HANDOFF / f, h / f)
    ev = h / "evidence"
    shutil.copytree(C.EVIDENCE / C.SUBDIR, ev / C.SUBDIR)
    shutil.copyfile(C.EVIDENCE / "custodian_ledger.jsonl", ev / "custodian_ledger.jsonl")
    return h, ev


def _status(report: dict) -> dict[str, str]:
    return {c["check"]: c["status"] for c in report["checks"]}


READY = {"table_hashes": lambda h, d: dict(SEALED), "platform_ok": lambda: True}


# --------------------------------------------------------------------------- dry run


def test_dry_run_on_committed_evidence_matches_and_writes_nothing():
    before = _snapshot(C.EVIDENCE)
    r = C.dry_run()
    assert _snapshot(C.EVIDENCE) == before
    st = _status(r)
    for k in ("family_manifest", "family_hypotheses", "plan:CONF-HA", "plan:CONF-MOM",
              "plan:CONF-HH", "research_code", "seal", "registration", "exposure"):
        assert st[k] == "PASS", (k, r["checks"])
    assert st["sealed_data"] == "NOT_CHECKED"  # no 2024-25 build on this machine
    assert r["ready"] is False
    assert r["family_hash"] == "684da846334bf72a7125add17130ffc00bc41749dcf0b010166a7375a2e1f9e0"
    assert r["code_hash"] == "ebf6aaa4c8e69130f85b6b06e2879d57501d383d1cf170f96a0e3dd49702f09e"
    assert not (C.EVIDENCE / C.SUBDIR / "final_result.json").exists()


def test_dry_run_ready_only_when_every_check_passes(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    r = C.dry_run(ev, tmp_path, h, **READY)
    assert r["ready"] is True and r["state"] == "UNRUN"
    r = C.dry_run(ev, tmp_path, h, table_hashes=READY["table_hashes"], platform_ok=lambda: False)
    assert r["ready"] is False and _status(r)["platform"] == "FAIL"


def test_dry_run_detects_edited_plan(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    p = ev / C.SUBDIR / "CONF-HA.plan.json"
    plan = json.loads(p.read_text())
    plan["params"]["practical_floor"] = 0.0
    p.write_text(json.dumps(plan))
    st = _status(C.dry_run(ev, tmp_path, h, **READY))
    assert st["plan:CONF-HA"] == "FAIL" and st["plan:CONF-MOM"] == "PASS"


def test_dry_run_detects_rehashed_plan_not_in_family(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    p = ev / C.SUBDIR / "CONF-HH.plan.json"
    plan = json.loads(p.read_text())
    plan["params"]["k"] = 2
    body = {k: v for k, v in plan.items() if k != "canonical_plan_hash"}
    plan["canonical_plan_hash"] = C._sha256(C._canonical_json(body))  # self-consistent edit
    p.write_text(json.dumps(plan))
    assert _status(C.dry_run(ev, tmp_path, h, **READY))["plan:CONF-HH"] == "FAIL"


def test_dry_run_detects_changed_research_code(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    k = h / "src/heatcheck/kernels.py"
    k.write_bytes(k.read_bytes() + b"\n# edited\n")
    r = C.dry_run(ev, tmp_path, h, **READY)
    assert _status(r)["research_code"] == "FAIL" and r["ready"] is False


def test_dry_run_detects_seal_and_registration_mismatch(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    led = ev / "custodian_ledger.jsonl"
    lines = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    for e in lines:
        if e["type"] == "seal" and e["epoch_id"] == FAMILY["final_epoch_id"]:
            e["input_hash"] = "0" * 64
    led.write_text("".join(json.dumps(e) + "\n" for e in lines))
    assert _status(C.dry_run(ev, tmp_path, h, **READY))["seal"] == "FAIL"
    led.write_text("".join(json.dumps(e) + "\n" for e in lines if e["type"] != "register"))
    assert _status(C.dry_run(ev, tmp_path, h, **READY))["registration"] == "FAIL"


def test_dry_run_detects_data_differing_from_seal(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    changed = {**SEALED, "game_labels": "f" * 64}
    r = C.dry_run(ev, tmp_path, h, table_hashes=lambda a, b: changed, platform_ok=lambda: True)
    c = next(c for c in r["checks"] if c["check"] == "sealed_data")
    assert c["status"] == "FAIL" and "game_labels" in c["detail"] and r["ready"] is False


def test_dry_run_detects_existing_reservation(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    with open(ev / "custodian_ledger.jsonl", "a") as f:
        f.write(json.dumps({"type": "reserve", "receipt_id": "r1", "epoch_id": FAMILY["final_epoch_id"]}) + "\n")
    r = C.dry_run(ev, tmp_path, h, **READY)
    assert _status(r)["exposure"] == "FAIL" and r["state"] == "RESERVED_INCOMPLETE"


# --------------------------------------------------------------------------- final mode (injected runner)


def _synthetic_result(ev: Path, receipt: str = "synthetic-receipt") -> dict:
    """SYNTHETIC numbers, not Research output: exercises Max's recorder only."""
    return {
        "protocol_version": "heatcheck-nba/1", "run_type": "EvaluationRun", "phase": "FINAL",
        "lane": "CONFIRMATORY", "season": "2024-25", "family_id": FAMILY["family_id"],
        "family_hash": FAMILY["canonical_family_hash"], "plan_hashes": FAMILY["hypotheses"],
        "final_epoch_id": FAMILY["final_epoch_id"], "authorised_by": "pytest",
        "exposure_receipt_id": receipt, "receipt_was_retry": False, "code_hash": FAMILY["code_hash"],
        "data_hashes": SEALED, "input_hash": FAMILY["sealed_input_hash"],
        "data_mode": "REAL_NBA_RETROSPECTIVE", "pseudo_out_of_sample": True,
        "results": {"_quarantined_games_excluded": [],
                    "CONF-HA": {"status": "EXECUTED", "n_games": 1200, "mean": 0.04,
                                "ci95": [0.01, 0.07], "p_one_sided": 0.003},
                    "CONF-MOM": {"status": "EXECUTED", "n_fga": 200000, "T": 0.002, "p_one_sided": 0.4},
                    "CONF-HH": {"status": "EXECUTED", "n_fga": 200000, "T": 0.004, "p_one_sided": 0.3}},
        "decisions": {"CONF-HA": {"decision": "SURVIVED_PROTOCOL", "reason": "Holm p<0.05, CI>0, mean>=floor",
                                  "p_one_sided": 0.003, "p_holm": 0.009},
                      "CONF-MOM": {"decision": "INSUFFICIENT_EVIDENCE", "reason": "not rejected at Holm 0.05",
                                   "p_one_sided": 0.4, "p_holm": 0.6},
                      "CONF-HH": {"decision": "INSUFFICIENT_EVIDENCE", "reason": "not rejected at Holm 0.05",
                                  "p_one_sided": 0.3, "p_holm": 0.6}},
        "multiplicity": FAMILY["multiplicity"],
        "ledger_history_of_receipt": [{"type": "reserve"}, {"type": "spend"}],
        "caveats": ["synthetic test result"], "created_at_utc": "2026-11-07T00:00:00Z",
    }


class FakeRunner:
    def __init__(self, ev: Path, result: dict | None = None):
        self.ev, self.calls, self.result = ev, [], result

    def __call__(self, argv, cwd):
        self.calls.append(argv)
        res = self.result or _synthetic_result(self.ev)
        (self.ev / C.SUBDIR / "final_result.json").write_text(json.dumps(res))
        with open(self.ev / "custodian_ledger.jsonl", "a") as f:
            for t in ("reserve", "spend"):
                f.write(json.dumps({"type": t, "receipt_id": res["exposure_receipt_id"],
                                    "epoch_id": FAMILY["final_epoch_id"]}) + "\n")

        class P:
            returncode, stderr = 0, ""
        return P()


def _lane(h, ev, tmp_path, runner, **kw):
    return C.ConfirmatoryLane(evidence=ev, data=tmp_path, handoff=h, runner=runner,
                              dry_run_kwargs=READY, **kw)


def test_dry_run_mode_never_calls_the_runner_or_writes(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    runner, ledger = FakeRunner(ev), EvidenceLedger(tmp_path / "ev.jsonl")
    out = _lane(h, ev, tmp_path, runner).evaluate("CONF-HA", ledger, {"role": "discoverer"})
    assert "dry_run" in out and runner.calls == [] and ledger.all() == []


def test_final_refuses_without_authoriser_or_when_not_ready(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    runner, ledger = FakeRunner(ev), EvidenceLedger(tmp_path / "ev.jsonl")
    with pytest.raises(C.ConfirmatoryRefused, match="authoriser"):
        _lane(h, ev, tmp_path, runner, mode="final").evaluate("CONF-HA", ledger, {})
    not_ready = C.ConfirmatoryLane(evidence=ev, data=None, handoff=h, runner=runner, mode="final",
                                   authorised_by="pytest")
    with pytest.raises(C.ConfirmatoryRefused, match="not ready"):
        not_ready.evaluate("CONF-HA", ledger, {})
    assert runner.calls == [] and ledger.all() == []
    with pytest.raises(C.ConfirmatoryRefused):
        _lane(h, ev, tmp_path, runner).evaluate("HH-K3", ledger, {})


def test_final_records_all_three_once_marked_confirmatory(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    runner, ledger = FakeRunner(ev), EvidenceLedger(tmp_path / "ev.jsonl")
    lane = _lane(h, ev, tmp_path, runner, mode="final", authorised_by="pytest")
    out = lane.evaluate("CONF-MOM", ledger, {"role": "discoverer", "rationale": "q"})
    assert len(runner.calls) == 1 and runner.calls[0][2:4] == [C.SCRIPT, "final"]
    assert runner.calls[0][-2:] == ["--authorised-by", "pytest"]
    entries = ledger.all()
    assert len(entries) == 3
    assert {e["identity"]["lane"] for e in entries} == {"CONFIRMATORY"}
    assert out["entry"]["identity"]["claim"]["claim_id"] == "CONF-MOM"
    assert out["entries"]["CONF-HA"]["identity"]["decision"] == "SURVIVED_PROTOCOL"
    assert out["entry"]["identity"]["family"]["canonical_family_hash"] == FAMILY["canonical_family_hash"]
    # A second question reuses the finished, verified run: no rerun, no new entries.
    out2 = lane.evaluate("CONF-HA", ledger, {"role": "discoverer"})
    assert len(runner.calls) == 1 and len(ledger.all()) == 3
    assert out2["entry"]["evidence_id"] == out["entries"]["CONF-HA"]["evidence_id"]


@pytest.mark.parametrize("field,value", [("family_hash", "0" * 64), ("code_hash", "0" * 64),
                                         ("data_hashes", {**SEALED, "events": "0" * 64}),
                                         ("lane", "DEVELOPMENT")])
def test_final_result_not_matching_the_family_is_refused(tmp_path, field, value):
    h, ev = _copy_handoff(tmp_path)
    res = {**_synthetic_result(ev), field: value}
    ledger = EvidenceLedger(tmp_path / "ev.jsonl")
    lane = _lane(h, ev, tmp_path, FakeRunner(ev, res), mode="final", authorised_by="pytest")
    with pytest.raises(C.ConfirmatoryRefused, match=field):
        lane.evaluate("CONF-HA", ledger, {})
    assert ledger.all() == []


def test_final_result_without_custodian_spend_is_refused(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    (ev / C.SUBDIR / "final_result.json").write_text(json.dumps(_synthetic_result(ev)))
    with pytest.raises(C.ConfirmatoryRefused, match="not reserved|not spent"):
        C.verify_final_result(_synthetic_result(ev), ev)


# --------------------------------------------------------------------------- dialogue


def test_mapping_accepts_confirmatory_ids():
    assert parse_mapping('{"claim_id": "CONF-HH"}') == "CONF-HH"
    enum = map_schema()["json_schema"]["schema"]["properties"]["claim_id"]["enum"]
    assert {"CONF-HA", "CONF-MOM", "CONF-HH"} <= set(enum)
    with pytest.raises(ValueError):
        parse_mapping('{"claim_id": "CONF-XX"}')


def test_dialogue_confirmatory_turn_in_dry_run_runs_nothing(tmp_path):
    before = _snapshot(C.EVIDENCE)
    ledger = EvidenceLedger(tmp_path / "ev.jsonl")
    d = Dialogue(view=None, ledger=ledger, llm=None, view_identity={"bundle": "none"})
    out = d.turn("Do home teams really win more often?")
    assert out["claim_id"] == "CONF-HA" and out["lane"] == "CONFIRMATORY"
    assert out["verdict"] is None and out["evidence_record_id"] is None
    assert out["confirmatory_status"] == "UNRUN_NOT_READY"
    assert "has not been run" in out["ref_text"] and "plans, code and seal match" in out["ref_text"]
    assert "not checked on this machine" in out["ref_text"]
    assert ledger.all() == [] and _snapshot(C.EVIDENCE) == before


def test_dialogue_confirmatory_final_turn_speaks_from_the_record(tmp_path):
    h, ev = _copy_handoff(tmp_path)
    ledger = EvidenceLedger(tmp_path / "ev.jsonl")
    lane = _lane(h, ev, tmp_path, FakeRunner(ev), mode="final", authorised_by="pytest")
    d = Dialogue(view=None, ledger=ledger, llm=None, view_identity={"bundle": "none"}, confirmatory=lane)
    out = d.turn("Is home court advantage real?")
    entry = next(e for e in ledger.all() if e["evidence_id"] == out["evidence_record_id"])
    assert out["verdict"] == entry["identity"]["decision"] == "SURVIVED_PROTOCOL"
    assert out["lane"] == "CONFIRMATORY" and "CONF-HA" in out["ref_text"]
    assert ref_guard_allows("Home teams won 1200 games under the rule.", entry)
    assert not ref_guard_allows("Home teams won 1234 games under the rule.", entry)  # invented


def test_development_loop_entries_are_marked_development(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ev.jsonl")
    entry = run_once(None, ledger, view_identity={"bundle": "none"})
    assert entry["identity"]["lane"] == "DEVELOPMENT"
