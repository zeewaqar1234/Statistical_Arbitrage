"""One-off measurement campaign for the BSDEX vs World engine, exported to Excel.

No orders are ever sent. Phases (each one is independent; a failure is logged
in the "Errors" sheet and the campaign continues):

  1. Environment   git commit, config snapshot, REST round-trip latency.
  2. Live          the real BSDEXStrategy paper engine runs for --hours while a
                   shadow sampler reads the same WebSocket books every
                   --sample-ms and measures executable spreads for several
                   order sizes, both directions, every fee tier, gap
                   persistence after a signal, maker edge and feed quality.
                   The engine also records 1-second quotes for phase 3.
  3. Quote replay  the recorded quotes replayed through run_quote_backtest for
                   every fee tier, plus a latency/threshold/window/cooldown sweep.
  4. Candles       --days of 1-minute candles (BTC, ETH) for every fee tier and
                   a threshold/window/cooldown sweep, both cost scenarios.
  5. Control pair  Bitstamp EUR vs Kraken EUR (no FX leg), last ~12 hours.
  6. Export        reports/campaign_<UTC>/campaign_<UTC>.xlsx (+ raw files).

Ctrl+C during the live phase stops it early and continues with the rest.

Example (from the repository root):
    venv/bin/python scripts/run_test_campaign.py --hours 8
"""
import argparse
import asyncio
import json
import logging
import math
import platform
import signal
import subprocess
import sys
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crypto_hft_tool import bsdex_historical_bt as hbt  # noqa: E402
from src.crypto_hft_tool import quote_data  # noqa: E402
from src.crypto_hft_tool.config import (  # noqa: E402
    BSDEX_DEFAULT_TIER_IDX, BSDEX_VOLUME_TIERS, BT_EXEC_COSTS, ECB_DFR,
    ENHANCED_SIGNAL_SETTINGS, FX_COST_BPS, LIVE_FILL_LATENCY_MS, MAX_FX_AGE_SEC,
    POOLS, STRATEGY_DEFAULTS,
)

MARKETS = {"btc-eur": ("btceur", "BTCUSDT"), "eth-eur": ("etheur", "ETHUSDT")}
TIERS = [
    {"idx": i, "label": t["label"], "a": t["bitstamp_taker"], "b": t["lmax_taker"],
     "be_bps": (t["bitstamp_taker"] + t["lmax_taker"]) * 1e4 + FX_COST_BPS}
    for i, t in enumerate(BSDEX_VOLUME_TIERS)
]
VERIFIED_TIER_IDX = 6                       # "> $250M", used in the 11 Oct verification
SWEEP_TIERS = [BSDEX_DEFAULT_TIER_IDX, VERIFIED_TIER_IDX]
LAGS_MS = [250, 500, 1000, 2000, 5000, 30000]
PING_URLS = {
    "bitstamp": "https://www.bitstamp.net/api/v2/ticker/btceur/",
    "binance": "https://api.binance.com/api/v3/ping",
    "kraken": "https://api.kraken.com/0/public/Time",
}

log = logging.getLogger("campaign")


def tier_name(idx):
    return f"{idx}: {TIERS[idx]['label']}"


# ---------------------------------------------------------------------------
# Shadow sampler: executable spreads straight from the engine's live books
# ---------------------------------------------------------------------------

def _levels(book, side, scale=1.0):
    prices = sorted(book[side], reverse=(side == "bids"))
    return [(float(p) * scale, float(book[side][p])) for p in prices]


def _vwap(levels, amount):
    left, cost = amount, 0.0
    for price, qty in levels:
        take = min(left, qty)
        cost += take * price
        left -= take
        if left <= 1e-12:
            return cost / amount
    return None


def _depth_within(levels, mid, bps):
    """EUR notional resting within `bps` of mid on one side."""
    return sum(p * q for p, q in levels if abs(p - mid) / mid * 1e4 <= bps)


