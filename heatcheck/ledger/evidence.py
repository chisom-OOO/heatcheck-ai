"""Append-only, content-addressed, hash-chained evidence ledger (JSONL).

Each line holds:
* ``evidence_id``     = sha256 of the canonical identity (plan, data, code, attacks, decision);
* ``entry_hash``      = sha256(canonical identity bytes + created_at_utc);
* ``prev_chain_hash`` = the previous line's ``chain_hash`` (64 zeros for the first line);
* ``chain_hash``      = sha256(prev_chain_hash + ":" + entry_hash).

Reading recomputes all four for every line and checks each line's ``prev_chain_hash`` against
the line before it. So an edited line whose two content hashes were recomputed, a deleted line
or reordered lines all fail on read (RV-AL1, RV-AL2). Limits:
* Removing lines from the END cannot be seen by the chain alone. Compare ``head()`` with a
  value recorded elsewhere (a report, a commit) to detect truncation.
* Someone who rewrites every later line can rebuild a consistent chain. Only an externally
  recorded head detects that. The hashes are unkeyed.

put() of an identity already present returns the stored entry (retry) and writes nothing. An
existing line is never rewritten. Writers serialise on a sidecar ``.lock`` file.
created_at_utc is recorded but excluded from the identity.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import canonical_bytes, loads_strict, sha256_hex

GENESIS = "0" * 64
LINE_KEYS = {"evidence_id", "identity", "created_at_utc", "entry_hash", "prev_chain_hash", "chain_hash"}
LEGACY_KEYS = {"evidence_id", "identity", "created_at_utc", "entry_hash"}


class LedgerError(RuntimeError):
    pass


def evidence_id(identity: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(identity))


def entry_hash(identity: dict[str, Any], created_at_utc: str) -> str:
    return sha256_hex(canonical_bytes(identity) + created_at_utc.encode())


def chain_hash(prev_chain_hash: str, entry_hash_: str) -> str:
    return sha256_hex(f"{prev_chain_hash}:{entry_hash_}".encode())


@contextmanager
def _locked(lock_path: Path, timeout_s: float = 30.0):
    """Cross-process exclusive lock on a sidecar file (msvcrt on Windows, flock elsewhere)."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerError(f"could not lock {lock_path} within {timeout_s} s") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class EvidenceLedger:
    def __init__(self, path: Path):
        """Writer. Creates the file (and its directory) if missing."""
        self.path = Path(path)
        self.readonly = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    @classmethod
    def open_readonly(cls, path: Path) -> EvidenceLedger:
        """Reader for an existing ledger. Never creates, touches or locks anything; put()
        raises. Every read verifies the full chain."""
        p = Path(path)
        if not p.is_file():
            raise LedgerError(f"no ledger file at {p}")
        led = cls.__new__(cls)
        led.path = p
        led.readonly = True
        return led

    # ------------------------------------------------------------------ reading

    def _entries(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        prev = GENESIS
        seen: set[str] = set()
        for n, line in enumerate(self.path.read_text("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            e = loads_strict(line)
            if not isinstance(e, dict):
                raise LedgerError(f"ledger line {n}: not a JSON object")
            if set(e) == LEGACY_KEYS:
                raise LedgerError(f"ledger line {n}: not hash-chained (legacy format); "
                                  "migrate with tools/migrate_ledger_chain.py")
            if set(e) != LINE_KEYS:
                raise LedgerError(f"ledger line {n}: unexpected fields {sorted(set(e) ^ LINE_KEYS)}")
            if evidence_id(e["identity"]) != e["evidence_id"]:
                raise LedgerError(f"ledger line {n}: identity hash mismatch (tampered)")
            if entry_hash(e["identity"], e["created_at_utc"]) != e["entry_hash"]:
                raise LedgerError(f"ledger line {n}: entry hash mismatch (tampered)")
            if e["prev_chain_hash"] != prev:
                raise LedgerError(f"ledger line {n}: chain broken (a line was edited, deleted, "
                                  "inserted or reordered before it)")
            if chain_hash(prev, e["entry_hash"]) != e["chain_hash"]:
                raise LedgerError(f"ledger line {n}: chain hash mismatch (tampered)")
            if e["evidence_id"] in seen:
                raise LedgerError(f"ledger line {n}: duplicate evidence_id")
            seen.add(e["evidence_id"])
            prev = e["chain_hash"]
            out.append(e)
        return out

    def get(self, eid: str) -> dict[str, Any]:
        for e in self._entries():
            if e["evidence_id"] == eid:
                return e
        raise LedgerError(f"unknown evidence_id {eid}")

    def all(self) -> list[dict[str, Any]]:
        return self._entries()

    def head(self) -> str:
        """chain_hash of the last line (GENESIS when empty). Record it elsewhere to detect
        truncation or a fully rebuilt chain."""
        entries = self._entries()
        return entries[-1]["chain_hash"] if entries else GENESIS

    # ------------------------------------------------------------------ writing

    def put(self, identity: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Store identity; returns (entry, retried). Retries return the original entry."""
        if getattr(self, "readonly", False):
            raise LedgerError("ledger opened read-only")
        eid = evidence_id(identity)
        with _locked(self.path.with_name(self.path.name + ".lock")):
            entries = self._entries()
            for e in entries:
                if e["evidence_id"] == eid:
                    return e, True
            prev = entries[-1]["chain_hash"] if entries else GENESIS
            created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            eh = entry_hash(identity, created)
            entry = {"evidence_id": eid, "identity": identity, "created_at_utc": created,
                     "entry_hash": eh, "prev_chain_hash": prev, "chain_hash": chain_hash(prev, eh)}
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return entry, False
