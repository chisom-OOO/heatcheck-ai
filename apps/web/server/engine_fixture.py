"""LOCAL FIXTURE ENGINE: SYNTHETIC data only. Stand-in for the Research engine.

Purpose: let the Experience layer run a real discover -> challenge -> referee loop end to end
with deterministic code until Research's engine JSON is integrated. Every output is labelled
engine="fixture-local" and data_mode="SYNTHETIC". It claims no NBA result.

Separation (tested in tests/test_engine.py):
  * `Custodian` holds the hidden configuration and generates data. Its config lives in
    name-mangled private attributes and is returned only by `reveal()`.
  * `analyse(data, plan, emit, cancelled)` is the product-side agent. It has no truth argument
    and the data dict it receives contains no configuration keys.
"""
import math

import numpy as np
from scipy import stats as sps

ENGINE_ID = "fixture-local-0.2"
FAMILIES = ("parametric_beta_binomial", "heavy_tailed_talent", "ar1_drift")
TUNING_FAMILIES = ("parametric_beta_binomial", "heavy_tailed_talent")
HELD_OUT_FAMILY = "ar1_drift"          # never used to tune the referee thresholds below
EFFECTS = ("null", "weak", "planted", "confounded")
EFFECT_SIZE = {"null": 0.0, "weak": 0.02, "planted": 0.08, "confounded": 0.0}
N_SHOOTERS, N_SHOTS, STREAK_K = 30, 300, 3
N_PERMS = 400
ALPHA = 0.05
PRACTICAL_FLOOR = 0.03


class Custodian:
    """Holds the hidden truth. Product agents never receive an instance."""

    def __init__(self, seed, family, effect, effect_size=None):
        if family not in FAMILIES or effect not in EFFECTS:
            raise ValueError("unknown family/effect")
        size = EFFECT_SIZE[effect] if effect_size is None else float(effect_size)
        if not (0.0 <= size <= 0.2):
            raise ValueError("effect_size outside allowed range [0, 0.2]")
        if effect in ("null", "confounded") and size != 0.0:
            raise ValueError("null/confounded leagues have no planted effect")
        self.__seed, self.__family, self.__effect, self.__size = int(seed), family, effect, size

    def generate(self):
        rng = np.random.default_rng(self.__seed)
        S, N = N_SHOOTERS, N_SHOTS
        if self.__family == "heavy_tailed_talent":
            base = 0.62 + 0.06 * rng.standard_t(3, size=S)
        else:
            base = rng.beta(60, 20, size=S)
        base = np.clip(base, 0.4, 0.95)
        seqs = np.zeros((S, N), dtype=np.int8)
        drift = np.zeros(S)
        u = rng.random((S, N))
        noise = rng.normal(0, 0.01, size=(S, N))
        t_idx = np.arange(N)
        for t in range(N):
            p = base.copy()
            if self.__family == "ar1_drift":
                drift = 0.9 * drift + noise[:, t]
                p = p + drift
            if self.__size > 0 and t >= STREAK_K:
                streak = seqs[:, t - STREAK_K:t].sum(axis=1) == STREAK_K
                p = p + self.__size * streak
            if self.__effect == "confounded":
                # slow within-sequence talent drift: fakes streak dependence with no causal effect
                p = p + 0.1 * np.sin(t_idx[t] / 25.0 + base * 10)
            seqs[:, t] = (u[:, t] < np.clip(p, 0.01, 0.99)).astype(np.int8)
        tokens = [f"P{i:03d}" for i in range(S)]   # anonymised shooter tokens
        return {"sequences": seqs, "shooters": tokens, "scope": "synthetic free-throw-like sequences"}

    def reveal(self):
        return {"family": self.__family, "effect": self.__effect, "effect_size": self.__size,
                "seed": self.__seed, "held_out_family": self.__family == HELD_OUT_FAMILY}


# ---------------------------------------------------------------- statistics (deterministic)

