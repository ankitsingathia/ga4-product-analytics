"""Experiment design on real baselines.

The GA4 sample contains no experiment, so nothing here pretends to read one.
It answers the questions that come BEFORE a test is launched:

  * how many users per arm, and how many days, to detect a given lift
  * whether the analysis would produce false positives (an A/A test)
  * how much CUPED would shrink the variance on this traffic
  * whether an observed split is a sample-ratio mismatch

Randomisation is by user, but conversion is measured per session. Sessions of
one user are correlated, so treating them as independent understates the
variance. The delta method (Deng et al., 2018) is the correct standard error
for such a ratio metric; the naive session-level test is kept alongside it
only so the A/A simulation can show what it gets wrong.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from scipy import optimize, stats


def _z(q: float) -> float:
    return float(stats.norm.ppf(q))


def wilson(k: float, n: float, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (float(centre - half), float(centre + half))


def two_prop_z(k1: float, n1: float, k2: float, n2: float) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (difference p2 - p1, two-sided p-value)."""
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se = np.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (p2 - p1, 1.0)
    return (float(p2 - p1), float(2 * stats.norm.sf(abs((p2 - p1) / se))))


# ---- sample size -----------------------------------------------------------

def _n_two_prop(p1: float, rel_mde: float, alpha: float, power: float) -> float:
    p2 = p1 * (1 + rel_mde)
    pbar = (p1 + p2) / 2
    num = _z(1 - alpha / 2) * np.sqrt(2 * pbar * (1 - pbar)) + _z(power) * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return float(num**2 / (p2 - p1) ** 2)


