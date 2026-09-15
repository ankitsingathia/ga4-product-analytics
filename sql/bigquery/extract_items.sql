-- One row per item on an ecommerce event. Kept separate from the event table
-- because UNNEST(items) multiplies rows: joining it inline would count each
-- purchase once per line item.
-- Used by the audit to reconcile item revenue against purchase revenue.
-- Parameter: @day, a 'YYYYMMDD' string.

SELECT
  PARSE_DATE('%Y%m%d', event_date)                        AS event_date,
  DATETIME(TIMESTAMP_MICROS(event_timestamp))             AS event_ts,
  event_name,
  user_pseudo_id,
  (SELECT MAX(value.int_value) FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
  ecommerce.transaction_id                                AS transaction_id,
  i.item_id,
  i.item_name,
  i.item_category,
  i.price_in_usd                                          AS price_usd,
  i.quantity,
  i.item_revenue_in_usd                                   AS item_revenue_usd
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
  UNNEST(items) AS i
WHERE _TABLE_SUFFIX = @day
  AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
