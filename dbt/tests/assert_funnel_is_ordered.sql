-- A session cannot reach a step without reaching every earlier one.
{% set steps = var('funnel_steps') %}
select session_key
from {{ ref('fct_sessions') }}
where {% for i in range(1, steps | length) %}reached_{{ steps[i] }} > reached_{{ steps[i - 1] }}{{ " or " if not loop.last }}{% endfor %}
