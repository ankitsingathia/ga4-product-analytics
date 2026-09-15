-- One row per event. Two kinds of row are dropped here, and both are counted
-- by the audit (src/gpa/audit.py), which runs before dbt and stops the build
-- if either is large:
--   exact duplicates   the same hit delivered twice, identical in every column
--   no session id      cannot be placed in a session
with deduped as (
    select distinct * from {{ raw('events') }}
)

select
    *,
    user_pseudo_id || ':' || cast(ga_session_id as varchar) as session_key
from deduped
where user_pseudo_id is not null
  and ga_session_id is not null
