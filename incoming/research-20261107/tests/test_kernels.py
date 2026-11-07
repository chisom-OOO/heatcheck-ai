import math
from fractions import Fraction

import numpy as np
import pytest
from scipy import stats

from heatcheck import kernels as K


def test_beta_binomial_golden_fixture():
    post = K.beta_binomial_posterior(2, 2, 8, 10)
    assert (post.a, post.b) == (10, 4)
    assert math.isclose(post.mean, 5 / 7, rel_tol=0, abs_tol=1e-15)
    assert math.isclose(post.var, 2 / 147, rel_tol=0, abs_tol=1e-15)
    # independent library check
    m, v = stats.beta(10, 4).stats(moments="mv")
    assert math.isclose(post.mean, float(m), abs_tol=1e-12) and math.isclose(post.var, float(v), abs_tol=1e-12)


def test_beta_binomial_no_observations_returns_prior_with_note():
    post = K.beta_binomial_posterior(2, 3, 0, 0)
    assert (post.a, post.b) == (2, 3) and "no observations" in post.note


def test_beta_binomial_rejects_invalid():
    with pytest.raises(ValueError):
        K.beta_binomial_posterior(2, 2, 11, 10)


def test_log_loss_and_brier_fixture():
    y = np.array([1, 0]); base = np.array([0.5, 0.5]); cand = np.array([0.8, 0.2])
    lb, lc = K.log_loss_per(y, base).mean(), K.log_loss_per(y, cand).mean()
    assert round(lb, 10) == 0.6931471806 and round(lc, 10) == 0.2231435513
    assert round(lb - lc, 10) == 0.4700036292
    assert math.isclose(K.brier_per(y, base).mean(), 0.25) and math.isclose(K.brier_per(y, cand).mean(), 0.04)


def test_scores_reject_nan_and_out_of_range():
    for bad in ([np.nan], [1.2], [-0.1]):
        with pytest.raises(ValueError):
            K.log_loss_per(np.array([1]), np.array(bad))


def test_miller_sanjurjo_exact_n4_k1():
    # Known result: for n=4, p=1/2, E[P̂(H|H)] over sequences where defined = 17/42 ≈ 0.405, not 0.5
    assert K.exact_expected_prop_after_streak(4, 1) == Fraction(17, 42)


def test_streak_undefined_when_no_streak():
    assert K.prop_after_streak((0, 1, 0, 1), 2) is None


def test_streak_counts_respect_group_boundaries():
    made = np.array([1, 1, 1, 1, 1, 1]); grp = np.array([0, 0, 0, 1, 1, 1])
    # k=2: only positions 2 (grp0) and 5 (grp1) qualify; no cross-boundary streak
    assert K.streak_counts(made, grp, 2) == (2, 2, 0, 0)
    assert K.streak_diff(made, grp, 2) is None   # no after-miss denominator → undefined


def test_permutation_preserves_stratum_multisets():
    rng = np.random.default_rng(0)
    made = np.array([1, 0, 1, 1, 0, 0, 1, 0]); strata = np.array([0, 0, 1, 1, 0, 1, 1, 0])
    out = K.permute_within(made, strata, rng)
    for s in (0, 1):
        assert sorted(out[strata == s]) == sorted(made[strata == s])


def test_permutation_null_p_values_super_uniform():
    """Under an exchangeable null, MC p-values must satisfy P(p<=a) <= a (+ MC noise)."""
    rng = np.random.default_rng(1)
    ps = []
    for _ in range(300):
        made = rng.binomial(1, 0.45, size=600); grp = np.repeat(np.arange(40), 15)
        t = K.streak_diff(made, grp, 2)
        null = [K.streak_diff(K.permute_within(made, grp, rng), grp, 2) for _ in range(99)]
        ps.append(K.mc_pvalue(t, np.array([x for x in null if x is not None])))
    ps = np.array(ps)
    for a in (0.05, 0.1, 0.2):
        # binomial 99.9% upper bound on rejection rate under exact level a
        ub = a + 3.3 * math.sqrt(a * (1 - a) / len(ps))
        assert (ps <= a).mean() <= ub, (a, (ps <= a).mean())


def test_mc_pvalue_formula_and_ties():
    assert K.mc_pvalue(1.0, np.array([1.0, 0.0, 2.0])) == (1 + 2) / 4


def test_holm_matches_statsmodels_definition():
    p = [0.01, 0.04, 0.03]
    # manual: sorted 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04→max(0.06)=0.06
    assert K.holm(p) == [0.03, 0.06, 0.06]


def test_block_bootstrap_insufficient_blocks():
    d = np.ones(30); day = np.repeat(np.arange(10), 3)
    r = K.moving_block_bootstrap(d, day, 7, 200, 0)
    assert r.status == "INSUFFICIENT_BLOCKS" and math.isnan(r.p_one_sided)


def test_block_bootstrap_detects_clear_effect_and_not_null():
    rng = np.random.default_rng(3)
    day = np.repeat(np.arange(60), 5)
    pos = K.moving_block_bootstrap(rng.normal(0.5, 1, 300), day, 7, 2000, 1)
    nul = K.moving_block_bootstrap(rng.normal(0.0, 1, 300) - 0.0, day, 7, 2000, 2)
    assert pos.status == "OK" and pos.ci[0] > 0 and pos.p_one_sided < 0.01
    assert nul.p_one_sided > 0.01
