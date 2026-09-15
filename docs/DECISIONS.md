# Decisions

Every rule a number in the readout depends on, why it was chosen, and what was
rejected. If a figure is questioned, the answer starts here.

## D-01 · Extract once from BigQuery, analyse locally

The flattening SQL (`sql/bigquery/`) runs in BigQuery, one daily table per
query, and writes Parquet. Everything downstream runs on DuckDB and dbt.

- **Why:** the BigQuery sandbox has quotas, and a reviewer should be able to
  rerun the analysis without a Google account. The nested-field work
  (`UNNEST(event_params)`) stays in BigQuery SQL, where it would live in a real
  team.
- **Rejected:** building the marts in BigQuery. Every rerun would cost quota,
  and the repo would only reproduce for people with GCP access.

## D-02 · A validity gate before the full extract

`python -m gpa.extract --check` pulls one day and refuses to continue if
`ga_session_id`, `ga_session_number` or `user_pseudo_id` come back mostly NULL.

- **Why:** each `event_params` key lives in one of four typed value slots.
  Reading the wrong slot returns NULL, not an error. The pipeline would then
  build a warehouse where every event is dropped or orphaned, without a single
  failure.

## D-03 · Session = `user_pseudo_id` + `ga_session_id`

`ga_session_id` is the session start time in epoch seconds, so it is only
unique within a user. Events with no session id are dropped in staging; the
audit counts them and fails the build above 20%.

## D-04 · Exact duplicate events are dropped

Rows identical in every column are the same hit delivered twice. They are
removed in `stg_events` with `select distinct`. The audit reports how many.

## D-05 · A purchase is (session, transaction id, revenue)

- **Why:** GA4 re-sends purchase hits about a second later with identical
  content, so the timestamp cannot be in the key. `transaction_id` alone cannot
  be the key either: a large share is `(not set)`.
- **Known cost:** two genuine `(not set)` purchases of identical value in one
  session merge into one. The audit reports how many rows the key collapses, so
  the size of this effect is visible.

## D-06 · The ordered funnel is primary; the open funnel is shown beside it

A step counts only if it happened at or after the previous step was first
reached in the same session. The open funnel (did it happen at all) is reported
next to it.

- **Why:** the ordered funnel is what "progressed through checkout" means. The
  gap between the two measures event-ordering problems in the data, and the
  audit counts purchases with no earlier `begin_checkout` directly.

## D-07 · Session channel, with a narrow first-touch fallback

Channel comes from the session-level `source`/`medium` event parameters. If a
session carries none, `traffic_source.*` is used, but **only on the user's
first session**. Otherwise the channel is `Unknown`.

- **Why:** `traffic_source.*` in the GA4 export is the user's first-touch
  acquisition source, not the source of each session. Using it for every session
  would credit a returning visitor's direct visit to the ad that first brought
  them.
- `<Other>` and `(data deleted)` form an `Obfuscated` bucket. It is kept visible,
  not redistributed.
- Measured on the real extract: 5.6% of sessions end up `Unknown`. They are
  real visits (98% have `session_start`) but short (3.5 events against 12.4
  elsewhere) and none purchased. They are reported, not dropped.

## D-08 · Weeks are ISO (Monday) and only full weeks are compared

The window starts on Sunday 1 November 2020, so the first week holds one day.
Every week records how many days the data covers, and weekly comparisons use
full weeks only.

## D-09 · Cohorts are censored on both sides

- **Left:** a user first seen on session number 5 is a returning customer whose
  real first visit predates the data. Only users whose first observed session
  is session 1 form a cohort.
- **Right:** a late cohort has fewer observable weeks. The retention grid holds
  only fully observed weeks, so missing weeks are blank, not zero.

## D-10 · Revenue changes are split with a log decomposition

`revenue = users × sessions/user × conversion × AOV` is an exact identity, so
`Δlog(revenue)` is the exact sum of the four `Δlog` terms. The baseline is the
geometric mean of the full pre-holiday weeks. A dbt test asserts the identity
holds every week.

- **Rejected:** comparing percentage changes of each factor. They do not add up
  to the revenue change, so the parts could not be ranked.

## D-11 · Opportunity is sized against an internal benchmark

For each step: *if mobile matched desktop's rate at this step, how many more
purchases and how much revenue?* Only gaps significant at p < 0.05 are
eligible to become the recommendation.

- **Why not "what if step X improved 10%":** in a multiplicative funnel, a 10%
  relative lift at any step yields exactly 10% more purchases. That framing
  cannot rank steps, whatever the data says.
- **Stated as an upper bound:** part of a device gap is intent (browsing on a
  phone), not friction. Separating the two is the experiment's job.
- **What the real data said:** no step shows a significant mobile-vs-desktop
  gap (every p > 0.17). The recommendation then falls back to the step inside
  the purchase path with the lowest rate, tested on all users. The first step
  (session to item view) is excluded from that choice: a session that never
  opens a product is browsing, not leaking.

## D-12 · There is no A/B test in this data, and none is invented

The experiment section designs the test the opportunity analysis points at,
using real baselines from a three-week post-holiday window (4 to 24 January
2021, ending before revenue tracking broke, D-18):

- **Unit:** users are randomised, but the metric is per session. Sessions of one
  user are correlated, so the variance comes from the **delta method** for ratio
  metrics (Deng et al., 2018), not from a session-level binomial.
- **A/A simulation:** real users are split at random 1,000 times with no
  treatment. The false-positive rate of both the naive and the delta-method test
  is reported. This is the check that the analysis would not cry wolf.
