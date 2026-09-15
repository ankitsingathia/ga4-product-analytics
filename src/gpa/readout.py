"""Render out/results.json as one self-contained HTML readout.

    python -m gpa.readout --results out/results.json --out out/readout_synthetic.html

Charts are inlined as PNG, and every chart has a table beside it with the same
numbers, so no value is only readable from a colour. Synthetic results are
stamped on every screen and refused anywhere under docs/.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# Validated reference palette, categorical slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
SEQ = LinearSegmentedColormap.from_list(
    "seq_blue", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"])

STEP = {
    "view_item": "Viewed products", "add_to_cart": "Cart", "begin_checkout": "Checkout",
    "add_shipping_info": "Shipping details", "add_payment_info": "Payment", "purchase": "Purchase",
}
COMP = {"users": "Visitors", "sessions_per_user": "Visits per visitor", "conversion": "Conversion",
        "aov": "Order size"}

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "font.size": 9,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titlesize": 10,
    "axes.titlecolor": INK,
})


# ---- formatting ------------------------------------------------------------

def pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{d}f}%"


def money(x):
    return f"${x:,.0f}"


def num(x):
    return f"{x:,.0f}"


def days(x):
    return "beyond the traffic this site gets" if math.isinf(x) else f"{x:,.0f} days"


def esc(s) -> str:
    return html.escape(str(s))


def table(headers: list[str], rows: list[list], numeric_from: int = 1) -> str:
    head = "".join(f"<th{' class=n' if i >= numeric_from else ''}>{esc(h)}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td{' class=n' if i >= numeric_from else ''}>{esc(c)}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ---- charts ----------------------------------------------------------------

def _axes(w=7.2, h=3.2):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(length=0)
    ax.set_axisbelow(True)
    return fig, ax


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chart_funnel_by_device(res: dict) -> str:
    by = res["funnel"]["by_device"]
    devices = [d for d in ("desktop", "mobile") if d in by]
    target = res["experiment"]["target_step"]
    steps = [s["step"] for s in by[devices[0]]]
    y = np.arange(len(steps))[::-1]
    h = 0.36
    fig, ax = _axes(7.2, 3.4)
    for i, d in enumerate(devices):
        rates = [s["step_rate"] for s in by[d]]
        ypos = y + (h / 2 + 0.02) * (1 if i == 0 else -1)
        ax.barh(ypos, rates, height=h, color=SERIES[i], label=d.capitalize())
        for s, r, yy in zip(steps, rates, ypos):
            if s == target:  # label only the step the story is about
                ax.text(r + 0.01, yy, pct(r), va="center", color=INK, fontsize=8.5)
    ax.set_yticks(y, [STEP[s] for s in steps])
    ax.set_xlim(0, 1.05)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_xlabel("Share of visits at the previous step that make it to this one")
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    return _png(fig)


def chart_metric_tree(res: dict) -> str:
    weeks = res["metric_tree"]["weeks"]
    comps = list(COMP)
    x = np.arange(len(weeks))
    fig, ax = _axes(7.2, 3.4)
    pos, neg = np.zeros(len(weeks)), np.zeros(len(weeks))
    for i, c in enumerate(comps):
        v = np.array([w["log_contrib"][c] for w in weeks])
        p, n = np.clip(v, 0, None), np.clip(v, None, 0)
        ax.bar(x, p, bottom=pos, width=0.66, color=SERIES[i], edgecolor=SURFACE, linewidth=1.2, label=COMP[c])
        ax.bar(x, n, bottom=neg, width=0.66, color=SERIES[i], edgecolor=SURFACE, linewidth=1.2)
        pos, neg = pos + p, neg + n
    totals = [w["log_total"] for w in weeks]
    ax.plot(x, totals, color=INK, linewidth=1.6, marker="o", markersize=4.5, label="Total", zorder=3)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.set_xticks(x, [w["week_start"][5:] for w in weeks], rotation=0, fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v * 100:+.0f}")
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_ylabel("Change vs early November (roughly %)")
    ax.set_xlabel("Week starting")
    lo, hi = min(neg.min(), min(totals)), max(pos.max(), max(totals))
    pad = 0.08 * (hi - lo)
    ax.set_ylim(lo - pad, hi + pad)
    # Legend above the plot, so it can never sit on the tallest week.
    ax.legend(frameon=False, ncol=5, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.01))
    return _png(fig)


def chart_retention(res: dict) -> str:
    r = res["retention"]
    m = np.array([[np.nan if v is None else v for v in row] for row in r["matrix"]], dtype=float)
    # Week 0 is 100% by definition, so it is dropped rather than shown as a
    # column that would flatten the colour scale. Cohorts with no later
    # fully observed week have nothing to show and are dropped too.
    offsets = r["offsets"][1:]
    shown = m[:, 1:]
    keep = np.isfinite(shown).any(axis=1)
    shown, cohorts = shown[keep], [c for c, k in zip(r["cohorts"], keep) if k]
    fig, ax = _axes(7.2, 3.6)
    vmax = np.nanmax(shown) if np.isfinite(shown).any() else 1
    im = ax.imshow(shown, cmap=SEQ, vmin=0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(offsets)), offsets)
    ax.set_yticks(range(len(cohorts)), [c[5:] for c in cohorts])
    ax.set_xlabel("Weeks since first visit")
    ax.set_ylabel("First visit in the week of")
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, labelsize=8, colors=MUTED)
    cb.formatter = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0%}")
    cb.update_ticks()
    return _png(fig)


def chart_areas(res: dict) -> str:
    ar = res["areas"]
    rows = sorted(ar["rows"], key=lambda r: r["checkout_rate"])
    y = np.arange(len(rows))
    fig, ax = _axes(7.2, 0.42 * len(rows) + 1.1)
    # Emphasis, not a second category: the sections the text is about in
    # slot 1, everything else in muted ink.
    for flagged, color, label in ((False, MUTED, "Other sections"), (True, SERIES[0], "Clearly below typical")):
        idx = [i for i, r in enumerate(rows) if r["clearly_below"] == flagged]
        if not idx:
            continue
        xs = [rows[i]["checkout_rate"] for i in idx]
        err = [[rows[i]["checkout_rate"] - rows[i]["checkout_ci"][0] for i in idx],
               [rows[i]["checkout_ci"][1] - rows[i]["checkout_rate"] for i in idx]]
        ax.errorbar(xs, y[idx], xerr=err, fmt="o", color=color, ecolor=color, elinewidth=1.4, capsize=0,
                    markersize=6, label=label)
    ax.axvline(ar["median"], color=INK2, linewidth=1)
    ax.text(ar["median"], len(rows) - 0.45, " typical section", color=INK2, fontsize=8, va="bottom")
    ax.set_yticks(y, [r["label"] for r in rows])
    ax.set_ylim(-0.6, len(rows) - 0.1)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_xlabel("Share of visits that go on to checkout, with 95% range")
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    return _png(fig)


CHART_MIN_SESSIONS = 1_000


def chart_channels(res: dict) -> str:
    # A channel with a few hundred sessions has an interval wide enough to set
    # the axis for everyone else. It stays in the table, just not the chart.
    ch = sorted((c for c in res["channels"] if c["sessions"] >= CHART_MIN_SESSIONS),
                key=lambda c: c["conversion"])
    y = np.arange(len(ch))
    fig, ax = _axes(7.2, 0.45 * len(ch) + 1.0)
    lo = [c["conversion"] - c["conversion_ci"][0] for c in ch]
    hi = [c["conversion_ci"][1] - c["conversion"] for c in ch]
    ax.errorbar([c["conversion"] for c in ch], y, xerr=[lo, hi], fmt="o", color=SERIES[0],
                ecolor=SERIES[0], elinewidth=1.4, capsize=0, markersize=6)
    ax.set_yticks(y, [c["channel"] for c in ch])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_xlabel("Share of visits ending in an order, with 95% range")
    return _png(fig)


def chart_aa(res: dict) -> str:
    aa = res["experiment"]["aa"]
    labels = ["Simple test\n(each visit counted alone)", "Delta method\n(each person counted once)"]
    vals = [aa["fpr_naive"], aa["fpr_delta"]]
    cis = [aa["fpr_naive_ci"], aa["fpr_delta_ci"]]
    fig, ax = _axes(5.4, 2.8)
    x = np.arange(2)
    ax.bar(x, vals, width=0.5, color=SERIES[0])
    ax.errorbar(x, vals, yerr=[[v - c[0] for v, c in zip(vals, cis)], [c[1] - v for v, c in zip(vals, cis)]],
                fmt="none", ecolor=INK2, elinewidth=1.2, capsize=0)
    ax.axhline(aa["alpha"], color=MUTED, linewidth=1)
    ax.text(1.88, aa["alpha"], f"α = {aa['alpha']:.0%}", ha="right", va="bottom", color=INK2, fontsize=8.5)
    for xi, v, c in zip(x, vals, cis):  # above the whisker, clear of the alpha line
        ax.text(xi, c[1] + 0.002, pct(v), ha="center", va="bottom", color=INK, fontsize=9)
    ax.set_ylim(0, max(c[1] for c in cis) + 0.012)
    ax.set_xticks(x, labels)
    ax.set_xlim(-0.6, 1.9)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_ylabel("Fake tests flagged as significant")
    return _png(fig)


# ---- page ------------------------------------------------------------------

CSS = """
:root{--bg:#fbfbf9;--ink:#1a1a18;--ink2:#55544f;--muted:#8a8984;--line:#e4e3dc;--warn:#8a5a00;--fail:#a11f1f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 22px 96px}
h1{font-size:30px;line-height:1.2;margin:0 0 8px;font-weight:650}
h2{font-size:20px;margin:56px 0 10px;font-weight:650}h3{font-size:16.5px;margin:30px 0 6px}
p{margin:12px 0}ol{padding-left:22px}li{margin:10px 0}a{color:#1f5fae}
.byline{color:var(--ink2);margin:0 0 28px;font-size:14.5px}
.small{color:var(--ink2);font-size:14.5px}
.stamp{border:2px solid #7a3b00;color:#7a3b00;padding:10px 14px;margin:0 0 24px;font-weight:600}
figure{margin:22px 0}figure img{width:100%;height:auto;display:block;border:1px solid var(--line)}
figcaption{color:var(--ink2);font-size:13.5px;margin-top:6px}
details{margin:14px 0}summary{cursor:pointer;color:var(--ink2);font-size:14.5px}
.tw{overflow-x:auto;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.sev-warn{color:var(--warn);font-weight:600}.sev-fail{color:var(--fail);font-weight:600}.sev-info{color:var(--muted)}
code{font-size:14px;background:#efeee8;padding:1px 5px;border-radius:3px}
"""

BLACK_FRIDAY_WEEK = "2020-11-23"  # Black Friday 2020 was 27 November
REPO_URL = "https://github.com/ankitsingathia/ga4-product-analytics"
PROSE = {
    "view_item": "looking at products", "add_to_cart": "the cart", "begin_checkout": "checkout",
    "add_shipping_info": "shipping details", "add_payment_info": "the payment step", "purchase": "a purchase",
}
GAIN = {"users": "more visitors", "sessions_per_user": "people visiting more often",
        "conversion": "more of them buying", "aov": "bigger orders"}
LOSS = {"users": "fewer visitors", "sessions_per_user": "fewer repeat visits",
        "conversion": "fewer visitors buying", "aov": "smaller orders"}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
WEEKS = {7: "a week", 14: "two weeks", 21: "three weeks", 28: "four weeks"}


def day(s, year: bool = False) -> str:
    d = date.fromisoformat(str(s)[:10])
    return f"{d.day} {d.strftime('%B')}" + (f" {d.year}" if year else "")


def fold(summary: str, inner: str) -> str:
    return f"<details><summary>{esc(summary)}</summary>{inner}</details>"


def join_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def about_money(x: float) -> str:
    """An estimate reads as one: $41,656 -> $41,700."""
    return f"${round(x, -2):,.0f}"


def reach(step: str) -> str:
    """'visits that {reach(step)}': view_item fires on listings and product pages, so say what it means."""
    return "look at any products" if step == "view_item" else f"reach {PROSE[step]}"


def area_line(res: dict) -> str:
    ar = res.get("areas") or {}
    rows = ar.get("rows", [])
    below = sorted((r for r in rows if r["clearly_below"]), key=lambda r: -r["extra_revenue_usd"])
    out = ""
    if below:
        names = join_and([esc(r["label"]) for r in below[:3]])
        lead = (f"The drop is much worse in {names}." if len(below) <= 3
                else f"The drop is much worse in {WORDS.get(len(below), str(len(below)))} parts of the store, "
                     f"led by {names}.")
        out += (f"<p>{lead} If the sections that do worst matched a typical one, that would be roughly "
                f"{num(ar['extra_orders'])} more orders over the three months, about "
                f"{about_money(ar['extra_revenue_usd'])}. That's where I'd start.</p>")
    for r in rows:
        if r["broken_checkout"]:
            out += (f"<p>Separately, {esc(r['label'])} looks broken: its visitors reach checkout "
                    f"{pct(r['checkout_rate'])} of the time, but only {pct(r['finish_rate'])} of those checkouts "
                    "end in an order.</p>")
    return out


def short_version(res: dict) -> str:
    x = res["experiment"]
    ordered = res["funnel"]["ordered"]
    steps = [s["step"] for s in ordered]
    idx = steps.index(x["target_step"])
    prev = steps[idx - 1] if idx else steps[0]
    row10 = next(g for g in x["grid"] if abs(g["rel_mde"] - 0.10) < 1e-9)
    longest = x["detectable"][-1]
    test = (
        f"<p>The catch is traffic. With the number of visitors this site gets, a {longest['days']}-day test "
        f"could only reliably pick up a lift of about {pct(longest['rel_mde'], 0)} or more. Proving a 10% "
        f"improvement would need {num(row10['users_per_arm'])} people in each group, roughly "
        f"{days(row10['days'])}. So whatever gets tested should be a real change to the page, not a small "
        f"tweak.</p>"
    )
    if x["device_specific"]:
        opp = next(o for o in res["opportunity"] if o["step"] == x["target_step"])
        return (
            f"<p>Phones are where this store loses sales. Of mobile visits that {reach(prev)}, "
            f"{pct(opp['mobile_rate'])} go on to {PROSE[opp['step']]}; on desktop it's {pct(opp['desktop_rate'])}. "
            f"If phones did as well as desktops at that one step, that would be about "
            f"{num(opp['extra_purchases'])} more orders over the period, around {money(opp['extra_revenue_usd'])}. "
            f"I'd treat that as a ceiling, since some people browse on their phone and buy later on a laptop.</p>"
            + area_line(res) + test
        )
    leak = res["leak"]
    after = ordered[idx + 1:]
    max_gap = max(abs(o["gap_pts"]) for o in res["opportunity"])
    tail = ""
    if after:
        bits = [f"{pct(s['step_rate'], 0)} of those buy" if s["step"] == "purchase"
                else f"{pct(s['step_rate'], 0)} get to {PROSE[s['step']]}" for s in after]
        tail = f" Once someone does start {PROSE[leak['step']]}, most of them finish: {join_and(bits)}."
    return (
        f"<p>Most people who look at products never start checkout. Only {pct(leak['step_rate'])} of visits "
        f"that {reach(prev)} go on to {PROSE[leak['step']]}, and that's the biggest drop in the whole "
        f"purchase path.{tail}</p>"
        f"<p>It isn't a mobile problem. Phones and desktops are within {max_gap * 100:.1f} points of each other "
        f"at every step, and none of the differences is statistically significant.</p>"
        + area_line(res) + test
    )


def render(res: dict) -> str:
    synthetic = res["source"] != "bigquery"
    h, a, tree, x = res["headline"], res["audit"], res["metric_tree"], res["experiment"]
    s = a["summary"]
    checks = {c["name"]: c for c in a["checks"]}

    def warned(name: str) -> bool:
        return checks.get(name, {}).get("severity") == "warn"

    def facts(name: str) -> dict:
        return checks.get(name, {}).get("facts") or {}

    parts = ["<title>Where the Google Merchandise Store loses its shoppers</title>", f"<style>{CSS}</style>", "<main>"]
    if synthetic:
        parts.append('<p class="stamp">This page was built from generated test data, not the real store. '
                     "None of these numbers mean anything yet.</p>")
    parts.append("<h1>Where the Google Merchandise Store loses its shoppers</h1>")
    parts.append(f'<p class="byline">Ankit Singathia &middot; GA4 data, {day(s["start"], True)} to '
                 f'{day(s["end"], True)}</p>')
    parts.append(
        f"<p>I looked at three months of events from Google's online merch store, using the public sample of its "
        f"Google Analytics 4 export. That's {num(s['events'])} events from {num(h['users'])} people over "
        f"{num(h['sessions'])} visits, ending in {num(h['transactions'])} orders worth {money(h['revenue_usd'])}. "
        f"About {pct(h['conversion'], 1)} of visits ended in an order, and the average order was "
        f"{money(h['aov']) if h['aov'] else 'n/a'}.</p>"
    )

    parts.append("<h2>The short version</h2>")
    parts.append(short_version(res))

    # ---- data trust ------------------------------------------------------
    parts.append("<h2>Before trusting any of it</h2>")
    problems = []
    if warned("add_to_cart_coverage"):
        f = facts("add_to_cart_coverage")
        if f.get("changed") and f.get("first_tracked_week"):
            problems.append(
                f"Add-to-cart wasn't tracked at first. It barely appears until the week of "
                f"{day(f['first_tracked_week'])}, and even after that it shows up in at most "
                f"{f['max_weekly']:.0%} of checkout visits. You can't check out without a cart, so this is "
                "missing tracking rather than missing shoppers, and I left it out of the funnel.")
        else:
            problems.append(
                f"Add-to-cart shows up in only {checks['add_to_cart_coverage']['value']:.0%} of checkout visits. "
                "You can't check out without a cart, so the tracking is incomplete, and I left the step out of "
                "the funnel.")
    if warned("checkout_shipping_simultaneous"):
        f = facts("checkout_shipping_simultaneous")
        problems.append(
            f"The shipping-details event fires at the same moment as checkout. In {num(f['ship_first'])} of "
            f"{num(f['both'])} visits it's even logged a fraction of a second earlier. Put in strict order, the "
            "funnel was dropping real buyers for no reason, so I took this step out as well.")
    first_bad = facts("zero_revenue_purchases").get("first_bad_day")
    if warned("zero_revenue_purchases") and first_bad:
        last_good = date.fromisoformat(first_bad) - timedelta(days=1)
        problems.append(
            f"Revenue stops being recorded properly at the very end. From {day(first_bad)}, most orders come "
            f"through at $0. Order counts are still fine, but I don't use revenue after {day(last_good)}.")
    if problems:
        n = len(problems)
        parts.append("<p>Google warns that this sample isn't fully consistent, so I checked the data before "
                     f"building anything on it. Most of it held up, but {WORDS.get(n, n)} "
                     f"thing{'s were' if n > 1 else ' was'} broken:</p>")
        parts.append("<ol>" + "".join(f"<li>{p}</li>" for p in problems) + "</ol>")
    else:
        parts.append("<p>I checked the data before building anything on it, and nothing in it looked broken.</p>")
    dup = checks.get("duplicate_purchase_rows", {}).get("value", 0)
    no_id = checks.get("not_set_transaction_ids", {}).get("value", 0)
    if dup:
        parts.append(f"<p>I also removed {num(dup)} purchase records that had been sent twice. {num(no_id)} "
                     "purchase records have no order ID, so I matched duplicates on the visit and the amount "
                     "instead.</p>")
    audit_table = table(["", "Check", "Measured", "What it would break"],
                        [[c["severity"].upper(), c["name"], c["detail"], c["consequence"]] for c in a["checks"]],
                        numeric_from=9).replace("<td>WARN</td>", '<td class="sev-warn">WARN</td>') \
        .replace("<td>FAIL</td>", '<td class="sev-fail">FAIL</td>') \
        .replace("<td>INFO</td>", '<td class="sev-info">ok</td>')
    parts.append(fold(f"All {len(a['checks'])} checks the build runs", audit_table))

    # ---- revenue ---------------------------------------------------------
    parts.append("<h2>Holiday revenue</h2>")
    pc = tree["peak_pct_change"]
    size = f"{1 + pc:.1f} times" if pc >= 0.5 else f"{pct(pc, 0)} above"
    bf = "" if tree["peak_week"] == BLACK_FRIDAY_WEEK else ", not Black Friday week"
    shares = tree["peak_share"]
    gains = sorted(((c, v) for c, v in shares.items() if v > 0), key=lambda cv: -cv[1])
    if len(gains) >= 2 and all(0.35 <= v <= 0.65 for _, v in gains[:2]):
        split = f" Roughly half of that came from {GAIN[gains[0][0]]} and half from {GAIN[gains[1][0]]}."
    elif gains:
        split = f" Most of it came from {GAIN[gains[0][0]]}."
    else:
        split = ""
    flat_aov = " Order size hardly changed." if abs(shares.get("aov", 1)) < 0.1 else ""
    parts.append(f"<p>The busiest week was the one starting {day(tree['peak_week'])}{bf}. Revenue that week was "
                 f"{size} the level of early November.{split}{flat_aov}</p>")
    low = min(tree["weeks"], key=lambda w: w["log_total"])
    if low["log_total"] < 0:
        worst = min(low["log_contrib"], key=low["log_contrib"].get)
        parts.append(f"<p>The quietest week started {day(low['week_start'])}, at {pct(1 + low['pct_change'], 0)} of "
                     f"the early-November level, mostly because of {LOSS[worst]}.</p>")
    left_out = (" The last week of January is left out because of the revenue problem above."
                if first_bad and warned("zero_revenue_purchases") else "")
    parts.append("<p class=small>How I split it: revenue = visitors &times; visits per visitor &times; share of "
                 "visits that buy &times; order size. That's an exact identity, so on a log scale the four "
                 "changes add up to the total. The baseline is the average of the full weeks before Black Friday "
                 f"week ({join_and([day(w) for w in tree['baseline_weeks']])}).{left_out}</p>")
    parts.append(f'<figure><img alt="Weekly revenue change split into visitors, visits per visitor, conversion '
                 f'and order size" src="{chart_metric_tree(res)}"><figcaption>Each bar is one week, split into '
                 "the four parts; the line is the total change.</figcaption></figure>")
    parts.append(fold("Week-by-week numbers", table(
        ["Week", "Revenue", "Users", "Conv.", "AOV"] + [f"Δ {COMP[c]}" for c in COMP] + ["Δ total"],
        [[w["week_start"], money(w["revenue_usd"]), num(w["users"]), pct(w["conversion"], 2), money(w["aov"])]
         + [f"{w['log_contrib'][c] * 100:+.1f}" for c in COMP] + [f"{w['log_total'] * 100:+.1f}"]
         for w in tree["weeks"]])))

    # ---- funnel ----------------------------------------------------------
    ordered, opened = res["funnel"]["ordered"], res["funnel"]["open"]
    route = f"from {PROSE[ordered[0]['step']]} to " + ", to ".join(PROSE[o["step"]] for o in ordered[1:])
    dropped = [name for name, key in (("add-to-cart", "add_to_cart_coverage"),
                                      ("shipping details", "checkout_shipping_simultaneous")) if warned(key)]
    left = ""
    if dropped:
        left = f" {join_and(dropped).capitalize()} {'are' if len(dropped) > 1 else 'is'} left out, for the reasons above."
    parts.append("<h2>The purchase path</h2>")
    parts.append(f"<p>The funnel goes {route}. A visit only counts at a step if it got there after the step "
                 f"before; the looser count next to it accepts the events in any order.{left}</p>")
    parts.append(table(["Step", "Visits", "Share of previous step", "Looser count", "Share of all visits"],
                       [[STEP[o["step"]], num(o["sessions"]), pct(o["step_rate"]), pct(p["step_rate"]),
                         pct(o["from_start"], 2)] for o, p in zip(ordered, opened)]))
    parts.append("<h3>Phones versus desktops</h3>")
    sig = [o for o in res["opportunity"] if o["significant"]]
    max_gap = max(abs(o["gap_pts"]) for o in res["opportunity"])
    if sig:
        o = sig[0]
        parts.append(f"<p>Phones fall behind at {PROSE[o['step']]}: {pct(o['mobile_rate'])} of mobile visits make "
                     f"it, against {pct(o['desktop_rate'])} on desktop."
                     + (" It's the only step where the gap is statistically significant." if len(sig) == 1 else "")
                     + "</p>")
    else:
        parts.append(f"<p>I went in expecting mobile to do worse. It doesn't: at every step phones and desktops "
                     f"are within {max_gap * 100:.1f} points of each other, and none of the differences is "
                     "significant.</p>")
    parts.append(f'<figure><img alt="Share of visits reaching each step, phones and desktops" '
                 f'src="{chart_funnel_by_device(res)}"><figcaption>Share of visits at each step that make it to '
                 "the next, phones and desktops side by side.</figcaption></figure>")
    parts.append("<p class=small>I sized each step by comparing phones with desktops rather than asking what a 10% "
                 "improvement would be worth. When every step multiplies the one before, a 10% gain anywhere gives "
                 "exactly 10% more orders, so that question can't tell you where to look.</p>")
    parts.append(fold("Device gap at each step", table(
        ["Step", "Mobile", "Desktop", "Gap", "p-value", "Extra orders", "Extra revenue"],
        [[STEP[o["step"]], pct(o["mobile_rate"]), pct(o["desktop_rate"]), f"{o['gap_pts'] * 100:+.1f} pts",
          f"{o['p_value']:.2g}", num(o["extra_purchases"]), money(o["extra_revenue_usd"])]
         for o in res["opportunity"]])))

    # ---- store sections --------------------------------------------------
    ar = res.get("areas") or {}
    if ar.get("rows"):
        parts.append("<h3>Where in the store people drop off</h3>")
        below = sorted((r for r in ar["rows"] if r["clearly_below"]), key=lambda r: r["checkout_rate"])
        text = ("<p>I grouped visits by the part of the store where they first looked at products, so each visit "
                f"counts once. A typical section sends {pct(ar['median'])} of its visits on to checkout.")
        if below:
            nb = len(below)
            names = join_and([f"{esc(r['label'])} ({pct(r['checkout_rate'])})" for r in below])
            text += (f" {WORDS.get(nb, str(nb)).capitalize()} section{'s are' if nb > 1 else ' is'} well below "
                     f"that: {names}. If {'they' if nb > 1 else 'it'} matched the typical section, that would be "
                     f"roughly {num(ar['extra_orders'])} more orders over the three months, about "
                     f"{about_money(ar['extra_revenue_usd'])}. That's a ceiling, because people often browse small "
                     "add-ons without meaning to buy, but it's a specific place to start. I'd look at what's "
                     "different about those pages: stock, prices, and whether adding to cart works the same way "
                     "there.")
        else:
            text += " No section is clearly below that."
        parts.append(text + "</p>")
        for r in ar["rows"]:
            if r["broken_checkout"]:
                parts.append(f"<p>{esc(r['label'])} looks broken rather than weak. Its visitors reach checkout "
                             f"{pct(r['checkout_rate'])} of the time, but only {pct(r['finish_rate'])} of those "
                             f"checkouts end in an order, against {pct(ar['site_finish_rate'])} across the site. "
                             "I'd check that checkout before anything else.</p>")
        parts.append(f'<figure><img alt="Checkout rate by store section" src="{chart_areas(res)}"><figcaption>'
                     f"Sections with at least {num(ar['min_sessions'])} visits; the vertical line is the typical "
                     "section.</figcaption></figure>")
        parts.append(fold("Numbers by section", table(
            ["Section", "Visits", "Reach checkout", "95% range", "Checkouts that finish", "Order value",
             "Extra orders", "Extra revenue"],
            [[r["label"], num(r["sessions"]), pct(r["checkout_rate"]),
              f"{pct(r['checkout_ci'][0])} – {pct(r['checkout_ci'][1])}", pct(r["finish_rate"]),
              money(r["order_value"]) if r["order_value"] else "n/a", num(r["extra_orders"]),
              money(r["extra_revenue_usd"])] for r in ar["rows"]])))

    # ---- retention -------------------------------------------------------
    r, w = res["retention"], res["retention"]["weighted"]
    low_ret = w.get("week_1", 1.0) < 0.10
    parts.append(f"<h2>{'Most new visitors never come back' if low_ret else 'Returning visitors'}</h2>")
    if "week_1" in w:
        parts.append(
            f"<p>Of people on their first ever visit, {pct(w['week_1'])} came back the following week"
            + (f" and {pct(w['week_4'])} four weeks later" if "week_4" in w else "") + "."
            + (" That's low, though maybe not surprising for a merch store that a lot of people visit once, for "
               "a gift or a conference shirt. It does mean most sales have to happen on the first visit."
               if low_ret else "") + "</p>")
    parts.append("<p class=small>I only counted someone as new if their first visit in the data was their first "
                 "visit ever, and I left out weeks the data doesn't fully cover instead of counting them as "
                 "zero.</p>")
    parts.append(f'<figure><img alt="Weekly new-visitor retention" src="{chart_retention(res)}">'
                 "<figcaption>Each row is the group of people who first visited that week; darker means more of "
                 "them came back.</figcaption></figure>")
    parts.append(fold("Retention by cohort", table(
        ["Cohort", "Users"] + [f"W{k}" for k in r["offsets"][1:9]],
        [[c, num(r["cohort_users"][c])] + [pct(v) if v is not None else "" for v in row[1:9]]
         for c, row in zip(r["cohorts"], r["matrix"])])))

    # ---- channels --------------------------------------------------------
    ch = res["channels"]
    parts.append("<h2>Where buyers come from</h2>")
    named = [c for c in ch if c["sessions"] >= CHART_MIN_SESSIONS
             and c["channel"] not in ("Unknown", "Obfuscated", "Other")]
    if len(named) >= 2:
        best = max(named, key=lambda c: c["conversion"])
        worst = min(named, key=lambda c: c["conversion"])
        direct = next((c for c in named if c["channel"] == "Direct"), None)
        below = (f", even below people who typed the address in directly ({pct(direct['conversion'], 1)})"
                 if direct and worst is not direct and worst["conversion"] < direct["conversion"] else "")
        text = (f"<p>{esc(best['channel'])} traffic converts best, with {pct(best['conversion'], 1)} of visits "
                f"ending in an order. {esc(worst['channel'])} is the weakest at {pct(worst['conversion'], 1)}{below}.")
        for c in ch:
            if c["sessions"] < CHART_MIN_SESSIONS and c["conversion"] > best["conversion"]:
                text += (f" {esc(c['channel'])} looks even better ({pct(c['conversion'], 1)}), but that's from only "
                         f"{num(c['sessions'])} visits, so I wouldn't lean on it.")
        parts.append(text + "</p>")
    parts.append("<p class=small>&ldquo;Obfuscated&rdquo; is traffic Google hid in this sample, and "
                 "&ldquo;Unknown&rdquo; is a return visit that didn't carry its own source. I kept both in view "
                 "rather than guessing where they came from.</p>")
    small = [c["channel"] for c in ch if c["sessions"] < CHART_MIN_SESSIONS]
    caption = (f" Channels with fewer than {num(CHART_MIN_SESSIONS)} visits ({esc(join_and(small))}) are only in "
               "the table, because their ranges are too wide to share the chart." if small else "")
    parts.append(f'<figure><img alt="Conversion by channel with 95% ranges" src="{chart_channels(res)}">'
                 f"<figcaption>Dots are conversion rates; lines show the 95% range.{caption}</figcaption></figure>")
    parts.append(fold("Channel numbers", table(
        ["Channel", "Visits", "Share", "Engaged", "Conversion", "95% range", "Revenue / visit"],
        [[c["channel"], num(c["sessions"]), pct(c["share"]), pct(c["engaged_rate"]), pct(c["conversion"], 2),
          f"{pct(c['conversion_ci'][0], 2)} – {pct(c['conversion_ci'][1], 2)}", f"${c['revenue_per_session']:.2f}"]
         for c in ch])))

    # ---- experiment ------------------------------------------------------
    aa, cu = x["aa"], x["cuped"]
    longest = x["detectable"][-1]
    who = "users" if x["population"] == "all users" else x["population"]
    parts.append("<h2>If I were to test a fix</h2>")
    parts.append("<p>There's no A/B test in this data, so I haven't invented one. What I can do is work out what a "
                 "real test would need, using the store's own numbers.</p>")
    parts.append(f"<p>I'd measure the share of visits that end in an order, and split by person so the same person "
                 f"always sees the same version. In the {longest['days']} days after the holidays there were "
                 f"{num(x['window_users'])} {esc(who)}, {pct(x['baseline_rate'], 2)} of visits converted, and people "
                 f"averaged {x['sessions_per_user']:.1f} visits each.</p>")
    reach = [f"{pct(d['rel_mde'], 0)} after {WEEKS.get(d['days'], str(d['days']) + ' days')}" for d in x["detectable"]]
    parts.append(f"<p>With that traffic, the smallest lift a test could reliably catch is about {join_and(reach)}.</p>")
    parts.append(fold("Sample sizes for different lifts", table(
        ["Lift to detect", "Users per group", "Time to fill both groups", "Visits needed if treated as independent",
         "Design effect"],
        [[pct(g["rel_mde"], 0), num(g["users_per_arm"]), days(g["days"]), num(g["naive_sessions_per_arm"]),
          f"{g['design_effect']:.2f}×"] for g in x["grid"]])
        + "<p class=small>Two-sided test at 5% significance with 80% power. A design effect above 1 means "
          "treating visits as independent would leave the test too small.</p>"))

    parts.append("<h3>Checking the statistics on fake tests</h3>")
    lo = aa["fpr_naive_ci"][0]
    if lo > aa["alpha"]:
        verdict = " So the simpler test really does overstate results on this traffic."
    elif abs(aa["fpr_naive"] - aa["alpha"]) <= 0.015:
        verdict = (f" Here the simpler test gets away with it because people average only "
                   f"{x['sessions_per_user']:.1f} visits each. It breaks down when people visit more often, which is "
                   "why I'd still use the delta method.")
    else:
        verdict = ""
    parts.append(f"<p>To check the maths, I split real users into two random groups {num(aa['n_sims'])} times, "
                 f"with nothing different between the groups. A correct test should call about "
                 f"{pct(aa['alpha'], 0)} of those splits significant just by chance. The delta method, which treats "
                 f"each person rather than each visit as the unit, flagged {pct(aa['fpr_delta'])}. A simpler test "
                 f"that treats every visit as independent flagged {pct(aa['fpr_naive'])}.{verdict}</p>")
    parts.append(f'<figure><img alt="False-positive rate over fake tests" src="{chart_aa(res)}"><figcaption>How '
                 "often each method called a fake test significant; the lines show the 95% range.</figcaption>"
                 "</figure>")
    parts.append("<h3>Using past behaviour (CUPED)</h3>")
    vr = cu["conversions_all"]["variance_reduction"]
    parts.append(f"<p>CUPED cuts noise by adjusting for what each person did before the test. Only "
                 f"{pct(cu['share_with_history'])} of these users had visited before, so it would reduce the noise by "
                 f"about {pct(vr)}"
                 + (". That isn't worth the extra complexity here, though it would be for a test aimed at returning "
                    "customers.</p>" if vr < 0.05 else ", which is worth having.</p>"))
    parts.append("<p class=small>One more thing I'd check before reading any real result: that the two groups came "
                 "out the size they were meant to be (a chi-square test on the split; stop and investigate if p is "
                 "below 0.001).</p>")
    parts.append(f'<p class=small>The rules behind every number are in <a href="{REPO_URL}/blob/main/docs/'
                 f'DECISIONS.md">DECISIONS.md</a>, and the code is on <a href="{REPO_URL}">GitHub</a>.</p></main>')
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    res = json.loads(args.results.read_text())
    if res["source"] != "bigquery" and "docs" in args.out.resolve().parts:
        print("Refusing to write a synthetic readout under docs/.", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(res), encoding="utf-8")
    print(f"Readout written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