def sample_books(bitstamp, binance, sizes, now):
    """One row per market. Binance levels are converted to EUR per side, as the
    engine does: bids / EURUSDT ask, asks / EURUSDT bid. Spreads are bps of the
    Bitstamp mid; sellA = sell Bitstamp & buy Binance, buyA = the reverse."""
    fxq = binance.get_quote("EURUSDT")
    rows = []
    for market, (ticker, symbol) in MARKETS.items():
        a, b, bq = bitstamp.get_book(ticker), binance.get_orderbook(symbol), binance.get_quote(symbol)
        age_a = bitstamp.age_sec(ticker)
        row = {
            "ts": now, "market": market, "ok": 0,
            "age_a_s": age_a if math.isfinite(age_a) else np.nan,
            "age_b_s": now - bq["ts"] if bq else np.nan,
            "age_fx_s": now - fxq["ts"] if fxq else np.nan,
            "ws_a": int(bool(getattr(bitstamp, "connected", False))),
            "ws_b": int(bool(getattr(binance, "connected", False))),
        }
        if not (a and b and fxq and a.get("bids") and a.get("asks") and b.get("bids") and b.get("asks")):
            rows.append(row)
            continue
        a_bids, a_asks = _levels(a, "bids"), _levels(a, "asks")
        b_bids, b_asks = _levels(b, "bids", 1 / fxq["ask"]), _levels(b, "asks", 1 / fxq["bid"])
        mid = (a_bids[0][0] + a_asks[0][0]) / 2
        fx_mid = (fxq["bid"] + fxq["ask"]) / 2
        row.update({
            "ok": 1, "a_bid": a_bids[0][0], "a_ask": a_asks[0][0],
            "b_bid_eur": b_bids[0][0], "b_ask_eur": b_asks[0][0],
            "eurusdt_bid": fxq["bid"], "eurusdt_ask": fxq["ask"],
            "a_half_bps": (a_asks[0][0] - a_bids[0][0]) / mid / 2 * 1e4,
            "b_half_bps": (b_asks[0][0] - b_bids[0][0]) / mid / 2 * 1e4,
            "fx_half_bps": (fxq["ask"] - fxq["bid"]) / fx_mid / 2 * 1e4,
            "a_depth10_eur": min(_depth_within(a_bids, mid, 10), _depth_within(a_asks, mid, 10)),
            "b_depth10_eur": min(_depth_within(b_bids, mid, 10), _depth_within(b_asks, mid, 10)),
            # Maker on Bitstamp at its best price, taker hedge on Binance (gross of fees).
            "maker_sellA_bps": (a_asks[0][0] - b_asks[0][0]) / mid * 1e4,
            "maker_buyA_bps": (b_bids[0][0] - a_bids[0][0]) / mid * 1e4,
            "tob_best_bps": max(a_bids[0][0] - b_asks[0][0], b_bids[0][0] - a_asks[0][0]) / mid * 1e4,
        })
        for size in sizes:
            amount = size / mid
            sa_sell, sb_buy = _vwap(a_bids, amount), _vwap(b_asks, amount)
            sb_sell, sa_buy = _vwap(b_bids, amount), _vwap(a_asks, amount)
            row[f"s{size}_sellA"] = (sa_sell - sb_buy) / mid * 1e4 if sa_sell and sb_buy else np.nan
            row[f"s{size}_buyA"] = (sb_sell - sa_buy) / mid * 1e4 if sb_sell and sa_buy else np.nan
        rows.append(row)
    return rows


def engine_state_rows(engine, now):
    rows = []
    for market in MARKETS:
        latest = engine.latest.get(market) or {}
        rows.append({
            "ts": now, "market": market,
            **{k: latest.get(k) for k in (
                "signal_state", "z_score", "threshold", "spread_pct", "breakeven_spread_pct",
                "fx_rate", "fx_age_sec", "depth_a_eur", "depth_b_eur", "price_model",
                "vwap_slip_a_bps", "vwap_slip_b_bps")},
        })
    return rows


# ---------------------------------------------------------------------------
# Phase 1 — environment
# ---------------------------------------------------------------------------

async def ping_venues(n=10):
    import aiohttp
    out = []
    async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10)) as s:
        for venue, url in PING_URLS.items():
            times, errors = [], []
            for _ in range(n):
                t0 = time.perf_counter()
                try:
                    async with s.get(url) as r:
                        await r.read()
                        if r.status != 200:
                            errors.append(f"HTTP {r.status}")
                            continue
                    times.append((time.perf_counter() - t0) * 1000)
                except Exception as exc:
                    errors.append(type(exc).__name__)
                await asyncio.sleep(0.2)
            out.append({"venue": venue, "url": url, "ok_requests": len(times), "failed": len(errors),
                        "errors": ", ".join(sorted(set(errors))),
                        "rtt_ms_min": min(times) if times else None,
                        "rtt_ms_median": float(np.median(times)) if times else None,
                        "rtt_ms_max": max(times) if times else None})
    return out


def environment_rows(args, started):
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=5).stdout.strip()
    except Exception:
        commit = "unknown"
    rows = [
        ("run_started_utc", started.isoformat()), ("git_commit", commit),
        ("python", sys.version.split()[0]), ("platform", platform.platform()),
        ("arguments", json.dumps(vars(args), default=str)),
        ("engine_capital_eur_per_leg", args.capital), ("engine_fee_tier", tier_name(args.tier)),
        ("live_fill_latency_ms", LIVE_FILL_LATENCY_MS), ("max_fx_age_sec", MAX_FX_AGE_SEC),
        ("fx_cost_bps", FX_COST_BPS), ("carry_pools", POOLS), ("carry_rate", ECB_DFR),
        ("live_trade_cooldown_sec", STRATEGY_DEFAULTS.get("trade_cooldown_sec")),
        ("live_signal_settings", json.dumps(ENHANCED_SIGNAL_SETTINGS)),
        ("backtest_zscore_window_bars", hbt.ZSCORE_WIN), ("backtest_zscore_threshold", hbt.ZSCORE_TH),
        ("backtest_cooldown_min", hbt.COOLDOWN_MIN), ("backtest_exec_costs", json.dumps(BT_EXEC_COSTS)),
    ]
    rows += [(f"tier {t['idx']}", f"{t['label']}: Bitstamp {t['a'] * 1e4:g} bps + LMAX {t['b'] * 1e4:g} bps"
                                  f" + FX {FX_COST_BPS:g} bp = break-even {t['be_bps']:g} bps") for t in TIERS]
    return rows


# ---------------------------------------------------------------------------
# Phase 2 — live engine + shadow sampler
# ---------------------------------------------------------------------------

