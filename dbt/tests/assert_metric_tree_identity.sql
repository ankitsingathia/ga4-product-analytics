-- revenue = users x sessions/user x conversion x AOV must hold exactly. If it
-- ever does not, the revenue decomposition in the readout is wrong.
select week_start
from {{ ref('fct_weekly_metrics') }}
where transactions > 0
  and abs(users * sessions_per_user * conversion * aov - revenue_usd) > 1e-6 * greatest(revenue_usd, 1)
