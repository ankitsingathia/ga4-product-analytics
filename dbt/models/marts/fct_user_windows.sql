-- One row per user active in the experiment-design window, with the same
-- metrics measured in the pre-period. This is the frame the experiment
-- calculations run on:
--   exp_*  what a test in this window would measure (the outcome)
--   pre_*  history before it (the CUPED covariate; zero for new users)
-- The user, not the session, is the unit, because users are what get
-- randomised.
with s as (
    select * from {{ ref('fct_sessions') }}
),

w as (
    select
        cast('{{ var("experiment_start") }}' as date) as exp_start,
        cast('{{ var("experiment_end") }}' as date) as exp_end
)

select
    s.user_pseudo_id,
    arg_min(s.device_category, s.session_start_ts) as device_category,
    count(*) filter (where s.session_date < w.exp_start) as pre_sessions,
    coalesce(sum(s.purchases) filter (where s.session_date < w.exp_start), 0) as pre_purchases,
    coalesce(sum(s.revenue_usd) filter (where s.session_date < w.exp_start), 0) as pre_revenue_usd,
    count(*) filter (where s.session_date between w.exp_start and w.exp_end) as exp_sessions,
    count(*) filter (where s.session_date between w.exp_start and w.exp_end and s.purchases > 0)
        as exp_converting_sessions,
    coalesce(sum(s.purchases) filter (where s.session_date between w.exp_start and w.exp_end), 0) as exp_purchases,
    coalesce(sum(s.revenue_usd) filter (where s.session_date between w.exp_start and w.exp_end), 0)
        as exp_revenue_usd,
    min(s.session_date) filter (where s.session_date between w.exp_start and w.exp_end) as exp_first_date
from s
cross join w
group by s.user_pseudo_id
having count(*) filter (where s.session_date between w.exp_start and w.exp_end) > 0