async def live_phase(args, run_dir, res):
    from src.crypto_hft_tool.bsdex_strategy import BSDEXStrategy
    from src.crypto_hft_tool.quote_recorder import QuoteRecorder

    engine = BSDEXStrategy()
    # Record into this run's own folder so a running backend cannot hold the lock.
    engine._quote_recorder = QuoteRecorder(engine._bitstamp_depth_ws, engine._binance_ws,
                                           output=run_dir / "quotes")
    tier = TIERS[args.tier]
    engine.set_fees(tier["a"], tier["b"], tier_label=tier["label"], tier_idx=tier["idx"], mode="campaign")
    engine.set_capital(args.capital)
    task = asyncio.create_task(engine.run())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
    except (NotImplementedError, RuntimeError):
        pass

    shadow, states = [], []
    started = time.time()
    end = started + args.hours * 3600
    next_state, next_print = started, started + 60
    period = args.sample_ms / 1000
    print(f"[live] running {args.hours:g} h until {datetime.fromtimestamp(end, timezone.utc):%Y-%m-%d %H:%M} UTC."
          " Ctrl+C stops early and continues with the backtests.", flush=True)
    while time.time() < end and not stop.is_set() and not task.done():
        now = time.time()
        shadow.extend(sample_books(engine._bitstamp_depth_ws, engine._binance_ws, args.sizes, now))
        if now >= next_state:
            states.extend(engine_state_rows(engine, now))
            next_state += 1
        if now - started > 180 and not any(r["ok"] for r in shadow):
            msg = ("no usable Bitstamp/Binance/EURUSDT books after 3 minutes; live phase stopped. "
                   "Check that wss://ws.bitstamp.net and wss://stream.binance.com:9443 are reachable.")
            print(f"[live] {msg}", flush=True)
            res["errors"].append(("live/feeds", msg))
            break
        if now >= next_print:
            recent = shadow[-int(len(MARKETS) * 60 / period):]
            ok = [r for r in shadow[-8:] if r["ok"]]
            print(f"[live] valid samples last minute: {sum(r['ok'] for r in recent) / max(len(recent), 1):.0%}",
                  flush=True)
            best = {r["market"]: round(max(r[f"s{args.capital_size}_sellA"], r[f"s{args.capital_size}_buyA"]), 2)
                    for r in ok}
            print(f"[live] {(now - started) / 60:6.1f} min | engine trades {len(engine.simulator.trades)}"
                  f" | best gap @€{args.capital_size:,} (bps) {best}", flush=True)
            next_print += 60
        await asyncio.sleep(max(0.0, period - (time.time() - now)))
    try:
        loop.remove_signal_handler(signal.SIGINT)
    except Exception:
        pass
    if task.done() and task.exception():
        res["errors"].append(("live/engine", repr(task.exception())))

    res["live_meta"] = {
        "live_started_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "live_ended_utc": datetime.now(timezone.utc).isoformat(),
        "live_minutes": round((time.time() - started) / 60, 2),
        "stopped_early": stop.is_set(),
        "ecb_usd_to_eur": engine.fx_cache.rate, "ecb_fixing_date": engine.fx_cache.fixing_date,
    }
    res["engine_status"] = engine.get_status()
    res["engine_trades"] = [dict(t) for t in engine.simulator.trades]
    res["engine_failures"] = [dict(f) for f in engine.execution_failures]
    engine.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    res["shadow"] = pd.DataFrame(shadow)
    res["states"] = pd.DataFrame(states)
    res["shadow"].to_csv(run_dir / "shadow_samples.csv.gz", index=False)
    res["states"].to_csv(run_dir / "engine_states.csv.gz", index=False)


# ---------------------------------------------------------------------------
# Live analysis
# ---------------------------------------------------------------------------

def _best(df, size):
    return np.fmax(df[f"s{size}_sellA"], df[f"s{size}_buyA"])


def _runs(mask, ts, max_gap):
    """(start, end) index pairs of consecutive True values; a time gap breaks a run."""
    out, start = [], None
    for i in range(len(mask)):
        if mask[i] and start is not None and ts[i] - ts[i - 1] > max_gap:
            out.append((start, i - 1))
            start = None
        if mask[i] and start is None:
            start = i
        elif not mask[i] and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def _pct(series, q):
    s = series.dropna()
    return float(np.percentile(s, q)) if len(s) else np.nan


