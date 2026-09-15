"""The flat event schema.

One definition, shared by the BigQuery extract and the synthetic generator, so
the warehouse cannot tell which of the two fed it. GA4 exports nested records
(event_params and items are arrays of structs); the extract SQL flattens them
to exactly these columns.
"""

from __future__ import annotations

from datetime import date

import pyarrow as pa

WINDOW_START = date(2020, 11, 1)
WINDOW_END = date(2021, 1, 31)

# The ordered purchase funnel. Order matters: the warehouse only credits a step
# if it happened at or after the previous one in the same session.
# Two GA4 events are deliberately absent, both for measured reasons:
#   add_to_cart        its tracking was switched on mid-window (D-16)
#   add_shipping_info  fires in the same instant as begin_checkout, in random
#                      order, so as a step it measures nothing (D-17)
# The audit re-measures both on every build. Must match funnel_steps in
# dbt/dbt_project.yml (a test enforces it).
FUNNEL_STEPS = (
    "view_item",
    "begin_checkout",
    "add_payment_info",
    "purchase",
)

# Values the obfuscated sample uses in place of real data.
PLACEHOLDERS = ("<Other>", "(not set)", "(data deleted)", "")

EVENTS = pa.schema(
    [
        ("event_date", pa.date32()),
        ("event_ts", pa.timestamp("us")),  # UTC, tz-naive
        ("event_name", pa.string()),
        ("user_pseudo_id", pa.string()),
        ("ga_session_id", pa.int64()),
        ("ga_session_number", pa.int64()),
        ("engagement_time_msec", pa.int64()),
        ("session_engaged", pa.string()),
        ("page_location", pa.string()),
        ("session_source", pa.string()),  # event_params: source
        ("session_medium", pa.string()),  # event_params: medium
        ("session_campaign", pa.string()),  # event_params: campaign
        ("ft_source", pa.string()),  # traffic_source.*: the user's FIRST touch
        ("ft_medium", pa.string()),
        ("ft_name", pa.string()),
        ("device_category", pa.string()),
        ("operating_system", pa.string()),
        ("browser", pa.string()),
        ("country", pa.string()),
        ("transaction_id", pa.string()),
        ("purchase_revenue_usd", pa.float64()),
        ("shipping_usd", pa.float64()),
        ("tax_usd", pa.float64()),
        ("total_item_quantity", pa.int64()),
    ]
)

ITEMS = pa.schema(
    [
        ("event_date", pa.date32()),
        ("event_ts", pa.timestamp("us")),
        ("event_name", pa.string()),
        ("user_pseudo_id", pa.string()),
        ("ga_session_id", pa.int64()),
        ("transaction_id", pa.string()),
        ("item_id", pa.string()),
        ("item_name", pa.string()),
        ("item_category", pa.string()),
        ("price_usd", pa.float64()),
        ("quantity", pa.int64()),
        ("item_revenue_usd", pa.float64()),
    ]
)


def conform(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Select the schema's columns in order and cast to its types.

    Raises if a column is missing, so a changed extract fails loudly instead of
    writing a file the warehouse would half-read.
    """
    missing = [f.name for f in schema if f.name not in table.column_names]
    if missing:
        raise ValueError(f"extract is missing columns: {missing}")
    return table.select(schema.names).cast(schema)
