#!/usr/bin/env python3
"""
Download historical data for the BSDEX vs World backtest.

Data sources
------------
  Venue A (BSDEX proxy): Bitstamp public REST OHLCV for BTC/EUR and ETH/EUR.
    → Why Bitstamp?  BSDEX's own history API requires authentication
      (HMAC, verified May 2026).  Bitstamp is a regulated EU exchange
      with a genuinely public history API and comparable EUR liquidity.
      All resulting files are clearly labelled as "bitstamp_as_bsdex_proxy".
      When you obtain BSDEX API keys, swap the downloader for a call to
      GET /api/v1/{market}/tradingview/history with HMAC headers.

  Venue B (world price): Binance OHLCV via ccxt (BTC/USDT, ETH/USDT)
      converted to EUR per-row using the Frankfurter historical FX series.

Output
------
  data/processed/bsdex_BTC_EUR.csv   (+ .meta.json)
  data/processed/bsdex_ETH_EUR.csv   (+ .meta.json)

Columns
-------
  timestamp, bsdex_bid, bsdex_ask, world_bid_eur, world_ask_eur, fx_rate, phase

Usage
-----
  python3 scripts/download_bsdex_data.py [--days DAYS] [--record]

  --days DAYS   how many days of history to pull (default 7, max ~14 for 1-min data)
  --record      additionally start a live recorder that appends real-time
                Bitstamp ticks to the same CSV (Ctrl-C to stop)
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp
import ccxt
import pandas as pd
import requests

from src.crypto_hft_tool.config import FX_RATE_SOURCE

# ── config ────────────────────────────────────────────────────────────────────
BITSTAMP_OHLCV_URL = "https://www.bitstamp.net/api/v2/ohlc/{pair}/"
FRANKFURTER_HIST   = "https://api.frankfurter.app/{date}?from=USD&to=EUR"
BINANCE_TF         = "1m"
BITSTAMP_STEP      = 60          # seconds per candle (1-min)
BITSTAMP_LIMIT     = 1000        # max candles per request
HALF_SPREAD        = 0.0001      # 1 bp synthetic half-spread for Bitstamp close→bid/ask

MARKET_MAP = {
    "btc-eur": {
        "bitstamp_pair":  "btceur",
        "binance_symbol": "BTC/USDT",
        "output_file":    "bsdex_BTC_EUR",
    },
    "eth-eur": {
        "bitstamp_pair":  "etheur",
        "binance_symbol": "ETH/USDT",
        "output_file":    "bsdex_ETH_EUR",
    },
}

OUT_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── FX helpers ─────────────────────────────────────────────────────────────────

def fetch_fx_series(start: datetime, end: datetime) -> dict:
    """Return {date_str: eur_per_usd} for all calendar days in range."""
    s = start.strftime("%Y-%m-%d")
    e = end.strftime("%Y-%m-%d")
    url = f"https://api.frankfurter.app/{s}..{e}?from=USD&to=EUR"
    print(f"[FX] Fetching EUR/USD series {s} → {e} …")
    r = requests.get(url, timeout=10)
    data = r.json()
    if "rates" not in data:
        # Single-day response
        return {data.get("date", s): float(data.get("rates", {}).get("EUR", 0.90))}
    return {date: float(rates["EUR"]) for date, rates in data["rates"].items()}


def fill_fx(series: dict, ts: datetime) -> float:
    """Forward-fill: find the nearest date <= ts."""
    date_str = ts.strftime("%Y-%m-%d")
    if date_str in series:
        return series[date_str]
    # walk backwards up to 7 days
    for i in range(1, 8):
        d = (ts - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in series:
            return series[d]
    return 0.90   # last-resort fallback


# ── Bitstamp OHLCV downloader ─────────────────────────────────────────────────

def fetch_bitstamp_ohlcv(pair: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    """Download 1-min OHLCV candles from Bitstamp in batches."""
    all_rows = []
    cursor = start_ts
    print(f"[Bitstamp] Downloading {pair} …", end="", flush=True)
    while cursor < end_ts:
        url = BITSTAMP_OHLCV_URL.format(pair=pair)
        params = {
            "step": BITSTAMP_STEP,
            "limit": BITSTAMP_LIMIT,
            "start": cursor,
            "end": min(cursor + BITSTAMP_STEP * BITSTAMP_LIMIT, end_ts),
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            print(f"\n[Bitstamp] HTTP {r.status_code} — {r.text[:120]}")
            break
        d = r.json().get("data", {}).get("ohlc", [])
        if not d:
            break
        all_rows.extend(d)
        cursor = int(d[-1]["timestamp"]) + BITSTAMP_STEP
        print(".", end="", flush=True)
        time.sleep(0.3)

    print(f" {len(all_rows)} candles")
    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df.set_index("timestamp").sort_index().drop_duplicates()
    return df


# ── Binance OHLCV downloader via ccxt ────────────────────────────────────────

def fetch_binance_ohlcv(symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    """Download 1-min OHLCV from Binance via ccxt (no auth needed)."""
    exchange = ccxt.binance({"enableRateLimit": True})
    all_rows = []
    since = start_ts * 1000  # ccxt uses milliseconds
    end_ms = end_ts * 1000
    print(f"[Binance] Downloading {symbol} …", end="", flush=True)
    while since < end_ms:
        try:
            rows = exchange.fetch_ohlcv(symbol, "1m", since=since, limit=1000)
        except Exception as exc:
            print(f"\n[Binance] Error: {exc}")
            break
        if not rows:
            break
        all_rows.extend(rows)
        since = rows[-1][0] + 60_000
        print(".", end="", flush=True)
        time.sleep(0.2)

    print(f" {len(all_rows)} candles")
    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index().drop_duplicates()
    return df


# ── Merge and save ────────────────────────────────────────────────────────────

def merge_and_save(market: str, cfg: dict, days: int):
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    start_ts = int(start_dt.timestamp())
    end_ts   = int(end_dt.timestamp())

    # --- fetch FX series ---
    fx_series = fetch_fx_series(start_dt, end_dt)

    # --- fetch Bitstamp (Venue A proxy) ---
    bst_df = fetch_bitstamp_ohlcv(cfg["bitstamp_pair"], start_ts, end_ts)
    if bst_df.empty:
        print(f"[WARN] No Bitstamp data for {market}; skipping.")
        return

    # --- fetch Binance (Venue B world) ---
    bnc_df = fetch_binance_ohlcv(cfg["binance_symbol"], start_ts, end_ts)
    if bnc_df.empty:
        print(f"[WARN] No Binance data for {market}; skipping.")
        return

    # --- align on minute index ---
    idx = bst_df.index.union(bnc_df.index)
    bst_df = bst_df.reindex(idx).ffill()
    bnc_df = bnc_df.reindex(idx).ffill()

    # --- build output dataframe ---
    rows = []
    for ts in idx:
        fx = fill_fx(fx_series, ts.to_pydatetime())
        bst_close = bst_df.loc[ts, "close"]
        bnc_close = bnc_df.loc[ts, "close"]

        rows.append({
            "timestamp":      ts.isoformat(),
            "bsdex_bid":      round(bst_close * (1 - HALF_SPREAD), 4),
            "bsdex_ask":      round(bst_close * (1 + HALF_SPREAD), 4),
            "world_bid_eur":  round(bnc_close * fx * (1 - HALF_SPREAD), 4),
            "world_ask_eur":  round(bnc_close * fx * (1 + HALF_SPREAD), 4),
            "fx_rate":        round(fx, 6),
            "phase":          "",   # not available from historical REST; populated by live recorder
        })

    out_df = pd.DataFrame(rows)
    out_path = OUT_DIR / f"{cfg['output_file']}.csv"
    out_df.to_csv(out_path, index=False)
    print(f"[OK] Saved {len(out_df)} rows → {out_path}")

    # --- meta file ---
    meta = {
        "market": market,
        "venue_a": {
            "label": "BSDEX (Bitstamp proxy)",
            "source": "bitstamp_ohlcv_rest",
            "pair": cfg["bitstamp_pair"],
            "note": (
                "BSDEX historical data requires authentication (HTTP 401 for all "
                "unauthenticated requests, verified May 2026).  Bitstamp EUR prices "
                "are used as a proxy — a regulated EU exchange with comparable "
                "liquidity.  Phase data is not available from the historical REST "
                "endpoint and is left blank; live-recorded CSV rows will include it."
            ),
        },
        "venue_b": {
            "label": "World (Binance price · LMAX fee model)",
            "source": "binance_ohlcv_ccxt",
            "symbol": cfg["binance_symbol"],
            "note": (
                "Binance USDT prices converted to EUR via ECB daily FX rate "
                "(Frankfurter API).  LMAX Digital fee schedule is applied — this is "
                "a modelling assumption, not a confirmed live LMAX connection."
            ),
        },
        "fx_source": "https://api.frankfurter.app (ECB daily reference rate)",
        "fx_granularity": "daily, forward-filled to 1-min bars",
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "rows": len(out_df),
        "granularity": "1m",
        "columns": list(out_df.columns),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "honesty_note": (
            "This dataset does NOT contain real BSDEX prices or real BSDEX phase "
            "transitions.  It is a reasonable proxy for backtesting the spread "
            "dynamics between a EUR-denominated regulated exchange (Bitstamp) and "
            "the global Binance price.  Do not present it as confirmed BSDEX history."
        ),
    }
    meta_path = OUT_DIR / f"{cfg['output_file']}.meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved meta  → {meta_path}")


# ── Live recorder (--record mode) ─────────────────────────────────────────────

async def live_record(markets_cfg: dict):
    """Append real-time Bitstamp top-of-book ticks to the CSV files."""
    import aiohttp as aio

    print("\n[Recorder] Starting live Bitstamp recorder (Ctrl-C to stop)…")
    fx_rate = 0.90

    # bootstrap FX
    try:
        r = requests.get(FX_RATE_SOURCE, timeout=5)
        fx_rate = float(r.json()["rates"]["EUR"])
        print(f"[Recorder] FX: 1 USD = {fx_rate:.5f} EUR")
    except Exception as e:
        print(f"[Recorder] FX fetch failed ({e}); using {fx_rate}")

    while True:
        ts = datetime.now(timezone.utc)
        for market, cfg in markets_cfg.items():
            out_path = OUT_DIR / f"{cfg['output_file']}.csv"
            bitstamp_ticker = cfg["bitstamp_pair"]
            try:
                async with aio.ClientSession() as session:
                    async with session.get(
                        f"https://www.bitstamp.net/api/v2/ticker/{bitstamp_ticker}/",
                        timeout=aio.ClientTimeout(total=5),
                    ) as resp:
                        d = await resp.json()
                        bid_a = float(d["bid"])
                        ask_a = float(d["ask"])

                    # world price from Binance
                    pair = cfg["binance_symbol"].replace("/", "")
                    async with session.get(
                        f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={pair}",
                        timeout=aio.ClientTimeout(total=5),
                    ) as resp2:
                        bd = await resp2.json()
                        bid_b = float(bd["bidPrice"]) * fx_rate
                        ask_b = float(bd["askPrice"]) * fx_rate

                row = {
                    "timestamp": ts.isoformat(),
                    "bsdex_bid": round(bid_a, 4),
                    "bsdex_ask": round(ask_a, 4),
                    "world_bid_eur": round(bid_b, 4),
                    "world_ask_eur": round(ask_b, 4),
                    "fx_rate": round(fx_rate, 6),
                    "phase": "continuous-trading",  # Bitstamp is always continuous
                }
                row_df = pd.DataFrame([row])
                row_df.to_csv(out_path, mode="a", header=not out_path.exists(), index=False)

            except Exception as exc:
                print(f"[Recorder] {market} error: {exc}")

        await asyncio.sleep(5)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download BSDEX historical data (Bitstamp proxy).")
    parser.add_argument("--days", type=int, default=7, help="Days of history to download (default 7)")
    parser.add_argument("--record", action="store_true", help="After download, start live recorder")
    args = parser.parse_args()

    for market, cfg in MARKET_MAP.items():
        print(f"\n=== {market.upper()} ===")
        merge_and_save(market, cfg, days=args.days)

    if args.record:
        asyncio.run(live_record(MARKET_MAP))


if __name__ == "__main__":
    main()
