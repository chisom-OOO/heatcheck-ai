"""One Jone -> Challenger -> Referee -> evidence iteration.

The orchestrator is the only part that touches the ledger. Jone and the Challenger produce
ids; attacks call Research's kernels; the Referee's decide() is pure; the evidence identity
binds plan hash, data identity, code hashes, selected attacks, all attack results and the
decision, then is written once to the append-only ledger.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from heatcheck.agents.attacks import IMPLEMENTATIONS
from heatcheck.agents.confirmatory import LANE_DEVELOPMENT
from heatcheck.agents.registry import REGISTRY_VERSION, catalogue
from heatcheck.agents.roles import (
    REFEREE_IDENTITY,
    DeterministicChallenger,
    DeterministicJone,
    decide,
    describe_ways_wrong,
    parse_proposal,
    required_attacks,
    validate_selection,
)
from heatcheck.agents.views import ShotView
from heatcheck.contracts.records import PROTOCOL_VERSION, sha256_hex
from heatcheck.contracts.research_bridge import RESEARCH_SRC
from heatcheck.ledger.evidence import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
CODE_FILES = [
    "heatcheck/agents/registry.py", "heatcheck/agents/attacks.py", "heatcheck/agents/roles.py",
    "heatcheck/agents/views.py", "heatcheck/agents/loop.py",
]


def code_identity() -> dict[str, str]:
    files = {p: sha256_hex((ROOT / p).read_bytes()) for p in CODE_FILES}
    files["research:src/heatcheck/kernels.py"] = sha256_hex((RESEARCH_SRC / "kernels.py").read_bytes())
    return files


def run_once(view: ShotView | None, ledger: EvidenceLedger, *, view_identity: dict | None = None,
             jone=None, challenger=None) -> dict[str, Any] | None:
    """Run one iteration. Returns the ledger entry, or None when Jone has nothing left."""
    jone = jone or DeterministicJone()
    challenger = challenger or DeterministicChallenger()
    vid = view.identity() if view is not None else view_identity
    done = {e["identity"]["claim"]["claim_id"] for e in ledger.all()
            if e["identity"]["data"] == vid}
    claim, rationale = parse_proposal(jone.propose(catalogue(), done))
    if claim is None:
        return None
    data_ok = view is not None and claim.data_requirement == "SHOT_VIEW"
    selected: list[str] = []
    required: list[str] = []
    to_run: list[str] = []
    results: dict[str, dict] = {}
    if data_ok:
        # The Referee's required set is computed here, deterministically, from the view. The
        # Challenger can add registered attacks to it, never remove any (RV-AL4/AL5).
        required = required_attacks(claim, view)
        selected = validate_selection(claim, challenger.select(claim, view))
        to_run = sorted(set(required) | set(selected))
        for attack_id in to_run:
            results[attack_id] = IMPLEMENTATIONS[attack_id](claim, view)
    decision, reason = decide(claim, results, data_ok, required=required if data_ok else None)
    identity = {
        "protocol_version": PROTOCOL_VERSION,
        "registry_version": REGISTRY_VERSION,
        "lane": LANE_DEVELOPMENT,
        "channel": claim.channel,
        "claim": {"claim_id": claim.claim_id, "version": claim.version,
                  "plan": claim.plan(), "canonical_plan_hash": claim.plan_hash()},
        "data": vid,
        "proposer": {**jone.identity, "rationale": rationale},
        "challenger": {**challenger.identity, "selected_attacks": selected,
                       "referee_required_attacks": required,
                       "omitted_required_attacks": sorted(set(required) - set(selected)),
                       "attacks_run": to_run,
                       "ways_claim_could_be_wrong": describe_ways_wrong(to_run)},
        "referee": REFEREE_IDENTITY,
        "code": code_identity(),
        "attack_results": [results[a] for a in sorted(results)],
        "decision": decision,
        "reason": reason,
        "limits": ("Simulator results are conditional on the generator; retrospective NBA data "
                   "are public and may be memorised; association under the stated null only."),
    }
    entry, _ = ledger.put(identity)
    return entry