def streak_stat(seqs, k=STREAK_K):
    """Pooled P(make | previous k makes) - P(make | otherwise), within each sequence."""
    seqs = np.asarray(seqs)
    win = np.lib.stride_tricks.sliding_window_view(seqs, k, axis=1)[:, :-1]  # windows ending t-1
    after = seqs[:, k:]
    mask = win.sum(axis=-1) == k
    na, nb = int(mask.sum()), int((~mask).sum())
    if na == 0 or nb == 0:
        return None, na
    return float(after[mask].mean() - after[~mask].mean()), na


def permutation_p(seqs, obs, rng, perms=N_PERMS):
    """Within-sequence permutation null. Preserves each shooter's make count, so it also
    absorbs the Miller-Sanjurjo finite-sequence bias of the naive estimator."""
    ge = 0
    for _ in range(perms):
        t, _ = streak_stat(rng.permuted(seqs, axis=1))
        if t is not None and t >= obs:
            ge += 1
    return (ge + 1) / (perms + 1)


def bootstrap_ci(seqs, rng, n=300):
    vals = []
    S = len(seqs)
    for _ in range(n):
        t, _ = streak_stat(seqs[rng.integers(0, S, S)])
        if t is not None:
            vals.append(t)
    if len(vals) < 50:
        return None
    lo, hi = np.quantile(vals, [0.025, 0.975])
    return [float(lo), float(hi)]


def shrinkage(seqs, tokens, level=0.90):
    """Beta-binomial empirical Bayes (method of moments). Returns raw vs shrunk per shooter."""
    makes = seqs.sum(axis=1).astype(float)
    n = np.full(len(makes), seqs.shape[1], dtype=float)
    raw = makes / n
    m, v = raw.mean(), raw.var(ddof=1)
    noise = m * (1 - m) / n.mean()
    var_t = max(v - noise, 1e-6)
    conc = max(m * (1 - m) / var_t - 1, 1.0)
    a0, b0 = m * conc, (1 - m) * conc
    a, b = a0 + makes, b0 + n - makes
    lo, hi = sps.beta.ppf((1 - level) / 2, a, b), sps.beta.ppf((1 + level) / 2, a, b)
    rows = [{"shooter": tokens[i], "attempts": int(n[i]), "makes": int(makes[i]),
             "raw": float(raw[i]), "shrunk": float(a[i] / (a[i] + b[i])),
             "interval": [float(lo[i]), float(hi[i])]} for i in range(len(makes))]
    return {
        "method": "beta-binomial empirical Bayes, method of moments",
        "prior": {"a": float(a0), "b": float(b0)},
        "reliability": float(var_t / v) if v > 0 else None,
        "interval_level": level,
        "rows": rows,
    }


# ---------------------------------------------------------------- product-side analysis

