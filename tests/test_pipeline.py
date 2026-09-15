"""The warehouse, the audit and the analysis must recover what was planted."""

from __future__ import annotations

import json

import duckdb
import numpy as np
import pytest

from gpa import analysis, crosscheck
from gpa.schema import FUNNEL_STEPS

AUDIT_TRUTH = [
    ("null_session_events", "n_null_session_events"),
    ("exact_duplicate_rows", "n_exact_duplicate_rows"),
    ("not_set_transaction_ids", "n_not_set_txn_rows"),
    ("duplicate_purchase_rows", "n_duplicate_purchase_rows"),
    ("item_revenue_mismatch", "n_item_revenue_mismatch"),
    ("purchases_without_items", "n_purchases_without_items"),
    ("left_censored_users", "n_left_censored_users"),
]


def _q(db, sql):
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql).df()


@pytest.mark.parametrize("check,truth_key", AUDIT_TRUTH)
def test_audit_counts_every_planted_quirk_exactly(built, check, truth_key):
    values = {c["name"]: c["value"] for c in built["audit"]["checks"]}
    assert values[check] == built["truth"][truth_key]


def test_audit_new_tracking_checks_stay_quiet_on_clean_data(built):
    # The generator logs shipping 20s after checkout and never records $0
    # revenue, and it tracks the cart every week, so all three must be info.
    by_name = {c["name"]: c for c in built["audit"]["checks"]}
    assert by_name["checkout_shipping_simultaneous"]["value"] == 0
    assert by_name["zero_revenue_purchases"]["value"] == 0
    for name in ("checkout_shipping_simultaneous", "zero_revenue_purchases", "add_to_cart_coverage"):
        assert by_name[name]["severity"] == "info", name


def test_biggest_leak_ignores_the_first_step():
    ordered = [
        {"step": "view_item", "step_rate": 0.05},
        {"step": "begin_checkout", "step_rate": 0.14},
        {"step": "add_payment_info", "step_rate": 0.61},
    ]
    assert analysis.biggest_leak(ordered)["step"] == "begin_checkout"


def test_revenue_split_skips_weeks_past_the_reliable_date(built):
    tree = analysis.metric_tree(analysis.load(built["db"])["fct_weekly_metrics"])
    assert "2021-01-25" not in [w["week_start"] for w in tree["weeks"]]


def test_audit_passes_synthetic_data(built):
    assert not [c for c in built["audit"]["checks"] if c["severity"] == "fail"]


def test_warehouse_recovers_sessions_funnel_and_revenue(built):
    t = built["truth"]
    row = _q(built["db"], "select * from fct_funnel_segments where segment_type = 'all'").iloc[0]
    assert row["sessions"] == t["n_sessions"]
    for step in FUNNEL_STEPS:
        assert row[f"reached_{step}"] == t["reached"][step], step
    # Duplicate purchase hits must collapse: purchases == real purchases, not rows.
    assert row["purchases"] == t["n_unique_purchases"] < t["n_purchase_rows"]
    assert row["revenue_usd"] == pytest.approx(t["revenue_total"], abs=0.01)


def test_funnel_by_device_matches_truth(built):
    rows = _q(built["db"], "select * from fct_funnel_segments where segment_type = 'device'")
    for _, r in rows.iterrows():
        d = r["segment"]
        assert r["sessions"] == built["truth"]["sessions_by_device"][d]
        for step in FUNNEL_STEPS:
            assert r[f"reached_{step}"] == built["truth"]["reached_by_device"][d][step], (d, step)


def test_pandas_crosscheck_agrees_with_dbt(built):
    assert crosscheck.compare(built["raw"], built["db"]) == []


def test_new_user_cohorts_exclude_left_censored_users(built):
    t = built["truth"]
    cohort_users = _q(built["db"], """
        select sum(cohort_users) as n from (
            select distinct cohort_week, cohort_users from fct_cohort_retention)
    """).iloc[0]["n"]
    # New users arriving in the partial first week (Sunday 1 Nov) have no full
    # cohort week, so they are also outside every cohort.
    partial = _q(built["db"], """
        select count(*) as n from (
            select user_pseudo_id, min(session_date) as d, arg_min(session_number, session_start_ts) as sn
            from fct_sessions group by 1) where d = date '2020-11-01' and sn = 1
    """).iloc[0]["n"]
    assert cohort_users == t["n_users"] - t["n_left_censored_users"] - partial


def test_opportunity_analysis_finds_the_planted_step(built):
    seg = analysis.load(built["db"])["fct_funnel_segments"]
    opp = analysis.device_gap_opportunity(seg)
    significant = [o for o in opp if o["significant"]]
    assert significant and significant[0]["step"] == "purchase"
    assert opp[0]["step"] == "purchase"


def test_metric_tree_contributions_add_up_exactly(built):
    tree = analysis.metric_tree(analysis.load(built["db"])["fct_weekly_metrics"])
    base = [w for w in tree["weeks"] if w["week_start"] in tree["baseline_weeks"]]
    base_log_rev = np.mean([np.log(w["revenue_usd"]) for w in base])
    for w in tree["weeks"]:
        assert sum(w["log_contrib"].values()) == pytest.approx(np.log(w["revenue_usd"]) - base_log_rev, abs=1e-9)


def test_holiday_week_is_the_peak(built):
    tree = analysis.metric_tree(analysis.load(built["db"])["fct_weekly_metrics"])
    assert tree["peak_week"] == "2020-11-23"


def test_full_analysis_runs_and_serialises(built):
    res = analysis.analyse(built["db"], built["audit"], n_sims=200)
    json.dumps(res, default=analysis._json_default)
    assert res["source"] == "synthetic"
    assert res["experiment"]["target_step"] == "purchase"
    assert 0.02 <= res["experiment"]["aa"]["fpr_delta"] <= 0.09

    from gpa import readout

    page = readout.render(json.loads(json.dumps(res, default=analysis._json_default)))
    assert "generated test data" in page
    # House style for the write-up: plain punctuation, no em dashes.
    assert "—" not in page
