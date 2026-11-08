"""Record Research's finished, custodian-receipted results in Max's evidence ledger.

Nothing is recomputed. A recorded entry copies Research's decision, reason and numbers
verbatim and binds them to their sources by hash:

* every evidence file used (result, plan, amendment, replay, ...) as {path, sha256};
* the custodian receipt id and the exact custodian-ledger lines for that receipt
  (reserve, spend, replay) as {line, type, sha256 of the line's bytes};
* Research's plan hash and the registry claim the result answers.

Before writing, the source is verified: the receipt must be reserved and spent in the
custodian ledger with the plan hash the result names, and source-specific checks (for the
GAME_PREDICTION result, that the reviewer-verified replay has identical decisions) must pass.
Entries are idempotent: recording the same source twice returns the existing entries.

Used for Research's GAME_PREDICTION final (receipt 3e238d2d) and for the confirmatory family
once its final has run (heatcheck/agents/confirmatory.py).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from heatcheck.contracts.records import PROTOCOL_VERSION, sha256_hex
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "handoff" / "research-20261107" / "evidence"
SOURCE = "RECORDED_RESEARCH_RESULT"
RECORDER_FILES = ["heatcheck/agents/recorded.py"]
REFEREE_IDENTITY = {"kind": "RECORDED_RESULT", "rule": "copied from Research's receipted result; "
                    "not recomputed", "version": "1"}


class RecordRefused(RuntimeError):
    pass


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canonical_json(obj: Any) -> bytes:  # Research's util.canonical_json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=str).encode()


def plan_self_hash_ok(plan: dict, key: str) -> bool:
    body = {k: v for k, v in plan.items() if k != key}
    return _sha256(_canonical_json(body)) == plan.get(key)


def file_ref(evidence: Path, rel: str) -> dict:
    return {"path": rel, "sha256": _sha256((Path(evidence) / rel).read_bytes())}


def custodian_lines(evidence: Path, receipt_id: str) -> list[dict]:
    """The custodian-ledger lines for one receipt, bound by the sha256 of their exact bytes."""
    raw = (Path(evidence) / "custodian_ledger.jsonl").read_bytes().split(b"\n")
    out = []
    for n, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("receipt_id") == receipt_id:
            out.append({"line": n, "type": e["type"], "sha256": _sha256(line), "entry": e})
    return out


def check_receipt(lines: list[dict], plan_hash: str) -> None:
    reserves = [x["entry"] for x in lines if x["type"] == "reserve"]
    if len(reserves) != 1:
        raise RecordRefused(f"receipt has {len(reserves)} reserve lines, expected 1")
    if reserves[0].get("plan_hash") != plan_hash:
        raise RecordRefused("custodian reservation is for a different plan hash")
    if not any(x["type"] == "spend" for x in lines):
        raise RecordRefused("receipt was never spent: no final result can exist")


@dataclass(frozen=True)
class Hypothesis:
    research_id: str  # e.g. "H1"
    claim_id: str     # registry or recorded-only id, e.g. "GP-REST"
    statement: str
    statement_source: str  # where the statement text comes from
    channel: str | None = None  # defaults to the source's channel


@dataclass(frozen=True)
class RecordedSource:
    source_id: str
    lane: str
    phase: str
    channel: str
    result_file: str
    receipt_id: str
    plan_hash: str          # the hash the custodian reservation names
    hypotheses: tuple[Hypothesis, ...]
    files: tuple[str, ...]  # every file bound by hash, result first
    data: dict = field(default_factory=dict)


def recorded_identity(src: RecordedSource, h: Hypothesis, result: dict, refs: list[dict],
                      lines: list[dict], proposer: dict | None, evidence_dir: str) -> dict:
    dec = result["decisions"][h.research_id]
    numbers = {k: v for k, v in dec.items() if k not in ("decision", "reason")}
    extra = result.get("results", {}).get(h.research_id)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "source": SOURCE,
        "lane": src.lane,
        "phase": src.phase,
        "channel": h.channel or src.channel,
        "claim": {"claim_id": h.claim_id, "statement": h.statement,
                  "statement_source": h.statement_source,
                  "research_hypothesis_id": h.research_id, "research_plan_hash": src.plan_hash},
        "recorded_source": src.source_id,
        "custodian": {"receipt_id": src.receipt_id,
                      "ledger_lines": [{k: x[k] for k in ("line", "type", "sha256")} for x in lines]},
        "evidence_dir": evidence_dir,
        "files": refs,
        "data": {**src.data, "data_mode": result.get("data_mode"),
                 "pseudo_out_of_sample": result.get("pseudo_out_of_sample"),
                 "data_hashes": result.get("data_hashes")},
        "proposer": proposer or {"role": "recorder", "note": "recorded on import, not proposed"},
        "referee": REFEREE_IDENTITY,
        "code": {p: sha256_hex((ROOT / p).read_bytes()) for p in RECORDER_FILES},
        "result": {**numbers, **({"detail": extra} if extra is not None else {})},
        "decision": dec["decision"],
        "reason": dec["reason"],
        "limits": " ".join(result.get("caveats", [])),
    }


def record(src: RecordedSource, ledger: EvidenceLedger, evidence: Path = EVIDENCE, *,
           proposers: dict[str, dict] | None = None) -> dict[str, dict]:
    """Verify ``src`` and write one entry per hypothesis. Returns {claim_id: entry}."""
    evidence = Path(evidence)
    raw = (evidence / src.result_file).read_bytes()
    result = json.loads(raw)
    if result.get("exposure_receipt_id") != src.receipt_id:
        raise RecordRefused("result file names a different receipt")
    missing = [h.research_id for h in src.hypotheses if h.research_id not in result.get("decisions", {})]
    if missing:
        raise RecordRefused(f"result has no decision for {missing}")
    lines = custodian_lines(evidence, src.receipt_id)
    check_receipt(lines, src.plan_hash)
    refs = [file_ref(evidence, f) for f in src.files]
    try:
        evidence_dir = evidence.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        evidence_dir = evidence.name  # outside the repository (tests)
    out = {}
    existing = ledger.all()
    for h in src.hypotheses:
        ident = recorded_identity(src, h, result, refs, lines, (proposers or {}).get(h.claim_id),
                                  evidence_dir)
        same = [e for e in existing if e["identity"].get("source") == SOURCE
                and e["identity"]["claim"]["claim_id"] == h.claim_id
                and e["identity"]["files"] == refs]
        out[h.claim_id] = same[0] if same else ledger.put(ident)[0]
    return out


def find_recorded(ledger: EvidenceLedger, claim_id: str) -> dict | None:
    """The latest recorded entry for a claim, or None."""
    hits = [e for e in ledger.all() if e["identity"].get("source") == SOURCE
            and e["identity"]["claim"]["claim_id"] == claim_id]
    return hits[-1] if hits else None


# --------------------------------------------------------------------------- GAME_PREDICTION 2023-24

GP_RESULT = "game_prediction_final.json"
GP_REPLAY = "game_prediction_final.replay-GP-2023-24-C1-vs-B1-AMEND-1.json"
GP_PLAN = "claim_plan_GP.json"
GP_AMENDMENT = "claim_plan_GP.amendment-1.json"
GP_RECEIPT = "3e238d2d-030e-45b4-aae7-db0787ecb873"

# Statements: H1 is the registered GP-REST claim (heatcheck/agents/registry.py), which Max's
# registry already states. H2 has no registry claim; its text restates the H2 estimand in
# Research's plan ("H2: logloss(B0) - logloss(B1)") and is recorded-only (GP-ELO).
GP_ELO_STATEMENT = ("A frozen Elo forecast has lower mean log loss than the home-win base-rate "
                    "forecast on unseen 2023-24 final-split games.")


def game_prediction_source(evidence: Path = EVIDENCE) -> RecordedSource:
    from heatcheck.agents.confirmatory import LANE_DEVELOPMENT
    from heatcheck.agents.registry import CLAIMS
    evidence = Path(evidence)
    plan = json.loads((evidence / GP_PLAN).read_text(encoding="utf-8"))
    if not plan_self_hash_ok(plan, "canonical_plan_hash"):
        raise RecordRefused(f"{GP_PLAN} does not match its canonical_plan_hash")
    amend = json.loads((evidence / GP_AMENDMENT).read_text(encoding="utf-8"))
    if not plan_self_hash_ok(amend, "canonical_amendment_hash"):
        raise RecordRefused(f"{GP_AMENDMENT} does not match its canonical_amendment_hash")
    if amend["amends_plan_hash"] != plan["canonical_plan_hash"]:
        raise RecordRefused("amendment amends a different plan")
    result = json.loads((evidence / GP_RESULT).read_text(encoding="utf-8"))
    replay = json.loads((evidence / GP_REPLAY).read_text(encoding="utf-8"))
    if result.get("claim_plan_hash") != plan["canonical_plan_hash"]:
        raise RecordRefused("result was produced under a different plan")
    if replay.get("exposure_receipt_id") != GP_RECEIPT or replay.get("decisions") != result.get("decisions"):
        raise RecordRefused("the amended replay does not reproduce the original decisions")
    return RecordedSource(
        source_id="research:GP-2023-24-C1-vs-B1:FINAL", lane=LANE_DEVELOPMENT, phase="FINAL",
        channel="GAME_PREDICTION", result_file=GP_RESULT, receipt_id=GP_RECEIPT,
        plan_hash=plan["canonical_plan_hash"],
        hypotheses=(
            Hypothesis("H1", "GP-REST", CLAIMS["GP-REST"].statement, "registry heatcheck-registry/1"),
            Hypothesis("H2", "GP-ELO", GP_ELO_STATEMENT, "Max restatement of Research plan H2 estimand"),
        ),
        files=(GP_RESULT, GP_PLAN, GP_AMENDMENT, GP_REPLAY),
        data={"season": "2023-24", "final_epoch_id": result.get("final_epoch_id"),
              "n_games": result.get("counts_coverage", {}).get("final_games")},
    )


RECORDED_ONLY_STATEMENTS = {"GP-ELO": GP_ELO_STATEMENT}

__all__ = ["RECORDED_ONLY_STATEMENTS", "RecordRefused", "RecordedSource", "find_recorded",
           "game_prediction_source", "record"]
