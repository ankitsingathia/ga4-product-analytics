"""Data trust audit: measure the raw extract before believing anything built on it.

    python -m gpa.audit --raw data/raw --json out/audit.json

Google says of this dataset that its "internal consistency might be somewhat
limited". This module turns that sentence into numbers. Each check reports a
value and what it would break downstream. A FAIL stops the build; a WARN is
carried into the readout so no chart is shown without its caveat.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from gpa import schema

# Columns whose placeholder share is worth knowing. session_source/medium are
# measured per session instead, because NULL on most event types is normal.
PLACEHOLDER_COLUMNS = ("ft_source", "ft_medium", "device_category", "country", "browser", "operating_system")
NULL_SESSION_FAIL = 0.20


@dataclass
class Check:
    name: str
    value: float
    detail: str
    severity: str  # "info" | "warn" | "fail"
    consequence: str


def _connect(raw: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    root = raw.resolve().as_posix()
    con.execute(f"create view ev as select * from read_parquet('{root}/events/*.parquet')")
    con.execute(f"create view it as select * from read_parquet('{root}/items/*.parquet')")
    return con


def run(raw: Path) -> dict:
    con = _connect(raw)

    def one(sql: str) -> tuple:
        return con.execute(sql).fetchone()

    checks: list[Check] = []
    rows, users, d0, d1, ndays = one(
        "select count(*), count(distinct user_pseudo_id), min(event_date), max(event_date), "
        "count(distinct event_date) from ev"
    )
    expected = (schema.WINDOW_END - schema.WINDOW_START).days + 1
    checks.append(Check(
        "missing_days", expected - ndays,
        f"{ndays} of {expected} days present ({d0} to {d1})",
        "fail" if ndays < expected else "info",
        "A missing day reads as a traffic collapse in every weekly metric.",
    ))

    null_sess, null_user = one(
        "select count(*) filter (where ga_session_id is null), "
        "count(*) filter (where user_pseudo_id is null) from ev"
    )
    share = null_sess / rows
    checks.append(Check(
        "null_session_events", null_sess,
        f"{share:.2%} of events carry no ga_session_id",
        "fail" if share > NULL_SESSION_FAIL else ("warn" if null_sess else "info"),
        "These events cannot be placed in a session and are dropped. Above "
        f"{NULL_SESSION_FAIL:.0%} the extract SQL is probably reading the wrong value slot.",
    ))
    checks.append(Check(
        "null_user_events", null_user, f"{null_user / rows:.2%} of events carry no user_pseudo_id",
        "fail" if null_user / rows > 0.01 else "info",
        "Users are the randomisation unit for every experiment calculation.",
    ))

    (distinct_rows,) = one("select count(*) from (select distinct * from ev)")
    dup = rows - distinct_rows
    checks.append(Check(
        "exact_duplicate_rows", dup, f"{dup:,} rows identical in every column to another row",
        "warn" if dup else "info",
        "Double-counts page views and engagement. Dropped in staging.",
    ))

    for col in PLACEHOLDER_COLUMNS:
        placeholders = ", ".join(f"'{p}'" for p in schema.PLACEHOLDERS)
        (ph,) = one(f"select avg(case when {col} is null or {col} in ({placeholders}) then 1.0 else 0 end) from ev")
        checks.append(Check(
            f"placeholder_share:{col}", round(ph, 4), f"{ph:.1%} of events have no real {col}",
            "warn" if ph > 0.25 else "info",
            "Any cut by this column carries an unattributable slice of this size.",
        ))

    p_rows, not_set, null_rev, p_keys = one(
        "select count(*), "
        "count(*) filter (where transaction_id is null or transaction_id = '(not set)'), "
        "count(*) filter (where purchase_revenue_usd is null), "
        "(select count(*) from (select distinct user_pseudo_id, ga_session_id, transaction_id, "
        "purchase_revenue_usd from ev where event_name = 'purchase')) "
        "from ev where event_name = 'purchase'"
    )
    checks.append(Check(
        "not_set_transaction_ids", not_set,
        f"{not_set:,} of {p_rows:,} purchase rows have no usable transaction_id",
        "warn" if not_set else "info",
        "Transaction id alone cannot deduplicate purchases; the key needs session and revenue too.",
    ))
    checks.append(Check(
        "duplicate_purchase_rows", p_rows - p_keys,
        f"{p_rows - p_keys:,} purchase rows collapse into another on (user, session, transaction, revenue)",
        "warn" if p_rows - p_keys else "info",
        "Counted naively these inflate conversion and revenue.",
    ))
    checks.append(Check(
        "null_revenue_purchases", null_rev, f"{null_rev:,} purchase rows have no revenue",
        "warn" if null_rev else "info",
        "They count as transactions with zero revenue, pulling AOV down.",
    ))

    no_items, mismatched, with_items = one("""
        with p as (
            select user_pseudo_id, event_ts, any_value(purchase_revenue_usd) as rev
            from ev where event_name = 'purchase' group by 1, 2
        ), i as (
            select user_pseudo_id, event_ts, sum(item_revenue_usd) as item_rev
            from it where event_name = 'purchase' group by 1, 2
        )
        select count(*) filter (where i.event_ts is null),
               count(*) filter (where i.event_ts is not null and p.rev is not null
                                and abs(i.item_rev - p.rev) > greatest(0.01, 0.01 * abs(p.rev))),
               count(*) filter (where i.event_ts is not null)
        from p left join i using (user_pseudo_id, event_ts)
    """)
    checks.append(Check(
        "item_revenue_mismatch", mismatched,
        f"{mismatched:,} of {with_items:,} purchases: line items do not sum to purchase revenue (>1%)",
        "warn" if mismatched else "info",
        "Product-level revenue and order-level revenue will not reconcile. Order-level is used.",
    ))
    checks.append(Check(
        "purchases_without_items", no_items, f"{no_items:,} purchase events have no line items",
        "warn" if no_items else "info",
        "Category analysis silently misses these orders.",
    ))

    p_sessions, no_checkout = one("""
        with e as (
            select user_pseudo_id || ':' || ga_session_id as k, event_name, event_ts
            from ev where ga_session_id is not null
        ), p as (select k, min(event_ts) as t from e where event_name = 'purchase' group by k),
        c as (select k, min(event_ts) as t from e where event_name = 'begin_checkout' group by k)
        select count(*), count(*) filter (where c.t is null or c.t > p.t)
        from p left join c using (k)
    """)
    checks.append(Check(
        "purchase_without_prior_checkout", no_checkout,
        f"{no_checkout:,} of {p_sessions:,} purchasing sessions have no earlier begin_checkout",
        "warn" if no_checkout else "info",
        "An ordered funnel will not credit these sessions with a purchase; an open funnel will. "
        "Both are reported.",
    ))

    checkout_sessions, with_cart = one("""
        select count(*) filter (where co = 1), count(*) filter (where co = 1 and cart = 1)
        from (select user_pseudo_id, ga_session_id,
                     max(case when event_name = 'begin_checkout' then 1 else 0 end) as co,
                     max(case when event_name = 'add_to_cart' then 1 else 0 end) as cart
              from ev where ga_session_id is not null group by 1, 2)
    """)
    coverage = with_cart / checkout_sessions if checkout_sessions else 1.0
    # Weekly, because an overall share hides a tracking change: 0% for two
    # weeks and 75% after averages to a harmless-looking 54%.
    weekly = con.execute("""
        select date_trunc('week', d)::date as wk,
               count(*) filter (where co = 1) as n,
               count(*) filter (where co = 1 and cart = 1) as k
        from (select user_pseudo_id, ga_session_id, min(event_date) as d,
                     max(case when event_name = 'begin_checkout' then 1 else 0 end) as co,
                     max(case when event_name = 'add_to_cart' then 1 else 0 end) as cart
              from ev where ga_session_id is not null group by 1, 2)
        group by 1 having count(*) filter (where co = 1) >= 50 order by 1
    """).fetchall()
    rates = [(wk, k / n) for wk, n, k in weekly]
    lo = min((r for _, r in rates), default=coverage)
    hi = max((r for _, r in rates), default=coverage)
    changed = lo < 0.10 and hi > 0.50
    detail = (f"{with_cart:,} of {checkout_sessions:,} checkout sessions contain an add_to_cart event "
              f"({coverage:.1%}); weekly coverage ranges {lo:.0%} to {hi:.0%}")
    if changed:
        detail += f", first above 50% in the week of {next(wk for wk, r in rates if r > 0.5)}"
    checks.append(Check(
        "add_to_cart_coverage", round(coverage, 4), detail,
        "warn" if coverage < 0.5 or changed else "info",
        "Nobody checks out without a cart, so coverage below ~100% is missing tracking, and coverage that "
        "jumps between weeks is a tracking change. A funnel through it would show a trend shoppers never "
        "made. add_to_cart is kept out of the funnel chain.",
    ))

    both, near, ship_first = one("""
        with f as (
            select user_pseudo_id, ga_session_id,
                   min(event_ts) filter (where event_name = 'begin_checkout') as co,
                   min(event_ts) filter (where event_name = 'add_shipping_info') as sh
            from ev
            where ga_session_id is not null and event_name in ('begin_checkout', 'add_shipping_info')
            group by 1, 2
        )
        select count(*) filter (where co is not null and sh is not null),
               count(*) filter (where abs(epoch_us(sh) - epoch_us(co)) < 1000000),
               count(*) filter (where sh < co)
        from f
    """)
    near_share = near / both if both else 0.0
    checks.append(Check(
        "checkout_shipping_simultaneous", round(near_share, 4),
        f"{near:,} of {both:,} sessions log add_shipping_info within 1 second of begin_checkout; "
        f"in {ship_first:,} it is logged first",
        "warn" if near_share > 0.5 else "info",
        "Two events fired by one action, in random order: an ordered funnel would drop sessions at random "
        "and the step rate would measure nothing. add_shipping_info is kept out of the funnel chain.",
    ))

    by_day = con.execute("""
        select event_date, count(*), count(*) filter (where purchase_revenue_usd = 0)
        from ev where event_name = 'purchase' group by 1 order by 1
    """).fetchall()
    zero_rows = sum(z for _, _, z in by_day)
    bad_days = [d for d, n, z in by_day if n >= 10 and z / n > 0.5]
    detail = f"{zero_rows:,} of {p_rows:,} purchase rows record $0 revenue"
    if bad_days:
        detail += f"; on {len(bad_days)} days most purchases do ({bad_days[0]} to {bad_days[-1]})"
    checks.append(Check(
        "zero_revenue_purchases", zero_rows, detail,
        "warn" if bad_days or zero_rows else "info",
        "A $0 purchase still counts as a transaction, so revenue and AOV sink while conversion does not. "
        "Weeks past dbt's revenue_reliable_through are left out of the revenue decomposition.",
    ))

    censored, measured = one("""
        select count(*) filter (where first_sn > 1), count(*)
        from (select user_pseudo_id, arg_min(ga_session_number, event_ts) as first_sn
              from ev where ga_session_number is not null group by 1)
    """)
    checks.append(Check(
        "left_censored_users", censored,
        f"{censored:,} of {measured:,} users are first seen on a session number above 1",
        "info",
        "Their real first visit predates the window. Excluded from new-user cohorts.",
    ))

    (no_source,) = one("""
        select avg(case when src is null then 1.0 else 0 end)
        from (select user_pseudo_id, ga_session_id, max(session_source) as src
              from ev where ga_session_id is not null group by 1, 2)
    """)
    checks.append(Check(
        "sessions_without_source", round(no_source, 4),
        f"{no_source:.1%} of sessions carry no session-level source on any event",
        "warn" if no_source > 0.25 else "info",
        "Those sessions fall back to first-touch channel (first session only) or 'Unknown'.",
    ))

    manifest = raw / "manifest.json"
    return {
        "source": json.loads(manifest.read_text()).get("source", "unknown") if manifest.exists() else "unknown",
        "summary": {"events": rows, "users": users, "start": str(d0), "end": str(d1), "days": ndays},
        "checks": [asdict(c) for c in checks],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    result = run(args.raw)
    s = result["summary"]
    print(f"Audit of {args.raw} ({result['source']}): {s['events']:,} events, {s['users']:,} users\n")
    for c in result["checks"]:
        print(f"  {c['severity'].upper():<5} {c['name']:<34} {c['detail']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, default=str))
    failed = [c["name"] for c in result["checks"] if c["severity"] == "fail"]
    if failed:
        print(f"\nFAILED: {failed}. The build stops here.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
