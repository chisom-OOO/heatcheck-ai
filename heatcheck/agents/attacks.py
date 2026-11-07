"""Registered attack implementations. Pure functions over a ShotView; all statistics come from
Research's kernels (incoming/research-20261107/src/heatcheck/kernels.py, loaded unchanged)."""

from __future__ import annotations

from typing import Any

import numpy as np

from heatcheck.agents.registry import ATTACKS, Claim
from heatcheck.agents.views import ShotView
from heatcheck.contracts.records import canonical_bytes, sha256_hex
from heatcheck.contracts.research_bridge import research_module


def _K():
    return research_module("kernels")


def _result(attack_id: str, claim: Claim, view: ShotView, status: str, reason: str,
            statistic=None, effect=None, interval=None, p_value=None, extra=None,
            null_method="n/a") -> dict[str, Any]:
    a = ATTACKS[attack_id]
    params = {"claim_params": claim.params, **(extra or {}).get("params", {})}
    out = {
        "claim_plan_hash": claim.plan_hash(),
        "test_id_version": f"{a.attack_id}@{a.version}",
        "parameters_hash": sha256_hex(canonical_bytes(params)),
        "input_hashes": [view.identity()["arrays_sha256"]],
        "scope": {"data_mode": view.data_mode, "source": view.source},
        "status": status,
        "reason": reason,
        "statistic": statistic,
        "effect_estimate": effect,
        "interval": interval,
        "p_value": p_value,
        "null_method_assumptions": null_method,
        "details": (extra or {}).get("details", {}),
    }
    out["evidence_hash"] = sha256_hex(canonical_bytes(out))
    return out


def input_integrity(claim: Claim, view: ShotView) -> dict:
    n = len(view.made)
    ok = (n > 0 and len(view.group) == len(view.strata) == len(view.value) == n
          and set(np.unique(view.made)).issubset({0, 1})
          and set(np.unique(view.value)).issubset({2, 3})
          and bool(np.all(np.diff(view.group) >= 0)))  # groups are contiguous blocks
    return _result("A-INPUT-INTEGRITY", claim, view, "EXECUTED" if ok else "FAILED",
                   "arrays aligned, binary outcomes, values in {2,3}, contiguous groups"
                   if ok else "malformed shot view")


def sample_size(claim: Claim, view: ShotView) -> dict:
    k, need = claim.params["k"], claim.params["min_n_each_side"]
    hm, nm, hx, nx = _K().streak_counts(view.made, view.group, k)
    enough = nm >= need and nx >= need
    return _result("A-SAMPLE-SIZE", claim, view, "EXECUTED",
                   f"after-{k}-makes n={nm}, after-{k}-misses n={nx}, need >= {need} each",
                   statistic=float(min(nm, nx)),
                   extra={"details": {"hits_after_makes": hm, "n_after_makes": nm,
                                      "hits_after_misses": hx, "n_after_misses": nx,
                                      "sufficient": enough}})


def permutation_null(claim: Claim, view: ShotView) -> dict:
    """Research D11 procedure: streak_diff, permute_within strata, mc_pvalue (one-sided)."""
    K = _K()
    k, B, seed = claim.params["k"], claim.params["B"], claim.params["seed"]
    t = K.streak_diff(view.made, view.group, k)
    if t is None:
        return _result("A-PERMUTATION-NULL", claim, view, "UNSUPPORTED",
                       "statistic undefined: no attempts after a streak on one side")
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(B):
        v = K.streak_diff(K.permute_within(view.made, view.strata, rng), view.group, k)
        if v is not None:
            null.append(v)
    null = np.asarray(null, dtype=float)
    p = K.mc_pvalue(t, null)
    effect = float(t - null.mean())
    return _result(
        "A-PERMUTATION-NULL", claim, view, "EXECUTED",
        f"T={t:.6f}, null mean={null.mean():.6f}, one-sided p={p:.6f} (B_eff={len(null)})",
        statistic=float(t), effect=effect,
        interval=[float(np.quantile(null, 0.025)), float(np.quantile(null, 0.975))],
        p_value=float(p),
        null_method=("outcomes exchangeable within player-game-shot_value strata; eligibility "
                     "recomputed per draw; ignores within-game difficulty drift (Research D11)"),
        extra={"details": {"null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)),
                           "B_effective": int(len(null))}})


def shot_value_selection(claim: Claim, view: ShotView) -> dict:
    k, gap_max = claim.params["k"], claim.params["max_shot_value_share_gap"]
    three = (view.value == 3).astype(np.int8)
    # positions eligible after k makes / k misses (same rule as kernels.streak_counts)
    n = len(view.made)
    allm = np.ones(n, dtype=bool)
    allx = np.ones(n, dtype=bool)
    for j in range(1, k + 1):
        prev = np.full(n, -1, dtype=np.int8)
        prev[j:] = view.made[:-j]
        same = np.zeros(n, dtype=bool)
        same[j:] = view.group[j:] == view.group[:-j]
        allm &= same & (prev == 1)
        allx &= same & (prev == 0)
    if allm.sum() == 0 or allx.sum() == 0:
        return _result("A-SHOT-VALUE-SELECTION", claim, view, "UNSUPPORTED",
                       "no attempts after a streak on one side")
    gap = float(three[allm].mean() - three[allx].mean())
    flagged = abs(gap) > gap_max
    return _result("A-SHOT-VALUE-SELECTION", claim, view, "EXECUTED",
                   f"3pt share after makes minus after misses = {gap:+.4f}; limit {gap_max}",
                   statistic=gap, extra={"details": {"flagged": flagged}})


def split_half(claim: Claim, view: ShotView) -> dict:
    """Disjoint halves by group-id parity; each half gets its own within-stratum permutation
    null (same B and seed), and reports its bias-corrected effect T - mean(null)."""
    K = _K()
    k, B, seed = claim.params["k"], claim.params["B"], claim.params["seed"]
    effects = {}
    for name, mask in (("even", view.group % 2 == 0), ("odd", view.group % 2 == 1)):
        made, group, strata = view.made[mask], view.group[mask], view.strata[mask]
        t = K.streak_diff(made, group, k)
        if t is None:
            return _result("A-SPLIT-HALF-REPLICATION", claim, view, "UNSUPPORTED",
                           f"statistic undefined on {name} half")
        rng = np.random.default_rng(seed)
        null = [v for _ in range(B)
                if (v := K.streak_diff(K.permute_within(made, strata, rng), group, k)) is not None]
        effects[name] = float(t - np.mean(null))
    return _result("A-SPLIT-HALF-REPLICATION", claim, view, "EXECUTED",
                   f"bias-corrected effect even={effects['even']:+.6f}, odd={effects['odd']:+.6f}",
                   extra={"details": {"effect_even": effects["even"], "effect_odd": effects["odd"],
                                      "same_positive_sign": effects["even"] > 0
                                      and effects["odd"] > 0}})


IMPLEMENTATIONS = {
    "A-INPUT-INTEGRITY": input_integrity,
    "A-SAMPLE-SIZE": sample_size,
    "A-PERMUTATION-NULL": permutation_null,
    "A-SHOT-VALUE-SELECTION": shot_value_selection,
    "A-SPLIT-HALF-REPLICATION": split_half,
}
