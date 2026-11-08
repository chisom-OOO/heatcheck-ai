"""Persistent record-level exposure ledger (DECISIONS D8; Shared_Protocol.final_unlock_policy).

* reserve(): atomically reserve a final family/epoch over underlying record IDs BEFORE work.
  Refuses if any record is already reserved/spent under a different job identity — renaming files,
  new family IDs, re-spelled record IDs or revised snapshots cannot reopen exposed records.
* Record IDs are canonicalised before any comparison (RV-R2): an NBA game id given as
  ``0022300901``, ``nba:0022300901`` or ``22300901`` is the same record ``nba:0022300901``.
  IDs with surrounding whitespace or control characters are refused, never trimmed.
* identical job retry (same canonical job identity) returns the ORIGINAL receipt; it is not a new
  evaluation. A reservation is bound to an ``input_hash`` of the evaluated data (RV-R1): a retry with
  different input data is refused, so a label change can never count as a retry. Reservations made
  before this binding existed are bound on their first retry that supplies an ``input_hash``.
* Every record id maps to ONE game before any exposure check (ruling 2026-11-07): ``SHOT:<game>:<seq>``,
  ``GAME:<game>``, EVENT ``nba:<game>:<event>:r<rev>`` and FEATURE_ROW/label ids all expose their game.
  An id that names no game, or more than one, is refused.
* seal(): reserve a whole final-data epoch (e.g. the 2024-25 season) BEFORE any claim runs on it.
  register(): bind the single pre-registered family/plan/code to the seal, allowed only before any
  reservation on it. A sealed game can be reserved only by that registered job, over the whole seal,
  with the sealed input data.
* replay(): an audited re-execution of an already SPENT receipt under amended code (same family,
  epoch and records; amendment hash and new code hash recorded). It exposes no new record, cannot
  change the bound input data, and every replay stays listed in the ledger. A second (or later) distinct
  amendment on the same receipt requires a recorded reviewer sign-off (DECISIONS D15).
* spend(): marks the epoch spent; must be called before any label/score leaves the evaluator.
Append-only JSONL with fsync and an exclusive flock. Isolation is LOGICAL until Max applies OS-level
permissions/process separation.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from .util import canonical_json, sha256_bytes, utc_now_iso


class ExposureRefused(RuntimeError):
    pass


_NBA_GAME = re.compile(r"(?:nba:)?([0-9]{1,10})")
_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


def canonical_record_id(record_id: object) -> str:
    """Canonical exposure key. NBA game ids -> ``nba:`` + 10 digits; other namespaces unchanged.
    Malformed ids are refused (fail closed) rather than repaired."""
    if not isinstance(record_id, str) or not record_id:
        raise ExposureRefused(f"malformed record id {record_id!r}: must be a non-empty string")
    if _BAD_CHARS.search(record_id):
        raise ExposureRefused(f"malformed record id {record_id!r}: whitespace/control characters")
    m = _NBA_GAME.fullmatch(record_id)
    if m:
        return "nba:" + m.group(1).zfill(10)
    if record_id.startswith("nba:") and ":" not in record_id[4:]:
        raise ExposureRefused(f"malformed NBA game id {record_id!r}: expected nba:<10 digits>")
    # composite ids (EVENT nba:<game>:<event>:r<rev>, SHOT:<game>:<seq>, ...) must name exactly one game
    exposure_key(record_id)
    return record_id


def canonical_record_ids(record_ids) -> list[str]:
    return sorted({canonical_record_id(r) for r in record_ids})


_GAME_PART = re.compile(r"00[0-9]{8}")


def exposure_key(record_id: object) -> str:
    """The game a record exposes: ``nba:<10 digits>`` or ``syn:<id>``. Refuses ids naming no game or
    more than one game (fail closed)."""
    if not isinstance(record_id, str) or not record_id or _BAD_CHARS.search(record_id):
        raise ExposureRefused(f"malformed record id {record_id!r}")
    rid = record_id
    m = _NBA_GAME.fullmatch(rid)
    if m:
        return "nba:" + m.group(1).zfill(10)
    parts = rid.split(":")
    games, i = set(), 0
    while i < len(parts):
        part = parts[i]
        if part in ("nba", "syn") and i + 1 < len(parts):
            nxt = parts[i + 1]
            if part == "nba":
                if not re.fullmatch(r"[0-9]{1,10}", nxt):
                    raise ExposureRefused(f"record id {record_id!r}: malformed NBA game id after 'nba:'")
                games.add("nba:" + nxt.zfill(10))
            else:
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", nxt):
                    raise ExposureRefused(f"record id {record_id!r}: malformed synthetic game id")
                games.add("syn:" + nxt)
            i += 2
            continue
        if _GAME_PART.fullmatch(part):
            games.add("nba:" + part)
        i += 1
    if len(games) != 1:
        raise ExposureRefused(f"record id {record_id!r} must map to exactly one game; found {sorted(games)}")
    return games.pop()


def exposure_keys(record_ids) -> list[str]:
    return sorted({exposure_key(r) for r in record_ids})


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
        """Job identity over CANONICAL record ids (so re-spelled ids are the same job)."""
        return sha256_bytes(canonical_json({"family": family_id, "epoch": epoch_id, "plan": plan_hash,
                                            "code": code_hash, "records": canonical_record_ids(record_ids)}))

    @classmethod
    def _entry_job_hash(cls, e: dict) -> str:
        # recomputed from the stored fields: legacy entries stored a hash over raw (uncanonicalised) ids
        return cls.job_hash(e["family_id"], e["epoch_id"], e["plan_hash"], e["code_hash"], e["record_ids"])

    @staticmethod
    def _bound_input(entries: list[dict], receipt_id: str) -> str | None:
        for e in entries:
            if e["type"] == "reserve" and e["receipt_id"] == receipt_id and e.get("input_hash"):
                return e["input_hash"]
        for e in entries:
            if e["type"] in ("bind", "replay") and e["receipt_id"] == receipt_id:
                return e["input_hash"]   # first binding wins: a bind, or the first replay's verified input
        return None

    def _seals(self, entries: list[dict]) -> list[dict]:
        return [e for e in entries if e["type"] == "seal"]

    def seal(self, *, epoch_id: str, record_ids: list[str], input_hash: str, data_hashes: dict,
             description: str) -> dict:
        """Seal final data before any claim runs on it. Idempotent for an identical seal."""
        if not input_hash:
            raise ExposureRefused("a seal must bind the input_hash of the sealed data")
        canon = canonical_record_ids(record_ids)
        games = exposure_keys(canon)
        with self._locked():
            entries = self._entries()
            for e in self._seals(entries):
                if e["epoch_id"] == epoch_id:
                    if (e["record_ids"], e["input_hash"]) == (canon, input_hash):
                        return {**e, "retry": True}
                    raise ExposureRefused(f"epoch_id {epoch_id} already sealed with different records or data")
            if any(e["type"] == "reserve" and e["epoch_id"] == epoch_id for e in entries):
                raise ExposureRefused(f"epoch_id {epoch_id} already used by a reservation")
            taken = {}
            for e in entries:
                if e["type"] == "reserve":
                    for g in exposure_keys(e["record_ids"]):
                        taken[g] = e["receipt_id"]
                elif e["type"] == "seal":
                    for g in e["exposed_games"]:
                        taken[g] = e["seal_id"]
            overlap = sorted(set(games) & taken.keys())
            if overlap:
                raise ExposureRefused(f"{len(overlap)} games already exposed or sealed; e.g. {overlap[:3]}")
            entry = {"type": "seal", "seal_id": str(uuid.uuid4()), "epoch_id": epoch_id, "record_ids": canon,
                     "exposed_games": games, "input_hash": input_hash, "data_hashes": data_hashes,
                     "description": description, "at_utc": utc_now_iso()}
            self._append(entry)
            return {**entry, "retry": False}

    def register(self, *, epoch_id: str, family_id: str, plan_hash: str, code_hash: str) -> dict:
        """Bind the one pre-registered family to a sealed epoch, before any reservation on it."""
        with self._locked():
            entries = self._entries()
            seals = [e for e in self._seals(entries) if e["epoch_id"] == epoch_id]
            if not seals:
                raise ExposureRefused(f"no seal for epoch {epoch_id}")
            if any(e["type"] == "reserve" and e["epoch_id"] == epoch_id for e in entries):
                raise ExposureRefused("the sealed epoch already has a reservation; registration closed")
            ident = {"family_id": family_id, "plan_hash": plan_hash, "code_hash": code_hash}
            for e in entries:
                if e["type"] == "register" and e["epoch_id"] == epoch_id:
                    if {k: e[k] for k in ident} == ident:
                        return {**e, "retry": True}
                    raise ExposureRefused(f"epoch {epoch_id} already has a different registered family")
            entry = {"type": "register", "register_id": str(uuid.uuid4()), "epoch_id": epoch_id,
                     "seal_id": seals[0]["seal_id"], **ident, "at_utc": utc_now_iso()}
            self._append(entry)
            return {**entry, "retry": False}

    def reserve(self, *, family_id: str, epoch_id: str, plan_hash: str, code_hash: str,
                record_ids: list[str], input_hash: str | None = None) -> dict:
        canon = canonical_record_ids(record_ids)
        games = exposure_keys(canon)
        jh = self.job_hash(family_id, epoch_id, plan_hash, code_hash, canon)
        with self._locked():
            entries = self._entries()
            for e in entries:
                if e["type"] == "reserve" and self._entry_job_hash(e) == jh:
                    bound = self._bound_input(entries, e["receipt_id"])
                    if bound is not None and input_hash != bound:
                        raise ExposureRefused(
                            f"input data differ from those bound to receipt {e['receipt_id']}; "
                            "this is not a retry and the records are already exposed")
                    if bound is None and input_hash is not None:
                        self._append({"type": "bind", "receipt_id": e["receipt_id"], "input_hash": input_hash,
                                      "note": "binding added on first retry; reservation predates input binding",
                                      "at_utc": utc_now_iso()})
                        bound = input_hash
                    return {**e, "retry": True, "input_hash_bound": bound}
            sealed = {}
            for e in self._seals(entries):
                for g in e["exposed_games"]:
                    sealed[g] = e
            hit = {sealed[g]["seal_id"]: sealed[g] for g in games if g in sealed}
            if hit:
                if len(hit) != 1:
                    raise ExposureRefused("records span more than one sealed epoch")
                sl = next(iter(hit.values()))
                if sl["epoch_id"] != epoch_id:
                    raise ExposureRefused(f"games are sealed under epoch {sl['epoch_id']}; refused for {epoch_id}")
                if games != sl["exposed_games"]:
                    raise ExposureRefused("a sealed epoch is reserved whole: records must cover exactly the sealed games")
                regs = [r for r in entries if r["type"] == "register" and r["epoch_id"] == epoch_id]
                ident = {"family_id": family_id, "plan_hash": plan_hash, "code_hash": code_hash}
                if not regs or {k: regs[0][k] for k in ident} != ident:
                    raise ExposureRefused("family/plan/code not registered for this sealed epoch before access")
                if input_hash != sl["input_hash"]:
                    raise ExposureRefused("input data differ from the sealed data")
            exposed = {}
            for e in entries:
                if e["type"] == "reserve":
                    for g in exposure_keys(e["record_ids"]):
                        exposed[g] = e["receipt_id"]
            overlap = sorted(set(games) & exposed.keys())
            if overlap:
                raise ExposureRefused(f"{len(overlap)} games already exposed under receipt(s) "
                                      f"{sorted({exposed[g] for g in overlap})}; e.g. {overlap[:3]}")
            if any(e["type"] == "reserve" and e["epoch_id"] == epoch_id for e in entries):
                raise ExposureRefused(f"epoch_id {epoch_id} already used with a different job identity")
            entry = {"type": "reserve", "receipt_id": str(uuid.uuid4()), "family_id": family_id,
                     "epoch_id": epoch_id, "plan_hash": plan_hash, "code_hash": code_hash,
                     "job_hash": jh, "record_ids": canon, "exposed_games": games, "input_hash": input_hash,
                     "at_utc": utc_now_iso()}
            self._append(entry)
            return {**entry, "retry": False, "input_hash_bound": input_hash}

    def replay(self, *, receipt_id: str, family_id: str, epoch_id: str, record_ids: list[str],
               amendment_hash: str, code_hash: str, input_hash: str,
               reviewer_signoff: dict | None = None) -> dict:
        """Audited re-execution of a SPENT receipt under amended code. Same family/epoch/records only.
        A second or later distinct amendment needs ``reviewer_signoff`` = {reviewer, receipt_id,
        amendment_hash} naming this exact amendment (DECISIONS D15). Sign-off is recorded, not verified:
        isolation is logical until Max applies access control."""
        if not input_hash:
            raise ExposureRefused("replay requires the input_hash of the evaluated data")
        canon = canonical_record_ids(record_ids)
        with self._locked():
            entries = self._entries()
            orig = [e for e in entries if e["type"] == "reserve" and e["receipt_id"] == receipt_id]
            if not orig:
                raise ExposureRefused("unknown receipt")
            o = orig[0]
            if not any(e["type"] == "spend" and e["receipt_id"] == receipt_id for e in entries):
                raise ExposureRefused("replay is only for a spent receipt; run the original evaluation first")
            if (o["family_id"], o["epoch_id"]) != (family_id, epoch_id):
                raise ExposureRefused("replay must use the original family and epoch")
            if canonical_record_ids(o["record_ids"]) != canon:
                raise ExposureRefused("replay must cover exactly the original records")
            bound = self._bound_input(entries, receipt_id)
            prior = [e for e in entries if e["type"] == "replay" and e["receipt_id"] == receipt_id]
            for e in prior:
                if e["input_hash"] != input_hash:
                    raise ExposureRefused("input data differ from an earlier replay of this receipt")
            if bound is not None and bound != input_hash:
                raise ExposureRefused("input data differ from those bound to the original receipt")
            for e in prior:
                if (e["amendment_hash"], e["code_hash"]) == (amendment_hash, code_hash):
                    return {**e, "retry": True, "replays_of_receipt": len(prior)}
            earlier = {e["amendment_hash"] for e in prior}
            if earlier and amendment_hash not in earlier:
                so = reviewer_signoff or {}
                if not (so.get("reviewer") and so.get("receipt_id") == receipt_id
                        and so.get("amendment_hash") == amendment_hash):
                    raise ExposureRefused("a second amendment on this receipt requires reviewer sign-off naming "
                                          "this receipt and amendment before it runs")
            entry = {"type": "replay", "replay_id": str(uuid.uuid4()), "receipt_id": receipt_id,
                     "family_id": family_id, "epoch_id": epoch_id, "amendment_hash": amendment_hash,
                     "code_hash": code_hash, "input_hash": input_hash,
                     "original_input_binding": "BOUND" if bound else "NONE_PREDATES_BINDING",
                     "reviewer_signoff": reviewer_signoff if earlier else None,
                     "at_utc": utc_now_iso()}
            self._append(entry)
            return {**entry, "retry": False, "replays_of_receipt": len(prior) + 1}

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

    def history_by_job(self, family_id: str, epoch_id: str) -> list[dict]:
        """Reserve entries for a family/epoch (normally one)."""
        return [e for e in self._entries()
                if e["type"] == "reserve" and e["family_id"] == family_id and e["epoch_id"] == epoch_id]

    def history(self, receipt_id: str) -> list[dict]:
        """Every ledger entry for a receipt (reserve, bind, spend, replay), in ledger order."""
        return [e for e in self._entries() if e.get("receipt_id") == receipt_id]
