"""Judge-operated tamper demo: POST /api/tamper/flip and POST /api/tamper/restore (Max, 8 Nov 2026).

flip: copy the committed evidence ledger (evidence/evidence.jsonl) to a scratch file, flip one byte
inside the verdict ("decision") value of a middle line, then read the copy with the real
EvidenceLedger reader, which re-verifies every line's hashes and the chain. The reader's own error
message is returned. The committed file is only ever read.

Each attempt is recorded as a TAMPER_ATTEMPT entry, a normal put() with the chain intact, in a
separate hash-chained ledger (default logs/tamper_events.jsonl). It is not written into the
dialogue evidence ledger, because the agent loop reads identity["data"] from every entry there
(heatcheck/agents/loop.py), so a non-claim entry would break the next question. The event holds the
timestamp, line, offset, the scratch path's hash and the validator message; never the bytes.

restore: delete the scratch copy. One flip per 5 s.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from heatcheck.ledger.evidence import EvidenceLedger, LedgerError

FLIP_INTERVAL_S = 5.0
VERDICT_FIELD = re.compile(rb'"decision":"([A-Z_]+)"')


class TamperError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self) -> dict:
        return {"error": self.code, "message": self.message}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _show(byte: int) -> str:
    ch = chr(byte)
    return f"0x{byte:02x} '{ch}'" if ch.isprintable() else f"0x{byte:02x}"


def choose_offset(data: bytes) -> tuple[int, int]:
    """(byte offset, 1-based line) of the first letter of the verdict value on the middle line
    that has one. Deterministic."""
    starts, pos = [], 0
    for line in data.split(b"\n"):
        if line.strip():
            starts.append((pos, line))
        pos += len(line) + 1
    with_verdict = [(i, s, ln) for i, (s, ln) in enumerate(starts) if VERDICT_FIELD.search(ln)]
    if not with_verdict:
        raise TamperError(500, "NO_VERDICT_FIELD", "no line with a verdict field to flip")
    i, start, line = with_verdict[len(with_verdict) // 2]
    m = VERDICT_FIELD.search(line)
    return start + m.start(1), i + 1


class Tamper:
    def __init__(self, committed: Path, scratch_dir: Path, events: EvidenceLedger,
                 clock: Callable[[], float] = time.monotonic, target_label: str = "evidence/evidence.jsonl"):
        self.target_label = target_label
        self.committed = Path(committed)
        self.scratch_dir = Path(scratch_dir)
        self.events = events
        self.clock = clock
        self._last = None
        self._lock = threading.Lock()
        self.scratch: Path | None = None

    def flip(self) -> dict:
        with self._lock:
            now = self.clock()
            if self._last is not None and now - self._last < FLIP_INTERVAL_S:
                raise TamperError(429, "RATE_LIMITED", f"one flip per {FLIP_INTERVAL_S:.0f} s")
            self._last = now
            original = self.committed.read_bytes()          # the committed file is only read
            offset, line = choose_offset(original)
            before = original[offset]
            after = before ^ 0x01                            # one bit: 'I' -> 'H', 'S' -> 'R', ...
            copy = bytearray(original)
            copy[offset] = after
            self._remove_scratch()
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
            self.scratch = self.scratch_dir / f"tamper-{uuid.uuid4().hex}.jsonl"
            self.scratch.write_bytes(bytes(copy))
            try:
                EvidenceLedger.open_readonly(self.scratch).all()   # the real reader, full chain check
                error = None
            except LedgerError as e:
                error = str(e)
            if error is None:   # the reader accepted a tampered copy: report it, never hide it
                raise TamperError(500, "NOT_DETECTED", "the ledger reader accepted the tampered copy")
            event, _ = self.events.put({
                "kind": "TAMPER_ATTEMPT", "at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "target": self.target_label,
                "target_sha256": _sha256(original), "line": line, "offset": offset,
                "scratch_path_sha256": _sha256(str(self.scratch.resolve()).encode()),
                "validator_message": error, "verdict": "DATA_INVALID"})
            return {"offset": offset, "line": line, "expected": _show(before), "actual": _show(after),
                    "verdict": "DATA_INVALID", "error": error, "ledger_event_id": event["evidence_id"]}

    def _remove_scratch(self) -> bool:
        if self.scratch is not None and self.scratch.exists():
            self.scratch.unlink()
            self.scratch = None
            return True
        self.scratch = None
        return False

    def restore(self) -> dict:
        with self._lock:
            self._remove_scratch()
            return {"restored": True}

    def events_list(self) -> list[dict]:
        return [{"evidence_id": e["evidence_id"], "created_at_utc": e["created_at_utc"], **e["identity"]}
                for e in self.events.all()]
