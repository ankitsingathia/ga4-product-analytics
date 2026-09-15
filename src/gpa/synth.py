"""Synthetic GA4 events in the exact flat schema the BigQuery extract writes.

    python -m gpa.synth --out data/raw_synth --users 60000

This exists so the pipeline and its tests run before, and without, a Google
account. Every quirk the audit hunts for is planted at a known rate, and the
realised counts are written to truth.json next to the data, so the tests can
demand exact recovery rather than "looks about right".

Nothing computed from this data is a finding. The readout built from it is
stamped SYNTHETIC and is never written to docs/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from gpa import schema

REPO = Path(__file__).resolve().parents[2]

# Conditional probability of reaching each step, given the previous one.
STEP_P = {
    "view_item": 0.55,
    "add_to_cart": 0.35,
    "begin_checkout": 0.50,
    "add_shipping_info": 0.75,
    "add_payment_info": 0.80,
    "purchase": 0.70,
}
# The generator still emits add_to_cart (a clean store would); the analysis
# funnel skips it, so truth is reported for schema.FUNNEL_STEPS only.
SYNTH_STEPS = tuple(STEP_P)
DEVICE_MIX = {"desktop": 0.57, "mobile": 0.40, "tablet": 0.03}
# The planted opportunity: mobile converts worse at the LAST step only. The
# analysis should find this step, and only this step, as the device gap.
DEVICE_PURCHASE_MULT = {"desktop": 1.0, "mobile": 0.70, "tablet": 0.90}
RETURNING_CART_MULT = 1.20
# Store sections: (share of sessions, multiplier on begin_checkout). The
# planted weak section is Accessories; the analysis should flag it, alone.
AREAS = {
    "Apparel": (0.45, 1.0),
    "Lifestyle": (0.25, 1.0),
    "Drinkware": (0.15, 1.0),
    "Accessories": (0.15, 0.35),
}
AREA_URL = "https://shop.googlemerchandisestore.com/Google+Redesign/"
PRE_EXISTING_SHARE = 0.15  # users whose history starts before the window
CHANNELS = [  # (source, medium, share of sessions)
    ("(direct)", "(none)", 0.30),
    ("google", "organic", 0.30),
    ("shop.googlemerchandisestore.com", "referral", 0.12),
    ("google", "cpc", 0.08),
    ("<Other>", "<Other>", 0.17),
    ("(data deleted)", "(data deleted)", 0.03),
]
QUIRKS = {
    "null_session_share": 0.02,  # of page_view/user_engagement events
    "not_set_txn_share": 0.30,  # of purchases
    "dup_purchase_share": 0.015,  # purchase hits re-sent 1s later
    "exact_dup_share": 0.005,  # page_view hits delivered twice
    "item_mismatch_share": 0.10,  # purchases whose items do not sum to revenue
}


def _day_profile(d: date) -> tuple[float, float]:
    """(traffic weight, add_to_cart multiplier) for one calendar day."""
    if date(2020, 11, 23) <= d <= date(2020, 11, 30):  # Black Friday to Cyber Monday
        return 1.8, 1.25
    if date(2020, 12, 1) <= d <= date(2020, 12, 20):
        return 1.3, 1.0
    if date(2020, 12, 24) <= d <= date(2020, 12, 26):
        return 0.6, 1.0
    if d.year == 2021:
        return 0.85, 1.0
    return 1.0, 1.0


def _within_group_index(counts: np.ndarray) -> np.ndarray:
    """[3, 2] -> [0, 1, 2, 0, 1]."""
    return np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)


def generate(n_users: int = 60_000, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    days = pd.date_range(schema.WINDOW_START, schema.WINDOW_END, freq="D")
    nd = len(days)
    profile = np.array([_day_profile(d.date()) for d in days])
    traffic, cart_mult = profile[:, 0], profile[:, 1]

    # ---- users ----------------------------------------------------------
    first_day = rng.choice(nd, size=n_users, p=traffic / traffic.sum())
    device = rng.choice(np.array(list(DEVICE_MIX)), n_users, p=list(DEVICE_MIX.values()))
    prior = np.where(rng.random(n_users) < PRE_EXISTING_SHARE, rng.integers(1, 6, n_users), 0)
    country = rng.choice(
        np.array(["United States", "India", "Canada", "United Kingdom", "(not set)"]),
        n_users, p=[0.55, 0.15, 0.12, 0.13, 0.05],
    )
    user_id = np.char.add(
        np.char.add((1_000_000_000 + np.arange(n_users) * 37).astype(str), "."),
        (1_604_000_000 + np.arange(n_users)).astype(str),
    )

    # ---- sessions -------------------------------------------------------
    n_sess = rng.geometric(0.65, n_users)
    uidx = np.repeat(np.arange(n_users), n_sess)
    grp_start = np.repeat(np.cumsum(n_sess) - n_sess, n_sess)
    k = _within_group_index(n_sess)
    # Time is continuous (in days) so a user's sessions are strictly ordered:
    # the first starts at a random time on its first day, each later one at
    # least 30 minutes after the previous. Drawing time-of-day independently
    # per session would let session 2 start before session 1.
    gap = 1 / 48 + rng.exponential(6.0, len(uidx))
    first_mask = k == 0
    gap[first_mask] = rng.random(int(first_mask.sum())) * 0.95
    cs = np.cumsum(gap)
    day_f = first_day[uidx] + (cs - cs[grp_start]) + gap[grp_start]
    # Sessions after the window are not observed. The 15-minute margin keeps a
    # session that starts late on the last day from spilling into February.
    keep = day_f < nd - 1 / 96
    uidx, k, day_f = uidx[keep], k[keep], day_f[keep]
    day = day_f.astype(int)
    n = len(uidx)

    start = days.values[0].astype("datetime64[s]") + np.round(day_f * 86_400).astype("timedelta64[s]")
    # GA4's session id is the session start in epoch seconds. +k keeps a
    # user's sessions distinct even if two start in the same second.
    ga_session_id = start.astype(np.int64) + k
    session_number = prior[uidx] + k + 1
    chan = rng.choice(len(CHANNELS), n, p=[c[2] for c in CHANNELS])
    ft_by_user = np.empty(n_users, dtype=int)
    ft_by_user[uidx[k == 0]] = chan[k == 0]
    ft = ft_by_user[uidx]
    dev = device[uidx]
    area_names = np.array(list(AREAS), dtype=object)
    area = rng.choice(len(AREAS), n, p=[v[0] for v in AREAS.values()])
    area_mult = np.array([v[1] for v in AREAS.values()])[area]

    # ---- funnel ---------------------------------------------------------
    steps = SYNTH_STEPS
    reached = np.zeros((n, len(steps)), dtype=bool)
    alive = np.ones(n, dtype=bool)
    purchase_mult = pd.Series(dev).map(DEVICE_PURCHASE_MULT).to_numpy()
    for j, step in enumerate(steps):
        p = np.full(n, STEP_P[step])
        if step == "add_to_cart":
            p = p * cart_mult[day] * np.where(session_number > 1, RETURNING_CART_MULT, 1.0)
        if step == "begin_checkout":
            p = p * area_mult
        if step == "purchase":
            p = p * purchase_mult
        alive &= rng.random(n) < np.clip(p, 0, 1)
        reached[:, j] = alive
    n_pages = 1 + rng.poisson(2.0, n) + reached.sum(axis=1)
    engaged = (n_pages >= 2) | reached[:, 0]

    # ---- events ---------------------------------------------------------
    idx_parts, name_parts, off_parts = [], [], []

    def add(idx: np.ndarray, name: str, offset_s: np.ndarray) -> None:
        idx_parts.append(idx)
        name_parts.append(np.full(len(idx), name, dtype=object))
        off_parts.append(np.asarray(offset_s, dtype=float))

    all_idx = np.arange(n)
    add(all_idx, "session_start", np.zeros(n))
    first = np.flatnonzero(session_number == 1)
    add(first, "first_visit", np.zeros(len(first)))
    pv = np.repeat(all_idx, n_pages)
    add(pv, "page_view", _within_group_index(n_pages) * 30.0 + 1)
    add(all_idx, "user_engagement", n_pages * 30.0 + 1)
    for j, step in enumerate(steps):
        idx = np.flatnonzero(reached[:, j])
        add(idx, step, n_pages[idx] * 30.0 + 20.0 * (j + 1))

    s = np.concatenate(idx_parts)
    name = np.concatenate(name_parts)
    off_us = (np.concatenate(off_parts) * 1e6).astype(np.int64).astype("timedelta64[us]")
    ts = start[s].astype("datetime64[us]") + off_us

    src = np.array([c[0] for c in CHANNELS], dtype=object)
    med = np.array([c[1] for c in CHANNELS], dtype=object)
    camp = pd.Series(med).map({"(none)": "(direct)", "organic": "(organic)",
                               "referral": "(referral)", "cpc": "holiday_sale"}).fillna("<Other>").to_numpy()
    carries_source = np.isin(name, ["session_start", "page_view"])

    os_by_dev = {"desktop": ["Windows", "Macintosh", "<Other>"], "mobile": ["iOS", "Android"], "tablet": ["iOS", "Android"]}
    session_os = np.empty(n, dtype=object)
    for d, opts in os_by_dev.items():
        mask = dev == d
        session_os[mask] = rng.choice(np.array(opts, dtype=object), int(mask.sum()))
    session_browser = rng.choice(np.array(["Chrome", "Safari", "<Other>"], dtype=object), n, p=[0.6, 0.3, 0.1])

    ev = pd.DataFrame({
        "event_ts": ts,
        "event_name": name,
        "user_pseudo_id": user_id[uidx][s],
        "ga_session_id": pd.array(ga_session_id[s], dtype="Int64"),
        "ga_session_number": pd.array(session_number[s], dtype="Int64"),
        "engagement_time_msec": pd.array(
            np.where(name == "user_engagement", rng.integers(1_000, 300_000, len(s)), 0), dtype="Int64"),
        "session_engaged": np.where(engaged[s], "1", "0"),
        "page_location": "https://shop.googlemerchandisestore.com/",
        "session_source": np.where(carries_source, src[chan[s]], None),
        "session_medium": np.where(carries_source, med[chan[s]], None),
        "session_campaign": np.where(carries_source, camp[chan[s]], None),
        "ft_source": src[ft[s]],
        "ft_medium": med[ft[s]],
        "ft_name": camp[ft[s]],
        "device_category": dev[s],
        "operating_system": session_os[s],
        "browser": session_browser[s],
        "country": country[uidx][s],
    })
    ev.loc[ev["event_name"] != "user_engagement", "engagement_time_msec"] = pd.NA
    ev["sidx"] = s
    view_rows = ev["event_name"].to_numpy() == "view_item"
    ev.loc[view_rows, "page_location"] = AREA_URL + area_names[area[s[view_rows]]]

    # ---- purchases ------------------------------------------------------
    is_p = (ev["event_name"] == "purchase").to_numpy()
    n_p = int(is_p.sum())
    revenue = np.round(rng.lognormal(np.log(70), 0.8, n_p), 2)
    txn = np.where(rng.random(n_p) < QUIRKS["not_set_txn_share"], "(not set)",
                   np.char.add("T", ev.loc[is_p, "sidx"].to_numpy().astype(str)))
    for col in ("transaction_id", "purchase_revenue_usd", "shipping_usd", "tax_usd", "total_item_quantity"):
        ev[col] = None
    ev.loc[is_p, "transaction_id"] = txn
    ev.loc[is_p, "purchase_revenue_usd"] = revenue
    ev.loc[is_p, "shipping_usd"] = np.round(revenue * 0.08, 2)
    ev.loc[is_p, "tax_usd"] = np.round(revenue * 0.07, 2)
    ev.loc[is_p, "total_item_quantity"] = 1 + rng.poisson(1.5, n_p)

    # ---- items ----------------------------------------------------------
    item_rows = []
    purchases = ev.loc[is_p, ["event_ts", "user_pseudo_id", "ga_session_id", "transaction_id", "purchase_revenue_usd"]]
    mismatch = rng.random(n_p) < QUIRKS["item_mismatch_share"]
    for (row, bad) in zip(purchases.itertuples(index=False), mismatch):
        lines = 1 + int(rng.random() < 0.4) + int(rng.random() < 0.2)
        w = rng.dirichlet(np.ones(lines))
        parts = np.round(row.purchase_revenue_usd * w, 2)
        parts[-1] = round(row.purchase_revenue_usd - parts[:-1].sum(), 2)
        if bad:
            parts = np.round(parts * 0.8, 2)
        for li, amount in enumerate(parts):
            item_rows.append((row.event_ts, "purchase", row.user_pseudo_id, row.ga_session_id,
                              row.transaction_id, f"SKU{li:03d}", "Google Tee", "Apparel", float(amount), 1, float(amount)))
    views = ev.loc[ev["event_name"] == "view_item", ["event_ts", "user_pseudo_id", "ga_session_id"]]
    for row in views.itertuples(index=False):
        item_rows.append((row.event_ts, "view_item", row.user_pseudo_id, row.ga_session_id,
                          None, "SKU000", "Google Tee", "Apparel", 20.0, 1, None))
    items = pd.DataFrame(item_rows, columns=["event_ts", "event_name", "user_pseudo_id", "ga_session_id",
                                             "transaction_id", "item_id", "item_name", "item_category",
                                             "price_usd", "quantity", "item_revenue_usd"])

    # ---- quirks, applied after the clean data exists ---------------------
    nullable = ev["event_name"].isin(["page_view", "user_engagement"]).to_numpy()
    kill = nullable & (rng.random(len(ev)) < QUIRKS["null_session_share"])
    ev.loc[kill, "ga_session_id"] = pd.NA

    p_rows = ev.index[is_p]
    dup_p = ev.loc[p_rows[rng.random(len(p_rows)) < QUIRKS["dup_purchase_share"]]].copy()
    dup_p["event_ts"] = dup_p["event_ts"] + pd.Timedelta(seconds=1)
    pv_rows = ev.index[(ev["event_name"] == "page_view").to_numpy()]
    dup_x = ev.loc[pv_rows[rng.random(len(pv_rows)) < QUIRKS["exact_dup_share"]]].copy()
    ev = pd.concat([ev, dup_p, dup_x], ignore_index=True).sort_values(["event_ts", "sidx"], kind="stable")

    ev["event_date"] = ev["event_ts"].dt.date
    items["event_date"] = items["event_ts"].dt.date

    # ---- realised truth -------------------------------------------------
    truth = {
        "n_users": int(n_users),
        "n_sessions": int(n),
        "n_events": int(len(ev)),
        "reached": {st: int(reached[:, steps.index(st)].sum()) for st in schema.FUNNEL_STEPS},
        "sessions_by_device": {d: int((dev == d).sum()) for d in DEVICE_MIX},
        "reached_by_device": {
            d: {st: int(reached[dev == d, steps.index(st)].sum()) for st in schema.FUNNEL_STEPS}
            for d in DEVICE_MIX
        },
        "n_purchase_rows": int(ev["event_name"].eq("purchase").sum()),
        "n_unique_purchases": n_p,
        "n_duplicate_purchase_rows": int(len(dup_p)),
        "n_not_set_txn_rows": int((ev["transaction_id"] == "(not set)").sum()),
        "revenue_total": round(float(revenue.sum()), 2),
        "n_null_session_events": int(ev["ga_session_id"].isna().sum()),
        "n_exact_duplicate_rows": int(len(dup_x)),
        "n_item_revenue_mismatch": int(mismatch.sum()),
        "n_purchases_without_items": int(len(dup_p)),
        "n_left_censored_users": int((prior > 0).sum()),
        "sessions_by_area": {
            name: int(reached[area == i, steps.index("view_item")].sum()) for i, name in enumerate(AREAS)
        },
        "planted": {
            "step_p": STEP_P,
            "device_purchase_mult": DEVICE_PURCHASE_MULT,
            "returning_cart_mult": RETURNING_CART_MULT,
            "area_checkout_mult": {k: v[1] for k, v in AREAS.items()},
            "quirks": QUIRKS,
        },
    }
    return ev.drop(columns="sidx"), items, truth


def write(out: Path, n_users: int, seed: int) -> dict:
    ev, items, truth = generate(n_users, seed)
    for sub, df, sch in (("events", ev, schema.EVENTS), ("items", items, schema.ITEMS)):
        (out / sub).mkdir(parents=True, exist_ok=True)
        for old in (out / sub).glob("*.parquet"):
            old.unlink()
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(schema.conform(table, sch), out / sub / "part-0.parquet")
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    (out / "manifest.json").write_text(json.dumps({
        "source": "synthetic", "seed": seed, "users": n_users,
        "event_rows": truth["n_events"], "item_rows": int(len(items)),
    }, indent=2))
    return truth


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "raw_synth")
    ap.add_argument("--users", type=int, default=60_000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    truth = write(args.out, args.users, args.seed)
    print(f"Synthetic GA4 extract: {truth['n_events']:,} events, {truth['n_sessions']:,} sessions "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
