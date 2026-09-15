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
    "view_item": "View item", "add_to_cart": "Add to cart", "begin_checkout": "Begin checkout",
    "add_shipping_info": "Shipping info", "add_payment_info": "Payment info", "purchase": "Purchase",
}
COMP = {"users": "Users", "sessions_per_user": "Sessions per user", "conversion": "Conversion", "aov": "Order value"}

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
    ax.set_xlabel("Share of sessions at the previous step that reach this one")
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
    ax.set_ylabel("Log-points vs baseline (about %)")
    ax.set_xlabel("Week starting (month-day)")
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
    ax.set_ylabel("Cohort (week starting)")
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, labelsize=8, colors=MUTED)
    cb.formatter = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0%}")
    cb.update_ticks()
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
    ax.set_xlabel("Session conversion rate, 95% interval")
    return _png(fig)


def chart_aa(res: dict) -> str:
    aa = res["experiment"]["aa"]
    labels = ["Naive\n(sessions independent)", "Delta method\n(users randomised)"]
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
    ax.set_ylabel("False-positive rate")
    return _png(fig)


# ---- page ------------------------------------------------------------------

CSS = """
:root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;
--warn:#8a5a00;--warnbg:#fff4d6;--fail:#a11f1f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:880px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px}h2{font-size:19px;margin:48px 0 8px;padding-top:18px;
border-top:1px solid var(--line)}h3{font-size:15px;margin:22px 0 6px}
p{margin:8px 0;max-width:68ch}.sub{color:var(--ink2);margin:0 0 20px}.note{color:var(--ink2);font-size:13.5px}
.stamp{background:#3a1d00;color:#fff;padding:12px 16px;border-radius:8px;margin:0 0 22px;font-weight:600}
.stamp span{font-weight:400;opacity:.85}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.tile b{display:block;font-size:22px;font-weight:600}.tile span{color:var(--ink2);font-size:12.5px}
.rec{background:var(--surface);border:1px solid var(--line);border-left:4px solid #2a78d6;border-radius:8px;
padding:14px 18px;margin:18px 0}
figure{margin:14px 0;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px}
figure img{width:100%;height:auto;display:block}figcaption{color:var(--ink2);font-size:13px;margin-top:6px}
.tw{overflow-x:auto;margin:10px 0}table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.sev-warn{color:var(--warn);font-weight:600}.sev-fail{color:var(--fail);font-weight:600}
.sev-info{color:var(--muted)}code{font-size:13px;background:#efeee9;padding:1px 5px;border-radius:4px}
"""


def recommendation(res: dict) -> str:
    x = res["experiment"]
    steps = [s["step"] for s in res["funnel"]["ordered"]]
    idx = steps.index(x["target_step"])
    prev = steps[idx - 1] if idx else None
    reached_from = f"that reach &ldquo;{STEP[prev]}&rdquo;" if prev else ""
    row10 = next(g for g in x["grid"] if abs(g["rel_mde"] - 0.10) < 1e-9)
    longest = x["detectable"][-1]
    test_line = (
        f"A {longest['days']}-day test on {esc(x['population'])} can detect a lift of "
        f"<b>{pct(longest['rel_mde'], 0)} or more</b> in session conversion; a 10% lift would need "
        f"{num(row10['users_per_arm'])} users per arm, about {days(row10['days'])}. So test a change big "
        f"enough to matter, not a button colour."
    )
    if x["device_specific"]:
        opp = next(o for o in res["opportunity"] if o["step"] == x["target_step"])
        return (
            f"<p><b>Fix mobile at &ldquo;{STEP[opp['step']]}&rdquo;.</b> Mobile sessions {reached_from} "
            f"go on to &ldquo;{STEP[opp['step']]}&rdquo; {pct(opp['mobile_rate'])} of the "
            f"time, against {pct(opp['desktop_rate'])} on desktop (p = {opp['p_value']:.1g}). If mobile matched "
            f"desktop at this one step, the window would have had about {num(opp['extra_purchases'])} more "
            f"purchases, roughly {money(opp['extra_revenue_usd'])}.</p>"
            f"<p>That figure is an <b>upper bound</b>. Part of the gap is probably intent (people browse on "
            f"phones and buy on laptops), not friction, and only an experiment separates the two. {test_line}</p>"
        )
    leak = res["leak"]
    max_gap = max(abs(o["gap_pts"]) for o in res["opportunity"])
    return (
        f"<p><b>The biggest leak is &ldquo;{STEP[prev]}&rdquo; to &ldquo;{STEP[leak['step']]}&rdquo;, and it "
        f"is the same on every device.</b> Only {pct(leak['step_rate'])} of sessions {reached_from} go on to "
        f"&ldquo;{STEP[leak['step']]}&rdquo;, the lowest rate of any step in the purchase path. Mobile and "
        f"desktop differ by at most {max_gap * 100:.1f} points at any step and no gap is statistically "
        f"significant, so this data does not support a device-specific fix.</p><p>{test_line}</p>"
    )