def analyse_live(shadow, states, sizes, capital_size, sample_ms):
    out = {}
    if shadow is None or shadow.empty:
        return out
    gap = 3 * sample_ms / 1000
    # Feeds that never delivered leave columns missing; keep the analysis total.
    expected = ["a_bid", "a_ask", "b_bid_eur", "b_ask_eur", "eurusdt_bid", "eurusdt_ask", "a_half_bps",
                "b_half_bps", "fx_half_bps", "a_depth10_eur", "b_depth10_eur", "maker_sellA_bps",
                "maker_buyA_bps", "tob_best_bps"] + [f"s{s}_{d}" for s in sizes for d in ("sellA", "buyA")]
    shadow = shadow.assign(**{c: np.nan for c in expected if c not in shadow})
    valid = shadow[shadow["ok"] == 1].copy()

    rows = []
    for market, d in valid.groupby("market"):
        for size in sizes:
            for label, s in (("sellA (sell Bitstamp, buy Binance)", d[f"s{size}_sellA"]),
                             ("buyA (buy Bitstamp, sell Binance)", d[f"s{size}_buyA"]),
                             ("best of both", _best(d, size))):
                rows.append({"market": market, "size_eur": size, "direction": label,
                             "samples": int(s.notna().sum()), "depth_insufficient": int(s.isna().sum()),
                             "mean_bps": s.mean(), **{f"p{q}_bps": _pct(s, q) for q in (1, 5, 25, 50, 75, 95, 99)},
                             "max_bps": s.max(), "pct_above_0": (s > 0).mean() * 100})
    out["Live_Spreads"] = pd.DataFrame(rows)

    rows = []
    for market, d in valid.groupby("market"):
        ts = d["ts"].to_numpy()
        for size in sizes:
            best = _best(d, size).to_numpy()
            for t in TIERS:
                net = best - t["be_bps"]
                runs = _runs(np.nan_to_num(net, nan=-1e9) > 0, ts, gap)
                dur = [ts[e] - ts[s] + sample_ms / 1000 for s, e in runs]
                rows.append({"market": market, "size_eur": size, "tier": tier_name(t["idx"]),
                             "breakeven_bps": t["be_bps"], "samples": int(np.isfinite(best).sum()),
                             "pct_time_profitable": float(np.mean(net > 0) * 100),
                             "episodes": len(runs),
                             "episodes_per_hour": len(runs) / max((ts[-1] - ts[0]) / 3600, 1e-9),
                             "median_episode_s": float(np.median(dur)) if dur else 0.0,
                             "max_episode_s": max(dur) if dur else 0.0,
                             "mean_net_bps_when_profitable": float(np.nanmean(net[net > 0])) if (net > 0).any() else np.nan})
    out["Live_Tier_Gate"] = pd.DataFrame(rows)

    # Does a gap survive the delay between seeing it and trading it?
    rows = []
    for market, d in valid.groupby("market"):
        ts = d["ts"].to_numpy()
        sell, buy = d[f"s{capital_size}_sellA"].to_numpy(), d[f"s{capital_size}_buyA"].to_numpy()
        best = np.fmax(sell, buy)
        p99 = float(np.nanpercentile(best, 99)) if np.isfinite(best).any() else np.nan
        triggers = [("gap > 0 bps", 0.0), ("top 1% of samples", p99),
                    (f"gap >= break-even {tier_name(VERIFIED_TIER_IDX)}", TIERS[VERIFIED_TIER_IDX]["be_bps"]),
                    (f"gap >= break-even {tier_name(BSDEX_DEFAULT_TIER_IDX)}", TIERS[BSDEX_DEFAULT_TIER_IDX]["be_bps"])]
        for name, level in triggers:
            starts = [s for s, _ in _runs(np.nan_to_num(best, nan=-1e9) >= level, ts, gap)]
            for lag in LAGS_MS:
                at, after = [], []
                for i in starts:
                    series = sell if sell[i] >= buy[i] else buy
                    j = int(np.searchsorted(ts, ts[i] + lag / 1000))
                    if j < len(ts) and ts[j] - ts[i] <= lag / 1000 + 1.0 and np.isfinite(series[j]):
                        at.append(series[i])
                        after.append(series[j])
                at, after = np.array(at), np.array(after)
                rows.append({"market": market, "trigger": name, "trigger_level_bps": level,
                             "events": len(starts), "events_measured": len(after), "lag_ms": lag,
                             "median_gap_at_signal_bps": float(np.median(at)) if len(at) else np.nan,
                             "median_gap_after_lag_bps": float(np.median(after)) if len(after) else np.nan,
                             "mean_change_bps": float(np.mean(after - at)) if len(at) else np.nan,
                             "pct_still_above_0": float(np.mean(after > 0) * 100) if len(after) else np.nan,
                             "pct_still_above_trigger": float(np.mean(after >= level) * 100) if len(after) else np.nan})
    out["Live_Persistence"] = pd.DataFrame(rows)

    rows = []
    for market, d in shadow.groupby("market"):
        v = d[d["ok"] == 1]
        row = {"market": market, "samples_total": len(d), "samples_valid": len(v),
               "pct_valid": len(v) / len(d) * 100 if len(d) else np.nan}
        for col in ("a_half_bps", "b_half_bps", "fx_half_bps"):
            row.update({f"{col}_p50": _pct(v[col], 50), f"{col}_p95": _pct(v[col], 95)})
        for col in ("a_depth10_eur", "b_depth10_eur"):
            row.update({f"{col}_p5": _pct(v[col], 5), f"{col}_p50": _pct(v[col], 50)})
        for col in ("age_a_s", "age_b_s", "age_fx_s"):
            row.update({f"{col}_p50": _pct(d[col], 50), f"{col}_p95": _pct(d[col], 95), f"{col}_max": d[col].max()})
        row["pct_fx_older_than_limit"] = (d["age_fx_s"] > MAX_FX_AGE_SEC).mean() * 100
        row["pct_ws_a_down"] = (d["ws_a"] == 0).mean() * 100
        row["pct_ws_b_down"] = (d["ws_b"] == 0).mean() * 100
        ts = d["ts"].to_numpy()
        row["longest_sampling_gap_s"] = float(np.max(np.diff(ts))) if len(ts) > 1 else np.nan
        rows.append(row)
    out["Live_Liquidity_Quality"] = pd.DataFrame(rows)

    rows = []
    for market, d in valid.groupby("market"):
        for side in ("maker_sellA_bps", "maker_buyA_bps", "tob_best_bps"):
            s = d[side]
            rows.append({"market": market, "measure": side, "samples": int(s.notna().sum()),
                         **{f"p{q}_bps": _pct(s, q) for q in (5, 25, 50, 75, 95, 99)}, "max_bps": s.max(),
                         "pct_above_0": (s > 0).mean() * 100,
                         "pct_above_LMAX_6bps_plus_FX": (s > 6 + FX_COST_BPS).mean() * 100,
                         "pct_above_LMAX_3bps_plus_FX": (s > 3 + FX_COST_BPS).mean() * 100})
    out["Live_Maker_Edge"] = pd.DataFrame(rows)

    rows = []
    valid["hour_utc"] = pd.to_datetime(valid["ts"], unit="s", utc=True).dt.hour
    for (market, hour), d in valid.groupby(["market", "hour_utc"]):
        best = _best(d, capital_size)
        rows.append({"market": market, "hour_utc": hour, "samples": int(best.notna().sum()),
                     "mean_bps": best.mean(), "p50_bps": _pct(best, 50), "p99_bps": _pct(best, 99),
                     "max_bps": best.max(), "pct_above_0": (best > 0).mean() * 100,
                     "bitstamp_half_spread_p50_bps": _pct(d["a_half_bps"], 50)})
    out["Live_Hourly"] = pd.DataFrame(rows)

    keep = ["ts", "market", "a_bid", "a_ask", "b_bid_eur", "b_ask_eur", "eurusdt_bid", "eurusdt_ask",
            "a_half_bps", "b_half_bps", "tob_best_bps", "maker_sellA_bps", "maker_buyA_bps"] + \
           [f"s{s}_{d}" for s in sizes for d in ("sellA", "buyA")]
    sec = valid.assign(sec=valid["ts"].astype(int)).groupby(["market", "sec"]).first().reset_index()
    sec["time_utc"] = pd.to_datetime(sec["ts"], unit="s", utc=True).dt.tz_localize(None)
    out["Samples_1s"] = sec[["time_utc"] + [c for c in keep if c in sec.columns]]

    if states is not None and not states.empty:
        rows = []
        for market, d in states.groupby("market"):
            counts = Counter(d["signal_state"].fillna("NO_DATA"))
            for state, n in counts.most_common():
                rows.append({"market": market, "signal_state": state, "seconds": n,
                             "pct_of_time": n / len(d) * 100})
        out["Engine_States"] = pd.DataFrame(rows)
        rows = []
        for market, d in states.groupby("market"):
            z, th = pd.to_numeric(d["z_score"], errors="coerce"), pd.to_numeric(d["threshold"], errors="coerce")
            sp, be = pd.to_numeric(d["spread_pct"], errors="coerce"), pd.to_numeric(d["breakeven_spread_pct"], errors="coerce")
            rows.append({"market": market, "seconds": len(d),
                         "abs_z_p50": _pct(z.abs(), 50), "abs_z_p95": _pct(z.abs(), 95), "abs_z_max": z.abs().max(),
                         "threshold_p5": _pct(th, 5), "threshold_p50": _pct(th, 50), "threshold_p95": _pct(th, 95),
                         "pct_threshold_at_floor_0.3": (th.round(4) <= 0.3).mean() * 100,
                         "pct_threshold_at_cap_2.0": (th.round(4) >= 2.0).mean() * 100,
                         "pct_z_above_threshold": (z.abs() >= th).mean() * 100,
                         "engine_spread_pct_p50": _pct(sp, 50), "engine_spread_pct_max": sp.max(),
                         "engine_breakeven_pct": be.median(),
                         "pct_spread_above_breakeven": (sp > be).mean() * 100})
        out["Engine_Signal_Stats"] = pd.DataFrame(rows)
    return out


