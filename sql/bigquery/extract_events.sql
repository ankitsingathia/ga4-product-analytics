-- One row per event, with the nested GA4 fields flattened.
-- Parameter: @day, a 'YYYYMMDD' string. Filtering on _TABLE_SUFFIX means
-- BigQuery scans one daily table, not all 92.
--
-- event_params is an array of (key, value) where value has four typed slots.
-- Each key lives in exactly one slot; reading the wrong slot returns NULL, not
-- an error. `python -m gpa.extract --check` exists to catch that.
-- MAX() instead of a bare scalar subquery: a key repeated within one event
-- would otherwise abort the whole day's query.

SELECT
  PARSE_DATE('%Y%m%d', event_date)                        AS event_date,
  DATETIME(TIMESTAMP_MICROS(event_timestamp))             AS event_ts,
  event_name,
  user_pseudo_id,
  (SELECT MAX(value.int_value)    FROM UNNEST(event_params) WHERE key = 'ga_session_id')        AS ga_session_id,
  (SELECT MAX(value.int_value)    FROM UNNEST(event_params) WHERE key = 'ga_session_number')    AS ga_session_number,
  (SELECT MAX(value.int_value)    FROM UNNEST(event_params) WHERE key = 'engagement_time_msec') AS engagement_time_msec,
  (SELECT MAX(COALESCE(value.string_value, CAST(value.int_value AS STRING)))
                                  FROM UNNEST(event_params) WHERE key = 'session_engaged')      AS session_engaged,
  (SELECT MAX(value.string_value) FROM UNNEST(event_params) WHERE key = 'page_location')        AS page_location,
  (SELECT MAX(value.string_value) FROM UNNEST(event_params) WHERE key = 'source')               AS session_source,
  (SELECT MAX(value.string_value) FROM UNNEST(event_params) WHERE key = 'medium')               AS session_medium,
  (SELECT MAX(value.string_value) FROM UNNEST(event_params) WHERE key = 'campaign')             AS session_campaign,
  traffic_source.source                                   AS ft_source,
  traffic_source.medium                                   AS ft_medium,
  traffic_source.name                                     AS ft_name,
  device.category                                         AS device_category,
  device.operating_system                                 AS operating_system,
  device.web_info.browser                                 AS browser,
  geo.country                                             AS country,
  ecommerce.transaction_id                                AS transaction_id,
  ecommerce.purchase_revenue_in_usd                       AS purchase_revenue_usd,
  ecommerce.shipping_value_in_usd                         AS shipping_usd,
  ecommerce.tax_value_in_usd                              AS tax_usd,
  ecommerce.total_item_quantity                           AS total_item_quantity
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX = @day
