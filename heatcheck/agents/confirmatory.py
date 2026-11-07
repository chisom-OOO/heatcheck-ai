"""CONFIRMATORY lane: Research's pre-registered 2024-25 family (CONF-HA, CONF-MOM, CONF-HH).

When the Discoverer (Heater) proposes one of these claims, the Referee does not run Max's
attacks. It delegates to Research's frozen procedure ``scripts/confirmatory.py final`` under
Research's custodian, then writes the result to the evidence ledger with ``lane: CONFIRMATORY``.
Development-lane entries (2023-24, run_once) carry ``lane: DEVELOPMENT``.

Two modes:

* ``dry_run`` (default): checks that the family manifest, the three plans, Research's code and
  the custodian's seal and registration all match, and, if a data directory is given, that the
  2024-25 tables hash to the sealed values. It reads only. It never imports Research's
  custodian, never runs a test, never reserves, and never writes to either ledger.
* ``final``: runs the final step once, only with a named authoriser and a dry run whose every
  check passes. Not to be used until the reviewer has verified the seal and the user says so.

The dry run lives here, not as a flag in Research's script: ``scripts/confirmatory.py`` is
inside the family's frozen ``code_hash``, so editing it would invalidate the registration.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "handoff" / "research-20261107"
EVIDENCE = HANDOFF / "evidence"
SUBDIR = "confirmatory-2024-25"
SCRIPT = "scripts/confirmatory.py"
CONFIRMATORY_IDS = ("CONF-HA", "CONF-MOM", "CONF-HH")
LANE_CONFIRMATORY = "CONFIRMATORY"
LANE_DEVELOPMENT = "DEVELOPMENT"
SEASON_TABLES = ("games", "events", "exclusions", "quarantine", "game_labels", "shot_labels")


class ConfirmatoryRefused(RuntimeError):
    pass


# --------------------------------------------------------------------------- hashing
# Same definitions as Research's util.canonical_json / sha256_file, re-stated so the dry run
# needs no Research import (their custodian imports fcntl, absent on Windows).


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=str).encode()


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _self_hash_ok(obj: dict, key: str) -> bool:
    body = {k: v for k, v in obj.items() if k != key}
    return _sha256(_canonical_json(body)) == obj.get(key)


def research_code_hash(handoff: Path, files: list[str]) -> str:
    return _sha256(_canonical_json({f: _sha256((handoff / f).read_bytes()) for f in files}))


def research_table_hashes(handoff: Path, data: Path) -> dict[str, str]:
    """Recompute logical table hashes with Research's own store.py, in a subprocess so its
    top-level package ``heatcheck`` does not shadow this one. Reads the data, writes nothing."""
    code = ("import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
            "from heatcheck import store;"
            "print(json.dumps(store.logical_table_hashes(Path(sys.argv[2]),store.SEASON_TABLES)))")
    p = subprocess.run([sys.executable, "-I", "-c", code, str(handoff / "src"), str(data)],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise ConfirmatoryRefused(f"table hashing failed: {p.stderr.strip()[-300:]}")
    return json.loads(p.stdout)


def _custodian_entries(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def final_platform_ok() -> bool:
    """Research's custodian locks with fcntl, so ``final`` runs on Linux/macOS only."""
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return False
    return True


# --------------------------------------------------------------------------- dry run


def _check(checks: list, name: str, ok: bool | None, detail: str) -> None:
    checks.append({"check": name, "status": "PASS" if ok else ("NOT_CHECKED" if ok is None else "FAIL"),
                   "detail": detail})