# ---------------------------------------------------------------------------
# Phases 3–5 — backtests
# ---------------------------------------------------------------------------

@contextmanager
def strategy_params(window=None, threshold=None, cooldown=None):
    saved = (hbt.ZSCORE_WIN, hbt.ZSCORE_TH, hbt.COOLDOWN_MIN)
    hbt.ZSCORE_WIN = window or saved[0]
    hbt.ZSCORE_TH = threshold or saved[1]
    hbt.COOLDOWN_MIN = cooldown or saved[2]
    try:
        yield
    finally:
        hbt.ZSCORE_WIN, hbt.ZSCORE_TH, hbt.COOLDOWN_MIN = saved


def summary_row(result, scenario, **labels):
    sc = result.get(scenario) or {}
    s, trades = sc.get("summary", {}), sc.get("trades", [])
    sig = [t["signal_spread_pct"] for t in trades if t.get("signal_spread_pct") is not None]
    real = [t["realized_spread_pct"] for t in trades if t.get("realized_spread_pct") is not None]
    return {**labels, "scenario": scenario,
            **{k: s.get(k) for k in ("start_dt", "end_dt", "duration_hours", "candles_processed",
                                     "snapshots_processed", "total_trades", "win_trades", "loss_trades",
                                     "win_rate_pct", "gross_pnl_eur", "total_fees_eur", "fx_cost_eur",
                                     "total_pnl_eur", "carry_eur", "net_after_carry_eur", "max_drawdown_eur",
                                     "sharpe_ratio", "breakeven_spread_pct", "failed_fills")},
            "avg_signal_spread_pct": float(np.mean(sig)) if sig else None,
            "avg_realized_spread_pct": float(np.mean(real)) if real else None,
            "avg_pnl_per_trade_eur": (s.get("total_pnl_eur") or 0) / s["total_trades"] if s.get("total_trades") else None}


