-- One row per session: who, when, where from, how far down the funnel, and
-- what it bought. Every other mart is an aggregate of this table.
{% set steps = var('funnel_steps') %}

with ev as (
    select * from {{ ref('stg_events') }}
),

base as (
    select
        session_key,
        any_value(user_pseudo_id) as user_pseudo_id,
        min(event_ts) as session_start_ts,
        max(ga_session_number) as session_number,
        arg_min(device_category, event_ts) as device_category,
        arg_min(country, event_ts) as country,
        arg_min(session_source, event_ts) filter (where session_source is not null) as session_source,
        arg_min(session_medium, event_ts) filter (where session_medium is not null) as session_medium,
        arg_min(ft_source, event_ts) as ft_source,
        arg_min(ft_medium, event_ts) as ft_medium,
        max(case when session_engaged = '1' then 1 else 0 end) as engaged,
        count(*) filter (where event_name = 'page_view') as page_views
    from ev
    group by session_key
),

purchases as (
    select session_key, count(*) as purchases, sum(purchase_revenue_usd) as revenue_usd
    from {{ ref('int_purchases') }}
    group by session_key
)

select
    b.session_key,
    b.user_pseudo_id,
    b.session_start_ts,
    cast(b.session_start_ts as date) as session_date,
    cast(date_trunc('week', b.session_start_ts) as date) as week_start,
    b.session_number,
    b.session_number = 1 as is_first_session,
    b.device_category,
    b.country,
    -- traffic_source.* is the user's FIRST touch, not this session's source.
    -- It is only a valid stand-in on the user's first session.
    case
        when b.session_source is not null or b.session_medium is not null
            then {{ channel_group('b.session_source', 'b.session_medium') }}
        when b.session_number = 1
            then {{ channel_group('b.ft_source', 'b.ft_medium') }}
        else 'Unknown'
    end as channel,
    b.engaged,
    b.page_views,
    {% for s in steps %}
    coalesce(f.reached_{{ s }}, 0) as reached_{{ s }},
    coalesce(f.any_{{ s }}, 0) as any_{{ s }},
    {% endfor %}
    coalesce(p.purchases, 0) as purchases,
    coalesce(p.revenue_usd, 0) as revenue_usd
from base b
left join {{ ref('int_session_funnel') }} f on f.session_key = b.session_key
left join purchases p on p.session_key = b.session_key
