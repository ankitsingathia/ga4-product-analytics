# Where the Google Merchandise Store loses its shoppers

I took three months of Google Analytics 4 data from Google's own online merch
store (the public BigQuery sample, 1 November 2020 to 31 January 2021) and tried
to answer four questions: where do shoppers drop out, what drove the holiday
peak, do new visitors come back, and how would you test a fix properly?

**[Read the full write-up, with charts](https://ankitsingathia.github.io/ga4-product-analytics/docs/readout.html)**

## What I found

The data covers 4,295,584 events from 270,154 people over 360,129 visits, ending
in 5,298 orders worth $339,343.

- **Most people who look at a product never start checkout.** Only 14.0% of
  visits that reach a product page go on to checkout (10,807 of 77,020). Once
  people start checkout, most finish: 61% get to payment and 71% of those buy.
- **It isn't a mobile problem.** Phones (14.2%) and desktops (13.9%) are within
  about a point of each other at every step, and none of the gaps is
  statistically significant.
- **The busiest week was 7 to 13 December, not Black Friday week.** Revenue was
  about 2.5 times the early-November level, roughly half from more visitors and
  half from more of them buying.
- **New visitors rarely come back:** 3.8% return the next week, 0.9% four
  weeks later.
- **A test here needs patience.** With this traffic, three weeks can only catch
  a lift of about 21% or more. Proving a 10% lift would take around 94 days.

## Three things wrong with the data

Google says this sample isn't fully consistent, so I audited it before trusting
anything. Three problems turned up.

1. **Add-to-cart wasn't tracked until mid-November.** My first look, at just the
   first four days, made me think it was broken for the whole period. The full
   three months showed it was switched on partway through, so the audit now
   checks it week by week.
2. **The shipping-details event fires at the same moment as checkout.** In 6,862
   of 11,104 visits it's logged a fraction of a second earlier. My first funnel
   put the steps in strict order and lost about a third of real buyers because
   of it.
3. **From 26 January most orders are recorded at $0,** so I don't use revenue
   after 25 January.

I also removed 394 purchase records that had been sent twice. 906 purchase
records have no order ID, so duplicates are matched on the visit and the amount
instead.

## How it's built

- **Extract:** BigQuery SQL flattens GA4's nested event data (`UNNEST`) into two
  flat tables, one day at a time, saved locally as Parquet.
- **Warehouse:** DuckDB and dbt, with tests that fail the build if the funnel or
  the revenue arithmetic stops adding up.
- **Audit:** 19 checks run first, and a hard failure stops the build.
- **Cross-check:** the funnel is computed a second time in pandas, sharing no
  code with dbt, and the two have to match exactly.
- **Statistics:** sample sizes from the real baselines, a delta-method test for
  per-visit metrics, 1,000 fake A/A splits to check the false-positive rate, and
  CUPED. On this traffic the simpler visit-level test also lands close to 5%
  (5.6%), because people average only 1.2 visits; the delta method stays
  correct when that changes.

The reasoning behind each rule is in [docs/DECISIONS.md](docs/DECISIONS.md).

Stack: BigQuery SQL, DuckDB, dbt, Python (pandas, SciPy), pytest, matplotlib.

## Running it

```bash
pip install -r requirements.txt
python scripts/build_all.py          # full build on generated test data, about a minute
python -m pytest                     # tests, including exact recovery of planted problems
```

For the real data, create a free BigQuery sandbox at
console.cloud.google.com/bigquery (no card needed) and note the project ID.

```bash
python -m gpa.extract --project YOUR_PROJECT_ID --check   # check one day first
python -m gpa.extract --project YOUR_PROJECT_ID           # all 92 days, resumable
python scripts/build_all.py --raw data/raw                # writes docs/readout.html
```

Set `PYTHONPATH=src` (or run `pip install -e .`) before running the `gpa`
modules directly.

## Layout

```
sql/bigquery/        extract SQL: nested GA4 export to flat events and items
src/gpa/             extract, test-data generator, audit, analysis, statistics, readout
dbt/                 staging, intermediate and mart models, plus data tests
scripts/build_all.py generate or verify, audit, dbt, cross-check, analysis, readout
tests/               pipeline recovery, statistics, extract contract
docs/DECISIONS.md    the reasoning behind every number
```
