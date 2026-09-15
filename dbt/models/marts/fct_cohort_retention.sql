-- Weekly new-user cohorts: of the users who first arrived in week W, what
-- share came back in week W+k, and what share bought.
--
-- Two censoring problems, handled explicitly:
--   LEFT   A user first seen here on session 5 is a returning customer whose
--          real cohort predates the data. Counting them as new inflates early
--          retention. Only users whose first observed session is session 1
--          enter a cohort.
--   RIGHT  A late cohort has fewer weeks left to be observed in. Weeks the
--          data does not fully cover are left out of the grid, not counted as
--          zero activity.
with s as (
    select user_pseudo_id, session_start_ts, session_number, week_start, purchases
    from {{ ref('fct_sessions') }}
),

full_weeks as (
    select week_start from {{ ref('fct_weekly_metrics') }} where is_full_week
),

first_seen as (
    select
        user_pseudo_id,
        min(session_start_ts) as first_ts,
        arg_min(session_number, session_start_ts) as first_session_number
    from s
    group by user_pseudo_id
),

new_users as (
    select user_pseudo_id, cast(date_trunc('week', first_ts) as date) as cohort_week
    from first_seen
    where first_session_number = 1
),

cohorts as (
    select n.cohort_week, count(*) as cohort_users
    from new_users n
    join full_weeks f on f.week_start = n.cohort_week
    group by n.cohort_week
),

activity as (
    select n.cohort_week, s.week_start, s.user_pseudo_id, max(s.purchases) > 0 as purchased
    from new_users n
    join s on s.user_pseudo_id = n.user_pseudo_id
    group by n.cohort_week, s.week_start, s.user_pseudo_id
),

grid as (
    select c.cohort_week, c.cohort_users, f.week_start as activity_week
    from cohorts c
    join full_weeks f on f.week_start >= c.cohort_week
),

counted as (
    select
        g.cohort_week,
        g.activity_week,
        g.cohort_users,
        count(a.user_pseudo_id) as active_users,
        count(a.user_pseudo_id) filter (where a.purchased) as purchasing_users
    from grid g
    left join activity a
      on a.cohort_week = g.cohort_week
     and a.week_start = g.activity_week
    group by g.cohort_week, g.activity_week, g.cohort_users
)

select
    cohort_week,
    activity_week,
    date_diff('week', cohort_week, activity_week) as week_offset,
    cohort_users,
    active_users,
    purchasing_users,
    active_users::double / cohort_users as retention,
    purchasing_users::double / cohort_users as purchase_retention
from counted
order by cohort_week, activity_week
