"""Everything the readout says, computed from the warehouse into one JSON file.

    python -m gpa.analysis --db data/warehouse.duckdb --audit out/audit.json --out out/results.json

Nothing in the readout is typed by hand. Every number is here first, with the
rule that produced it, so any figure can be re-derived on a whiteboard.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gpa import experiment as xp
from gpa.schema import FUNNEL_STEPS

HOLIDAY_START = date(2020, 11, 23)  # the week containing Black Friday
MDE_GRID = (0.05, 0.10, 0.15, 0.20)
SIGNIFICANCE = 0.05


def load(db: Path) -> dict[str, pd.DataFrame]:
    # Explicit ordering: DuckDB returns table rows in no guaranteed order, and
    # the A/A simulation assigns arms by row position. Unordered, the same data
    # gave a different false-positive rate on every build.
    tables = {
        "fct_funnel_segments": "segment_type, segment",
        "fct_weekly_metrics": "week_start",
        "fct_cohort_retention": "cohort_week, week_offset",
        "fct_user_windows": "user_pseudo_id",
    }
    with duckdb.connect(str(db), read_only=True) as con:
        return {t: con.execute(f"select * from {t} order by {key}").df() for t, key in tables.items()}


def _segment(seg: pd.DataFrame, seg_type: str, name: str) -> pd.Series:
    rows = seg[(seg["segment_type"] == seg_type) & (seg["segment"] == name)]
    if rows.empty:
        raise KeyError(f"no {seg_type}={name} segment in the warehouse")
    return rows.iloc[0]


def funnel_steps(row: pd.Series, prefix: str = "reached") -> list[dict]:
    """Per step: sessions reaching it, rate from the previous step, rate from all sessions."""
    out, prev = [], float(row["sessions"])
    for step in FUNNEL_STEPS:
        k = float(row[f"{prefix}_{step}"])
        lo, hi = xp.wilson(k, prev)
        out.append({
            "step": step,
            "sessions": int(k),
            "step_rate": k / prev if prev else float("nan"),
            "step_rate_ci": [lo, hi],
            "from_start": k / row["sessions"],
        })
        prev = k
    return out


def device_gap_opportunity(seg: pd.DataFrame) -> list[dict]:
    """Size each step's mobile-vs-desktop gap in purchases and revenue.

    Why a device gap and not "a 10% lift at step X": in a multiplicative funnel
    a 10% relative lift at ANY step yields exactly 10% more purchases, so that
    framing cannot rank steps. A gap to an internal benchmark can. It is an
    upper bound: part of the gap may be intent (people browse on phones), not
    friction. Separating the two is what the experiment is for.
    """
    desk, mob = _segment(seg, "device", "desktop"), _segment(seg, "device", "mobile")
    mob_aov = mob["revenue_usd"] / mob["purchases"] if mob["purchases"] else 0.0
    rows = []
    for j, step in enumerate(FUNNEL_STEPS):
        prev_col = "sessions" if j == 0 else f"reached_{FUNNEL_STEPS[j - 1]}"
        n_m, n_d = float(mob[prev_col]), float(desk[prev_col])
        k_m, k_d = float(mob[f"reached_{step}"]), float(desk[f"reached_{step}"])
        if min(n_m, n_d) == 0 or k_m == 0:
            continue
        rate_m, rate_d = k_m / n_m, k_d / n_d
        _, p = xp.two_prop_z(k_m, n_m, k_d, n_d)
        downstream = float(mob["reached_purchase"]) / k_m
        extra = n_m * max(rate_d - rate_m, 0.0) * downstream
        rows.append({
            "step": step,
            "mobile_rate": rate_m,
            "desktop_rate": rate_d,
            "gap_pts": rate_d - rate_m,
            "p_value": p,
            "significant": bool(p < SIGNIFICANCE and rate_d > rate_m),
            "extra_purchases": extra,
            "extra_revenue_usd": extra * mob_aov,
        })
    return sorted(rows, key=lambda r: -r["extra_revenue_usd"])


def biggest_leak(ordered: list[dict]) -> dict:
    """The step inside the purchase path that keeps the smallest share of sessions.

    The first step is excluded: a session that never opens a product is
    browsing, not leaking out of a purchase it had started.
    """
    return min(ordered[1:], key=lambda s: s["step_rate"])


def metric_tree(weekly: pd.DataFrame) -> dict:
    """Split each full week's revenue change vs the pre-holiday baseline.

    log(rev) = log(users) + log(sessions/user) + log(conversion) + log(AOV),
    so the change in log revenue splits into four parts that add up exactly.
    Baseline: the geometric mean of the full weeks before the holiday week.
    """
    full = weekly[weekly["is_full_week"] & weekly["revenue_complete"] & (weekly["transactions"] > 0)].copy()
    full["week_start"] = pd.to_datetime(full["week_start"]).dt.date
    comps = ["users", "sessions_per_user", "conversion", "aov"]
    base = full[full["week_start"] < HOLIDAY_START]
    if base.empty:
        raise ValueError("no full pre-holiday week to use as a baseline")
    base_log = {c: float(np.log(base[c]).mean()) for c in comps}

    weeks = []
    for _, w in full.iterrows():
        contrib = {c: float(np.log(w[c]) - base_log[c]) for c in comps}
        total = sum(contrib.values())
        weeks.append({
            "week_start": str(w["week_start"]),
            "revenue_usd": float(w["revenue_usd"]),
            "users": int(w["users"]),
            "sessions_per_user": float(w["sessions_per_user"]),
            "conversion": float(w["conversion"]),
            "aov": float(w["aov"]),
            "log_contrib": contrib,
            "log_total": total,
            "pct_change": float(np.expm1(total)),
        })
    peak = max(weeks, key=lambda w: w["revenue_usd"])
    return {
        "baseline_weeks": [str(d) for d in base["week_start"]],
        "weeks": weeks,
        "peak_week": peak["week_start"],
        "peak_pct_change": peak["pct_change"],
        "peak_share": {c: peak["log_contrib"][c] / peak["log_total"] for c in comps} if peak["log_total"] else {},
    }


def channels(seg: pd.DataFrame) -> list[dict]:
    rows = []
    ch = seg[seg["segment_type"] == "channel"]
    total = float(ch["sessions"].sum())
    for _, r in ch.iterrows():
        n = float(r["sessions"])
        k = float(r["any_purchase"])
        rows.append({
            "channel": r["segment"],
            "sessions": int(n),
            "share": n / total,
            "engaged_rate": float(r["engaged_sessions"]) / n,
            "conversion": k / n,
            "conversion_ci": list(xp.wilson(k, n)),
            "revenue_per_session": float(r["revenue_usd"]) / n,
        })
    return sorted(rows, key=lambda r: -r["sessions"])


def retention(coh: pd.DataFrame) -> dict:
    coh = coh.copy()
    coh["cohort_week"] = pd.to_datetime(coh["cohort_week"]).dt.date.astype(str)
    grid = coh.pivot(index="cohort_week", columns="week_offset", values="retention")
    summary = {}
    for k in (1, 2, 4, 8):
        sub = coh[coh["week_offset"] == k]
        if len(sub):
            summary[f"week_{k}"] = float(sub["active_users"].sum() / sub["cohort_users"].sum())
            summary[f"week_{k}_cohorts"] = int(len(sub))
    return {
        "cohorts": list(grid.index),
        "offsets": [int(c) for c in grid.columns],
        "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in grid.to_numpy()],
        "cohort_users": coh.groupby("cohort_week")["cohort_users"].first().astype(int).to_dict(),
        "weighted": summary,
    }


def experiment_design(users: pd.DataFrame, target_step: str | None, device_specific: bool, n_sims: int) -> dict:
    """Design the test the analysis points at, on real baselines.

    A significant device gap means a mobile-only test. Without one, the fix is
    for everyone, so the test population is every user.
    """
    mob = users[users["device_category"] == "mobile"]
    frame = mob if device_specific and len(mob) >= 1_000 else users
    population = "mobile users" if frame is mob else "all users"
    y = frame["exp_converting_sessions"].to_numpy(float)
    n = frame["exp_sessions"].to_numpy(float)
    rate, _ = xp.ratio_variance(y, n)
    first_dates = pd.to_datetime(frame["exp_first_date"]).to_numpy()
    sessions_per_user = n.mean()

    grid = []
    for m in MDE_GRID:
        users_arm = xp.sample_size_ratio(y, n, m)
        naive_sessions_arm = xp.sample_size_two_prop(rate, m)
        grid.append({
            "rel_mde": m,
            "users_per_arm": users_arm,
            "days": xp.days_to_reach(first_dates, 2 * users_arm),
            "naive_sessions_per_arm": naive_sessions_arm,
            # Sessions the correct design needs vs the naive count: >1 means
            # the naive calculation would under-power the test.
            "design_effect": users_arm * sessions_per_user / naive_sessions_arm,
        })

    # The question a PM actually asks: with the traffic we have, what is the
    # smallest lift a one-, two- or three-week test could see? Three weeks is
    # the whole clean window.
    detectable = []
    for window in (7, 14, 21):
        cutoff = first_dates.min() + np.timedelta64(window, "D")
        per_arm = int((first_dates < cutoff).sum()) // 2
        detectable.append({"days": window, "users_per_arm": per_arm, "rel_mde": xp.mde_ratio(y, n, per_arm)})

    aa = xp.aa_simulation(users["exp_converting_sessions"].to_numpy(float),
                          users["exp_sessions"].to_numpy(float), n_sims=n_sims, seed=11)
    has_history = users["pre_sessions"] > 0
    return {
        "target_step": target_step,
        "device_specific": bool(frame is mob),
        "population": population,
        "window_users": int(len(frame)),
        "metric": "session conversion (sessions with a purchase / sessions), randomised by user",
        "baseline_rate": rate,
        "sessions_per_user": float(sessions_per_user),
        "grid": grid,
        "detectable": detectable,
        "aa": aa,
        "cuped": {
            "share_with_history": float(has_history.mean()),
            "revenue_all": xp.cuped(users["exp_revenue_usd"], users["pre_revenue_usd"]),
            "conversions_all": xp.cuped(users["exp_converting_sessions"], users["pre_sessions"]),
            "conversions_with_history": xp.cuped(users.loc[has_history, "exp_converting_sessions"],
                                                 users.loc[has_history, "pre_sessions"])
            if has_history.sum() > 2 else None,
        },
    }


def analyse(db: Path, audit: dict, n_sims: int = 1000) -> dict:
    t = load(db)
    seg = t["fct_funnel_segments"]
    everyone = _segment(seg, "all", "all")
    opp = device_gap_opportunity(seg)
    significant = [o for o in opp if o["significant"]]
    ordered = funnel_steps(everyone, "reached")
    leak = biggest_leak(ordered)
    # A significant device gap is the sharper recommendation; without one,
    # fall back to the leakiest step, for everyone.
    target, device_specific = (significant[0]["step"], True) if significant else (leak["step"], False)

    return {
        "source": audit.get("source", "unknown"),
        "audit": audit,
        "headline": {
            "sessions": int(everyone["sessions"]),
            "users": int(everyone["users"]),
            "transactions": int(everyone["purchases"]),
            "revenue_usd": float(everyone["revenue_usd"]),
            "conversion": float(everyone["purchases"]) / float(everyone["sessions"]),
            "aov": float(everyone["revenue_usd"]) / float(everyone["purchases"]) if everyone["purchases"] else None,
        },
        "leak": leak,
        "funnel": {
            "ordered": ordered,
            "open": funnel_steps(everyone, "any"),
            "by_device": {d: funnel_steps(_segment(seg, "device", d))
                          for d in seg.loc[seg["segment_type"] == "device", "segment"]},
        },
        "opportunity": opp,
        "metric_tree": metric_tree(t["fct_weekly_metrics"]),
        "channels": channels(seg),
        "retention": retention(t["fct_cohort_retention"]),
        "experiment": experiment_design(t["fct_user_windows"], target, device_specific, n_sims),
    }


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (date, pd.Timestamp)):
        return str(o)
    raise TypeError(type(o))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sims", type=int, default=1000)
    args = ap.parse_args(argv)
    results = analyse(args.db, json.loads(args.audit.read_text()), args.sims)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, default=_json_default))
    target = results["experiment"]["target_step"]
    print(f"Analysis written to {args.out} (source: {results['source']}, experiment target: {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
