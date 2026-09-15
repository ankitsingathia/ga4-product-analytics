-- Funnel counts overall and by segment. Rates and confidence intervals are
-- computed in Python (src/gpa/analysis.py) from these counts.
{% set steps = var('funnel_steps') %}
{% set segments = [
    ('all', "'all'"),
    ('device', 'device_category'),
    ('channel', 'channel'),
    ('user_type', "case when is_first_session then 'new' else 'returning' end"),
] %}

with s as (
    select * from {{ ref('fct_sessions') }}
)

{% for seg_type, expr in segments %}
select
    '{{ seg_type }}' as segment_type,
    coalesce(cast({{ expr }} as varchar), '(null)') as segment,
    count(*) as sessions,
    count(distinct user_pseudo_id) as users,
    {% for st in steps %}
    sum(reached_{{ st }}) as reached_{{ st }},
    sum(any_{{ st }}) as any_{{ st }},
    {% endfor %}
    sum(engaged) as engaged_sessions,
    sum(purchases) as purchases,
    sum(revenue_usd) as revenue_usd
from s
group by 1, 2
{% if not loop.last %}union all{% endif %}
{% endfor %}