def trade_rows(result, scenario, **labels):
    return [{**labels, **{k: v for k, v in t.items() if not isinstance(v, (dict, list))}}
            for t in ((result.get(scenario) or {}).get("trades") or [])]


def quote_replay_phase(args, run_dir, res):
    path = run_dir / "quotes" if args.quotes is None else Path(args.quotes)
    cache = {}
    original = quote_data.read_quotes

    def cached(p, symbol):
        key = (str(p), symbol)
        if key not in cache:
            cache[key] = original(p, symbol)
        return cache[key]

    quote_data.read_quotes = cached
    summaries, trades = [], []
    try:
        grid = [(m, t["idx"], 300, None, None, None) for m in MARKETS for t in TIERS]
        if not args.quick:
            grid += [(m, tier, lat, win, th, cd) for m in MARKETS for tier in SWEEP_TIERS
                     for lat in (300, 1000, 2000) for win in (10, 60) for th in (1.0, 1.5, 2.5) for cd in (1, 30)]
        for market, tier, lat, win, th, cd in grid:
            labels = {"run": "sweep" if win else "base", "market": market, "tier": tier_name(tier), "latency_ms": lat,
                      "zscore_window_min": win or hbt.ZSCORE_WIN, "zscore_threshold": th or hbt.ZSCORE_TH,
                      "cooldown_min": cd or hbt.COOLDOWN_MIN}
            try:
                with strategy_params(win, th, cd):
                    r = hbt.run_quote_backtest(quote_path=path, symbol=market, tier=tier,
                                               capital_eur=args.capital, latency_ms=lat)
                summaries.append(summary_row(r, "realistic", **labels))
                if win is None and tier in SWEEP_TIERS:
                    trades += trade_rows(r, "realistic", **labels)
            except Exception as exc:
                summaries.append({**labels, "error": str(exc)[:300]})
    finally:
        quote_data.read_quotes = original
    res["replay"], res["replay_trades"] = pd.DataFrame(summaries), pd.DataFrame(trades)


async def candle_phase(args, res):
    cache = {}
    original = hbt._fetch_ohlcv

    async def cached(*a):
        if a not in cache:
            cache[a] = await original(*a)
        return cache[a]

    original_fx = hbt._fetch_fx_range

    async def cached_fx(*a):
        if ("fx",) + a not in cache:
            cache[("fx",) + a] = await original_fx(*a)
        return cache[("fx",) + a]

    hbt._fetch_ohlcv, hbt._fetch_fx_range = cached, cached_fx
    end =datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    start = end - timedelta(days=args.days)
    summaries, trades, control = [], [], []
    try:
        grid = [(m, t["idx"], None, None, None) for m in MARKETS for t in TIERS]
        if not args.quick:
            grid += [(m, tier, win, th, cd) for m in MARKETS for tier in SWEEP_TIERS
                     for win in (30, 60, 240) for th in (1.0, 1.5, 2.0, 2.5, 3.0) for cd in (5, 30)]
        for i, (market, tier, win, th, cd) in enumerate(grid):
            labels = {"run": "sweep" if win else "base", "market": market, "tier": tier_name(tier),
                      "zscore_window_bars": win or hbt.ZSCORE_WIN,
                      "zscore_threshold": th or hbt.ZSCORE_TH, "cooldown_min": cd or hbt.COOLDOWN_MIN}
            try:
                with strategy_params(win, th, cd):
                    r = await hbt.run_historical_backtest(market, start, end, TIERS[tier]["a"], TIERS[tier]["b"],
                                                          args.capital, tier_label=TIERS[tier]["label"])
                for sc in ("realistic", "upper_bound"):
                    summaries.append(summary_row(r, sc, **labels))
                if win is None and tier in SWEEP_TIERS:
                    trades += trade_rows(r, "realistic", **labels)
            except Exception as exc:
                summaries.append({**labels, "error": str(exc)[:300]})
            if i % 20 == 0:
                print(f"[candles] {i + 1}/{len(grid)} runs", flush=True)

        # FX-free control pair: Kraken serves ~12 h of 1-minute candles.
        c_end = end
        c_start = c_end - timedelta(hours=11, minutes=50)
        for t in TIERS:
            labels = {"run": "base", "market": "btc-eur-kraken (control, no FX)", "tier": tier_name(t["idx"])}
            try:
                r = await hbt.run_historical_backtest("btc-eur-kraken", c_start, c_end, t["a"], t["b"],
                                                      args.capital, tier_label=t["label"])
                for sc in ("realistic", "upper_bound"):
                    control.append(summary_row(r, sc, **labels))
            except Exception as exc:
                control.append({**labels, "error": str(exc)[:300]})
    finally:
        hbt._fetch_ohlcv, hbt._fetch_fx_range = original, original_fx
    res["candles"], res["candle_trades"], res["control"] = (
        pd.DataFrame(summaries), pd.DataFrame(trades), pd.DataFrame(control))


# ---------------------------------------------------------------------------
# Summary + Excel
# ---------------------------------------------------------------------------

