-- Checkout and purchase by the part of the store where a visit first looked at
-- products. Each visit counts once, in the section of its first view_item
-- page, so the rows add up and the gaps can be summed into one opportunity.
--
-- The section comes from the page URL, not the items on the event: view_item
-- fires on listing pages and product pages alike, with up to 12 items, and the
-- item ids on views and checkouts use different schemes (DECISIONS D-19).
with first_view as (
    select
        session_key,
        first(regexp_extract(page_location, '^https?://[^/]+(/[^?#]*)', 1) order by event_ts, page_location) as path
    from {{ ref('stg_events') }}
    where event_name = 'view_item'
    group by session_key
),

areas as (
    select
        session_key,
        case
            when path is null or path in ('', '/') then 'Unknown'
            when path like '/Google+Redesign/%' then split_part(path, '/', 3)
            else split_part(path, '/', 2)
        end as entry_area
    from first_view
),

reliable as (
    select cast('{{ var("revenue_reliable_through") }}' as date) as last_day
)

select
    coalesce(nullif(a.entry_area, ''), 'Unknown') as entry_area,
    count(*) as sessions,
    sum(s.reached_begin_checkout) as checkouts,
    sum(s.reached_purchase) as purchase_sessions,
    count(*) filter (where s.reached_purchase = 1 and s.session_date <= r.last_day) as purchase_sessions_reliable,
    coalesce(sum(s.revenue_usd) filter (where s.reached_purchase = 1 and s.session_date <= r.last_day), 0)
        as revenue_reliable_usd
from areas a
join {{ ref('fct_sessions') }} s on s.session_key = a.session_key
cross join reliable r
where s.reached_view_item = 1
group by 1
order by sessions desc
