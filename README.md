# GA4 Product Analytics: Google Merchandise Store

Where does the purchase funnel leak, what actually moved revenue over the 2020
holidays, do new users come back, and how would you test a fix without fooling
yourself?

Built on Google's public GA4 BigQuery export for the Google Merchandise Store:
about 4.3 million real, obfuscated events from 1 November 2020 to 31 January 2021.

## What the data says

From the full extract: 4,295,584 events, 270,154 users, 360,129 sessions,
5,298 purchases, $339,343 revenue. Full readout: [`docs/readout.html`](docs/readout.html).

- **The leak is product page to checkout, on every device.** Only 14.0% of
  sessions that view a product start checkout (10,807 of 77,020). After that,
  61% reach payment and 71% of those buy. Mobile (14.2%) and desktop (13.9%)
  are statistically indistinguishable at this and every other step
  (all p > 0.17), so a mobile-specific fix is not supported.
- **The holiday peak was the week of 7 December, not Black Friday:** revenue
  +153% over the pre-holiday baseline, about half from more users and half from
  higher conversion. Order value barely moved.
- **New users rarely come back:** 3.8% return in week 1, 0.9% in week 4.
- **A three-week test on all users can detect a lift of 21% or more** in session
  conversion. A 10% lift would need 144,273 users per arm, about 94 days. A
  1,000-split A/A test confirms the analysis holds its 5% false-positive rate,
  and CUPED would cut variance by only ~1%, because just 4.7% of users in the
  window have any earlier history.

**Three tracking problems found before any of that was trusted** (details in
[`docs/DECISIONS.md`](docs/DECISIONS.md), D-16 to D-18):

1. `add_to_cart` was not recorded until 16 November, and at most 82% of
   checkout sessions carry it after. It is measured, not chained into the funnel.
2. `add_shipping_info` fires in the same instant as `begin_checkout`, logged
   *first* in 6,862 of 11,104 sessions. Chained in order, it discarded a third
   of real buyers.
3. From 26 January most purchases record $0 revenue, so revenue after 25
   January is excluded from the revenue analysis.

Also removed: 394 re-sent purchase hits that would have inflated revenue, found
with a dedupe key that does not rely on `transaction_id` (missing on 906
purchase rows).

## Questions answered

| # | Question | Method |
|---|---|---|
| 0 | Can this data be trusted? | 19 audit checks run before anything is built: duplicate hits, missing session ids, `(not set)` transactions, item-vs-order revenue reconciliation, left-censored users. A FAIL stops the build. |
| 1 | What moved revenue week to week? | Metric tree `revenue = users × sessions/user × conversion × AOV`, with an exact log decomposition against a pre-holiday baseline |
| 2 | Where does the funnel leak? | Ordered and open four-step funnels by device, channel and user type (add-to-cart tracking was switched on mid-window and shipping info fires with checkout, so the audit measures both instead of chaining them); each step's mobile gap sized in purchases and dollars, with significance |
| 3 | Do new users come back? | Weekly new-user cohorts, censored on both sides |
| 4 | Which channels bring buyers? | Session conversion with Wilson 95% intervals |
| 5 | How would we test the fix? | Sample size and duration on real baselines, delta-method variance, 1,000-split A/A test, measured CUPED reduction, SRM guardrail |

## What makes this more than a dashboard

- **No experiment is faked.** The data contains none. The experiment section
  designs one and proves, with an A/A simulation on real users, that the
  analysis would not produce false positives.
- **The naive A/B calculation is shown to be wrong, not just avoided.**
  Randomising users but counting sessions as independent inflates the
  false-positive rate. The delta method fixes it, and the A/A test measures both.
- **Every number has a written rule** in [`docs/DECISIONS.md`](docs/DECISIONS.md):
  the purchase dedupe key, why first-touch source is not a session source, why
  "a 10% lift at step X" cannot rank funnel steps.
- **Two independent implementations must agree.** dbt and a separate pandas
  implementation have to match to the session and the cent, or the build stops.

## Stack

BigQuery SQL (extract and `UNNEST` flattening) · DuckDB · dbt (5 marts, schema
and custom data tests) · Python (pandas, SciPy) · pytest · matplotlib

## Run it

```bash
pip install -r requirements.txt
python scripts/build_all.py          # full build on synthetic data, about a minute
python -m pytest                     # tests, including exact recovery of planted truth
```

On real data, one-time setup: create a free BigQuery sandbox at
console.cloud.google.com/bigquery (no card needed) and note the project id.

```bash
python -m gpa.extract --project YOUR_PROJECT_ID --check   # validate one day first
python -m gpa.extract --project YOUR_PROJECT_ID           # 92 days, resumable
python scripts/build_all.py --raw data/raw                # writes docs/readout.html
```

Set `PYTHONPATH=src` (or `pip install -e .`) before running the `gpa` modules
directly.

## Layout

```
sql/bigquery/        extract SQL: nested GA4 export -> flat events and items
src/gpa/             extract, synthetic generator, audit, analysis, experiment stats, readout
dbt/                 staging -> intermediate -> marts, plus data tests
scripts/build_all.py generate/verify -> audit -> dbt -> cross-check -> analysis -> readout
tests/               pipeline recovery, statistics, extract contract
docs/DECISIONS.md    every rule behind every number
```
