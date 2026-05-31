"""
Download 1-minute OHLCV candle data from Binance and Kraken via ccxt (no API key needed),
reconstruct bid/ask from close price ± per-exchange spread, align timestamps, and write
the result to data/processed/{SYMBOL}_real_1m.csv.

Usage:
    python scripts/download_real_data.py

Outputs for each symbol:
    data/processed/BTC_USDT_real_1m.csv       — aligned bid/ask data
    data/processed/BTC_USDT_real_1m.meta.json — provenance / transparency record

IMPORTANT CAVEAT (document in any report that uses this data):
    Bid/ask prices here are *reconstructed* from 1-minute candle close prices ±
    a constant per-symbol spread. This is NOT true L2 orderbook data.
    Real bid/ask differs in three ways:
      1. Real spread varies with volatility; ours is constant.
      2. Real depth is limited; we assume infinite size at the top of book.
      3. Real fills include slippage and partial fills.
    For a production backtest, paid L2 data (Tardis.dev, Kaiko) would be needed.
    For a manager demo, candle-derived bid/ask is acceptable IF this caveat is stated.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt.async_support as ccxt
import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────────

SYMBOLS = ["BTC/USDT", "ETH/USDT"]

# Number of 1-minute candles to fetch — 10080 = one full week
NUM_CANDLES = 10080

# Spread assumptions in basis points (bps) for bid/ask reconstruction.
# Binance typically tighter than Kraken for top pairs.
SPREAD_BPS_BY_EXCHANGE: dict = {
    "binance": {"BTC/USDT": 1.0, "ETH/USDT": 1.5},
    "kraken":  {"BTC/USDT": 4.0, "ETH/USDT": 6.0},
}

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _reconstruct_bid_ask(close: pd.Series, spread_bps: float) -> tuple[pd.Series, pd.Series]:
    """Return (bid, ask) reconstructed from close ± half spread."""
    half_spread = close * (spread_bps / 10_000) / 2
    return close - half_spread, close + half_spread


async def _fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, num_candles: int) -> pd.DataFrame:
    """Fetch up to `num_candles` 1-minute candles in batched requests."""
    all_candles: list = []
    limit_per_request = 1000  # safe maximum for both exchanges
    since: int | None = None

    # Work backwards: calculate the earliest timestamp we need
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since = now_ms - num_candles * 60 * 1000  # go back num_candles minutes

    while len(all_candles) < num_candles:
        batch = await exchange.fetch_ohlcv(symbol, timeframe="1m", since=since, limit=limit_per_request)
        if not batch:
            break
        all_candles.extend(batch)
        if len(batch) < limit_per_request:
            break  # reached the available data boundary
        since = batch[-1][0] + 60_000  # next minute after last fetched

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return df.tail(num_candles).reset_index(drop=True)


async def download_symbol(symbol: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"Downloading {symbol}")
    print(f"{'=' * 60}")

    binance = ccxt.binance({"enableRateLimit": True})
    kraken  = ccxt.kraken({"enableRateLimit": True})

    try:
        print(f"  Fetching Binance {symbol} ({NUM_CANDLES} candles) …")
        df_binance = await _fetch_ohlcv(binance, symbol, NUM_CANDLES)
        print(f"  → {len(df_binance)} rows from Binance")

        print(f"  Fetching Kraken {symbol} ({NUM_CANDLES} candles) …")
        df_kraken = await _fetch_ohlcv(kraken, symbol, NUM_CANDLES)
        print(f"  → {len(df_kraken)} rows from Kraken")
    finally:
        await binance.close()
        await kraken.close()

    if df_binance.empty or df_kraken.empty:
        print(f"  ERROR: One or both exchanges returned no data for {symbol}. Skipping.")
        return

    # Reconstruct bid/ask
    b_spread_bps = SPREAD_BPS_BY_EXCHANGE["binance"][symbol]
    k_spread_bps = SPREAD_BPS_BY_EXCHANGE["kraken"][symbol]

    df_binance["bid"], df_binance["ask"] = _reconstruct_bid_ask(df_binance["close"], b_spread_bps)
    df_kraken["bid"],  df_kraken["ask"]  = _reconstruct_bid_ask(df_kraken["close"],  k_spread_bps)

    # Align on minute-level timestamp (inner join — only rows both exchanges have)
    df_b = df_binance[["timestamp", "bid", "ask"]].rename(
        columns={"bid": "binance_bid", "ask": "binance_ask"}
    )
    df_k = df_kraken[["timestamp", "bid", "ask"]].rename(
        columns={"bid": "kraken_bid", "ask": "kraken_ask"}
    )
    merged = pd.merge(df_b, df_k, on="timestamp", how="inner").sort_values("timestamp")
    print(f"  → {len(merged)} aligned rows after inner join")

    if len(merged) < 7000:
        print(f"  WARNING: Only {len(merged)} rows. Expected ≥ 7000. Check exchange data availability.")

    # Save CSV
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("/", "_")
    csv_path = DATA_DIR / f"{safe_symbol}_real_1m.csv"
    merged.to_csv(csv_path, index=False)
    print(f"  Saved → {csv_path}")

    # Save metadata
    meta = {
        "source": "binance + kraken via ccxt (public endpoints, no API key)",
        "symbol": symbol,
        "timeframe": "1m",
        "candle_count": len(merged),
        "date_range_utc": {
            "start": str(merged["timestamp"].iloc[0]),
            "end":   str(merged["timestamp"].iloc[-1]),
        },
        "spread_reconstruction": {
            "method": "close_price +/- half_spread",
            "binance_spread_bps": b_spread_bps,
            "kraken_spread_bps":  k_spread_bps,
            "caveat": (
                "This is NOT true L2 orderbook data. Spread is constant; real spread "
                "varies with volatility. No slippage or partial fills are modelled."
            ),
        },
        "download_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "columns": list(merged.columns),
    }
    meta_path = DATA_DIR / f"{safe_symbol}_real_1m.meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"  Saved → {meta_path}")


async def main() -> None:
    for symbol in SYMBOLS:
        await download_symbol(symbol)
    print("\nDone. Use backtest.py to run the strategy against these files.")


if __name__ == "__main__":
    asyncio.run(main())