- **CUPED:** the variance reduction is measured, not assumed, and it equals
  `corr(y, x)²`. It is reported alongside the share of users who have any
  pre-period history, which bounds how much CUPED can help.
- **Duration:** days to enrol comes from the observed curve of *new* users, not
  daily actives, because returning users add no sample.
- **SRM:** a chi-square check on the arm split is specified as a guardrail, with
  p < 0.001 as the stop rule.

## D-13 · Two implementations must agree

`src/gpa/crosscheck.py` recomputes sessions, every funnel step, purchases and
revenue from raw Parquet in pandas, sharing no code with dbt. The build stops if
the two disagree by one session or one cent.

## D-14 · A rebuild must reproduce every number exactly

Money is cast to `DECIMAL(38, 6)` at the purchase grain, so sums are exact and
independent of the order DuckDB's parallel aggregation adds them in. Every
table the analysis reads is loaded with an explicit `ORDER BY`, because the A/A
simulation assigns arms by row position; unordered, the same data gave a
different false-positive rate on each build.

## D-15 · Synthetic data never becomes a finding

`gpa.synth` writes events in the exact extract schema, with every quirk the
audit hunts for planted at a known rate, and records the realised counts in
`truth.json`. The tests demand exact recovery. A readout built from synthetic
data is stamped on screen, written to `out/`, and refused under `docs/`.

## D-16 · add_to_cart is left out of the funnel chain: its tracking was switched on mid-window

Measured on the real extract. Share of `begin_checkout` sessions that also
contain `add_to_cart`, by week: 0% through the week of 9 November, 24% in the
week of 16 November, 46% the week after, then a steady 68–82% from 30 November
to the end. The event was not recorded until 16 November and never fully
after. Nobody checks out without a cart, so this is tracking, not shoppers.

- **Rejected:** keeping the step. The funnel would show a cart "collapse" in
  early November and a cart "recovery" from mid-November, both invented by a
  tracking change.
- **Rejected:** keeping it for the period after 30 November only. Coverage
  is still ~72% there, so the step rate would still be a tracking rate.
- The first four real days showed 1 of 487 checkout sessions with a cart, and
  the first version of this entry concluded "under-recorded throughout". The
  full window proved that wrong. The audit now measures coverage **weekly**,
  because the overall 53.7% looks harmless and hides the switch.

## D-17 · add_shipping_info is left out: it fires with begin_checkout, in random order

In 11,104 sessions with both events, `add_shipping_info` is logged *before*
`begin_checkout` in 6,862. The median gap is about 0.2 milliseconds: one click
fires both. Chained in order, the funnel kept 3,192 purchasing sessions out of
4,848 that actually purchased, discarding a third of real buyers because of
timestamp noise. Without the step, the ordered funnel keeps 4,688.

## D-18 · Revenue is not trusted after 25 January 2021

From 26 January, most purchases record $0 revenue: 31 of 53 on the 26th, 41 of
53 on the 27th, all 18 on the 31st. A $0 purchase still counts as a
transaction, so conversion is unaffected but revenue and AOV collapse (the last
week's AOV reads $16 against about $65). Weeks running past
`revenue_reliable_through` are left out of the revenue decomposition, and the
experiment window ends on 24 January.

- $0 purchases first appear in the week of 16 November, the same week
  `add_to_cart` tracking switched on. The store's tracking was changed that
  week; the readout says so rather than reading either signal as behaviour.

## D-19 · What the item data can and can't do

Measured on the real extract before building anything item-level:

- `view_item` fires on product pages and category listings alike, carrying up
  to 12 items. Only 3.6% of view events have a single item, and listing URLs
  such as `/Google+Redesign/Apparel` carry 12. So the funnel's first step is
  "looked at products", not "opened a product page", and the write-up says so.
- Item IDs do not link across events. Views use SKU-style IDs
  (`GGOEYXXX1207`), checkouts use numeric ones (`9200710`), and 0 of 18,876
  checked-out item-visits match a viewed ID. Item names do link: 15,224 of
  17,858 (85%).
- Category names follow two schemes by event type. Views and `add_to_cart`
  use paths (`Home/Apparel/Men's / Unisex/`); checkout and purchase use plain
  names (`Men's / Unisex`).

So the store-section analysis (D-20) uses the page URL of a visit's first
product view, not the items or categories on the event.

## D-20 · Store sections are sized against the typical section

Each visit counts once, in the section where it first looked at products (the
second path segment of the page URL). Sections need at least 1,000 visits. The
benchmark is the median checkout rate across sections, 14.1%. A section is
"clearly below" only if its whole 95% range sits under the median. Extra orders
= visits × gap × that section's own checkout-to-purchase rate; extra revenue
uses that section's order value from the days revenue can be trusted (D-18).

- **Result:** five sections are clearly below: Accessories 2.7%, Bags 3.8%,
  Office 3.8%, Drinkware 6.6% and Shop by Brand 8.6%. Matching the typical
  section would add about 685 orders, around $41,700 over the three months.
- **Stated as an upper bound:** accessories and drinkware are often browsed as
  add-ons with no intent to buy. The figure says where to look, not what a fix
  is worth.
- **Rejected:** crediting the category of the first item viewed (view events
  list up to 12 items), and crediting every section a visit touched (a visit
  would count several times, so the gaps could not be summed).
- **Flagged separately:** visits that start on the Super G Unisex Joggers page
  reach checkout 58% of the time, but only 3.6% of those checkouts finish,
  against 43% site-wide. Their checkout events fire on the same page as
  everyone else's (`/yourinfo.html`), so this is not a mis-tagged event. The
  write-up calls it a checkout to investigate and does not guess the cause.
