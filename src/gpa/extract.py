"""Pull the GA4 sample from BigQuery into local Parquet, one file per day.

    python -m gpa.extract --project YOUR_SANDBOX_ID --check   # one day, no files written
    python -m gpa.extract --project YOUR_SANDBOX_ID           # all 92 days, resumable

The first run opens a browser for a Google login; the token is cached after
that. The BigQuery sandbox is enough: each day scans one small daily table.

--check exists because the flattening SQL can be wrong without failing. Each
event_params key lives in one of four typed value slots, and reading the wrong
slot yields NULL rather than an error. The check pulls one day and refuses to
continue if a field the warehouse depends on comes back mostly empty.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from gpa import schema

REPO = Path(__file__).resolve().parents[2]
SQL_DIR = REPO / "sql" / "bigquery"
SCOPES = ["https://www.googleapis.com/auth/bigquery"]
RETRIES = 4  # per day; waits of 15, 30 and 60 seconds between attempts

# Maximum tolerated NULL share on the check day. Above this the SQL is reading
# the wrong slot (or the export changed) and every downstream number is wrong.
CRITICAL_NULL_SHARE = {
    "event_ts": 0.0,
    "event_name": 0.0,
    "user_pseudo_id": 0.01,
    "ga_session_id": 0.20,
    "ga_session_number": 0.20,
}


def all_days() -> list[date]:
    n = (schema.WINDOW_END - schema.WINDOW_START).days + 1
    return [schema.WINDOW_START + timedelta(days=i) for i in range(n)]


def connect(project: str):
    import pydata_google_auth
    from google.cloud import bigquery

    creds = pydata_google_auth.get_user_credentials(SCOPES, use_local_webserver=True)
    return bigquery.Client(project=project, credentials=creds)


def fetch(bq, sql: str, day: date) -> tuple[pa.Table, int]:
    from google.cloud import bigquery

    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("day", "STRING", day.strftime("%Y%m%d"))
        ]
    )
    job = bq.query(sql, job_config=cfg)
    table = job.result().to_arrow(create_bqstorage_client=False)
    return table, int(job.total_bytes_processed or 0)


def null_shares(table: pa.Table) -> dict[str, float]:
    n = max(table.num_rows, 1)
    return {c: table.column(c).null_count / n for c in table.column_names}


def check(bq, day: date) -> int:
    events, scanned = fetch(bq, (SQL_DIR / "extract_events.sql").read_text(), day)
    events = schema.conform(events, schema.EVENTS)
    shares = null_shares(events)

    print(f"Check day {day}: {events.num_rows:,} events, {scanned / 1e6:,.1f} MB scanned\n")
    print(f"{'column':<24}{'null share':>12}")
    failed = []
    for col, share in shares.items():
        limit = CRITICAL_NULL_SHARE.get(col)
        flag = ""
        if limit is not None and share > limit:
            flag = f"  FAIL (limit {limit:.0%})"
            failed.append(col)
        print(f"{col:<24}{share:>11.1%}{flag}")

    counts = pc.value_counts(events.column("event_name")).to_pylist()
    print("\nevent_name counts:")
    for row in sorted(counts, key=lambda r: -r["counts"]):
        mark = "  <- funnel" if row["values"] in schema.FUNNEL_STEPS else ""
        print(f"  {row['values']:<28}{row['counts']:>8,}{mark}")

    missing_steps = set(schema.FUNNEL_STEPS) - {r["values"] for r in counts}
    if missing_steps:
        print(f"\nWARNING: funnel steps absent on this day: {sorted(missing_steps)}")
    if failed:
        print(f"\nFAILED: {failed} mostly NULL. Fix sql/bigquery/*.sql before extracting.")
        return 1
    print("\nOK: critical fields populated. Safe to run the full extract.")
    return 0


def extract(bq, out: Path, days: list[date]) -> int:
    sql_events = (SQL_DIR / "extract_events.sql").read_text()
    sql_items = (SQL_DIR / "extract_items.sql").read_text()
    (out / "events").mkdir(parents=True, exist_ok=True)
    (out / "items").mkdir(parents=True, exist_ok=True)

    scanned_total = 0
    for i, day in enumerate(days, 1):
        stem = day.strftime("%Y%m%d")
        ev_path, it_path = out / "events" / f"{stem}.parquet", out / "items" / f"{stem}.parquet"
        if ev_path.exists() and it_path.exists():
            print(f"[{i:>2}/{len(days)}] {day}  already extracted", flush=True)
            continue
        # A home connection drops now and then; one dropped socket should not
        # end a 92-day run. Retry the day with growing waits, then give up
        # loudly (the run resumes from the next unfinished day anyway).
        for attempt in range(1, RETRIES + 1):
            try:
                events, s1 = fetch(bq, sql_events, day)
                items, s2 = fetch(bq, sql_items, day)
                break
            except Exception as exc:  # network errors surface as several unrelated types
                if attempt == RETRIES:
                    raise
                wait = 15 * 2 ** (attempt - 1)
                print(f"[{i:>2}/{len(days)}] {day}  attempt {attempt} failed ({type(exc).__name__}); "
                      f"retrying in {wait}s", flush=True)
                time.sleep(wait)
        # Write to a temp name and rename, so an interrupted run never leaves a
        # half-written file that the resume check would mistake for done.
        for table, sch, path in ((events, schema.EVENTS, ev_path), (items, schema.ITEMS, it_path)):
            tmp = path.with_suffix(".tmp")
            pq.write_table(schema.conform(table, sch), tmp)
            tmp.replace(path)
        scanned_total += s1 + s2
        print(f"[{i:>2}/{len(days)}] {day}  {events.num_rows:>7,} events  {items.num_rows:>7,} items", flush=True)

    event_rows = sum(pq.read_metadata(p).num_rows for p in (out / "events").glob("*.parquet"))
    item_rows = sum(pq.read_metadata(p).num_rows for p in (out / "items").glob("*.parquet"))
    manifest = {
        "source": "bigquery",
        "dataset": "bigquery-public-data.ga4_obfuscated_sample_ecommerce",
        "days": len(list((out / "events").glob("*.parquet"))),
        "event_rows": event_rows,
        "item_rows": item_rows,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nDone: {event_rows:,} events, {item_rows:,} items. "
          f"{scanned_total / 1e9:,.2f} GB scanned this run.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="Your BigQuery (sandbox) project id")
    ap.add_argument("--out", type=Path, default=REPO / "data" / "raw")
    ap.add_argument("--check", action="store_true", help="Pull one day and validate; write nothing")
    ap.add_argument("--limit", type=int, default=None, help="Only the first N days")
    args = ap.parse_args(argv)

    bq = connect(args.project)
    days = all_days()
    if args.check:
        return check(bq, days[0])
    return extract(bq, args.out, days[: args.limit] if args.limit else days)


if __name__ == "__main__":
    sys.exit(main())
