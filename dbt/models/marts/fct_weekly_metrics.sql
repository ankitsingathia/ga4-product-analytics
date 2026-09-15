-- The metric tree, one row per ISO week (Monday start):
--
--   revenue = users x sessions/user x conversion (transactions/session) x AOV
--
-- The identity is exact by construction, which is what lets the analysis
-- split a revenue change into four additive log contributions.
-- The window starts on a Sunday, so the first week holds one day. Weeks are
-- flagged by how many days the data actually covers, and only full weeks are
-- compared.
with s as (
    select * from {{ ref('fct_sessions') }}
),

bounds as (
    select min(session_date) as d0, max(session_date) as d1 from s
),

w as (
    select
        week_start,
        count(distinct user_pseudo_id) as users,
        count(*) as sessions,
        sum(purchases) as transactions,
        sum(revenue_usd) as revenue_usd
    from s
    group by week_start
),

covered as (
    select
        w.*,
        date_diff('day', greatest(w.week_start, b.d0), least(w.week_start + 6, b.d1)) + 1 as days_observed
    from w cross join bounds b
)

select
    week_start,
    days_observed,
    days_observed = 7 as is_full_week,
    -- False for a week that runs past the last day revenue can be trusted.
    week_start + 6 <= cast('{{ var("revenue_reliable_through") }}' as date) as revenue_complete,
    users,
    sessions,
    transactions,
    revenue_usd,
    sessions::double / users as sessions_per_user,
    transactions::double / sessions as conversion,
    revenue_usd / nullif(transactions, 0) as aov
from covered
order by week_start