def dry_run(evidence: Path = EVIDENCE, data: Path | None = None, handoff: Path = HANDOFF, *,
            table_hashes: Callable[[Path, Path], dict] = research_table_hashes,
            platform_ok: Callable[[], bool] = final_platform_ok) -> dict[str, Any]:
    """Check plans, code and seal against each other without running anything. Read-only."""
    checks: list[dict] = []
    out = Path(evidence) / SUBDIR
    try:
        fam = json.loads((out / "family.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _check(checks, "family_manifest", False, f"family.json unreadable: {e}")
        return {"mode": "DRY_RUN", "ready": False, "state": "NOT_READY", "checks": checks}
    _check(checks, "family_manifest", _self_hash_ok(fam, "canonical_family_hash"),
           f"family.json self-hash {fam.get('canonical_family_hash')}")
    ids_ok = sorted(fam.get("hypotheses", {})) == sorted(CONFIRMATORY_IDS)
    _check(checks, "family_hypotheses", ids_ok, f"hypotheses {sorted(fam.get('hypotheses', {}))}")
    plans = {}
    for hid in CONFIRMATORY_IDS:
        try:
            plan = json.loads((out / f"{hid}.plan.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            _check(checks, f"plan:{hid}", False, f"unreadable: {e}")
            continue
        plans[hid] = plan
        ok = (_self_hash_ok(plan, "canonical_plan_hash")
              and plan.get("canonical_plan_hash") == fam.get("hypotheses", {}).get(hid)
              and plan.get("hypothesis_id") == hid
              and plan.get("final_epoch_id") == fam.get("final_epoch_id"))
        _check(checks, f"plan:{hid}", ok, f"plan hash {plan.get('canonical_plan_hash')} vs family "
               f"{fam.get('hypotheses', {}).get(hid)}")
    try:
        code = research_code_hash(Path(handoff), fam["code_files"])
        _check(checks, "research_code", code == fam.get("code_hash"),
               f"recomputed {code} vs frozen {fam.get('code_hash')} over {len(fam['code_files'])} files")
    except (OSError, KeyError) as e:
        _check(checks, "research_code", False, f"cannot hash code: {e}")

    state = "NOT_READY"
    try:
        entries = _custodian_entries(Path(evidence) / "custodian_ledger.jsonl")
    except (OSError, ValueError) as e:
        entries = None
        _check(checks, "seal", False, f"custodian ledger unreadable: {e}")
    if entries is not None:
        epoch = fam.get("final_epoch_id")
        seals = [e for e in entries if e.get("type") == "seal" and e.get("epoch_id") == epoch]
        sl = seals[0] if len(seals) == 1 else None
        _check(checks, "seal", sl is not None and sl.get("seal_id") == fam.get("seal_id")
               and sl.get("input_hash") == fam.get("sealed_input_hash")
               and sl.get("data_hashes") == fam.get("sealed_data_hashes")
               and len(sl.get("record_ids", [])) == fam.get("n_sealed_games"),
               f"{len(seals)} seal(s) for {epoch}; family seal {fam.get('seal_id')}")
        regs = [e for e in entries if e.get("type") == "register" and e.get("epoch_id") == epoch]
        _check(checks, "registration", len(regs) == 1
               and regs[0].get("plan_hash") == fam.get("canonical_family_hash")
               and regs[0].get("code_hash") == fam.get("code_hash")
               and regs[0].get("family_id") == fam.get("family_id")
               and regs[0].get("seal_id") == fam.get("seal_id"),
               f"{len(regs)} registration(s) for {epoch}")
        reserves = [e for e in entries if e.get("type") == "reserve" and e.get("epoch_id") == epoch]
        spent = {e["receipt_id"] for e in entries if e.get("type") == "spend"}
        if not reserves:
            state = "UNRUN"
        elif all(r["receipt_id"] in spent for r in reserves) and (out / "final_result.json").exists():
            state = "FINAL_DONE"
        else:
            state = "RESERVED_INCOMPLETE"
        _check(checks, "exposure", state in ("UNRUN", "FINAL_DONE"),
               f"{len(reserves)} reservation(s) on {epoch}: {state}")
    if data is None or not Path(data).exists():
        _check(checks, "sealed_data", None, "no 2024-25 data directory on this machine; "
               "the seal accepts only identical bytes (rebuild with build_confirmatory.py)")
    else:
        try:
            h = table_hashes(Path(handoff), Path(data))
            diff = sorted(k for k in set(h) | set(fam.get("sealed_data_hashes", {}))
                          if h.get(k) != fam.get("sealed_data_hashes", {}).get(k))
            _check(checks, "sealed_data", not diff, f"tables differing from the seal: {diff}")
        except ConfirmatoryRefused as e:
            _check(checks, "sealed_data", False, str(e))
    plat = platform_ok()
    _check(checks, "platform", plat, "fcntl available" if plat else
           "Research's custodian needs fcntl: run final on Linux/macOS, not Windows")
    ready = all(c["status"] == "PASS" for c in checks)
    return {"mode": "DRY_RUN", "ready": ready, "state": state if ready or state != "UNRUN" else
            "UNRUN_NOT_READY", "family_id": fam.get("family_id"),
            "family_hash": fam.get("canonical_family_hash"), "seal_id": fam.get("seal_id"),
            "code_hash": fam.get("code_hash"), "plan_hashes": fam.get("hypotheses"),
            "statements": {h: p.get("claim") for h, p in plans.items()}, "checks": checks}


# --------------------------------------------------------------------------- final + record


def verify_final_result(result: dict, evidence: Path) -> dict:
    """Check a final_result.json against the frozen family and the custodian ledger."""
    out = Path(evidence) / SUBDIR
    fam = json.loads((out / "family.json").read_text(encoding="utf-8"))
    problems = []
    for key, want in (("lane", LANE_CONFIRMATORY), ("phase", "FINAL"),
                      ("family_id", fam["family_id"]), ("family_hash", fam["canonical_family_hash"]),
                      ("plan_hashes", fam["hypotheses"]), ("code_hash", fam["code_hash"]),
                      ("data_hashes", fam["sealed_data_hashes"]),
                      ("final_epoch_id", fam["final_epoch_id"])):
        if result.get(key) != want:
            problems.append(f"{key} differs from the frozen family")
    if sorted(result.get("decisions", {})) != sorted(CONFIRMATORY_IDS):
        problems.append("decisions do not cover exactly the three hypotheses")
    rid = result.get("exposure_receipt_id")
    entries = _custodian_entries(Path(evidence) / "custodian_ledger.jsonl")
    if not any(e.get("type") == "reserve" and e.get("receipt_id") == rid for e in entries):
        problems.append("receipt not reserved in the custodian ledger")
    if not any(e.get("type") == "spend" and e.get("receipt_id") == rid for e in entries):
        problems.append("receipt not spent in the custodian ledger")
    if problems:
        raise ConfirmatoryRefused("; ".join(problems))
    return fam


def confirmatory_source(result: dict, fam: dict, evidence: Path):
    """The recorded-result description of a verified confirmatory final (heatcheck/agents/
    recorded.py): the same recorder as Research's GAME_PREDICTION final."""
    from heatcheck.agents.recorded import Hypothesis, RecordedSource
    hyps = []
    for hid in CONFIRMATORY_IDS:
        plan = json.loads((Path(evidence) / SUBDIR / f"{hid}.plan.json").read_text(encoding="utf-8"))
        hyps.append(Hypothesis(hid, hid, plan["claim"], f"Research frozen plan {hid}",
                               channel=plan["channel"]))
    return RecordedSource(
        source_id=f"research:{fam['family_id']}:FINAL", lane=LANE_CONFIRMATORY, phase="FINAL",
        channel="MIXED", result_file=f"{SUBDIR}/final_result.json",
        receipt_id=result["exposure_receipt_id"], plan_hash=fam["canonical_family_hash"],
        hypotheses=tuple(hyps),
        files=(f"{SUBDIR}/final_result.json", f"{SUBDIR}/family.json",
               *(f"{SUBDIR}/{h}.plan.json" for h in CONFIRMATORY_IDS)),
        data={"season": result["season"], "final_epoch_id": result["final_epoch_id"],
              "input_hash": result["input_hash"], "n_sealed_games": fam["n_sealed_games"],
              "seal_id": fam["seal_id"], "authorised_by": result["authorised_by"],
              "multiplicity": fam["multiplicity"]},
    )


RECORD_EXEMPT_CHECKS = ("sealed_data", "platform")


def _default_runner(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


@dataclass
class ConfirmatoryLane:
    """The Referee's handle on the confirmatory family. Defaults to dry run."""

    evidence: Path = EVIDENCE
    data: Path | None = None
    handoff: Path = HANDOFF
    mode: str = "dry_run"  # or "final"
    authorised_by: str | None = None
    runner: Callable[[list[str], Path], Any] = _default_runner
    dry_run_kwargs: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ("dry_run", "final"):
            raise ValueError(f"unknown mode {self.mode!r}")

    def dry_run(self) -> dict:
        return dry_run(self.evidence, self.data, self.handoff, **self.dry_run_kwargs)

    def final_argv(self) -> list[str]:
        return [sys.executable, "-I", SCRIPT, "final", str(self.data), str(self.evidence),
                "--authorised-by", str(self.authorised_by)]

    def record_final_done(self, ledger: EvidenceLedger, proposers: dict | None = None) -> dict:
        """Record a finished, verified final into ``ledger``. Never runs anything, in any mode.

        Requires state FINAL_DONE and every dry-run check to PASS except ``sealed_data`` and
        ``platform``: those gate *running* final (sealed bytes on disk, a Linux custodian), not
        recording a run that the custodian ledger shows reserved and spent. Idempotent."""
        report = self.dry_run()
        if report["state"] != "FINAL_DONE":
            raise ConfirmatoryRefused(f"no finished final to record (state {report['state']})")
        failed = [c["check"] for c in report["checks"]
                  if c["status"] != "PASS" and c["check"] not in RECORD_EXEMPT_CHECKS]
        if failed:
            raise ConfirmatoryRefused(f"finished final does not match the frozen family: {failed}")
        from heatcheck.agents.recorded import record
        result = json.loads((Path(self.evidence) / SUBDIR / "final_result.json").read_bytes())
        fam = verify_final_result(result, self.evidence)
        return record(confirmatory_source(result, fam, self.evidence), ledger, self.evidence,
                      proposers=proposers)

    def evaluate(self, claim_id: str, ledger: EvidenceLedger, proposer: dict) -> dict[str, Any]:
        """FINAL_DONE (any mode): records the finished run, never reruns, returns
        {"entry": entry for claim_id, "entries": all three}. Otherwise dry run returns
        {"dry_run": report} and writes nothing; final runs the family once from UNRUN only."""
        if claim_id not in CONFIRMATORY_IDS:
            raise ConfirmatoryRefused(f"{claim_id!r} is not a confirmatory claim")
        report = self.dry_run()
        if report["state"] == "FINAL_DONE":
            entries = self.record_final_done(ledger, proposers={claim_id: proposer})
            return {"entry": entries[claim_id], "entries": entries}
        if self.mode == "dry_run":
            return {"dry_run": report}
        if not self.authorised_by:
            raise ConfirmatoryRefused("final needs a named authoriser")
        if not report["ready"]:
            failed = [c["check"] for c in report["checks"] if c["status"] != "PASS"]
            raise ConfirmatoryRefused(f"dry run not ready: {failed}")
        result_path = Path(self.evidence) / SUBDIR / "final_result.json"
        if report["state"] != "UNRUN" or result_path.exists():
            # The final runs once. A result file or reservation without FINAL_DONE is an
            # incomplete or tampered state: refuse rather than run again.
            raise ConfirmatoryRefused(f"final never runs again (state {report['state']}, "
                                      f"result file {'present' if result_path.exists() else 'absent'})")
        p = self.runner(self.final_argv(), Path(self.handoff))
        if p.returncode != 0:
            raise ConfirmatoryRefused(f"final exited {p.returncode}: {(p.stderr or '')[-300:]}")
        from heatcheck.agents.recorded import record
        result = json.loads(result_path.read_bytes())
        fam = verify_final_result(result, self.evidence)
        entries = record(confirmatory_source(result, fam, self.evidence), ledger, self.evidence,
                         proposers={claim_id: proposer})
        return {"entry": entries[claim_id], "entries": entries}


__all__ = ["CONFIRMATORY_IDS", "ConfirmatoryLane", "ConfirmatoryRefused", "LANE_CONFIRMATORY",
           "LANE_DEVELOPMENT", "dry_run", "verify_final_result"]
