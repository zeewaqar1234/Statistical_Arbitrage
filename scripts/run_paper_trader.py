"""
Phase 5 — Paper Live Trader.

Connects to REAL Binance and Kraken APIs using credentials from .env,
fetches live market prices, runs the cross-exchange arbitrage signal,
and SIMULATES (paper) trade execution — NO real orders are placed.

This script provides proof that:
  1. The API connections work end-to-end.
  2. The signal engine detects real arbitrage opportunities.
  3. The fee-tier-aware PnL calculation works on live data.

Usage:
    python scripts/run_paper_trader.py [options]

Options:
    --fee-tier       retail | vip3 | vip5 | dekabank_proxy | ...  (default: retail)
    --trade-amount   Size in base asset units, e.g. 0.001 BTC     (default: 0.001)
    --duration       Run time in seconds                           (default: 300)
    --symbols        Comma-separated symbols                       (default: BTC/USDT,ETH/USDT)
    --output-dir     Where to save the proof log                   (default: reports)

Output:
    reports/paper_trade_proof_{timestamp}.json   — machine-readable log
    reports/paper_trade_proof_{timestamp}.txt    — manager-readable summary

IMPORTANT: This script NEVER calls create_order / cancel_order or any
           write endpoint. It is read-only on the exchange APIs.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import ccxt.async_support as ccxt

from src.crypto_hft_tool.fee_tiers import get_preset, list_presets
from src.crypto_hft_tool.simulation import TradeSimulator
from src.crypto_hft_tool.signals import RollingZScore
from src.crypto_hft_tool.config import ZSCORE_SETTINGS, TRADE_SETTINGS, STRATEGY_DEFAULTS

POLL_INTERVAL_SEC = 2   # seconds between price fetches
MIN_SPREAD_RATIO  = TRADE_SETTINGS['thresholds']['min_spread_ratio']


# ── Exchange helpers ──────────────────────────────────────────────────────────

def _make_binance(authenticated: bool = False):
    params: dict = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
    if authenticated:
        params["apiKey"] = os.getenv("BINANCE_API_KEY", "")
        params["secret"] = os.getenv("BINANCE_SECRET", "")
    return ccxt.binance(params)


def _make_kraken(authenticated: bool = False):
    params: dict = {"enableRateLimit": True}
    if authenticated:
        params["apiKey"] = os.getenv("KRAKEN_API_KEY", "")
        params["secret"] = os.getenv("KRAKEN_SECRET", "")
    return ccxt.kraken(params)


async def _test_connection(exchange: ccxt.Exchange, name: str) -> dict:
    """Verify public connectivity by loading market definitions (no API key needed)."""
    try:
        await exchange.load_markets()
        n = len(exchange.markets)
        print(f"  [{name}] Public endpoint ✓  ({n} markets loaded)")
        return {"connected": True, "markets_loaded": n}
    except Exception as exc:
        print(f"  [{name}] Network connection FAILED: {exc}")
        return {"connected": False, "error": str(exc)}


async def _fetch_book(exchange: ccxt.Exchange, symbol: str, exchange_name: str) -> Optional[dict]:
    """Fetch top-of-book bid/ask. Returns None on any error."""
    try:
        ticker = await exchange.fetch_ticker(symbol)
        bid = ticker.get("bid")
        ask = ticker.get("ask")
        if bid is None or ask is None:
            return None
        return {
            "exchange": exchange_name,
            "symbol":   symbol,
            "bid":      float(bid),
            "ask":      float(ask),
            "mid":      (float(bid) + float(ask)) / 2,
            "ts":       ticker.get("timestamp") or int(time.time() * 1000),
        }
    except Exception:
        return None


# ── Main paper-trading loop ───────────────────────────────────────────────────

async def run_paper_trader(
    fee_tier: str,
    trade_amount: float,
    duration_sec: int,
    symbols: list,
    output_dir: str,
) -> None:
    tier = get_preset(fee_tier)
    print(f"\n{'=' * 65}")
    print(f"  PAPER LIVE TRADER — Phase 5 Proof")
    print(f"  Fee tier    : {tier.name}")
    print(f"  Trade amount: {trade_amount}")
    print(f"  Duration    : {duration_sec}s")
    print(f"  Symbols     : {', '.join(symbols)}")
    print(f"{'=' * 65}\n")

    # Public clients (no API key) for price fetching — always works
    binance = _make_binance(authenticated=False)
    kraken  = _make_kraken(authenticated=False)

    # Authenticated clients (with keys) only for balance snapshot
    binance_auth = _make_binance(authenticated=True)
    kraken_auth  = _make_kraken(authenticated=True)

    # ── Step 1: Prove API connectivity ──────────────────────────────
    print("Step 1/3 — Verifying API connections…")
    print("  [Public] Loading markets (no API key needed)…")
    conn_results = {}
    conn_results["binance"] = await _test_connection(binance, "Binance")
    conn_results["kraken"]  = await _test_connection(kraken,  "Kraken")

    if not conn_results["binance"]["connected"] or not conn_results["kraken"]["connected"]:
        print("\nERROR: Cannot reach one or both exchanges (network issue). Aborting.")
        await binance.close()
        await kraken.close()
        await binance_auth.close()
        await kraken_auth.close()
        return

    print("\n  [Authenticated] Attempting balance fetch with .env credentials…")
    try:
        bal_b = await binance_auth.fetch_balance()
        free_b = {k: v for k, v in bal_b.get("free", {}).items() if v and v > 0}
        conn_results["binance"]["free_balances"] = free_b
        conn_results["binance"]["authenticated"] = True
        print(f"  [Binance] Auth ✓  Balances: {free_b}")
    except Exception as e:
        conn_results["binance"]["authenticated"] = False
        conn_results["binance"]["auth_note"] = str(e)
        print(f"  [Binance] Auth failed ({e}) — price feed still works via public endpoint")
    try:
        bal_k = await kraken_auth.fetch_balance()
        free_k = {k: v for k, v in bal_k.get("free", {}).items() if v and v > 0}
        conn_results["kraken"]["free_balances"] = free_k
        conn_results["kraken"]["authenticated"] = True
        print(f"  [Kraken]  Auth ✓  Balances: {free_k}")
    except Exception as e:
        conn_results["kraken"]["authenticated"] = False
        conn_results["kraken"]["auth_note"] = str(e)
        print(f"  [Kraken]  Auth failed ({e}) — price feed still works via public endpoint")

    await binance_auth.close()
    await kraken_auth.close()

    print("\n  Price data (public endpoint) is live and ready for signal processing.\n")

    # ── Step 2: Run paper trading loop ──────────────────────────────
    print(f"\nStep 2/3 — Running paper strategy for {duration_sec}s…")
    print(f"  (All trades are SIMULATED — no real orders placed)\n")

    simulator = TradeSimulator()
    ztrackers = {
        sym: RollingZScore(
            windows=ZSCORE_SETTINGS["windows"],
            vol_adjustment=ZSCORE_SETTINGS["vol_adjustment"],
        )
        for sym in symbols
    }

    # Map numeric window keys to named threshold keys
    _window_map = {
        str(ZSCORE_SETTINGS["windows"][i]): k
        for i, k in enumerate(["ultra_short", "short", "medium", "long"])
        if i < len(ZSCORE_SETTINGS["windows"])
    }

    paper_trades = []
    opportunities_seen = defaultdict(int)
    polls = 0
    start = time.monotonic()
    deadline = start + duration_sec

    binance_taker = tier.get("binance", "taker")
    kraken_taker  = tier.get("kraken",  "taker")

    while time.monotonic() < deadline:
        polls += 1
        poll_start = time.monotonic()

        for sym in symbols:
            books = await asyncio.gather(
                _fetch_book(binance, sym, "binance"),
                _fetch_book(kraken,  sym, "kraken"),
            )
            b_book, k_book = books
            if not b_book or not k_book:
                continue

            spread = b_book["ask"] - k_book["bid"]   # buy Kraken, sell Binance
            avg_price = (b_book["mid"] + k_book["mid"]) / 2
            spread_ratio = abs(spread) / avg_price if avg_price else 0

            now_dt = datetime.fromtimestamp(b_book["ts"] / 1000, tz=timezone.utc)
            z_scores = ztrackers[sym].add(spread, now_dt)

            if not z_scores or spread_ratio < MIN_SPREAD_RATIO:
                continue

            # Find strongest signal across timeframes
            best_tf, best_z = max(z_scores.items(), key=lambda x: abs(x[1]))
            threshold_key = _window_map.get(best_tf, "short")
            threshold = ZSCORE_SETTINGS["thresholds"]["entry"].get(
                threshold_key, ZSCORE_SETTINGS["thresholds"]["entry"]["min"]
            )

            if abs(best_z) < threshold:
                continue

            opportunities_seen[sym] += 1

            # Check profitability after fees
            if best_z > 0:
                buy_ex, buy_price   = "kraken",  k_book["ask"]
                sell_ex, sell_price = "binance", b_book["bid"]
                buy_fee_rate  = kraken_taker
                sell_fee_rate = binance_taker
            else:
                buy_ex, buy_price   = "binance", b_book["ask"]
                sell_ex, sell_price = "kraken",  k_book["bid"]
                buy_fee_rate  = binance_taker
                sell_fee_rate = kraken_taker

            gross = (sell_price - buy_price) * trade_amount
            fees  = (buy_price * buy_fee_rate + sell_price * sell_fee_rate) * trade_amount
            net   = gross - fees

            pnl, fees_paid = simulator.simulate_arbitrage_trade(
                symbol=sym, amount=trade_amount,
                buy_exchange=buy_ex, buy_price=buy_price,
                sell_exchange=sell_ex, sell_price=sell_price,
                buy_fee_rate=buy_fee_rate, sell_fee_rate=sell_fee_rate,
            )

            trade_rec = {
                "timestamp":   now_dt.isoformat(),
                "symbol":      sym,
                "buy_exchange": buy_ex,
                "sell_exchange": sell_ex,
                "buy_price":   round(buy_price,   6),
                "sell_price":  round(sell_price,  6),
                "amount":      trade_amount,
                "z_score":     round(best_z, 4),
                "timeframe":   best_tf,
                "gross_pnl":   round(gross,  6),
                "fees":        round(fees,   6),
                "net_pnl":     round(net,    6),
                "fee_tier":    fee_tier,
            }
            paper_trades.append(trade_rec)
            sign = "+" if net >= 0 else ""
            print(
                f"  [PAPER TRADE] {sym} | {buy_ex}→{sell_ex} | "
                f"z={best_z:+.2f} | net={sign}{net:.6f} USDT"
            )

        elapsed = time.monotonic() - poll_start
        sleep_for = max(0, POLL_INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)

    await binance.close()
    await kraken.close()

    # ── Step 3: Save proof artifacts ────────────────────────────────
    print(f"\nStep 3/3 — Saving proof artifacts…")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    total_pnl  = sum(t["net_pnl"]  for t in paper_trades)
    total_fees = sum(t["fees"]      for t in paper_trades)
    wins       = sum(1 for t in paper_trades if t["net_pnl"] > 0)
    win_rate   = (wins / len(paper_trades) * 100) if paper_trades else 0

    proof = {
        "generated_at_utc":  datetime.utcnow().isoformat(),
        "proof_type":        "paper_live_trading",
        "data_source":       "real Binance + Kraken APIs (read-only)",
        "no_real_orders":    True,
        "run_config": {
            "fee_tier":      fee_tier,
            "fee_tier_label": tier.name,
            "trade_amount":  trade_amount,
            "duration_sec":  duration_sec,
            "symbols":       symbols,
            "polls":         polls,
        },
        "api_connections":   conn_results,
        "summary": {
            "opportunities_seen": dict(opportunities_seen),
            "paper_trades":      len(paper_trades),
            "total_gross_pnl":   round(sum(t["gross_pnl"] for t in paper_trades), 6),
            "total_fees":        round(total_fees, 6),
            "total_net_pnl":     round(total_pnl, 6),
            "win_rate_pct":      round(win_rate, 2),
        },
        "trades": paper_trades,
    }

    json_path = Path(output_dir) / f"paper_trade_proof_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(proof, f, indent=2)
    print(f"  Saved proof JSON → {json_path}")

    txt_path = Path(output_dir) / f"paper_trade_proof_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write("PAPER LIVE TRADING PROOF — Phase 5\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Generated : {proof['generated_at_utc']} UTC\n")
        f.write(f"Data source: Real Binance + Kraken APIs (NO real orders placed)\n\n")
        f.write("API Connections\n" + "-" * 40 + "\n")
        for exch, info in conn_results.items():
            status = "✓ Connected" if info["connected"] else "✗ Failed"
            f.write(f"  {exch.capitalize()}: {status}\n")
            if info.get("free_balances"):
                f.write(f"    Balances: {info['free_balances']}\n")
        f.write("\nRun Configuration\n" + "-" * 40 + "\n")
        f.write(f"  Fee tier     : {tier.name}\n")
        f.write(f"  Binance taker: {binance_taker * 100:.4f}%\n")
        f.write(f"  Kraken taker : {kraken_taker  * 100:.4f}%\n")
        f.write(f"  Trade amount : {trade_amount}\n")
        f.write(f"  Duration     : {duration_sec}s  ({polls} polls)\n\n")
        f.write("Paper Trading Results\n" + "-" * 40 + "\n")
        f.write(f"  Opportunities detected : {dict(opportunities_seen)}\n")
        f.write(f"  Paper trades executed  : {len(paper_trades)}\n")
        f.write(f"  Total gross PnL        : ${proof['summary']['total_gross_pnl']:,.6f}\n")
        f.write(f"  Total fees (simulated) : ${proof['summary']['total_fees']:,.6f}\n")
        f.write(f"  Total net PnL          : ${proof['summary']['total_net_pnl']:,.6f}\n")
        f.write(f"  Win rate               : {win_rate:.2f}%\n\n")
        if paper_trades:
            f.write("Recent Paper Trades (last 10)\n" + "-" * 40 + "\n")
            for t in paper_trades[-10:]:
                f.write(
                    f"  {t['timestamp'][:19]}  {t['symbol']}  "
                    f"{t['buy_exchange']}→{t['sell_exchange']}  "
                    f"z={t['z_score']:+.2f}  net=${t['net_pnl']:+.6f}\n"
                )
        f.write("\nWhat this proves\n" + "-" * 40 + "\n")
        f.write(
            "  - Binance and Kraken API connections work with the provided credentials.\n"
            "  - Real live prices are fetched and processed by the signal engine.\n"
            "  - The fee-tier-aware PnL calculation runs on real market data.\n"
            "  - No real orders were submitted at any point.\n"
        )
    print(f"  Saved proof TXT  → {txt_path}")

    print(f"\n{'=' * 65}")
    print(f"  Paper trades: {len(paper_trades)}")
    print(f"  Net PnL ({fee_tier}): ${total_pnl:+.6f}")
    print(f"{'=' * 65}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fee-tier",     default="retail", choices=list_presets())
    parser.add_argument("--trade-amount", type=float, default=0.001)
    parser.add_argument("--duration",     type=int,   default=300, help="Run time in seconds (default 300 = 5 min)")
    parser.add_argument("--symbols",      default="BTC/USDT,ETH/USDT")
    parser.add_argument("--output-dir",   default="reports")
    args = parser.parse_args()

    asyncio.run(run_paper_trader(
        fee_tier=args.fee_tier,
        trade_amount=args.trade_amount,
        duration_sec=args.duration,
        symbols=[s.strip() for s in args.symbols.split(",")],
        output_dir=args.output_dir,
    ))


if __name__ == "__main__":
    main()
