-- Every cohort member is active in their own first week, and no rate can
-- leave [0, 1]. A failure here means the cohort and activity joins disagree.
select cohort_week, week_offset, retention
from {{ ref('fct_cohort_retention') }}
where (week_offset = 0 and retention <> 1)
   or retention < 0 or retention > 1
   or purchase_retention > retention
