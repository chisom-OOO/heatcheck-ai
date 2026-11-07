"""Hash-chained evidence ledger (RV-AL1/AL2) and EvidenceLedger.open_readonly()."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from heatcheck.contracts.records import canonical_bytes, sha256_hex
from heatcheck.ledger.evidence import GENESIS, EvidenceLedger, LedgerError, evidence_id

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "reports" / "max" / "logs" / "2026-11-07-loop" / "evidence_real_game.jsonl"
# Values from the pre-chain ledger (commit cb7320c). The migration must not change them.
ORIGINAL_IDS = ["2c754d04a06536b1594b0cfc6eb851ad2c9b5686925e19c6fb00c82040c86000"]


def ident(i: int) -> dict:
    return {"claim": {"claim_id": f"T{i}"}, "decision": "NOT_SUPPORTED", "n": i}


def write(path: Path, entries: list[dict]) -> None:
    path.write_text("".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n"
                            for e in entries), "utf-8")


def three(tmp_path) -> tuple[EvidenceLedger, list[dict]]:
    led = EvidenceLedger(tmp_path / "l.jsonl")
    for i in range(3):
        led.put(ident(i))
    return led, led.all()


def test_chain_links_and_head(tmp_path):
    led, es = three(tmp_path)
    assert es[0]["prev_chain_hash"] == GENESIS
    assert [e["prev_chain_hash"] for e in es[1:]] == [e["chain_hash"] for e in es[:-1]]
    assert led.head() == es[-1]["chain_hash"]
    again, retried = led.put(ident(1))
    assert retried and again == es[1] and len(led.all()) == 3


@pytest.mark.parametrize("attack", ["forge_middle", "delete_first", "delete_middle", "swap",
                                    "insert_copy", "edit_chain_field"])
def test_tampering_detected(tmp_path, attack):
    _, es = three(tmp_path)
    es = copy.deepcopy(es)
    if attack == "forge_middle":  # edit identity, recompute evidence_id and entry_hash
        e = es[1]
        e["identity"]["decision"] = "SURVIVED_PROTOCOL"
        e["evidence_id"] = evidence_id(e["identity"])
        e["entry_hash"] = sha256_hex(canonical_bytes(e["identity"]) + e["created_at_utc"].encode())
    elif attack == "delete_first":
        es = es[1:]
    elif attack == "delete_middle":
        es = [es[0], es[2]]
    elif attack == "swap":
        es = [es[1], es[0], es[2]]
    elif attack == "insert_copy":
        es = [es[0], es[0], es[1], es[2]]
    elif attack == "edit_chain_field":
        es[2]["chain_hash"] = "f" * 64
    write(tmp_path / "t.jsonl", es)
    with pytest.raises(LedgerError):
        EvidenceLedger.open_readonly(tmp_path / "t.jsonl").all()


def test_truncating_the_tail_needs_an_external_head(tmp_path):
    """Documented limit: the chain alone cannot see removed final lines; a recorded head can."""
    led, es = three(tmp_path)
    head = led.head()
    write(tmp_path / "t.jsonl", es[:2])
    short = EvidenceLedger.open_readonly(tmp_path / "t.jsonl")
    assert len(short.all()) == 2 and short.head() != head


def test_legacy_unchained_line_refused(tmp_path):
    _, es = three(tmp_path)
    legacy = {k: es[0][k] for k in ("evidence_id", "identity", "created_at_utc", "entry_hash")}
    write(tmp_path / "t.jsonl", [legacy])
    with pytest.raises(LedgerError, match="legacy"):
        EvidenceLedger.open_readonly(tmp_path / "t.jsonl").all()


def test_open_readonly_never_creates_or_writes(tmp_path):
    with pytest.raises(LedgerError):
        EvidenceLedger.open_readonly(tmp_path / "missing.jsonl")
    assert not (tmp_path / "missing.jsonl").exists()
    led, _ = three(tmp_path)
    before = led.path.read_bytes()
    ro = EvidenceLedger.open_readonly(led.path)
    assert len(ro.all()) == 3
    with pytest.raises(LedgerError, match="read-only"):
        ro.put(ident(9))
    assert led.path.read_bytes() == before


def test_committed_ledger_migrated_without_changing_evidence(tmp_path):
    es = EvidenceLedger.open_readonly(COMMITTED).all()
    assert es[0]["evidence_id"] == ORIGINAL_IDS[0]
    assert [e["identity"]["decision"] for e in es] == ["INSUFFICIENT_EVIDENCE", "NOT_SUPPORTED", "BLOCKED"]
    # The committed pre-chain bytes (git) and the migrated file agree on every original field.
    old = subprocess.run(["git", "show", f"cb7320c:{COMMITTED.relative_to(ROOT).as_posix()}"],
                         cwd=ROOT, capture_output=True, check=False)
    if old.returncode != 0:
        pytest.skip("NOT_RUN: git history unavailable")
    old_lines = [json.loads(x) for x in old.stdout.decode().splitlines() if x.strip()]
    assert [{k: e[k] for k in o} for e, o in zip(es, old_lines, strict=True)] == old_lines


def test_migration_tool_refuses_chained_file(tmp_path):
    led, _ = three(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "migrate_ledger_chain.py"), str(led.path)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0 and "not a legacy line" in r.stderr
