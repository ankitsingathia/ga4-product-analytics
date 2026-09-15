"""The statistics, checked against hand calculations and known behaviour."""

from __future__ import annotations

import numpy as np
import pytest

from gpa import experiment as xp


def test_sample_size_matches_hand_calculation():
    # p1 = 0.10, p2 = 0.11, alpha 0.05 two-sided, power 0.80:
    # (1.95996 * sqrt(2 * .105 * .895) + 0.84162 * sqrt(.09 + .0979))^2 / .01^2 = 14,750.7
    assert xp.sample_size_two_prop(0.10, 0.10) == 14_751


def test_mde_inverts_sample_size():
    n = xp.sample_size_two_prop(0.04, 0.15)
    assert xp.mde_two_prop(0.04, n) == pytest.approx(0.15, rel=1e-3)


def test_mde_ratio_inverts_sample_size_ratio():
    rng = np.random.default_rng(7)
    n = 1 + rng.poisson(1.0, 30_000)
    y = rng.binomial(n, 0.04).astype(float)
    users = xp.sample_size_ratio(y, n, 0.12)
    assert xp.mde_ratio(y, n, users) == pytest.approx(0.12, rel=1e-3)


def test_ratio_variance_reduces_to_binomial_with_one_session_each():
    rng = np.random.default_rng(1)
    y = (rng.random(50_000) < 0.07).astype(float)
    r, var = xp.ratio_variance(y, np.ones_like(y))
    assert r == pytest.approx(y.mean())
    assert var == pytest.approx(y.var(ddof=1))


def test_aa_is_calibrated_on_independent_users():
    rng = np.random.default_rng(2)
    y = (rng.random(20_000) < 0.05).astype(float)
    res = xp.aa_simulation(y, np.ones_like(y), n_sims=400, seed=3)
    assert 0.02 <= res["fpr_delta"] <= 0.085
    assert 0.02 <= res["fpr_naive"] <= 0.085


def test_naive_session_test_is_overconfident_when_sessions_cluster():
    # Users differ in how likely they are to convert, and each has many
    # sessions. Sessions are then not independent draws, and the naive test's
    # false-positive rate climbs well above alpha. The delta method does not.
    rng = np.random.default_rng(4)
    users = 4_000
    n = 1 + rng.poisson(5, users)
    propensity = rng.beta(0.5, 9.5, users)
    y = rng.binomial(n, propensity).astype(float)
    res = xp.aa_simulation(y, n.astype(float), n_sims=400, seed=5)
    assert res["fpr_naive"] > 0.10
    assert 0.02 <= res["fpr_delta"] <= 0.085


def test_cuped_reduction_is_correlation_squared():
    rng = np.random.default_rng(6)
    x = rng.normal(size=10_000)
    y = 0.6 * x + rng.normal(size=10_000)
    res = xp.cuped(y, x)
    assert res["variance_reduction"] == pytest.approx(res["corr"] ** 2, abs=1e-9)


def test_cuped_does_nothing_without_history():
    res = xp.cuped(np.arange(10.0), np.zeros(10))
    assert res["variance_reduction"] == 0.0


def test_srm_flags_a_one_percent_skew_at_scale():
    assert xp.srm_pvalue(50_000, 50_000) > 0.5
    assert xp.srm_pvalue(50_500, 49_500) < 0.01


def test_days_to_reach_inside_and_beyond_window():
    days = np.repeat(np.arange("2021-01-04", "2021-01-11", dtype="datetime64[D]"), 100)  # 100 new users/day, 7 days
    assert xp.days_to_reach(days, 250) == 3
    assert xp.days_to_reach(days, 1_000) == pytest.approx(10.0)


def test_wilson_interval_stays_inside_zero_one():
    lo, hi = xp.wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-12) and 0 < hi < 1
