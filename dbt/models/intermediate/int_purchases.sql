-- One row per real purchase.
--
-- GA4 re-sends purchase hits, and the copies land a second or so later with
-- identical content, so the timestamp is deliberately NOT part of the key.
-- transaction_id alone will not do either: a large share is '(not set)'.
-- Key: (session, transaction id, revenue).
-- Known cost: two genuine '(not set)' purchases of identical value in one
-- session merge into one. The audit reports how many rows the key collapses.
--
-- Revenue becomes DECIMAL here so every downstream sum is exact. Summed as
-- DOUBLE, DuckDB's parallel aggregation adds in a different order each run and
-- the totals drift in the 14th digit, so two builds of identical data would not
-- produce identical results.
select
    session_key,
    user_pseudo_id,
    transaction_id,
    cast(purchase_revenue_usd as decimal(38, 6)) as purchase_revenue_usd,
    min(event_ts) as purchase_ts,
    count(*) as n_rows
from {{ ref('stg_events') }}
where event_name = 'purchase'
group by session_key, user_pseudo_id, transaction_id, purchase_revenue_usd
