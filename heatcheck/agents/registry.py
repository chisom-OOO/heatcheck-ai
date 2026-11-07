"""Registered claims and attacks for the Jone -> Challenger -> Referee loop.

The registry is data, not model output. Jone may only pick a claim_id listed here; the
Challenger may only pick attack ids listed here; the Referee applies the decision rule
stored with the claim. Parameters marked RESEARCH_D11 are copied from Research's
pre-registration (incoming/research-20261107/DECISIONS.md D11). Parameters marked
MAX_PROPOSED are Max's proposals awaiting Research review; they are not research results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from heatcheck.contracts.records import canonical_bytes, sha256_hex

REGISTRY_VERSION = "heatcheck-registry/1"


@dataclass(frozen=True)
class Attack:
    attack_id: str
    version: str
    mandatory: bool
    way_claim_could_be_wrong: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    claim_id: str
    version: str
    channel: str
    statement: str
    estimand: str
    data_requirement: str  # SHOT_VIEW or GAME_SEASON_VIEW
    params: dict[str, Any] = field(default_factory=dict)
    param_sources: dict[str, str] = field(default_factory=dict)

    def plan(self) -> dict[str, Any]:
        attacks = sorted(a.attack_id for a in ATTACKS.values() if a.mandatory)
        return {
            "registry_version": REGISTRY_VERSION,
            "claim_id": self.claim_id,
            "version": self.version,
            "kind": self.channel,
            "statement": self.statement,
            "estimand": self.estimand,
            "data_requirement": self.data_requirement,
            "params": self.params,
            "param_sources": self.param_sources,
            "mandatory_attacks": attacks,
        }

    def plan_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.plan()))


ATTACKS: dict[str, Attack] = {a.attack_id: a for a in [
    Attack("A-INPUT-INTEGRITY", "1", True,
           "Shot order, grouping or outcomes are malformed, so any statistic is meaningless."),
    Attack("A-SAMPLE-SIZE", "1", True,
           "Too few attempts follow streaks to say anything; absence of rejection is not evidence."),
    Attack("A-PERMUTATION-NULL", "1", True,
           "The naive streak difference is biased under the null (Miller-Sanjurjo); the observed "
           "value may be ordinary once eligibility is recomputed under within-stratum shuffles."),
    Attack("A-SHOT-VALUE-SELECTION", "1", False,
           "After makes players may take different (e.g. more 3pt) shots, so the comparison "
           "mixes shot difficulty with streak state.", requires=("value",)),
    Attack("A-SPLIT-HALF-REPLICATION", "1", False,
           "The effect may come from a handful of player-games; it should keep its sign on "
           "disjoint halves of the groups.", requires=("min_groups_2",)),
]}

_HH_SOURCES = {
    "k": "RESEARCH_D11", "B": "RESEARCH_D11", "seed": "RESEARCH_D11", "alpha": "RESEARCH_D11",
    "strata": "RESEARCH_D11",
    "min_n_each_side": "MAX_PROPOSED", "practical_floor": "MAX_PROPOSED",
    "max_shot_value_share_gap": "MAX_PROPOSED",
}

CLAIMS: dict[str, Claim] = {c.claim_id: c for c in [
    Claim(
        "HH-K3", "1", "SHOT_ASSOCIATION",
        "Within a player-game, a field goal after 3 straight makes is made more often than one "
        "after 3 straight misses, beyond what within-stratum shuffling produces.",
        "pooled P(make | prev 3 FGA made) - P(make | prev 3 FGA missed), within player-game",
        "SHOT_VIEW",
        {"k": 3, "B": 999, "seed": 20261107, "alpha": 0.05,
         "strata": "player-game-shot_value", "min_n_each_side": 30, "practical_floor": 0.01,
         "max_shot_value_share_gap": 0.10},
        _HH_SOURCES,
    ),
    Claim(
        "HH-K2", "1", "SHOT_ASSOCIATION",
        "Same as HH-K3 with streak length 2.",
        "pooled P(make | prev 2 FGA made) - P(make | prev 2 FGA missed), within player-game",
        "SHOT_VIEW",
        {"k": 2, "B": 999, "seed": 20261107, "alpha": 0.05,
         "strata": "player-game-shot_value", "min_n_each_side": 30, "practical_floor": 0.01,
         "max_shot_value_share_gap": 0.10},
        {**_HH_SOURCES, "k": "MAX_PROPOSED"},
    ),
    Claim(
        "GP-REST", "1", "GAME_PREDICTION",
        "Rest-day difference and back-to-backs improve pre-tip win forecasts over Elo.",
        "mean(log_loss_elo - log_loss_elo_plus_rest) on unseen games",
        "GAME_SEASON_VIEW",
        {}, {},
    ),
]}


def catalogue() -> list[dict[str, Any]]:
    """What Jone is allowed to see: ids, statements and data requirements, no results."""
    return [{"claim_id": c.claim_id, "version": c.version, "channel": c.channel,
             "statement": c.statement, "data_requirement": c.data_requirement}
            for c in CLAIMS.values()]
