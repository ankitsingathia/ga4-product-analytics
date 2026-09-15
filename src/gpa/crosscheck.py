"""Recompute the funnel from raw Parquet in pandas and compare it to the warehouse.

    python -m gpa.crosscheck --raw data/raw --db data/warehouse.duckdb

The dbt models and this script share no code, only the definitions in
docs/DECISIONS.md. If they disagree, one of them has a bug, and no number in
the readout is quoted until the build is rerun clean.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

from gpa.schema import FUNNEL_STEPS

COLUMNS = ["user_pseudo_id", "ga_session_id", "event_name", "event_ts", "transaction_id", "purchase_revenue_usd"]


def pandas_funnel(raw: Path) -> dict:
    ev = pd.read_parquet(raw / "events", columns=COLUMNS)
    ev = ev.dropna(subset=["user_pseudo_id", "ga_session_id"])
    ev["k"] = ev["user_pseudo_id"] + ":" + ev["ga_session_id"].astype("int64").astype(str)

    reached, prev = {}, None
    for step in FUNNEL_STEPS:
        cur = ev.loc[ev["event_name"] == step, ["k", "event_ts"]]
        if prev is not None:
            cur = cur.merge(prev, on="k")
            cur = cur[cur["event_ts"] >= cur["t"]]
        prev = cur.groupby("k", as_index=False)["event_ts"].min().rename(columns={"event_ts": "t"})
        reached[step] = len(prev)

    purchases = ev[ev["event_name"] == "purchase"].drop_duplicates(["k", "transaction_id", "purchase_revenue_usd"])
    return {
        "sessions": int(ev["k"].nunique()),
        "reached": reached,
        "purchases": int(len(purchases)),
        "revenue_usd": round(float(purchases["purchase_revenue_usd"].sum()), 2),
    }


def warehouse_funnel(db: Path) -> dict:
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute("select * from fct_funnel_segments where segment_type = 'all'").df().iloc[0]
    return {
        "sessions": int(row["sessions"]),
        "reached": {s: int(row[f"reached_{s}"]) for s in FUNNEL_STEPS},
        "purchases": int(row["purchases"]),
        "revenue_usd": round(float(row["revenue_usd"]), 2),
    }


def compare(raw: Path, db: Path) -> list[str]:
    p, w = pandas_funnel(raw), warehouse_funnel(db)
    diffs = []
    for key in ("sessions", "purchases"):
        if p[key] != w[key]:
            diffs.append(f"{key}: pandas {p[key]:,} vs warehouse {w[key]:,}")
    if abs(p["revenue_usd"] - w["revenue_usd"]) > 0.01:
        diffs.append(f"revenue: pandas {p['revenue_usd']:,.2f} vs warehouse {w['revenue_usd']:,.2f}")
    for step in FUNNEL_STEPS:
        if p["reached"][step] != w["reached"][step]:
            diffs.append(f"reached_{step}: pandas {p['reached'][step]:,} vs warehouse {w['reached'][step]:,}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    args = ap.parse_args(argv)
    diffs = compare(args.raw, args.db)
    if diffs:
        print("Cross-check FAILED:\n  " + "\n  ".join(diffs), file=sys.stderr)
        return 1
    print("Cross-check OK: pandas and dbt agree on sessions, every funnel step, purchases and revenue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
