-- Funnel progress per session, two ways.
--
--   reached_<step>  ORDERED: the step happened at or after the previous step
--                   was first reached. This is the primary funnel.
--   any_<step>      OPEN: the step happened at all in the session.
--
-- They differ when events arrive out of order (a purchase with no earlier
-- begin_checkout). The audit measures how often; the readout shows both.
{% set steps = var('funnel_steps') %}

with ev as (
    select session_key, event_name, event_ts
    from {{ ref('stg_events') }}
    where event_name in ({% for s in steps %}'{{ s }}'{{ ", " if not loop.last }}{% endfor %})
),

s1 as (
    select session_key, min(event_ts) as t1
    from ev
    where event_name = '{{ steps[0] }}'
    group by session_key
),
{% for i in range(1, steps | length) %}
s{{ i + 1 }} as (
    -- first {{ steps[i] }} at or after the first qualifying {{ steps[i - 1] }}
    select e.session_key, min(e.event_ts) as t{{ i + 1 }}
    from ev e
    join s{{ i }} p
      on e.session_key = p.session_key
     and e.event_ts >= p.t{{ i }}
    where e.event_name = '{{ steps[i] }}'
    group by e.session_key
),
{% endfor %}

open_funnel as (
    select
        session_key,
        {% for s in steps %}
        max(case when event_name = '{{ s }}' then 1 else 0 end) as any_{{ s }}{{ "," if not loop.last }}
        {% endfor %}
    from ev
    group by session_key
)

select
    o.session_key,
    {% for s in steps %}
    o.any_{{ s }},
    {% endfor %}
    {% for i in range(steps | length) %}
    case when s{{ i + 1 }}.t{{ i + 1 }} is not null then 1 else 0 end as reached_{{ steps[i] }}{{ "," if not loop.last }}
    {% endfor %}
from open_funnel o
{% for i in range(steps | length) %}
left join s{{ i + 1 }} on s{{ i + 1 }}.session_key = o.session_key
{% endfor %}