def analyse(data, plan, emit, cancelled, perms=N_PERMS, include_talent=True):
    """Product-side Discoverer/Challenger/Referee loop. No truth access.
    emit(stage, detail) reports actual stage events; returns None if cancelled."""
    seqs = np.asarray(data["sequences"])
    tokens = data.get("shooters") or [f"P{i:03d}" for i in range(len(seqs))]
    rng = np.random.default_rng(1234)
    k = int(plan.get("streak_length") or STREAK_K)
    floor = float(plan.get("practical_effect_floor", PRACTICAL_FLOOR))
    emit("validating", f"{seqs.shape[0]} sequences, {seqs.size} attempts")
    if seqs.ndim != 2 or not np.isin(seqs, (0, 1)).all():
        return {"decision": "DATA_INVALID", "reason": "non-binary outcome or ragged sequences", "attacks": []}
    if cancelled():
        return None

    emit("estimating", f"pooled P(make | previous {k} makes) minus P(make | otherwise)")
    obs, n_streak = streak_stat(seqs, k)
    if obs is None:
        return {"decision": "INSUFFICIENT_EVIDENCE", "reason": "no eligible streak positions", "attacks": []}
    ci = bootstrap_ci(seqs, rng)
    attacks = []

    emit("challenging", "Challenger: within-sequence permutation null")
    p = permutation_p(seqs, obs, rng, perms)
    attacks.append(_attack("permutation_within_sequence", obs, ci, p, obs > 0 and p < ALPHA,
                           "make/miss exchangeable within a shooter under the null; corrects finite-sequence bias",
                           f"{perms} permutations"))
    if cancelled():
        return None

    emit("challenging", "Challenger: split-half replication")
    half = seqs.shape[1] // 2
    t1, _ = streak_stat(seqs[:, :half], k)
    t2, _ = streak_stat(seqs[:, half:], k)
    same = t1 is not None and t2 is not None and t1 > 0 and t2 > 0
    attacks.append(_attack("split_half_sign", [t1, t2], None, None, bool(same),
                           "first and second halves are independent samples of the same process",
                           "pass requires a positive estimate in both halves"))

    emit("challenging", "Challenger: placebo (labels shifted by 7 shots)")
    lag_t, _ = _lagged_stat(seqs, k, lag=7)
    placebo_p = permutation_p_lag(seqs, lag_t, rng, k, 7, max(100, perms // 3)) if lag_t is not None else None
    placebo_ok = placebo_p is None or placebo_p > ALPHA
    attacks.append(_attack("placebo_lag7", lag_t, None, placebo_p, placebo_ok,
                           "a streak 7 shots earlier should not predict the current shot", "pass requires p > 0.05"))
    if cancelled():
        return None

    emit("challenging", "Challenger: leave-one-shooter-out influence")
    signs = []
    for i in range(len(seqs)):
        t, _ = streak_stat(np.delete(seqs, i, axis=0), k)
        signs.append(bool(t is not None and t > 0))
    attacks.append(_attack("leave_one_out_sign", sum(signs), None, None, all(signs),
                           "no single shooter drives the sign", f"positive in {sum(signs)} of {len(signs)} drops"))
    if cancelled():
        return None

    talent = None
    if include_talent:
        emit("estimating", "raw versus shrunk talent (descriptive, not a check)")
        talent = shrinkage(seqs, tokens)
    emit("referee", "Referee: deterministic protocol rules")
    checks_pass = all(a["pass"] for a in attacks) and ci is not None and ci[0] > 0
    if checks_pass and obs >= floor:
        decision, reason = "SURVIVED_PROTOCOL", "every registered check passed and the estimate clears the practical floor"
    elif checks_pass:
        decision, reason = "NOT_SUPPORTED", "checks passed but the estimate is below the practical floor"
    elif ci is not None and ci[0] <= 0 <= ci[1] and (ci[1] - ci[0]) > 2 * floor:
        decision, reason = "INSUFFICIENT_EVIDENCE", "interval includes zero and is wide relative to the practical floor"
    else:
        failed = [a["test_id"] for a in attacks if not a["pass"]]
        decision, reason = "NOT_SUPPORTED", "failed registered check(s): " + ", ".join(failed)
    out = {
        "engine": ENGINE_ID, "data_mode": "SYNTHETIC",
        "decision": decision, "reason": reason, "effect_estimate": obs, "interval": ci,
        "interval_method": "shooter-level bootstrap, 300 resamples, 95%",
        "eligible_positions": n_streak, "sequences": int(seqs.shape[0]), "attempts": int(seqs.size),
        "practical_effect_floor": floor, "alpha": ALPHA, "attacks": attacks,
        "effect_units": "difference in make probability (absolute)",
    }
    if include_talent:
        out["talent"] = talent
    return out


def _attack(test_id, statistic, interval, p_value, passed, assumption, note):
    return {"test_id": test_id, "version": "1", "status": "OK", "statistic": statistic,
            "interval": interval, "p_value": p_value, "pass": bool(passed),
            "null_method_assumptions": assumption, "note": note}


def _lagged_stat(seqs, k, lag):
    """P(make at t | makes at t-lag-k..t-lag-1) - otherwise."""
    if seqs.shape[1] <= k + lag:
        return None, 0
    win = np.lib.stride_tricks.sliding_window_view(seqs, k, axis=1)[:, : seqs.shape[1] - k - lag]
    after = seqs[:, k + lag:]
    mask = win.sum(axis=-1) == k
    if mask.sum() == 0 or (~mask).sum() == 0:
        return None, 0
    return float(after[mask].mean() - after[~mask].mean()), int(mask.sum())


def permutation_p_lag(seqs, obs, rng, k, lag, perms):
    ge = 0
    for _ in range(perms):
        t, _ = _lagged_stat(rng.permuted(seqs, axis=1), k, lag)
        if t is not None and t >= obs:
            ge += 1
    return (ge + 1) / (perms + 1)


# ---------------------------------------------------------------- harness batch (custodian side)

def harness_batch(leagues_per_cell=12, seed0=10_000, perms=150, sizes=(0.0, 0.02, 0.04, 0.06, 0.08, 0.12),
                  progress=None, cancelled=lambda: False):
    """Runs the registered policy on many synthetic leagues. The Custodian scores decisions
    against truth AFTER each decision; analyse() never sees the configuration.
    Reports tuning families and the held-out family separately."""
    plan = {"streak_length": STREAK_K, "practical_effect_floor": PRACTICAL_FLOOR}
    seed = seed0
    cells = {}
    detect = {}
    total = len(FAMILIES) * len(EFFECTS) * leagues_per_cell + len(sizes) * leagues_per_cell
    done = 0

    def tick():
        nonlocal done
        done += 1
        if progress:
            progress(done, total)

    for fam in FAMILIES:
        for eff in EFFECTS:
            counts = {}
            for _ in range(leagues_per_cell):
                if cancelled():
                    return None
                seed += 1
                res = analyse(Custodian(seed, fam, eff).generate(), plan, lambda *a: None, cancelled,
                              perms=perms, include_talent=False)
                counts[res["decision"]] = counts.get(res["decision"], 0) + 1
                tick()
            cells[f"{fam}|{eff}"] = {"family": fam, "effect": eff, "truth_has_effect": EFFECT_SIZE[eff] > 0,
                                     "held_out": fam == HELD_OUT_FAMILY, "n": leagues_per_cell, "decisions": counts}
    for s in sizes:
        surv = 0
        for _ in range(leagues_per_cell):
            if cancelled():
                return None
            seed += 1
            eff = "null" if s == 0 else "planted"
            res = analyse(Custodian(seed, "parametric_beta_binomial", eff, s).generate(), plan,
                          lambda *a: None, cancelled, perms=perms, include_talent=False)
            surv += res["decision"] == "SURVIVED_PROTOCOL"
            tick()
        lo, hi = wilson(surv, leagues_per_cell)
        detect[str(s)] = {"effect_size": s, "n": leagues_per_cell, "survived": surv,
                          "rate": surv / leagues_per_cell, "interval95": [lo, hi]}

    def summarise(held_out):
        fp = tp = nulls = reals = 0
        for c in cells.values():
            if c["held_out"] != held_out:
                continue
            s = c["decisions"].get("SURVIVED_PROTOCOL", 0)
            if c["truth_has_effect"]:
                tp += s
                reals += c["n"]
            else:
                fp += s
                nulls += c["n"]
        return {"null_leagues": nulls, "false_survivals": fp, "false_survival_rate": fp / nulls if nulls else None,
                "false_survival_interval95": list(wilson(fp, nulls)) if nulls else None,
                "effect_leagues": reals, "true_survivals": tp, "power": tp / reals if reals else None,
                "power_interval95": list(wilson(tp, reals)) if reals else None,
                "survived_total": fp + tp,
                "false_discovery_proportion": (fp / (fp + tp)) if (fp + tp) else None}

    return {
        "engine": ENGINE_ID, "data_mode": "SYNTHETIC",
        "scope": f"{N_SHOOTERS} shooters x {N_SHOTS} attempts per league; streak length {STREAK_K}; "
                 f"{perms} permutations per league in batch mode",
        "leagues_per_cell": leagues_per_cell, "seed0": seed0,
        "tuning_families": list(TUNING_FAMILIES), "held_out_family": HELD_OUT_FAMILY,
        "cells": cells, "tuning_summary": summarise(False), "held_out_summary": summarise(True),
        "detectability": detect,
        "caveat": "Simulator-conditioned. Says nothing about real NBA shooting. Small league counts: read the intervals.",
    }


def wilson(k, n, z=1.959964):
    if n == 0:
        return (None, None)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))