def headline(res, args):
    rows = []

    def add(section, item, value, note=""):
        rows.append({"section": section, "item": item, "value": value, "note": note})

    meta = res.get("live_meta", {})
    for k, v in meta.items():
        add("Live run", k, v)
    shadow = res.get("shadow")
    if shadow is not None and not shadow.empty:
        valid = shadow[shadow["ok"] == 1]
        for market, d in valid.groupby("market"):
            best = _best(d, args.capital_size)
            add("Live gap", f"{market} median best executable gap @€{args.capital_size:,}", _pct(best, 50), "bps, after crossing both books, before fees")
            add("Live gap", f"{market} 99th percentile gap @€{args.capital_size:,}", _pct(best, 99), "bps")
            add("Live gap", f"{market} max gap @€{args.capital_size:,}", best.max(), "bps")
            add("Live gap", f"{market} % of time gap > 0", (best > 0).mean() * 100, "%")
            for t in (TIERS[BSDEX_DEFAULT_TIER_IDX], TIERS[VERIFIED_TIER_IDX], TIERS[-1]):
                add("Live gap", f"{market} % of time gap > break-even {tier_name(t['idx'])}",
                    (best > t["be_bps"]).mean() * 100, f"break-even {t['be_bps']:g} bps")
            add("Venues", f"{market} Bitstamp half-spread p50", _pct(d["a_half_bps"], 50), "bps (backtest assumes 5)")
            add("Venues", f"{market} Binance→EUR half-spread p50", _pct(d["b_half_bps"], 50), "bps incl. EUR/USDT (backtest assumes 1.5)")
            fx_mid = (d["eurusdt_bid"] + d["eurusdt_ask"]) / 2
            if meta.get("ecb_usd_to_eur"):
                ecb_eurusd = 1 / meta["ecb_usd_to_eur"]
                add("FX", f"{market} EUR/USDT mid vs ECB EUR/USD fixing", float((fx_mid.median() - ecb_eurusd) / ecb_eurusd * 1e4),
                    f"bps; ECB fixing {meta.get('ecb_fixing_date')}")
    status = res.get("engine_status") or {}
    for k in ("total_trades", "win_rate_pct", "total_pnl_eur", "total_fees_eur", "tier_label", "capital_eur",
              "breakeven_spread_pct", "quote_recording"):
        if k in status:
            add("Live engine", k, json.dumps(status[k], default=str) if isinstance(status[k], dict) else status[k])
    trades = res.get("engine_trades") or []
    if trades:
        add("Live engine", "avg signal spread %", float(np.mean([t.get("signal_spread_pct", np.nan) for t in trades])))
        add("Live engine", "avg realised spread %", float(np.mean([t.get("realized_spread_pct", np.nan) for t in trades])))
    add("Live engine", "failed executions", len(res.get("engine_failures") or []))
    for name in ("replay", "candles", "control"):
        df = res.get(name)
        if df is None or df.empty or "total_trades" not in df:
            continue
        base = df[df.get("error").isna()] if "error" in df else df
        base = base[(base["scenario"] == "realistic") & (base["run"] == "base")]
        for _, r in base.iterrows():
            if r["tier"] in (tier_name(BSDEX_DEFAULT_TIER_IDX), tier_name(VERIFIED_TIER_IDX)):
                add(name.capitalize(), f"{r['market']} {r['tier']}: trades / wins / net €",
                    f"{r['total_trades']} / {r['win_trades']} / {r['total_pnl_eur']}")
        if name in ("replay", "candles"):
            ok = df[(df["scenario"] == "realistic") & df["total_pnl_eur"].notna()] if "scenario" in df else df
            for market, d in ok.groupby("market"):
                for label, pool in (("best of all tested settings", d),
                                    ("best setting with >= 1 trade", d[d["total_trades"] > 0])):
                    if pool.empty:
                        add(name.capitalize(), f"{market} {label}: net €", None, "no setting traded")
                        continue
                    top = pool.sort_values("total_pnl_eur", ascending=False).iloc[0]
                    params = {k: top[k] for k in ("tier", "latency_ms", "zscore_window_min", "zscore_window_bars",
                                                  "zscore_threshold", "cooldown_min") if k in top and pd.notna(top[k])}
                    add(name.capitalize(), f"{market} {label}: net €", top["total_pnl_eur"],
                        json.dumps(params, default=str) + f"; {top['total_trades']} trades")
                add(name.capitalize(), f"{market} settings with net > 0", int((d["total_pnl_eur"] > 0).sum()),
                    f"of {len(d)} realistic runs")
    for r in res.get("ping") or []:
        add("Network", f"{r['venue']} REST round trip median ms", r["rtt_ms_median"], r["errors"])
    return pd.DataFrame(rows)


DEFINITIONS = [
    ("bps", "Basis points: 1 bp = 0.01%."),
    ("sellA / buyA", "sellA = sell on Bitstamp and buy on Binance; buyA = buy on Bitstamp and sell on Binance."),
    ("executable gap (s<size>_*)", "Sell-side VWAP minus buy-side VWAP for the full order size, in bps of the Bitstamp mid, before fees. Binance prices converted per side with EUR/USDT (bids / EURUSDT ask, asks / EURUSDT bid)."),
    ("break-even", "Bitstamp taker + LMAX taker + 1 bp FX for the tier. A gap above it is profitable if it lasts until the fill."),
    ("Live_Tier_Gate", "Share of time and number of episodes in which the gap exceeded each tier's break-even."),
    ("Live_Persistence", "For each moment a gap appeared, the same-direction gap again after each lag. The engine fills 300 ms after a signal."),
    ("maker_*_bps", "Gap if the Bitstamp leg is a resting order at Bitstamp's best price and the Binance leg is a taker hedge; gross of fees, assumes the resting order fills."),
    ("tob_best_bps", "Best-price-only gap (a few euros of size)."),
    ("Engine_*", "The real paper engine running with the chosen tier and capital; states sampled once per second."),
    ("Quote_Replay", "run_quote_backtest on the quotes recorded during this run. Needs at least the z-score window (10 or 60 min) of data."),
    ("Candle_Backtests", "run_historical_backtest on 1-minute candles. realistic = with bid/ask and slippage costs; upper_bound = mid prices."),
    ("Control_Pair", "Same backtest for Bitstamp EUR vs Kraken EUR: no currency conversion at all."),
]


