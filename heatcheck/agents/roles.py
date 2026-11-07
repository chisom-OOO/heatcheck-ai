"""Runtime roles: Jone (Discoverer), Challenger and the deterministic Referee.

Jone and the Challenger are interfaces with deterministic stand-ins. A model-backed
implementation may replace the stand-in later, but its output passes the same validation:
it can only name registered ids. The Referee is always deterministic code; no model output
reaches a decision.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from heatcheck.agents.registry import ATTACKS, CLAIMS, REGISTRY_VERSION, Claim, catalogue
from heatcheck.agents.views import ShotView

STANDIN = {"kind": "DETERMINISTIC_STANDIN", "model": None, "prompt": None, "version": "1"}


class ProposalRefused(ValueError):
    pass


# --------------------------------------------------------------------------- Jone


class Proposer(Protocol):
    identity: dict

    def propose(self, catalogue: list[dict], already_evaluated: set[str]) -> str: ...


class DeterministicJone:
    """Picks the first registered claim, in registry order, not yet evaluated on this view."""

    identity = {**STANDIN, "role": "jone"}

    def propose(self, catalogue: list[dict], already_evaluated: set[str]) -> str:
        for c in catalogue:
            if c["claim_id"] not in already_evaluated:
                return json.dumps({"claim_id": c["claim_id"],
                                   "rationale": "next unevaluated registered claim"})
        return json.dumps({"claim_id": None, "rationale": "all registered claims evaluated"})


def parse_proposal(raw: str) -> tuple[Claim | None, str]:
    """Validate Jone's output. Anything but a registered claim id is refused."""
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        raise ProposalRefused("proposal is not JSON") from None
    if not isinstance(obj, dict) or set(obj) != {"claim_id", "rationale"}:
        raise ProposalRefused("proposal must be exactly {claim_id, rationale}")
    if obj["claim_id"] is None:
        return None, str(obj["rationale"])
    if obj["claim_id"] not in CLAIMS:
        raise ProposalRefused(f"claim_id {obj['claim_id']!r} is not registered")
    return CLAIMS[obj["claim_id"]], str(obj["rationale"])[:500]


# --------------------------------------------------------------------------- Challenger


class DeterministicChallenger:
    """Names the ways the claim could be wrong, then selects every mandatory attack plus each
    optional attack whose prerequisites the view meets."""

    identity = {**STANDIN, "role": "challenger"}

    def select(self, claim: Claim, view: ShotView) -> list[str]:
        have = {"value"} if view.value is not None else set()
        import numpy as np

        if len(np.unique(view.group)) >= 2:
            have.add("min_groups_2")
        return sorted(a.attack_id for a in ATTACKS.values()
                      if a.mandatory or set(a.requires) <= have)


def validate_selection(claim: Claim, selected: list[str]) -> list[str]:
    unknown = [a for a in selected if a not in ATTACKS]
    if unknown:
        raise ProposalRefused(f"unregistered attacks {unknown}")
    return sorted(set(selected))


# --------------------------------------------------------------------------- Referee


def decide(claim: Claim, results: dict[str, dict], data_available: bool) -> tuple[str, str]:
    """Deterministic decision rule (registry version heatcheck-registry/1). Pure."""
    if not data_available:
        return "BLOCKED", f"no {claim.data_requirement} implemented for {claim.claim_id}"
    missing = [a.attack_id for a in ATTACKS.values() if a.mandatory and a.attack_id not in results]
    if missing:
        return "BLOCKED", f"mandatory attacks not run: {missing}"
    if results["A-INPUT-INTEGRITY"]["status"] != "EXECUTED":
        return "DATA_INVALID", results["A-INPUT-INTEGRITY"]["reason"]
    unsupported = [a for a, r in results.items()
                   if ATTACKS[a].mandatory and r["status"] != "EXECUTED"]
    if unsupported:
        return "INSUFFICIENT_EVIDENCE", f"mandatory attacks not executable: {unsupported}"
    ss = results["A-SAMPLE-SIZE"]["details"]
    if not ss["sufficient"]:
        return "INSUFFICIENT_EVIDENCE", results["A-SAMPLE-SIZE"]["reason"]
    perm = results["A-PERMUTATION-NULL"]
    alpha, floor = claim.params["alpha"], claim.params["practical_floor"]
    if not (perm["p_value"] <= alpha and perm["effect_estimate"] >= floor):
        return "NOT_SUPPORTED", (f"p={perm['p_value']:.4f} (alpha {alpha}), bias-corrected "
                                 f"effect {perm['effect_estimate']:+.4f} (floor {floor})")
    sv = results.get("A-SHOT-VALUE-SELECTION")
    if sv and sv["status"] == "EXECUTED" and sv["details"]["flagged"]:
        return "INSUFFICIENT_EVIDENCE", "rejected the null, but shot-value selection not excluded: " \
            + sv["reason"]
    sh = results.get("A-SPLIT-HALF-REPLICATION")
    if sh and sh["status"] == "EXECUTED" and not sh["details"]["same_positive_sign"]:
        return "INSUFFICIENT_EVIDENCE", "rejected the null, but not replicated on both halves: " \
            + sh["reason"]
    return "SURVIVED_PROTOCOL", (f"p={perm['p_value']:.4f} <= {alpha}, effect "
                                 f"{perm['effect_estimate']:+.4f} >= {floor}; selected attacks "
                                 "did not overturn it. Association under the stated null only.")


REFEREE_IDENTITY = {"kind": "DETERMINISTIC_CODE", "rule": REGISTRY_VERSION, "version": "1"}

__all__ = ["DeterministicChallenger", "DeterministicJone", "ProposalRefused", "Proposer",
           "REFEREE_IDENTITY", "catalogue", "decide", "parse_proposal", "validate_selection"]


def describe_ways_wrong(attack_ids: list[str]) -> list[dict[str, Any]]:
    return [{"attack_id": a, "way_claim_could_be_wrong": ATTACKS[a].way_claim_could_be_wrong}
            for a in attack_ids]
