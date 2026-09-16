# GA4 Product Analytics: Google Merchandise Store

An end-to-end analysis of three months of Google Analytics 4 data from the
Google Merchandise Store, using Google's public BigQuery sample
(1 November 2020 to 31 January 2021). The work covers data quality, the
purchase funnel, holiday revenue, retention, acquisition channels and the design
of a follow-up experiment.

**[Full write-up with charts](https://ankitsingathia.github.io/ga4-product-analytics/docs/readout.html)** ·
[Decision log](docs/DECISIONS.md)

| Events | Users | Sessions | Orders | Revenue | Session conversion |
|---:|---:|---:|---:|---:|---:|
| 4,295,584 | 270,154 | 360,129 | 5,298 | $339,343 | 1.47% |

## Key findings

1. **The largest drop is between viewing products and starting checkout.** Only
   14.0% of sessions that view products go on to checkout (10,807 of 77,020).
   Checkout itself performs well: 61.0% of checkouts reach payment, and 71.1% of
   those complete a purchase.
2. **Device is not the driver.** Mobile (14.2%) and desktop (13.9%) convert at
   the same rate at every step. The largest gap is 1.2 percentage points and no
   difference is statistically significant (all p > 0.17).
3. **Five store sections convert far below the rest.** A typical section sends
   14.1% of its sessions to checkout. Accessories (2.7%), Bags (3.8%), Office
   (3.8%), Drinkware (6.6%) and Shop by Brand (8.6%) are clearly below it.
   Closing that gap is worth up to about 685 orders, or roughly $41,700 over the
   period. This is an upper bound: part of the gap reflects browsing intent
   rather than friction.
4. **One product page shows a likely checkout fault.** Sessions that start on the
   Super G Unisex Joggers page reach checkout 58.4% of the time, but only 3.6% of
   those checkouts complete, against 43.4% across the site.
5. **The holiday peak came in the week of 7 December, not Black Friday week.**
   Revenue reached 2.5 times the early-November baseline, driven roughly equally
   by more visitors and higher conversion. Order value was essentially flat.
6. **Repeat visits are rare.** 3.8% of new visitors return in the following
   week and 0.9% four weeks later, so most revenue depends on first-visit
   conversion.

## Recommendations

| Priority | Action | Basis |
|---|---|---|
| 1 | Investigate the checkout flow for the Super G Unisex Joggers page | 3.6% checkout completion against a 43.4% site average |
| 2 | Review the five low-converting sections for stock, pricing and add-to-cart behaviour | Up to ~685 orders (~$41,700) if they reached the typical section's rate |
| 3 | Test substantial product-page changes site-wide rather than small tweaks | Current traffic supports detecting lifts of about 21% or more in a three-week test |
| 4 | Fix the three tracking issues below before the next analysis cycle | Each one distorts a headline metric if left in place |

## Data quality

The sample is obfuscated, and Google notes that its internal consistency is
limited. The export was audited (19 automated checks) before any analysis, and
the following issues were found and handled:

| Issue | Evidence | Handling |
|---|---|---|
| `add_to_cart` not tracked until mid-November | Weekly coverage of checkout sessions rises from 0% to at most 82% | Excluded from the funnel; coverage measured on every build |
| `add_shipping_info` fires with `begin_checkout` | Logged first in 6,862 of 11,104 sessions, typically by under a millisecond | Excluded from the funnel; strict ordering would have dropped about a third of real buyers |
| Revenue recorded as $0 from 26 January | Most orders from 26 to 31 January carry $0 | Revenue after 25 January excluded; order counts unaffected |
| Duplicate purchase events | 394 re-sent purchase rows | Deduplicated on session, transaction and amount, since 906 rows lack a transaction ID |
| Item IDs differ between events | Views use SKU codes, checkouts use numeric IDs; 0 of 18,876 match | Item-level analysis uses product names or page URLs instead |

Each rule, and the alternatives that were rejected, is documented in
[docs/DECISIONS.md](docs/DECISIONS.md).

## Experiment design

The dataset contains no A/B test, so none is simulated as a result. Instead,
the follow-up test was designed on the real post-holiday baselines:

- **Metric and unit:** session conversion, randomised by user.
- **Power:** a 21-day test detects relative lifts of about 21% or more. A 10%
  lift would need 144,273 users per group, roughly 94 days of traffic.
- **Validation:** 1,000 A/A splits of real users gave a 5.0% false-positive
  rate for the delta-method test, matching the 5% target. A test that treats
  each visit as independent gave 5.6%, which is close here only because users
  average 1.2 visits.
- **Variance reduction:** CUPED would reduce variance by about 0.9%, because
  only 4.7% of users in the test window have any earlier activity.
- **Guardrail:** a sample-ratio check on the group split before reading results.

## Method

| Stage | Implementation |
|---|---|
| Extract | BigQuery SQL flattens the nested GA4 export (`UNNEST` over `event_params` and `items`), one daily table per query, saved as Parquet |
| Audit | 19 checks run before the build; any hard failure stops it |
| Warehouse | DuckDB with dbt: staging, intermediate and mart models, with schema and custom data tests |
| Validation | The funnel is recomputed independently in pandas and must match dbt exactly; rebuilds are byte-identical |
| Analysis | Funnel, device and section comparisons with Wilson intervals, an exact log decomposition of weekly revenue, censored cohort retention, experiment sizing |
| Output | A self-contained HTML write-up generated from the results, with a table behind every chart |

**Stack:** BigQuery SQL, DuckDB, dbt, Python (pandas, SciPy), pytest, matplotlib.
The test suite covers the pipeline, the statistics and the extract contract, and
runs against generated data in the export format with known, planted problems.

## Reproducing the analysis

```bash
pip install -r requirements.txt
python scripts/build_all.py          # full build on generated data, about a minute
python -m pytest                     # test suite
```

To run on the real data, create a free BigQuery sandbox at
console.cloud.google.com/bigquery (no billing required) and note the project ID:

```bash
python -m gpa.extract --project YOUR_PROJECT_ID --check   # validate one day first
python -m gpa.extract --project YOUR_PROJECT_ID           # all 92 days, resumable
python scripts/build_all.py --raw data/raw                # writes docs/readout.html
```

Set `PYTHONPATH=src` or run `pip install -e .` before calling the `gpa` modules
directly.

## Repository structure

```
sql/bigquery/        extract queries: nested GA4 export to flat events and items
src/gpa/             extract, audit, analysis, statistics, readout, test-data generator
dbt/                 staging, intermediate and mart models with data tests
scripts/build_all.py end-to-end build: audit, dbt, cross-check, analysis, readout
tests/               pipeline, statistics and extract tests
docs/                decision log, generated write-up, dashboard data and build guide
```
