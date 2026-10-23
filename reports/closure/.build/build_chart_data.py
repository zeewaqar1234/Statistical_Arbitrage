"""Build reports/closure/data/chart_data.json: the single source for every chart in the
memo and the deck.

- Strategy 1 (cross-exchange spot): figures from docs/BSDEX_Explainer_Guide.html
  (4-hour live campaign, 14 Oct 2026) and docs/engine-integrity.md.
- Strategy 2 (perpetual funding carry): computed from data/perp_funding.csv
  (public funding history, see data/meta.json). Net-yield range from docs/eurc_live_test.md.
- Strategy 3 (EURC depeg capture): computed from data/eurc_daily.csv; the ladder uses the
  same rule as scripts/eurc_live_test.py::ladder_backtest. Live-test figures from
  docs/eurc_live_test_results.md.
"""
import json
import sys
from pathlib import Path

import pandas as pd

DATA = Path(sys.argv[1])
AS_OF = pd.Timestamp("2026-10-22T23:59:59Z")  # decision date; same window as the repo docs

out = {"as_of": "2026-10-22"}

# ── Strategy 1 ──────────────────────────────────────────────────────────────
out["s1"] = {
    "by_size": {  # median tradeable gap after crossing both books, before fees (bps)
        "sizes": ["€1k", "€10k", "€100k", "€250k"],
        "btc_median": [-0.37, -0.58, -2.26, -4.99],
        "eth_median": [-0.52, -0.75, -4.10, -8.47],
        "btc_p99": [1.55, 1.35, -0.24, -2.44],
        "eth_p99": [1.57, 1.42, -1.12, -4.35],
    },
    "breakeven_bps": {"Retail (< $5M)": 47, "> $20M (default)": 17, "> $250M": 9, "> $1B": 7},
    "backtest_before_after_eur": {"before": 275.81, "after": -1547.98, "after_carry": -1739.76},
}

# ── Strategy 2 ──────────────────────────────────────────────────────────────
f = pd.read_csv(DATA / "perp_funding.csv")
f["ts"] = pd.to_datetime(f["ts"], utc=True, format="ISO8601")
f = f[f["ts"] <= AS_OF]
f["ann_pct"] = f["rate"] * f["periods_per_year"] * 100
s2 = {"rolling30": {}, "stats": {}}
for (venue, asset), g in f.groupby(["venue", "asset"]):
    daily = g.set_index("ts")["ann_pct"].resample("1D").mean().dropna()
    roll = daily.rolling(30, min_periods=30).mean().dropna()
    roll = roll[roll.index > AS_OF - pd.Timedelta(days=366)]
    key = f"{venue} {asset}"
    s2["rolling30"][key] = {"dates": [d.strftime("%Y-%m-%d") for d in roll.index],
                            "values": [round(v, 2) for v in roll.values]}
    last365 = g[g["ts"] > AS_OF - pd.Timedelta(days=365)]
    days = (last365["ts"].max() - last365["ts"].min()).days + 1
    r90 = daily.rolling(90, min_periods=90).mean().dropna()
    r90 = r90[r90.index > AS_OF - pd.Timedelta(days=366)]
    s2["stats"][key] = {
        "mean_ann_pct": round(last365["ann_pct"].mean(), 2),
        "window_days": int(days),
        "share_negative_pct": round((last365["rate"] < 0).mean() * 100, 1),
        "share_days_rolling90_above_7pct": round((r90 > 7).mean() * 100, 1) if len(r90) else None,
    }
s2["deposit_pct"] = 2.5
s2["needed_pct"] = 7.0  # docs/eurc_live_test.md: switch to carry only above ~7% sustained 90-day funding
s2["net_on_40k_eur_before_fx_hedge"] = [960, 1720]  # docs/eurc_live_test_results.md row 6
out["s2"] = s2

# ── Strategy 3 ──────────────────────────────────────────────────────────────
e = pd.read_csv(DATA / "eurc_daily.csv")
e["date"] = pd.to_datetime(e["date"])
win = e[(e["date"] > AS_OF.tz_localize(None) - pd.Timedelta(days=366)) & (e["date"] <= AS_OF.tz_localize(None))]
k = win[win["venue"] == "kraken"].sort_values("date")
LEVELS = [0.9990, 0.9975, 0.9950, 0.9925, 0.9900, 0.9800, 0.9700]
TARGET = 0.9995


def ladder(c, fee):
    lows, highs, closes, days = c["low"].tolist(), c["high"].tolist(), c["close"].tolist(), len(c)
    res = []
    for lvl in LEVELS:
        cycles, pnl, op = 0, 0.0, None
        for i in range(days):
            if op is None:
                if lows[i] < lvl:
                    op = i
            elif highs[i] > TARGET:
                cycles += 1
                pnl += (TARGET * (1 - fee) - lvl * (1 + fee)) / lvl * 1e4
                op = None
        mtm = ((closes[-1] - lvl) / lvl * 1e4) if op is not None else 0.0
        res.append({"level": lvl, "fills": cycles, "ann_pct": round((pnl + mtm) / 1e4 * 365 / days * 100, 2)})
    return res


out["s3"] = {
    "kraken_daily": {"dates": k["date"].dt.strftime("%Y-%m-%d").tolist(),
                     "low": k["low"].round(4).tolist(), "close": k["close"].round(4).tolist()},
    "kraken_days_below_09925": int((k["low"] < 0.9925).sum()),
    "kraken_min_low": float(k["low"].min()),
    "kraken_median_daily_volume": round(float(k["volume"].median())),
    "ladder_kraken_fee_020": ladder(k, 0.002),
    "live_test": {"mm_bitvavo_eur": -29, "mm_mid_eur": -2.48, "cross_venue_best_bps_10k": -39,
                  "deep_bid_one_event_eur": 12.2, "sleeve_eur_per_year": [100, 300]},
}

# ── Comparison on €40k for one year ──────────────────────────────────────────
out["compare_40k"] = [
    {"name": "Bank deposit (2.5%)", "low": 1000, "high": 1000, "kind": "hurdle"},
    {"name": "1 · Cross-exchange spot", "low": 0, "high": 0, "kind": "fail"},
    {"name": "2 · Perpetual funding carry", "low": 960, "high": 1720, "kind": "marginal"},
    {"name": "3 · EURC depeg capture", "low": 100, "high": 300, "kind": "small"},
]

(DATA / "chart_data.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(json.dumps({k: out["s2"]["stats"][k] for k in out["s2"]["stats"]}, indent=1))
print({k: v for k, v in out["s3"].items() if k not in ("kraken_daily",)})