def write_excel(path, res, args, env_rows):
    sheets = [
        ("README", pd.DataFrame([{"key": k, "value": v} for k, v in env_rows] +
                                [{"key": f"definition: {k}", "value": v} for k, v in DEFINITIONS])),
        ("Summary", headline(res, args)),
        ("Network", pd.DataFrame(res.get("ping") or [])),
    ]
    for name in ("Live_Spreads", "Live_Tier_Gate", "Live_Persistence", "Live_Liquidity_Quality",
                 "Live_Maker_Edge", "Live_Hourly", "Engine_States", "Engine_Signal_Stats"):
        sheets.append((name, res.get("analysis", {}).get(name, pd.DataFrame())))
    sheets += [
        ("Engine_Trades", pd.DataFrame(res.get("engine_trades") or [])),
        ("Engine_Failures", pd.DataFrame(res.get("engine_failures") or [])),
        ("Quote_Replay", res.get("replay", pd.DataFrame())),
        ("Quote_Replay_Trades", res.get("replay_trades", pd.DataFrame())),
        ("Candle_Backtests", res.get("candles", pd.DataFrame())),
        ("Candle_Trades", res.get("candle_trades", pd.DataFrame())),
        ("Control_Pair", res.get("control", pd.DataFrame())),
        ("Samples_1s", res.get("analysis", {}).get("Samples_1s", pd.DataFrame())),
        ("Errors", pd.DataFrame(res["errors"], columns=["phase", "error"])),
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets:
            df = df if df is not None and not df.empty else pd.DataFrame({"note": ["no data"]})
            for col in df.columns:
                if isinstance(df[col].dtype, pd.DatetimeTZDtype):
                    df[col] = df[col].dt.tz_localize(None)
                elif df[col].dtype == object:
                    df[col] = df[col].map(lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.book[name[:31]]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(len(str(col)) + 2, 10), 48)


# ---------------------------------------------------------------------------

async def main(args):
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.out or ROOT / "reports" / f"campaign_{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    res = {"errors": []}
    env = environment_rows(args, started)

    async def step(name, coro):
        print(f"[{name}] starting", flush=True)
        t0 = time.time()
        try:
            await coro
        except Exception as exc:
            res["errors"].append((name, f"{exc!r}\n{traceback.format_exc()[-1500:]}"))
            print(f"[{name}] FAILED: {exc!r} (continuing)", flush=True)
        print(f"[{name}] done in {(time.time() - t0) / 60:.1f} min", flush=True)

    async def pings():
        res["ping"] = await ping_venues()
    await step("network", pings())
    if args.hours > 0 and args.quotes is None:
        await step("live", live_phase(args, run_dir, res))
        try:
            res["analysis"] = analyse_live(res.get("shadow"), res.get("states"), args.sizes,
                                           args.capital_size, args.sample_ms)
        except Exception as exc:
            res["errors"].append(("live/analysis", repr(exc)))
    if not args.skip_replay:
        await step("quote-replay", asyncio.to_thread(quote_replay_phase, args, run_dir, res))
    if not args.skip_candles:
        await step("candles", candle_phase(args, res))

    env.append(("run_finished_utc", datetime.now(timezone.utc).isoformat()))
    xlsx = run_dir / f"campaign_{stamp}.xlsx"
    write_excel(xlsx, res, args, env)
    print(f"\nDone. Upload this file:\n  {xlsx}\n", flush=True)
    return xlsx


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hours", type=float, default=8.0, help="live phase length (default 8; 0 skips it)")
    p.add_argument("--capital", type=float, default=100_000, help="EUR per leg for engine and backtests")
    p.add_argument("--tier", type=int, default=BSDEX_DEFAULT_TIER_IDX, help="fee tier index for the live engine")
    p.add_argument("--sizes", default="1000,10000,100000,250000", help="order sizes (EUR) the sampler measures")
    p.add_argument("--sample-ms", type=int, default=250, help="shadow sampling period in ms")
    p.add_argument("--days", type=float, default=7, help="candle backtest length in days (max 7)")
    p.add_argument("--quotes", default=None, help="replay an existing quote folder instead of a live run")
    p.add_argument("--skip-replay", action="store_true")
    p.add_argument("--skip-candles", action="store_true")
    p.add_argument("--quick", action="store_true", help="no parameter sweeps (smoke test)")
    p.add_argument("--out", default=None, help="output folder (default reports/campaign_<UTC>)")
    args = p.parse_args(argv)
    args.sizes = sorted({int(float(s)) for s in args.sizes.split(",")} | {int(args.capital)})
    args.capital_size = int(args.capital)
    if not 0 <= args.tier < len(TIERS):
        p.error(f"--tier must be 0..{len(TIERS) - 1}")
    if not 0 < args.days <= hbt.MAX_DAYS:
        p.error(f"--days must be in (0, {hbt.MAX_DAYS}]")
    return args


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main(parse_args()))
