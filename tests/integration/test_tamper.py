"""POST /api/tamper/flip and /api/tamper/restore (Max, 8 Nov 2026)."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from heatcheck.api.dialogue_server import serve
from heatcheck.api.tamper import FLIP_INTERVAL_S, Tamper, TamperError, choose_offset
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "evidence" / "evidence.jsonl"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def clock():
    return [1000.0]


@pytest.fixture
def tamper(tmp_path, clock):
    return Tamper(COMMITTED, tmp_path / "scratch", EvidenceLedger(tmp_path / "events.jsonl"),
                  clock=lambda: clock[0])


def test_flip_uses_the_real_reader_and_leaves_the_committed_file_byte_identical(tamper, tmp_path):
    before = sha(COMMITTED)
    out = tamper.flip()
    assert sha(COMMITTED) == before
    assert set(out) == {"offset", "line", "expected", "actual", "verdict", "error", "ledger_event_id"}
    assert out["verdict"] == "DATA_INVALID"
    assert out["error"].startswith(f"ledger line {out['line']}: ") and "tampered" in out["error"]
    # exactly one byte differs, at the reported offset, inside the verdict value
    orig, copy = COMMITTED.read_bytes(), tamper.scratch.read_bytes()
    diff = [i for i, (a, b) in enumerate(zip(orig, copy, strict=True)) if a != b]
    assert diff == [out["offset"]]
    line_start = orig.rfind(b"\n", 0, out["offset"]) + 1
    assert orig[line_start:out["offset"]].endswith(b'"decision":"')
    assert out["expected"].startswith(f"0x{orig[out['offset']]:02x}") and out["actual"].startswith(f"0x{copy[out['offset']]:02x}")
    # the committed ledger itself still reads cleanly
    assert EvidenceLedger.open_readonly(COMMITTED).all()


def test_the_attempt_is_a_normal_chained_entry_without_the_bytes(tamper, tmp_path):
    out = tamper.flip()
    events = EvidenceLedger.open_readonly(tmp_path / "events.jsonl").all()   # chain verified on read
    assert [e["evidence_id"] for e in events] == [out["ledger_event_id"]]
    ident = events[0]["identity"]
    assert ident["kind"] == "TAMPER_ATTEMPT" and ident["validator_message"] == out["error"]
    assert set(ident) == {"kind", "at_utc", "target", "target_sha256", "line", "offset",
                          "scratch_path_sha256", "validator_message", "verdict"}
    assert out["expected"] not in json.dumps(ident) and out["actual"] not in json.dumps(ident)


def test_rate_limit_one_flip_per_five_seconds(tamper, clock):
    tamper.flip()
    clock[0] += FLIP_INTERVAL_S - 0.1
    with pytest.raises(TamperError) as e:
        tamper.flip()
    assert e.value.status == 429
    clock[0] += 0.2
    tamper.flip()


def test_restore_deletes_the_scratch_copy(tamper):
    tamper.flip()
    scratch = tamper.scratch
    assert scratch.exists()
    assert tamper.restore() == {"restored": True} and not scratch.exists()
    assert tamper.restore() == {"restored": True}   # idempotent


def test_offset_is_in_a_middle_lines_verdict():
    data = COMMITTED.read_bytes()
    offset, line = choose_offset(data)
    n = sum(1 for x in data.split(b"\n") if x.strip())
    assert 1 < line < n and data[offset:offset + 1].isalpha()


# ------------------------------------------------------------------ HTTP routes

class _NoDialogue:
    def turn(self, q):
        raise AssertionError("not used")


def post(base, path):
    req = urllib.request.Request(base + path, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    started = []

    def start(t):
        srv = serve(_NoDialogue(), 0, None, None, None, None, t)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def test_http_flip_and_restore(tamper, server, clock):
    before = sha(COMMITTED)
    base = server(tamper)
    status, out = post(base, "/api/tamper/flip")
    assert status == 200 and out["verdict"] == "DATA_INVALID" and out["ledger_event_id"]
    assert post(base, "/api/tamper/flip")[0] == 429
    with urllib.request.urlopen(base + "/api/tamper/events", timeout=10) as r:
        events = json.loads(r.read())["events"]
    assert [e["evidence_id"] for e in events] == [out["ledger_event_id"]]
    assert post(base, "/api/tamper/restore") == (200, {"restored": True})
    assert sha(COMMITTED) == before


def test_http_tamper_off(server):
    base = server(None)
    assert post(base, "/api/tamper/flip")[0] == 503
    assert post(base, "/api/tamper/restore")[0] == 503
