# Building the dashboard in Tableau Public

The CSVs in `docs/tableau/` are the analysis, already summarised. They carry the
decisions the audit forced, so a dashboard built on them cannot show the broken
metrics: `add_to_cart` and `add_shipping_info` are not in the funnel (D-16,
D-17), and every week is marked so revenue past 25 January can be excluded
(D-18). Regenerate them at any time with:

```bash
python scripts/export_tableau.py
```

| File | One row per | Use it for |
|---|---|---|
| `headline.csv` | the whole window | Title figures: events, users, sessions, orders, revenue |
| `funnel_by_device.csv` | device and step | Sheet 1, the funnel |
| `store_sections.csv` | store section | Sheet 2, where visits drop off |
| `weekly_revenue.csv` | week | Sheet 3, what moved revenue |
| `channels.csv` | channel | Sheet 4, where buyers come from |
| `retention.csv` | cohort and week offset | Sheet 5, optional heatmap |

## Step 0: install and sign up

1. Download **Tableau Public** (free) from `tableau.com/products/public/download`
   and install it.
2. Create a free Tableau Public account at `public.tableau.com`. Saving a
   workbook requires it, and everything saved there is public, which is fine
   because this dataset is Google's public sample.

## Step 1: connect the data

1. Open Tableau Public. On the left under **Connect**, choose **Text file**.
2. Select `docs/tableau/funnel_by_device.csv` and open it.
3. Repeat for each other CSV: **Data > New Data Source > Text file**. Keep them
   as five separate sources. Do not join or relate them; each sheet uses one.
4. In `weekly_revenue.csv` and `retention.csv`, click the **Abc** icon above
   `week_start` and `cohort_week` and change the type to **Date**.

## Step 2: Sheet 1, the funnel by device

Name the sheet `Funnel by device`.

1. Data source: `funnel_by_device.csv`.
2. Drag **step** to **Rows**, and **rate from previous** to **Columns**.
3. On the Columns pill, set **Measure > Average** (each row already holds one
   rate; averaging keeps it unchanged).
4. Drag **device** to **Color**, then to **Filter** and keep only `desktop` and
   `mobile` (exclude `all`, which is the site total).
5. Right-click the axis, choose **Format**, and set the number format to
   **Percentage** with 1 decimal place.
6. Drag **rate from previous** to **Label** so each bar shows its value.
7. Title: `Mobile and desktop convert the same at every step`.

## Step 3: Sheet 2, where visits drop off

Name it `Store sections`.

1. Data source: `store_sections.csv`.
2. **section** to **Rows**, **checkout rate** (set to **Average**) to **Columns**.
3. Sort the section pill **descending by checkout rate** so the weak sections
   sit at the bottom.
4. Drag **clearly below typical** to **Color**. True is the group the story is
   about, so give it the strong colour and leave False grey.
5. Add a reference line: right-click the axis, **Add Reference Line**, choose
   **Average of typical section rate**, label it `typical section`.
6. Drag **sessions**, **checkouts that finish**, **extra orders if typical** and
   **extra revenue if typical** to **Tooltip**.
7. Filter **sessions** to at least 1,000 so tiny sections do not appear.
8. Title: `Five sections convert far below the rest`.

## Step 4: Sheet 3, what moved revenue

Name it `Weekly revenue`.

1. Data source: `weekly_revenue.csv`.
2. **week start** to **Columns**, set it to **Exact Date** and **Discrete** (the
   blue pill), so each week is its own bar.
3. Drag **Measure Values** to **Rows**. In the **Measure Values** card, remove
   everything except the four fields starting with `change`, and set each to
   **Average**.
4. Drag **Measure Names** to **Color**. The bars now stack into the four parts
   of the revenue change, which add up to the total by construction.
5. Drag **pct vs baseline** to **Tooltip** so the hover shows the total change.
6. Title: `The peak was the week of 7 December, split between more visitors and
   better conversion`.

## Step 5: Sheet 4, where buyers come from

Name it `Channels`.

1. Data source: `channels.csv`.
2. **channel** to **Rows**, **conversion** (**Average**) to **Columns**, sorted
   descending.
3. Drag **small sample** to **Filter** and keep **False**, so the 197-visit Email
   channel does not stretch the axis. Mention it in the caption instead.
4. Drag **ci low**, **ci high** and **sessions** to **Tooltip**, so anyone can
   see how certain each rate is.
5. Title: `Referral traffic converts best; paid search worst`.

## Step 6 (optional): Sheet 5, retention

Name it `Retention`. Data source `retention.csv`. **week offset** to
**Columns**, **cohort week** to **Rows**, **Marks** type **Square**, and
**retention** (**Average**) to **Colour**. Use one blue ramp, light to dark.

## Step 7: assemble the dashboard

1. **Dashboard > New Dashboard**. Set **Size** to **Fixed, 1200 x 1000**.
2. Drag the sheets in: funnel and sections on the top row, weekly revenue and
   channels below.
3. Add a **Text** object at the top with the title
   `Google Merchandise Store: where the funnel leaks` and one line beneath it:
   `GA4 sample, 1 November 2020 to 31 January 2021. 4.3M events, 270,154 people,
   5,298 orders.`
4. Under each sheet, add a small **Text** object with the finding in one
   sentence:
   - Funnel: `Only 14.0% of visits that look at products start checkout. Mobile
     and desktop are within 1.2 points at every step.`
   - Sections: `A typical section sends 14.1% of visits to checkout. Five are
     clearly below, worth about 685 orders (roughly $41,700) if they caught up.`
   - Weekly revenue: `The peak week was 7 December, at 2.5 times the
     early-November level. Revenue after 25 January is excluded because it was
     not recorded properly.`
   - Channels: `Referral converts at 2.2%, paid search at 0.4%. Email looks
     higher but has only 197 visits.`
5. Add a **device** filter from the funnel sheet: on the sheet, right-click
   **device > Show Filter**, then on the dashboard set it to apply to that sheet
   only.
6. At the bottom add a text line:
   `Add-to-cart and shipping steps are excluded: their tracking is unreliable in
   this export. Full method: github.com/ankitsingathia/ga4-product-analytics`

## Step 8: publish

1. **File > Save to Tableau Public As...**, sign in when prompted.
2. Name it `Google Merchandise Store: where the funnel leaks`.
3. After it saves, the browser opens the live workbook. Copy that URL.
4. On `public.tableau.com`, open the workbook, click **Edit Details**, and add
   the same one-line description.

Send me the URL and I will add it to the project README and your GitHub profile.