def sample_size_two_prop(p1: float, rel_mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Units per arm to detect a relative lift in a proportion, independent units."""
    return int(np.ceil(_n_two_prop(p1, rel_mde, alpha, power)))


def mde_two_prop(p1: float, n_per_arm: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest relative lift detectable with n units per arm."""
    upper = min(50.0, (1 - 1e-9) / p1 - 1)  # the lifted rate must stay below 100%
    return float(optimize.brentq(lambda m: _n_two_prop(p1, m, alpha, power) - n_per_arm, 1e-6, upper))


def ratio_variance(y: np.ndarray, n: np.ndarray) -> tuple[float, float]:
    """(R, per-user variance of the linearised ratio) for R = sum(y) / sum(n).

    Var(R_hat) ~= var(y - R*n) / (N * mean(n)^2). Returning the per-user
    numerator lets sample size be computed in users, the randomisation unit.
    """
    y, n = np.asarray(y, float), np.asarray(n, float)
    r = y.sum() / n.sum()
    lin = (y - r * n) / n.mean()
    return float(r), float(lin.var(ddof=1))


def sample_size_ratio(y: np.ndarray, n: np.ndarray, rel_mde: float,
                      alpha: float = 0.05, power: float = 0.8) -> int:
    """USERS per arm to detect a relative lift in a per-session ratio metric."""
    r, var = ratio_variance(y, n)
    delta = r * rel_mde
    return int(np.ceil(2 * (_z(1 - alpha / 2) + _z(power)) ** 2 * var / delta**2))


def mde_ratio(y: np.ndarray, n: np.ndarray, users_per_arm: int,
              alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest relative lift in a per-session ratio detectable with this many users per arm."""
    r, var = ratio_variance(y, n)
    return float((_z(1 - alpha / 2) + _z(power)) * np.sqrt(2 * var / users_per_arm) / r)


def sample_size_mean(values: np.ndarray, rel_mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Units per arm to detect a relative lift in a mean (e.g. revenue per user)."""
    v = np.asarray(values, float)
    delta = v.mean() * rel_mde
    return int(np.ceil(2 * (_z(1 - alpha / 2) + _z(power)) ** 2 * v.var(ddof=1) / delta**2))


def days_to_reach(first_dates: list[date] | np.ndarray, users_needed: int) -> float:
    """Days of traffic until `users_needed` distinct users have been seen.

    Uses the observed cumulative curve inside the window. Beyond it,
    extrapolates at the last seven days' rate of NEW users, which is lower
    than daily active users because returning users do not add sample.
    """
    d = np.sort(np.asarray(first_dates, dtype="datetime64[D]"))
    if len(d) == 0:
        return float("inf")
    day_idx = (d - d[0]).astype(int)
    per_day = np.bincount(day_idx)
    cum = np.cumsum(per_day)
    hit = np.flatnonzero(cum >= users_needed)
    if len(hit):
        return float(hit[0] + 1)
    rate = per_day[-7:].mean()
    if rate <= 0:
        return float("inf")
    return float(len(per_day) + (users_needed - cum[-1]) / rate)


# ---- tests -----------------------------------------------------------------

def delta_method_z(y_a, n_a, y_b, n_b) -> tuple[float, float]:
    """Test R_b - R_a for a ratio metric with user-level randomisation."""
    def arm(y, n):
        y, n = np.asarray(y, float), np.asarray(n, float)
        r = y.sum() / n.sum()
        return r, ((y - r * n) ** 2).sum() / (len(y) - 1) / (len(y) * n.mean() ** 2)

    ra, va = arm(y_a, n_a)
    rb, vb = arm(y_b, n_b)
    se = np.sqrt(va + vb)
    return float(rb - ra), float(2 * stats.norm.sf(abs((rb - ra) / se)))


def aa_simulation(y: np.ndarray, n: np.ndarray, n_sims: int = 1000, alpha: float = 0.05,
                  seed: int = 0, chunk: int = 100) -> dict:
    """Split real users at random many times; count how often each test says 'significant'.

    With no treatment, a correct test is significant alpha of the time. The
    naive test treats sessions as independent draws; the delta-method test
    respects that users, not sessions, were randomised.
    """
    y, n = np.asarray(y, float), np.asarray(n, float)
    rng = np.random.default_rng(seed)
    crit = _z(1 - alpha / 2)
    hits_naive = hits_delta = 0
    stacked = np.column_stack([np.ones_like(y), y, n, y * y, n * n, y * n])
    done = 0
    while done < n_sims:
        m = min(chunk, n_sims - done)
        arms = rng.integers(0, 2, size=(m, len(y))).astype(np.float64)
        b = arms @ stacked  # per-sim sums for arm B
        a = stacked.sum(axis=0) - b  # and arm A
        z_naive, z_delta = [], []
        for s in (a, b):
            cnt, sy, sn, syy, snn, syn = s.T
            r = sy / sn
            var_lin = (syy - 2 * r * syn + r * r * snn) / (cnt - 1)
            z_delta.append((r, var_lin / (cnt * (sn / cnt) ** 2)))
            z_naive.append((r, sy, sn))
        (ra, va), (rb, vb) = z_delta
        hits_delta += int((np.abs(rb - ra) / np.sqrt(va + vb) > crit).sum())
        (_, ka, na), (_, kb, nb) = z_naive
        pool = (ka + kb) / (na + nb)
        se = np.sqrt(pool * (1 - pool) * (1 / na + 1 / nb))
        hits_naive += int((np.abs(kb / nb - ka / na) / se > crit).sum())
        done += m
    return {
        "n_sims": n_sims,
        "alpha": alpha,
        "fpr_naive": hits_naive / n_sims,
        "fpr_naive_ci": wilson(hits_naive, n_sims),
        "fpr_delta": hits_delta / n_sims,
        "fpr_delta_ci": wilson(hits_delta, n_sims),
    }


def cuped(y: np.ndarray, x: np.ndarray) -> dict:
    """CUPED: y_adj = y - theta * (x - mean(x)), theta = cov(y, x) / var(x).

    The variance reduction equals corr(y, x)^2. It only helps where the
    covariate carries information, i.e. for users with pre-period history.
    """
    y, x = np.asarray(y, float), np.asarray(x, float)
    vx = x.var(ddof=1)
    if vx == 0:
        return {"theta": 0.0, "variance_reduction": 0.0, "corr": 0.0}
    theta = np.cov(y, x, ddof=1)[0, 1] / vx
    y_adj = y - theta * (x - x.mean())
    return {
        "theta": float(theta),
        "variance_reduction": float(1 - y_adj.var(ddof=1) / y.var(ddof=1)),
        "corr": float(np.corrcoef(y, x)[0, 1]),
    }


def srm_pvalue(n_a: int, n_b: int, expected_share_a: float = 0.5) -> float:
    """Chi-square goodness of fit for the arm split. p < 0.001 means stop and debug."""
    total = n_a + n_b
    exp = [total * expected_share_a, total * (1 - expected_share_a)]
    return float(stats.chisquare([n_a, n_b], f_exp=exp).pvalue)