def render(res: dict) -> str:
    synthetic = res["source"] != "bigquery"
    h = res["headline"]
    a = res["audit"]
    tree = res["metric_tree"]
    x = res["experiment"]
    parts = ["<title>GA4 Merchandise Store — Product Readout</title>", f"<style>{CSS}</style>", "<main>"]
    if synthetic:
        parts.append('<div class="stamp">SYNTHETIC DATA — NOT FINDINGS. '
                     "<span>Built from generated events in the GA4 export format to test the pipeline. "
                     "No number on this page describes the real store.</span></div>")
    parts.append("<h1>Google Merchandise Store: where the funnel leaks, and how to test the fix</h1>")
    parts.append(f'<p class="sub">GA4 event export, {esc(a["summary"]["start"])} to {esc(a["summary"]["end"])} · '
                 f'{num(a["summary"]["events"])} events · source: {esc(res["source"])}</p>')
    tiles = [("Sessions", num(h["sessions"])), ("Users", num(h["users"])), ("Transactions", num(h["transactions"])),
             ("Revenue", money(h["revenue_usd"])), ("Conversion", pct(h["conversion"], 2)),
             ("Order value", money(h["aov"]) if h["aov"] else "n/a")]
    parts.append('<div class="tiles">' + "".join(f"<div class=tile><b>{v}</b><span>{k}</span></div>" for k, v in tiles)
                 + "</div>")
    parts.append(f'<div class="rec">{recommendation(res)}</div>')

    # 0. audit
    parts.append("<h2>0 · Can this data be trusted?</h2>")
    parts.append("<p>Google says this sample's internal consistency &ldquo;might be somewhat limited&rdquo;. "
                 "Every check below runs before anything is built, and a FAIL stops the build.</p>")
    parts.append(table(["", "Check", "Measured", "What it would break"],
                       [[c["severity"].upper(), c["name"], c["detail"], c["consequence"]] for c in a["checks"]],
                       numeric_from=9).replace("<td>WARN</td>", '<td class="sev-warn">WARN</td>')
                 .replace("<td>FAIL</td>", '<td class="sev-fail">FAIL</td>')
                 .replace("<td>INFO</td>", '<td class="sev-info">info</td>'))

    # 1. metric tree
    shares = tree["peak_share"]
    lead = max(shares, key=lambda c: abs(shares[c])) if shares else None
    parts.append("<h2>1 · What moves revenue week to week</h2>")
    parts.append("<p>Revenue = users × sessions per user × conversion × order value. That identity is exact, so "
                 "the change in log revenue splits into four parts that add up. The baseline is the geometric mean "
                 f"of the full pre-holiday weeks ({', '.join(tree['baseline_weeks'])}).</p>")
    zero = next((c for c in a["checks"] if c["name"] == "zero_revenue_purchases"), None)
    if zero and "most purchases" in zero["detail"]:
        parts.append(f"<p><b>Revenue stops being trustworthy near the end.</b> {esc(zero['detail'])}. Weeks "
                     "that run past the last reliable day are left out of this split; conversion, which counts "
                     "purchases rather than dollars, is unaffected.</p>")
    if lead:
        parts.append(f"<p>The peak week, starting {tree['peak_week']}, ran {pct(tree['peak_pct_change'], 0)} above "
                     f"baseline. The largest part came from <b>{COMP[lead].lower()}</b> "
                     f"({pct(shares[lead], 0)} of the log change).</p>")
    parts.append(f'<figure><img alt="Weekly revenue change split into users, sessions per user, conversion and '
                 f'order value" src="{chart_metric_tree(res)}"><figcaption>Bars: each driver\'s contribution. '
                 f"Line: total change. Table below has every value.</figcaption></figure>")
    parts.append(table(["Week", "Revenue", "Users", "Conv.", "AOV"] + [f"Δ {COMP[c]}" for c in COMP] + ["Δ total"],
                       [[w["week_start"], money(w["revenue_usd"]), num(w["users"]), pct(w["conversion"], 2),
                         money(w["aov"])] + [f"{w['log_contrib'][c] * 100:+.1f}" for c in COMP]
                        + [f"{w['log_total'] * 100:+.1f}"] for w in tree["weeks"]]))

    # 2. funnel
    parts.append("<h2>2 · Where the funnel leaks</h2>")
    parts.append("<p>The <b>ordered</b> funnel only credits a step reached after the previous one; the "
                 "<b>open</b> funnel credits it if it happened at all. Where they differ, events arrived out of "
                 "order.</p>")
    checks = {c["name"]: c for c in a["checks"]}
    cart = checks.get("add_to_cart_coverage")
    if cart and cart["severity"] == "warn":
        parts.append(f"<p><b>Add to cart is not in the chain.</b> {esc(cart['detail'])}. Nobody checks out "
                     "without a cart, so this is tracking, not shoppers. A funnel through it would show a trend "
                     "the shoppers never made.</p>")
    ship = checks.get("checkout_shipping_simultaneous")
    if ship and ship["severity"] == "warn":
        parts.append(f"<p><b>Nor is shipping info.</b> {esc(ship['detail'])}. One click fires both events, in "
                     "random order, so as a step it measures nothing and an ordered funnel would drop real "
                     "buyers at random.</p>")
    rows = [[STEP[o["step"]], num(o["sessions"]), pct(o["step_rate"]), pct(p["step_rate"]), pct(o["from_start"], 2)]
            for o, p in zip(res["funnel"]["ordered"], res["funnel"]["open"])]
    parts.append(table(["Step", "Sessions (ordered)", "Step rate", "Step rate (open)", "Of all sessions"], rows))
    parts.append(f'<figure><img alt="Funnel step rates, desktop vs mobile" src="{chart_funnel_by_device(res)}">'
                 "<figcaption>Step rate by device. Labelled: the step the recommendation is about."
                 "</figcaption></figure>")
    parts.append("<h3>Sizing each step's mobile gap</h3>")
    parts.append("<p>Not &ldquo;what if step X improved 10%&rdquo;: in a multiplicative funnel a 10% lift at any "
                 "step gives exactly 10% more purchases, so that cannot rank steps. Instead: what if mobile matched "
                 "desktop at this step?</p>")
    parts.append(table(["Step", "Mobile", "Desktop", "Gap", "p-value", "Extra purchases", "Extra revenue"],
                       [[STEP[o["step"]], pct(o["mobile_rate"]), pct(o["desktop_rate"]), f"{o['gap_pts'] * 100:+.1f} pts",
                         f"{o['p_value']:.2g}", num(o["extra_purchases"]), money(o["extra_revenue_usd"])]
                        for o in res["opportunity"]]))

    # 3. retention
    r = res["retention"]
    wsum = r["weighted"]
    parts.append("<h2>3 · Do new users come back?</h2>")
    parts.append("<p>Only users whose first session in the window is their first session ever form a cohort; "
                 "someone first seen on session 5 is a returning customer from before the data starts. Weeks the "
                 "data does not fully cover are left blank, not counted as zero.</p>")
    if "week_1" in wsum:
        parts.append(f"<p>Across cohorts, {pct(wsum['week_1'])} of new users return in week 1"
                     + (f" and {pct(wsum['week_4'])} in week 4" if "week_4" in wsum else "") + ".</p>")
    parts.append(f'<figure><img alt="Weekly new-user retention heatmap" src="{chart_retention(res)}">'
                 "<figcaption>Share of each cohort active k weeks later (week 0 is 100% and omitted).</figcaption>"
                 "</figure>")
    parts.append(table(["Cohort", "Users"] + [f"W{k}" for k in r["offsets"][1:9]],
                       [[c, num(r["cohort_users"][c])] + [pct(v) if v is not None else "" for v in row[1:9]]
                        for c, row in zip(r["cohorts"], r["matrix"])]))

    # 4. channels
    parts.append("<h2>4 · Which channels bring buyers</h2>")
    parts.append("<p>&ldquo;Obfuscated&rdquo; is the sample's own <code>&lt;Other&gt;</code> and "
                 "<code>(data deleted)</code>, kept as a bucket rather than guessed at. Overlapping intervals "
                 "mean the data cannot rank those channels. &ldquo;Unknown&rdquo; is a returning visit that "
                 "carries no source of its own; the user's first-touch source is not used as a stand-in "
                 "(DECISIONS D-07).</p>")
    small = [c["channel"] for c in res["channels"] if c["sessions"] < CHART_MIN_SESSIONS]
    caption = (f"<figcaption>Channels under {num(CHART_MIN_SESSIONS)} sessions ({esc(', '.join(small))}) are "
               "in the table only: their intervals are too wide to share an axis.</figcaption>") if small else ""
    parts.append(f'<figure><img alt="Session conversion by channel with 95% intervals" src="{chart_channels(res)}">'
                 f"{caption}</figure>")
    parts.append(table(["Channel", "Sessions", "Share", "Engaged", "Conversion", "95% interval", "Revenue / session"],
                       [[c["channel"], num(c["sessions"]), pct(c["share"]), pct(c["engaged_rate"]),
                         pct(c["conversion"], 2), f"{pct(c['conversion_ci'][0], 2)} – {pct(c['conversion_ci'][1], 2)}",
                         f"${c['revenue_per_session']:.2f}"] for c in res["channels"]]))

    # 5. experiment
    aa, cu = x["aa"], x["cuped"]
    parts.append("<h2>5 · Designing the test</h2>")
    parts.append("<p><b>This dataset contains no experiment, and none is simulated as if it were real.</b> This "
                 "section answers what has to be settled before launch, using the real baselines above.</p>")
    parts.append(f"<p>Population: {esc(x['population'])} in the post-holiday window ({num(x['window_users'])} users). "
                 f"Metric: {esc(x['metric'])}. Baseline {pct(x['baseline_rate'], 2)}, "
                 f"{x['sessions_per_user']:.2f} sessions per user.</p>")
    parts.append(table(["Relative lift to detect", "Users per arm", "Time to enrol both arms",
                        "Naive sessions per arm", "Design effect"],
                       [[pct(g["rel_mde"], 0), num(g["users_per_arm"]), days(g["days"]),
                         num(g["naive_sessions_per_arm"]), f"{g['design_effect']:.2f}×"] for g in x["grid"]]))
    parts.append("<p class=note>α = 0.05 two-sided, power 0.80. Design effect above 1× means a calculation that "
                 "treats sessions as independent would under-power the test.</p>")
    parts.append("<p>Turned around, the question a team actually asks: " + "; ".join(
        f"a {d['days']}-day test ({num(d['users_per_arm'])} users per arm) can detect a lift of "
        f"<b>{pct(d['rel_mde'], 0)}</b> or more" for d in x["detectable"]) + ".</p>")
    parts.append("<h3>Would the analysis cry wolf? An A/A test on real users</h3>")
    parts.append(f"<p>Real users were split at random {num(aa['n_sims'])} times with no treatment. A correct test "
                 f"calls {pct(aa['alpha'], 0)} of those splits significant. The delta method did so "
                 f"{pct(aa['fpr_delta'])} of the time; the naive session-level test {pct(aa['fpr_naive'])}.</p>")
    parts.append(f'<figure><img alt="A/A false-positive rates" src="{chart_aa(res)}"><figcaption>Whiskers: 95% '
                 "interval over the simulations.</figcaption></figure>")
    parts.append("<h3>Would CUPED help here?</h3>")
    with_hist = cu["conversions_with_history"]
    parts.append(f"<p>CUPED uses each user's pre-period behaviour to cancel noise. Only "
                 f"{pct(cu['share_with_history'])} of users in the window have any pre-period history, so it cuts "
                 f"variance by {pct(cu['conversions_all']['variance_reduction'])} for conversions and "
                 f"{pct(cu['revenue_all']['variance_reduction'])} for revenue across all users"
                 + (f", and {pct(with_hist['variance_reduction'])} among users with history" if with_hist else "")
                 + ". Worth it for logged-in or returning-customer tests; not for a new-visitor checkout test.</p>")
    parts.append("<p class=note>Guardrail before reading any real result: a sample-ratio check on the arm split "
                 "(chi-square, stop if p &lt; 0.001).</p>")
    parts.append('<p class=note>Every rule behind these numbers is in <code>docs/DECISIONS.md</code>.</p></main>')
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
