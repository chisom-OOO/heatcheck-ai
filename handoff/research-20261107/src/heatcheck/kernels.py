"""Pure deterministic statistical kernels. No model ever produces these numbers."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

# --------------------------------------------------------------------------- beta-binomial
@dataclass(frozen=True)
class BetaPosterior:
    a: float
    b: float
    n: int
    note: str = ""

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    @property
    def var(self) -> float:
        s = self.a + self.b
        return self.a * self.b / (s * s * (s + 1))


def beta_binomial_posterior(a: float, b: float, s: int, n: int) -> BetaPosterior:
    if not (a > 0 and b > 0) or s < 0 or n < 0 or s > n:
        raise ValueError("invalid prior or counts")
    note = "no observations: prior returned, not a measured talent estimate" if n == 0 else ""
    return BetaPosterior(a + s, b + n - s, n, note)


# --------------------------------------------------------------------------- proper scores
def clip(p: np.ndarray, eps: float) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("probabilities must be finite and in [0,1]")
    return np.clip(p, eps, 1 - eps)


def log_loss_per(y: np.ndarray, p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    y = np.asarray(y, dtype=float); p = clip(p, eps)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier_per(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = clip(p, 0.0)
    return (p - np.asarray(y, dtype=float)) ** 2


# --------------------------------------------------------------------------- streak statistics
def prop_after_streak(seq: tuple[int, ...] | np.ndarray, k: int) -> float | None:
    """Within one sequence: proportion of hits immediately following k consecutive hits.
    None (undefined) when no trial follows such a streak."""
    seq = list(seq)
    num = den = 0
    for i in range(k, len(seq)):
        if all(seq[i - j] == 1 for j in range(1, k + 1)):
            den += 1; num += seq[i]
    return None if den == 0 else num / den


def exact_expected_prop_after_streak(n: int, k: int, p: Fraction = Fraction(1, 2)) -> Fraction:
    """Exact E[P̂(H|k hits) | defined] over all 2^n Bernoulli(p) sequences (Miller–Sanjurjo).
    Exhaustive enumeration — only for tiny n."""
    if n > 20:
        raise ValueError("enumeration limited to n<=20")
    tot_w = Fraction(0); acc = Fraction(0)
    for seq in itertools.product((0, 1), repeat=n):
        v = prop_after_streak(seq, k)
        if v is None:
            continue
        h = sum(seq); w = p ** h * (1 - p) ** (n - h)
        tot_w += w; acc += w * Fraction(v).limit_denominator(10 ** 6)
    return acc / tot_w


def streak_counts(made: np.ndarray, group: np.ndarray, k: int) -> tuple[int, int, int, int]:
    """Pooled counts over all groups: (hits_after_k_makes, n_after_k_makes, hits_after_k_misses, n_after_k_misses).
    `made` must be ordered within group; `group` is an integer label per row (contiguous blocks)."""
    made = np.asarray(made, dtype=np.int8); group = np.asarray(group)
    n = len(made)
    allm = np.ones(n, dtype=bool); allx = np.ones(n, dtype=bool)
    for j in range(1, k + 1):
        prev = np.empty(n, dtype=np.int8); prev[:j] = -1; prev[j:] = made[:-j]
        same = np.zeros(n, dtype=bool); same[j:] = group[j:] == group[:-j]
        allm &= same & (prev == 1); allx &= same & (prev == 0)
    return int(made[allm].sum()), int(allm.sum()), int(made[allx].sum()), int(allx.sum())


def streak_diff(made, group, k) -> float | None:
    hm, nm, hx, nx = streak_counts(made, group, k)
    if nm == 0 or nx == 0:
        return None
    return hm / nm - hx / nx


def permute_within(made: np.ndarray, strata: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Shuffle outcomes within each stratum (positions fixed). Strata need not be contiguous."""
    keys = rng.random(len(made))
    order = np.lexsort((keys, strata))           # sort by stratum, random within
    pos = np.lexsort((np.arange(len(made)), strata))  # stratum-sorted original positions
    out = np.empty_like(made)
    out[pos] = made[order]
    return out


def mc_pvalue(t_obs: float, t_null: np.ndarray) -> float:
    """p = (1 + #{T* >= T}) / (B + 1); ties counted as exceedances (conservative)."""
    t_null = np.asarray(t_null, dtype=float)
    return (1 + int(np.sum(t_null >= t_obs - 1e-15))) / (len(t_null) + 1)


# --------------------------------------------------------------------------- multiplicity
def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m; running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


# --------------------------------------------------------------------------- block bootstrap
@dataclass
class BlockBootResult:
    mean: float
    ci: tuple[float, float]
    p_one_sided: float
    n_obs: int
    n_days: int
    nonoverlap_blocks: int
    status: str  # OK | INSUFFICIENT_BLOCKS


def moving_block_bootstrap(d: np.ndarray, day_index: np.ndarray, block_days: int, B: int, seed: int,
                           min_blocks: int = 5) -> BlockBootResult:
    """Moving-block bootstrap over calendar days. `day_index` = integer day number for each paired
    difference. Blocks are runs of `block_days` consecutive calendar days (circular), resampled
    with replacement until the resample spans the original number of days."""
    d = np.asarray(d, float); day_index = np.asarray(day_index, int)
    d0 = day_index.min(); days = day_index - d0; span = int(days.max()) + 1
    by_day = [d[days == i] for i in range(span)]
    nonoverlap = span // block_days
    mean = float(d.mean())
    if nonoverlap < min_blocks:
        return BlockBootResult(mean, (math.nan, math.nan), math.nan, len(d), span, nonoverlap, "INSUFFICIENT_BLOCKS")
    rng = np.random.default_rng(seed)
    nblk = math.ceil(span / block_days)
    sums = np.array([x.sum() for x in by_day]); cnts = np.array([len(x) for x in by_day])
    # circular block sums for every start
    idx = (np.arange(span)[:, None] + np.arange(block_days)[None, :]) % span
    bsum = sums[idx].sum(1); bcnt = cnts[idx].sum(1)
    starts = rng.integers(0, span, size=(B, nblk))
    tot = bsum[starts].sum(1); n = bcnt[starts].sum(1)
    boot = tot / np.maximum(n, 1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    centred = boot - boot.mean()
    p = (1 + int(np.sum(centred >= mean))) / (B + 1)
    return BlockBootResult(mean, (float(lo), float(hi)), float(p), len(d), span, nonoverlap, "OK")
