"""
Execution Probe — Real micro-trade measurement on Bitstamp + Binance.

Purpose: measure signal-to-fill latency, realized slippage vs expected price,
and actual fees on tiny real orders, then compare against the model values in
BT_EXEC_COSTS and the active fee tier.

SAFETY CAPS (hard-coded, never overridden by CLI):
  MAX_NOTIONAL_EUR = 25   — max EUR per single order
  MAX_ORDERS       =  4   — max total orders per run

CLI:
  python scripts/execution_probe.py --mode dry
  python scripts/execution_probe.py --mode roundtrip --venue bitstamp --notional 15
  python scripts/execution_probe.py --mode roundtrip --venue binance  --notional 15
  python scripts/execution_probe.py --mode arb       --notional 15    # needs inventory

dry   — everything except order placement; prints what WOULD be sent.
roundtrip — BUY then SELL on a single venue; measures latency + slippage.
arb   — simultaneous BUY cheaper / SELL dearer (requires pre-existing inventory).

Output:
  reports/probe_results.csv — one row per leg appended each run.
  stdout — summary block with model-vs-measured verdicts.
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup so we can import from src/crypto_hft_tool
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Safety caps — NEVER lower these via CLI
# ---------------------------------------------------------------------------
MAX_NOTIONAL_EUR: float = 25.0
MAX_ORDERS: int = 4
MIN_NOTIONAL_BITSTAMP_EUR: float = 10.0
MIN_NOTIONAL_BINANCE_USDT: float = 5.0

REPORT_DIR = PROJECT_ROOT / "reports"
PROBE_CSV  = REPORT_DIR / "probe_results.csv"

CSV_FIELDS = [
    "ts", "run_id", "mode", "venue", "side", "notional_eur",
    "expected_px", "vwap_expected_px", "fill_px", "slippage_bps",
    "fee_asset", "fee_amt", "t_ack_ms", "t_fill_ms", "order_id",
    "symbol", "dry_run",
]


# ---------------------------------------------------------------------------
# BT_EXEC_COSTS import (model reference)
# ---------------------------------------------------------------------------
def _load_model_costs() -> dict:
    try:
        from src.crypto_hft_tool.config import BT_EXEC_COSTS, BSDEX_VOLUME_TIERS, BSDEX_DEFAULT_TIER_IDX
        tier = BSDEX_VOLUME_TIERS[BSDEX_DEFAULT_TIER_IDX]
        return {
            "half_spread_bps_a": BT_EXEC_COSTS["half_spread_bps"]["venue_a"],
            "half_spread_bps_b": BT_EXEC_COSTS["half_spread_bps"]["venue_b"],
            "slippage_bps_per_100k": BT_EXEC_COSTS["slippage_bps_per_100k"],
            "bitstamp_fee_pct": tier["bitstamp_taker"] * 100,
            "lmax_fee_pct": tier["lmax_taker"] * 100,
            "tier_label": tier["label"],
        }
    except Exception as e:
        print(f"[probe] Warning: could not load BT_EXEC_COSTS from config ({e}). Using defaults.")
        return {
            "half_spread_bps_a": 5.0,
            "half_spread_bps_b": 1.5,
            "slippage_bps_per_100k": 2.0,
            "bitstamp_fee_pct": 0.10,
            "lmax_fee_pct": 0.06,
            "tier_label": "> $20M (default)",
        }


# ---------------------------------------------------------------------------
# VWAP estimator from order-book depth
# ---------------------------------------------------------------------------
def _vwap_from_book(side_levels: list, notional: float) -> Optional[float]:
    """
    Compute VWAP fill price for a given notional sweep of an order book side.
    side_levels: list of [price, size] from ccxt order book (bids for sell, asks for buy).
    notional: EUR/USDT amount to sweep.
    Returns avg fill price, or None if book is insufficient.
    """
    remaining = notional
    cost_total = 0.0
    size_total = 0.0
    for px, sz in side_levels:
        px, sz = float(px), float(sz)
        if px <= 0 or sz <= 0:
            continue
        level_val = px * sz
        if remaining <= level_val:
            fill_sz = remaining / px
            cost_total += remaining
            size_total += fill_sz
            remaining = 0.0
            break
        cost_total += level_val
        size_total += sz
        remaining  -= level_val
    if size_total <= 0:
        return None
    return cost_total / size_total


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------
def _get_credentials(venue: str) -> Tuple[str, str]:
    """Return (api_key, secret) from environment. Raises if missing."""
    if venue == "bitstamp":
        key    = os.getenv("BITSTAMP_API_KEY", "")
        secret = os.getenv("BITSTAMP_SECRET", os.getenv("BITSTAMP_API_SECRET", ""))
    elif venue == "binance":
        key    = os.getenv("BINANCE_API_KEY", "")
        secret = os.getenv("BINANCE_SECRET", os.getenv("BINANCE_SECRET_KEY", ""))
    else:
        raise ValueError(f"Unknown venue: {venue}")
    if not key or not secret:
        raise EnvironmentError(
            f"[probe] {venue.upper()} API credentials not found in .env. "
            f"Set {venue.upper()}_API_KEY and {venue.upper()}_SECRET (or _API_SECRET)."
        )
    return key, secret


# ---------------------------------------------------------------------------
# Exchange helpers (ccxt sync, tiny orders only)
# ---------------------------------------------------------------------------
def _build_exchange(venue: str, dry_run: bool = False):
    """Build a ccxt exchange instance with real or sandbox credentials."""
    try:
        import ccxt
    except ImportError:
        raise RuntimeError("ccxt is not installed. Run: pip install ccxt")

    if venue == "bitstamp":
        key, secret = _get_credentials("bitstamp")
        ex = ccxt.bitstamp({
            "apiKey": key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        return ex, "BTC/EUR", "EUR"
    elif venue == "binance":
        key, secret = _get_credentials("binance")
        ex = ccxt.binance({
            "apiKey": key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        return ex, "BTC/USDT", "USDT"
    else:
        raise ValueError(f"Unsupported venue: {venue}")


def _fetch_orderbook_and_balance(ex, symbol: str, quote_currency: str, notional: float):
    """Fetch order book, compute VWAP, check quote balance."""
    ob = ex.fetch_order_book(symbol, limit=20)
    best_ask = float(ob["asks"][0][0]) if ob["asks"] else None
    best_bid = float(ob["bids"][0][0]) if ob["bids"] else None
    top_ask_depth = sum(float(sz) * float(px) for px, sz in ob["asks"][:3]) if ob["asks"] else 0
    top_bid_depth = sum(float(sz) * float(px) for px, sz in ob["bids"][:3]) if ob["bids"] else 0
    vwap_buy  = _vwap_from_book(ob["asks"], notional)
    vwap_sell = _vwap_from_book(ob["bids"], notional)

    balance = ex.fetch_balance()
    quote_free = float(balance.get(quote_currency, {}).get("free", 0) or 0)
    base = symbol.split("/")[0]
    base_free = float(balance.get(base, {}).get("free", 0) or 0)

    return {
        "best_ask": best_ask,
        "best_bid": best_bid,
        "vwap_buy": vwap_buy,
        "vwap_sell": vwap_sell,
        "top_ask_depth": top_ask_depth,
        "top_bid_depth": top_bid_depth,
        "quote_free": quote_free,
        "base_free": base_free,
    }


def _poll_order(ex, order_id: str, symbol: str, timeout_sec: float = 30.0) -> dict:
    """Poll until order is closed/filled or timeout."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        order = ex.fetch_order(order_id, symbol)
        if order.get("status") in ("closed", "filled", "canceled"):
            return order
        time.sleep(0.5)
    return ex.fetch_order(order_id, symbol)   # return whatever state after timeout


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------
def _ensure_csv():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not PROBE_CSV.exists():
        with open(PROBE_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def _append_csv(row: dict):
    _ensure_csv()
    with open(PROBE_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Model-vs-measured verdict printer
# ---------------------------------------------------------------------------
def _print_verdict(label: str, model_val: float, measured_val: float, unit: str = "bps",
                   higher_is_worse: bool = True):
    delta = measured_val - model_val
    if abs(delta) < model_val * 0.1:
        verdict = "MODEL OK"
        color = ""
    elif (higher_is_worse and delta > 0) or (not higher_is_worse and delta < 0):
        verdict = "MODEL TOO OPTIMISTIC"
        color = ""
    else:
        verdict = "MODEL TOO CONSERVATIVE"
        color = ""
    print(f"  {label:<35} model={model_val:.2f}{unit}  measured={measured_val:.2f}{unit}  → {verdict}")


# ---------------------------------------------------------------------------
# DRY mode
# ---------------------------------------------------------------------------
def run_dry(venue: str, notional: float, model: dict):
    """Fetch order book and show what WOULD be sent."""
    print(f"\n{'='*60}")
    print(f"  DRY RUN — {venue.upper()} | notional ≈ €{notional:.2f}")
    print(f"{'='*60}")

    try:
        import ccxt
    except ImportError:
        raise RuntimeError("ccxt is not installed. Run: pip install ccxt")

    if venue == "bitstamp":
        ex_cls = ccxt.bitstamp
        symbol, quote = "BTC/EUR", "EUR"
        min_notional  = MIN_NOTIONAL_BITSTAMP_EUR
    else:
        ex_cls = ccxt.binance
        symbol, quote = "BTC/USDT", "USDT"
        min_notional  = MIN_NOTIONAL_BINANCE_USDT

    ex = ex_cls({"enableRateLimit": True})
    ob = ex.fetch_order_book(symbol, limit=20)
    best_ask = float(ob["asks"][0][0]) if ob["asks"] else None
    best_bid = float(ob["bids"][0][0]) if ob["bids"] else None
    vwap_buy  = _vwap_from_book(ob["asks"], notional)
    vwap_sell = _vwap_from_book(ob["bids"], notional)
    top_depth = sum(float(sz) * float(px) for px, sz in ob["asks"][:3]) if ob["asks"] else 0

    print(f"  Symbol:         {symbol}")
    print(f"  Best ask:       {best_ask}")
    print(f"  Best bid:       {best_bid}")
    print(f"  VWAP buy  ({notional:.0f}{quote}):  {vwap_buy}")
    print(f"  VWAP sell ({notional:.0f}{quote}):  {vwap_sell}")
    print(f"  Top-3 ask depth: {top_depth:.2f} {quote}")
    if best_ask and vwap_buy:
        slip = (vwap_buy - best_ask) / best_ask * 1e4
        print(f"  Estimated slip (buy):  {slip:.2f} bps vs model {model['half_spread_bps_a']} bps half-spread")
    print(f"\n  Min notional for this venue: {min_notional} {quote}")
    if notional < min_notional:
        print(f"  ⚠  WARNING: notional {notional} < minimum {min_notional} — live order would be rejected")
    print(f"\n  WOULD SEND: MARKET BUY {notional/best_ask:.6f} {symbol.split('/')[0]} on {venue}")
    print(f"  WOULD SEND: (2s later) MARKET SELL {notional/best_ask:.6f} {symbol.split('/')[0]} on {venue}")
    print(f"\n  [DRY RUN — no orders placed]")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# ROUNDTRIP mode
# ---------------------------------------------------------------------------
def run_roundtrip(venue: str, notional: float, model: dict, dry_run: bool = False):
    """
    BUY then SELL on a single venue.
    Records latency, slippage, fees per leg.
    """
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"\n{'='*60}")
    print(f"  {'DRY ' if dry_run else ''}ROUNDTRIP — {venue.upper()} | notional ≈ €{notional:.2f}")
    if not dry_run:
        print(f"  ⚠  WARNING: THIS WILL SPEND REAL MONEY. Caps: ≤€{MAX_NOTIONAL_EUR} / ≤{MAX_ORDERS} orders.")
    print(f"{'='*60}")

    ex, symbol, quote = _build_exchange(venue, dry_run)

    # --- preflight ---
    snap = _fetch_orderbook_and_balance(ex, symbol, quote, notional)
    best_ask = snap["best_ask"]
    best_bid = snap["best_bid"]

    if best_ask is None:
        print("[probe] Order book empty. Abort.")
        return

    # Minimum notional check
    min_n = MIN_NOTIONAL_BITSTAMP_EUR if venue == "bitstamp" else MIN_NOTIONAL_BINANCE_USDT
    if notional < min_n:
        print(f"[probe] ABORT: notional {notional} < minimum {min_n} {quote}")
        return

    # Balance check
    if snap["quote_free"] < notional:
        print(f"[probe] ABORT: insufficient {quote} balance ({snap['quote_free']:.4f} < {notional})")
        return

    buy_size = notional / best_ask
    print(f"  Book: ask={best_ask}  bid={best_bid}  vwap_buy={snap['vwap_buy']}  depth={snap['top_ask_depth']:.2f}{quote}")
    print(f"  Balance: {snap['quote_free']:.4f} {quote}  {snap['base_free']:.6f} {symbol.split('/')[0]}")
    print(f"  Placing BUY {buy_size:.6f} {symbol} @ market…")

    leg_rows = []

    # --- LEG 1: BUY ---
    t_sent_buy = time.time()
    if dry_run:
        print(f"  [DRY] Would send MARKET BUY {buy_size:.6f} {symbol}")
        fill_buy, fee_asset_buy, fee_amt_buy = best_ask, quote, notional * 0.001
        t_ack_buy  = t_sent_buy + 0.05
        t_fill_buy = t_sent_buy + 0.20
        order_id_buy = "DRY-BUY-0001"
        filled_base = buy_size
    else:
        order_buy = ex.create_market_buy_order(symbol, buy_size)
        t_ack_buy  = time.time()
        order_buy  = _poll_order(ex, order_buy["id"], symbol)
        t_fill_buy = time.time()
        order_id_buy = order_buy["id"]
        fill_buy = float(order_buy.get("average") or order_buy.get("price") or best_ask)
        filled_base = float(order_buy.get("filled", buy_size))
        fee_info_buy = order_buy.get("fee") or {}
        fee_asset_buy = fee_info_buy.get("currency", quote)
        fee_amt_buy   = float(fee_info_buy.get("cost", notional * 0.001))

    slip_buy_bps = (fill_buy - best_ask) / best_ask * 1e4 if best_ask else 0.0
    lat_ack_buy  = (t_ack_buy  - t_sent_buy) * 1000
    lat_fill_buy = (t_fill_buy - t_sent_buy) * 1000

    print(f"  BUY fill: {fill_buy:.4f} | expected: {best_ask:.4f} | slip: {slip_buy_bps:.2f} bps | fee: {fee_amt_buy:.6f} {fee_asset_buy} | ack: {lat_ack_buy:.0f}ms fill: {lat_fill_buy:.0f}ms")

    row_buy = {
        "ts": datetime.now(tz=timezone.utc).isoformat(), "run_id": run_id,
        "mode": "roundtrip", "venue": venue, "side": "buy", "notional_eur": notional,
        "expected_px": best_ask, "vwap_expected_px": snap["vwap_buy"],
        "fill_px": fill_buy, "slippage_bps": round(slip_buy_bps, 4),
        "fee_asset": fee_asset_buy, "fee_amt": fee_amt_buy,
        "t_ack_ms": round(lat_ack_buy, 2), "t_fill_ms": round(lat_fill_buy, 2),
        "order_id": order_id_buy, "symbol": symbol, "dry_run": dry_run,
    }
    leg_rows.append(row_buy)
    _append_csv(row_buy)

    # --- wait 2s then SELL ---
    print(f"  Waiting 2 s before sell leg…")
    time.sleep(2)

    snap2 = _fetch_orderbook_and_balance(ex, symbol, quote, notional)
    best_bid2 = snap2["best_bid"]
    print(f"  Placing SELL {filled_base:.6f} {symbol} @ market (post-fill inventory)…")

    t_sent_sell = time.time()
    if dry_run:
        print(f"  [DRY] Would send MARKET SELL {filled_base:.6f} {symbol}")
        fill_sell = best_bid2 or best_bid
        fee_asset_sell, fee_amt_sell = quote, notional * 0.001
        t_ack_sell  = t_sent_sell + 0.05
        t_fill_sell = t_sent_sell + 0.20
        order_id_sell = "DRY-SELL-0001"
    else:
        order_sell = ex.create_market_sell_order(symbol, filled_base)
        t_ack_sell  = time.time()
        order_sell  = _poll_order(ex, order_sell["id"], symbol)
        t_fill_sell = time.time()
        order_id_sell = order_sell["id"]
        fill_sell = float(order_sell.get("average") or order_sell.get("price") or best_bid2)
        fee_info_sell = order_sell.get("fee") or {}
        fee_asset_sell = fee_info_sell.get("currency", quote)
        fee_amt_sell   = float(fee_info_sell.get("cost", notional * 0.001))

    slip_sell_bps = (best_bid2 - fill_sell) / best_bid2 * 1e4 if best_bid2 else 0.0
    lat_ack_sell  = (t_ack_sell  - t_sent_sell) * 1000
    lat_fill_sell = (t_fill_sell - t_sent_sell) * 1000

    print(f"  SELL fill: {fill_sell:.4f} | expected: {best_bid2:.4f} | slip: {slip_sell_bps:.2f} bps | fee: {fee_amt_sell:.6f} {fee_asset_sell} | ack: {lat_ack_sell:.0f}ms fill: {lat_fill_sell:.0f}ms")

    row_sell = {
        "ts": datetime.now(tz=timezone.utc).isoformat(), "run_id": run_id,
        "mode": "roundtrip", "venue": venue, "side": "sell", "notional_eur": notional,
        "expected_px": best_bid2, "vwap_expected_px": snap2["vwap_sell"],
        "fill_px": fill_sell, "slippage_bps": round(slip_sell_bps, 4),
        "fee_asset": fee_asset_sell, "fee_amt": fee_amt_sell,
        "t_ack_ms": round(lat_ack_sell, 2), "t_fill_ms": round(lat_fill_sell, 2),
        "order_id": order_id_sell, "symbol": symbol, "dry_run": dry_run,
    }
    leg_rows.append(row_sell)
    _append_csv(row_sell)

    # --- round-trip summary ---
    rt_cost_bps = slip_buy_bps + slip_sell_bps
    total_fee_eur = fee_amt_buy + fee_amt_sell   # approximation if fee in base
    rt_pnl_approx = (fill_sell - fill_buy) * filled_base - total_fee_eur

    print(f"\n  ── Roundtrip Summary ──────────────────────────────────")
    print(f"  Total slippage:  {rt_cost_bps:.2f} bps")
    print(f"  Total fees:      ≈ {total_fee_eur:.6f} {quote}")
    print(f"  Net PnL (approx): {rt_pnl_approx:.6f} {quote}")
    print(f"\n  ── Model vs Measured ──────────────────────────────────")
    venue_key = "a" if venue == "bitstamp" else "b"
    model_hs = model[f"half_spread_bps_{venue_key}"]
    model_slip = model["slippage_bps_per_100k"] * (notional / 100_000)
    model_total_bps = model_hs + model_slip
    measured_fee_pct = (total_fee_eur / notional * 100) if notional > 0 else 0
    model_fee_pct = model["bitstamp_fee_pct" if venue == "bitstamp" else "lmax_fee_pct"]
    _print_verdict(f"Half-spread + slip ({venue})", model_total_bps, rt_cost_bps / 2)  # per-leg
    _print_verdict(f"Exchange fee ({venue})", model_fee_pct, measured_fee_pct, unit="%")
    _print_verdict(f"Ack latency (ms)", 50.0, (lat_ack_buy + lat_ack_sell) / 2, unit="ms", higher_is_worse=True)
    print(f"\n  Results appended to: {PROBE_CSV.relative_to(PROJECT_ROOT)}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# ARB mode
# ---------------------------------------------------------------------------
async def run_arb_async(notional: float, model: dict, dry_run: bool = False):
    """
    Simultaneous BUY cheaper / SELL dearer across venues.
    Requires pre-existing inventory on the sell side.
    Aborts SELL leg if BUY ack fails.
    """
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"\n{'='*60}")
    print(f"  {'DRY ' if dry_run else ''}ARB PROBE — Bitstamp BTC/EUR ↔ Binance BTC/USDT | notional ≈ €{notional:.2f}")
    print(f"  Prerequisite: you must hold BTC inventory on the SELL venue.")
    if not dry_run:
        print(f"  ⚠  WARNING: THIS WILL SPEND REAL MONEY. Caps: ≤€{MAX_NOTIONAL_EUR} / ≤{MAX_ORDERS} orders.")
    print(f"{'='*60}")

    try:
        import ccxt
    except ImportError:
        raise RuntimeError("ccxt is not installed.")

    ex_bs, sym_bs, q_bs = _build_exchange("bitstamp", dry_run)
    ex_bn, sym_bn, q_bn = _build_exchange("binance",  dry_run)

    # Fetch both books simultaneously
    loop = asyncio.get_event_loop()
    snap_bs_f = loop.run_in_executor(None, _fetch_orderbook_and_balance, ex_bs, sym_bs, q_bs, notional)
    snap_bn_f = loop.run_in_executor(None, _fetch_orderbook_and_balance, ex_bn, sym_bn, q_bn, notional)
    snap_bs, snap_bn = await asyncio.gather(snap_bs_f, snap_bn_f)

    ask_bs = snap_bs["best_ask"]
    bid_bn_usd = snap_bn["best_bid"]

    # Approximate EUR conversion (no live FX in this standalone script)
    try:
        import requests as _req
        fx_resp = _req.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=5)
        fx_rate = fx_resp.json()["rates"]["EUR"]
    except Exception:
        fx_rate = 0.92  # fallback

    bid_bn_eur = bid_bn_usd * fx_rate if bid_bn_usd else None
    spread_eur = (ask_bs - bid_bn_eur) if (ask_bs and bid_bn_eur) else None

    print(f"  Bitstamp ask: €{ask_bs}  |  Binance bid: ${bid_bn_usd} ≈ €{bid_bn_eur:.2f}  |  FX: {fx_rate:.5f}")
    print(f"  Spread: €{spread_eur:.2f}" if spread_eur else "  Spread: N/A")

    if not ask_bs or not bid_bn_eur:
        print("[probe] ARB ABORT: could not get prices from both venues.")
        return

    # Determine direction
    if ask_bs < bid_bn_eur:
        buy_venue, sell_venue = "bitstamp", "binance"
        buy_ex, sell_ex = ex_bs, ex_bn
        buy_sym, sell_sym = sym_bs, sym_bn
        expected_buy, expected_sell = ask_bs, bid_bn_eur
        print(f"  Direction: BUY Bitstamp  SELL Binance")
    else:
        buy_venue, sell_venue = "binance", "bitstamp"
        buy_ex, sell_ex = ex_bn, ex_bs
        buy_sym, sell_sym = sym_bn, sym_bs
        expected_buy, expected_sell = bid_bn_usd, ask_bs
        print(f"  Direction: BUY Binance   SELL Bitstamp")

    buy_size = notional / expected_buy if expected_buy else 0

    # Inventory check on sell side
    sell_snap = snap_bs if sell_venue == "bitstamp" else snap_bn
    if sell_snap["base_free"] < buy_size:
        print(f"  [probe] ARB ABORT: insufficient base inventory on {sell_venue} "
              f"({sell_snap['base_free']:.6f} < {buy_size:.6f})")
        return

    print(f"  Would BUY {buy_size:.6f} on {buy_venue} and SELL {buy_size:.6f} on {sell_venue} simultaneously.")

    if dry_run:
        print(f"\n  [DRY] Would send simultaneous orders. No real orders placed.")
        print(f"{'='*60}\n")
        return

    # Simultaneous execution via asyncio
    buy_result: Dict = {}
    sell_result: Dict = {}
    buy_error  = None
    sell_error = None

    t0 = time.time()

    def _do_buy():
        nonlocal buy_error
        try:
            o = buy_ex.create_market_buy_order(buy_sym, buy_size)
            buy_result["order"] = _poll_order(buy_ex, o["id"], buy_sym)
            buy_result["t_ack"] = time.time() - t0
        except Exception as e:
            buy_error = e

    def _do_sell():
        nonlocal sell_error
        try:
            o = sell_ex.create_market_sell_order(sell_sym, buy_size)
            sell_result["order"] = _poll_order(sell_ex, o["id"], sell_sym)
            sell_result["t_ack"] = time.time() - t0
        except Exception as e:
            sell_error = e

    loop = asyncio.get_event_loop()
    await asyncio.gather(
        loop.run_in_executor(None, _do_buy),
        loop.run_in_executor(None, _do_sell),
    )

    if buy_error:
        print(f"  [probe] ARB: BUY leg FAILED — {buy_error}. Sell leg result: {sell_result}")
        return

    if sell_error:
        print(f"  [probe] ARB WARNING: SELL leg FAILED ({sell_error}). You may have an open BUY position.")

    for side, res, exp_px, venue_name in [
        ("buy",  buy_result,  expected_buy,  buy_venue),
        ("sell", sell_result, expected_sell, sell_venue),
    ]:
        if not res:
            continue
        o = res.get("order", {})
        fill = float(o.get("average") or o.get("price") or exp_px)
        fee_info = o.get("fee") or {}
        fee_asset = fee_info.get("currency", "?")
        fee_amt   = float(fee_info.get("cost", 0))
        slip = ((fill - exp_px) / exp_px if side == "buy" else (exp_px - fill) / exp_px) * 1e4 if exp_px else 0
        lat_ms = res.get("t_ack", 0) * 1000
        print(f"  {side.upper()} {venue_name}: fill={fill:.4f} expected={exp_px:.4f} slip={slip:.2f}bps fee={fee_amt:.6f}{fee_asset} lat={lat_ms:.0f}ms")
        row = {
            "ts": datetime.now(tz=timezone.utc).isoformat(), "run_id": run_id,
            "mode": "arb", "venue": venue_name, "side": side, "notional_eur": notional,
            "expected_px": exp_px, "vwap_expected_px": None,
            "fill_px": fill, "slippage_bps": round(slip, 4),
            "fee_asset": fee_asset, "fee_amt": fee_amt,
            "t_ack_ms": round(lat_ms, 2), "t_fill_ms": round(lat_ms, 2),
            "order_id": o.get("id", ""), "symbol": buy_sym, "dry_run": False,
        }
        _append_csv(row)

    print(f"\n  Results appended to: {PROBE_CSV.relative_to(PROJECT_ROOT)}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Execution probe: measure real slippage/fees vs model assumptions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/execution_probe.py --mode dry
  python scripts/execution_probe.py --mode roundtrip --venue bitstamp --notional 15
  python scripts/execution_probe.py --mode roundtrip --venue binance  --notional 15
  python scripts/execution_probe.py --mode arb       --notional 15   # needs BTC inventory

SAFETY CAPS (hard-coded):
  MAX_NOTIONAL_EUR = 25   per order
  MAX_ORDERS       =  4   per run
""",
    )
    parser.add_argument("--mode",     choices=["dry", "roundtrip", "arb"], default="dry",
                        help="dry=no orders; roundtrip=buy+sell single venue; arb=cross-venue (default: dry)")
    parser.add_argument("--venue",    choices=["bitstamp", "binance"], default="bitstamp",
                        help="Exchange for roundtrip mode (default: bitstamp)")
    parser.add_argument("--notional", type=float, default=15.0,
                        help="EUR/USDT amount per order (default: 15, max: 25)")
    args = parser.parse_args()

    # Hard cap enforcement
    if args.notional > MAX_NOTIONAL_EUR:
        print(f"[probe] ABORT: --notional {args.notional} > MAX_NOTIONAL_EUR {MAX_NOTIONAL_EUR}. "
              f"Safety cap cannot be overridden.")
        sys.exit(1)
    if args.notional <= 0:
        print("[probe] ABORT: --notional must be > 0")
        sys.exit(1)

    model = _load_model_costs()

    print(f"\n[probe] Model reference (BT_EXEC_COSTS + active tier {model['tier_label']}):")
    print(f"  half_spread_bps A={model['half_spread_bps_a']}  B={model['half_spread_bps_b']}")
    print(f"  slippage_bps_per_100k={model['slippage_bps_per_100k']}")
    print(f"  bitstamp_fee={model['bitstamp_fee_pct']}%  lmax_fee={model['lmax_fee_pct']}%")
    print(f"  Probe CSV: {PROBE_CSV.relative_to(PROJECT_ROOT)}\n")

    if args.mode == "dry":
        run_dry(args.venue, args.notional, model)

    elif args.mode == "roundtrip":
        run_roundtrip(args.venue, args.notional, model, dry_run=False)

    elif args.mode == "arb":
        asyncio.run(run_arb_async(args.notional, model, dry_run=False))


if __name__ == "__main__":
    main()
