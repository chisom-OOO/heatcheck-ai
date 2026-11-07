"""Append-only, content-addressed evidence ledger (JSONL).

* evidence_id = sha256 of the canonical identity (plan, data, code, attacks, decision inputs).
* put() of an identical identity returns the stored record (retry), never a second line.
* An existing line is never rewritten. get()/verify() recompute every hash and fail loudly on
  tampering. created_at_utc is recorded but excluded from the identity.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import canonical_bytes, loads_strict, sha256_hex


class LedgerError(RuntimeError):
    pass


def evidence_id(identity: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(identity))


class EvidenceLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _entries(self) -> list[dict[str, Any]]:
        out = []
        for n, line in enumerate(self.path.read_text("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            e = loads_strict(line)
            if evidence_id(e["identity"]) != e["evidence_id"]:
                raise LedgerError(f"ledger line {n}: identity hash mismatch (tampered)")
            if sha256_hex(canonical_bytes(e["identity"]) + e["created_at_utc"].encode()) \
                    != e["entry_hash"]:
                raise LedgerError(f"ledger line {n}: entry hash mismatch (tampered)")
            out.append(e)
        return out

    def put(self, identity: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Store identity; returns (entry, retried). Retries return the original entry."""
        eid = evidence_id(identity)
        for e in self._entries():
            if e["evidence_id"] == eid:
                return e, True
        created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        entry = {"evidence_id": eid, "identity": identity, "created_at_utc": created,
                 "entry_hash": sha256_hex(canonical_bytes(identity) + created.encode())}
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry, False

    def get(self, eid: str) -> dict[str, Any]:
        for e in self._entries():
            if e["evidence_id"] == eid:
                return e
        raise LedgerError(f"unknown evidence_id {eid}")

    def all(self) -> list[dict[str, Any]]:
        return self._entries()
