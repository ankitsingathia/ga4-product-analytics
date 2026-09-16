"""Export the analysis as flat CSVs for a BI tool (Tableau Public).

    python scripts/export_tableau.py            # writes docs/tableau/*.csv

The files carry the decisions the audit forced, so a dashboard built on them
cannot show the broken metrics: add_to_cart and add_shipping_info are not in
the funnel (D-16, D-17), and revenue past the reliable date is flagged so those
weeks can be excluded (D-18). Every number comes from out/results.json and the
warehouse, so the CSVs and the write-up can never disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "tableau"
STEP = {"view_item": "1 Viewed products", "begin_checkout": "2 Checkout",
        "add_payment_info": "3 Payment", "purchase": "4 Purchase"}


def main() -> int:
    res = json.loads((REPO / "out" / "results.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    h = res["headline"]
    pd.DataFrame([{
        "events": res["audit"]["summary"]["events"], "users": h["users"], "sessions": h["sessions"],
        "orders": h["transactions"], "revenue_usd": round(h["revenue_usd"], 2),
        "session_conversion": h["conversion"], "order_value_usd": h["aov"],
        "window_start": res["audit"]["summary"]["start"], "window_end": res["audit"]["summary"]["end"],
    }]).to_csv(OUT / "headline.csv", index=False)

    rows = []
    for device, steps in list(res["funnel"]["by_device"].items()) + [("all", res["funnel"]["ordered"])]:
        for i, s in enumerate(steps):
            rows.append({"device": device, "step": STEP[s["step"]], "step_order": i + 1,
                         "sessions": s["sessions"], "rate_from_previous": s["step_rate"],
                         "rate_from_all_sessions": s["from_start"]})
    pd.DataFrame(rows).to_csv(OUT / "funnel_by_device.csv", index=False)

    ar = res["areas"]
    pd.DataFrame([{
        "section": r["label"], "sessions": r["sessions"], "checkout_rate": r["checkout_rate"],
        "ci_low": r["checkout_ci"][0], "ci_high": r["checkout_ci"][1],
        "typical_section_rate": ar["median"], "checkouts_that_finish": r["finish_rate"],
        "order_value_usd": r["order_value"], "clearly_below_typical": r["clearly_below"],
        "possible_checkout_fault": r["broken_checkout"], "extra_orders_if_typical": round(r["extra_orders"], 1),
        "extra_revenue_if_typical": round(r["extra_revenue_usd"], 2),
    } for r in ar["rows"]]).to_csv(OUT / "store_sections.csv", index=False)

    pd.DataFrame([{
        "week_start": w["week_start"], "revenue_usd": round(w["revenue_usd"], 2), "users": w["users"],
        "sessions_per_user": w["sessions_per_user"], "conversion": w["conversion"], "order_value_usd": w["aov"],
        "change_visitors": w["log_contrib"]["users"], "change_visits_per_visitor": w["log_contrib"]["sessions_per_user"],
        "change_conversion": w["log_contrib"]["conversion"], "change_order_size": w["log_contrib"]["aov"],
        "change_total": w["log_total"], "pct_vs_baseline": w["pct_change"],
    } for w in res["metric_tree"]["weeks"]]).to_csv(OUT / "weekly_revenue.csv", index=False)

    pd.DataFrame([{
        "channel": c["channel"], "sessions": c["sessions"], "share_of_sessions": c["share"],
        "engaged_rate": c["engaged_rate"], "conversion": c["conversion"],
        "ci_low": c["conversion_ci"][0], "ci_high": c["conversion_ci"][1],
        "revenue_per_session_usd": c["revenue_per_session"], "small_sample": c["sessions"] < 1000,
    } for c in res["channels"]]).to_csv(OUT / "channels.csv", index=False)

    with duckdb.connect(str(REPO / "data" / "warehouse.duckdb"), read_only=True) as con:
        con.execute("""
            select cohort_week, week_offset, cohort_users, active_users, retention, purchase_retention
            from fct_cohort_retention where week_offset > 0 order by cohort_week, week_offset
        """).df().to_csv(OUT / "retention.csv", index=False)

    for f in sorted(OUT.glob("*.csv")):
        print(f"{f.name:<24}{sum(1 for _ in f.open()) - 1:>5} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
