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
from heatcheck.contracts.records import loads_strict

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


MAX_RATIONALE = 500


def _strict_object(raw: str, keys: set[str], what: str) -> dict:
    """Strict JSON object: no duplicate keys, no NaN/Infinity, exactly ``keys`` (RV-AL6)."""
    if not isinstance(raw, str):
        raise ProposalRefused(f"{what} must be a JSON string")
    try:
        obj = loads_strict(raw)
    except (TypeError, ValueError) as e:
        raise ProposalRefused(f"{what} is not strict JSON: {e}") from None
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ProposalRefused(f"{what} must be exactly {{{', '.join(sorted(keys))}}}")
    return obj


def parse_proposal(raw: str) -> tuple[Claim | None, str]:
    """Validate the Discoverer's output: exactly {claim_id, rationale}. claim_id is null or a
    string that is exactly a registered id (no case folding, no trimming); rationale is a
    string of at most 500 characters. Anything else is refused, never coerced (RV-AL6)."""
    obj = _strict_object(raw, {"claim_id", "rationale"}, "proposal")
    cid, rationale = obj["claim_id"], obj["rationale"]
    if not isinstance(rationale, str):
        raise ProposalRefused("rationale must be a string")
    if len(rationale) > MAX_RATIONALE:
        raise ProposalRefused(f"rationale longer than {MAX_RATIONALE} characters")
    if cid is None:
        return None, rationale
    if not isinstance(cid, str):
        raise ProposalRefused(f"claim_id must be a string or null, not {type(cid).__name__}")
    if cid not in CLAIMS:
        raise ProposalRefused(f"claim_id {cid!r} is not registered")
    return CLAIMS[cid], rationale


def parse_selection(raw: str) -> list[str]:
    """Validate a model Challenger's JSON output: exactly {"attacks": [...]}. The ids are then
    checked by validate_selection."""
    obj = _strict_object(raw, {"attacks"}, "selection")
    if not isinstance(obj["attacks"], list):
        raise ProposalRefused("attacks must be a list")
    return obj["attacks"]


# --------------------------------------------------------------------------- Challenger


def view_capabilities(view: ShotView) -> set[str]:
    import numpy as np

    have = {"value"} if view.value is not None else set()
    if len(np.unique(view.group)) >= 2:
        have.add("min_groups_2")
    return have


def required_attacks(claim: Claim, view: ShotView) -> list[str]:
    """Deterministic: every mandatory attack plus every optional attack whose prerequisites the
    view meets. The Referee requires all of them (RV-AL4); a Challenger can add, never remove."""
    have = view_capabilities(view)
    return sorted(a.attack_id for a in ATTACKS.values() if a.mandatory or set(a.requires) <= have)


class DeterministicChallenger:
    """Names the ways the claim could be wrong; selects exactly the required attack set."""

    identity = {**STANDIN, "role": "challenger"}

    def select(self, claim: Claim, view: ShotView) -> list[str]:
        return required_attacks(claim, view)


def validate_selection(claim: Claim, selected: list[str]) -> list[str]:
    """A Challenger's selection: a list of distinct registered attack id strings. Refused,
    never repaired, otherwise (RV-AL6)."""
    if not isinstance(selected, list) or not all(isinstance(a, str) for a in selected):
        raise ProposalRefused("selection must be a list of attack id strings")
    if len(set(selected)) != len(selected):
        raise ProposalRefused(f"duplicate attack ids in selection {selected}")
    unknown = [a for a in selected if a not in ATTACKS]
    if unknown:
        raise ProposalRefused(f"unregistered attacks {unknown}")
    return sorted(selected)


# --------------------------------------------------------------------------- Referee


def decide(claim: Claim, results: dict[str, dict], data_available: bool,
           required: list[str] | None = None) -> tuple[str, str]:
    """Deterministic decision rule (registry version heatcheck-registry/1). Pure.

    ``required`` is the attack set the Referee demands (``required_attacks``). When it is not
    given, every registered attack is required. Optional attacks can only overturn
    SURVIVED_PROTOCOL, so a missing required optional attack blocks that outcome and yields
    INSUFFICIENT_EVIDENCE (RV-AL4)."""
    required = sorted(ATTACKS) if required is None else sorted(required)
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
    not_run = [a for a in required if a not in results]
    if not_run:
        return "INSUFFICIENT_EVIDENCE", ("rejected the null, but required attacks were not run: "
                                         f"{not_run}")
    return "SURVIVED_PROTOCOL", (f"p={perm['p_value']:.4f} <= {alpha}, effect "
                                 f"{perm['effect_estimate']:+.4f} >= {floor}; selected attacks "
                                 "did not overturn it. Association under the stated null only.")


REFEREE_IDENTITY = {"kind": "DETERMINISTIC_CODE", "rule": REGISTRY_VERSION, "version": "1"}

__all__ = ["DeterministicChallenger", "DeterministicJone", "ProposalRefused", "Proposer",
           "REFEREE_IDENTITY", "catalogue", "decide", "parse_proposal", "parse_selection",
           "required_attacks", "validate_selection"]


def describe_ways_wrong(attack_ids: list[str]) -> list[dict[str, Any]]:
    return [{"attack_id": a, "way_claim_could_be_wrong": ATTACKS[a].way_claim_could_be_wrong}
            for a in attack_ids]
