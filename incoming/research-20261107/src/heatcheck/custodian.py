"""Persistent record-level exposure ledger (DECISIONS D8; Shared_Protocol.final_unlock_policy).

* reserve(): atomically reserve a final family/epoch over underlying record IDs BEFORE work.
  Refuses if any record is already reserved/spent under a different job identity — renaming files,
  new family IDs or revised snapshots cannot reopen exposed records.
* identical job retry (same job_hash) returns the ORIGINAL receipt; it is not a new evaluation.
* spend(): marks the epoch spent; must be called before any label/score leaves the evaluator.
Append-only JSONL with fsync and an exclusive flock. Isolation is LOGICAL until Max applies OS-level
permissions/process separation.
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from .util import canonical_json, sha256_bytes, utc_now_iso


class ExposureRefused(RuntimeError):
    pass


class Custodian:
    def __init__(self, ledger_path: Path):
        self.path = Path(ledger_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    @contextmanager
    def _locked(self):
        with open(self.path.with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def _entries(self) -> list[dict]:
        with open(self.path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def _append(self, entry: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush(); os.fsync(f.fileno())

    @staticmethod
    def job_hash(family_id: str, epoch_id: str, plan_hash: str, code_hash: str, record_ids: list[str]) -> str:
        return sha256_bytes(canonical_json({"family": family_id, "epoch": epoch_id, "plan": plan_hash,
                                            "code": code_hash, "records": sorted(record_ids)}))

    def reserve(self, *, family_id: str, epoch_id: str, plan_hash: str, code_hash: str,
                record_ids: list[str]) -> dict:
        jh = self.job_hash(family_id, epoch_id, plan_hash, code_hash, record_ids)
        with self._locked():
            entries = self._entries()
            for e in entries:
                if e["type"] == "reserve" and e["job_hash"] == jh:
                    return {**e, "retry": True}
            exposed = {}
            for e in entries:
                if e["type"] == "reserve":
                    for r in e["record_ids"]:
                        exposed[r] = e["receipt_id"]
            overlap = sorted(set(record_ids) & exposed.keys())
            if overlap:
                raise ExposureRefused(f"{len(overlap)} records already exposed under receipt(s) "
                                      f"{sorted({exposed[r] for r in overlap})}; e.g. {overlap[:3]}")
            if any(e["type"] == "reserve" and e["epoch_id"] == epoch_id for e in entries):
                raise ExposureRefused(f"epoch_id {epoch_id} already used with a different job identity")
            entry = {"type": "reserve", "receipt_id": str(uuid.uuid4()), "family_id": family_id,
                     "epoch_id": epoch_id, "plan_hash": plan_hash, "code_hash": code_hash,
                     "job_hash": jh, "record_ids": sorted(record_ids), "at_utc": utc_now_iso()}
            self._append(entry)
            return {**entry, "retry": False}

    def spend(self, receipt_id: str) -> dict:
        with self._locked():
            entries = self._entries()
            if not any(e["type"] == "reserve" and e["receipt_id"] == receipt_id for e in entries):
                raise ExposureRefused("unknown receipt")
            for e in entries:
                if e["type"] == "spend" and e["receipt_id"] == receipt_id:
                    return e
            entry = {"type": "spend", "receipt_id": receipt_id, "at_utc": utc_now_iso()}
            self._append(entry)
            return entry

    def is_spent(self, receipt_id: str) -> bool:
        return any(e["type"] == "spend" and e["receipt_id"] == receipt_id for e in self._entries())
