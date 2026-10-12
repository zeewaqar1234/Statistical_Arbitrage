"""
BSDEX vs World — Historical Backtest Engine
============================================
Fetches REAL 1-minute OHLCV from:
  Venue A — Bitstamp public API (BTC/EUR or ETH/EUR)
  Venue B — Binance  public API (BTC/USDT or ETH/USDT)
  FX      — Binance EURUSDT 1m klines (primary); Frankfurter daily (fallback)

Runs the same spread / z-score logic as the live strategy and returns a
dual-scenario report:
  "upper_bound" — mid-price fills, P4 exec costs zeroed (minus P1/P2 bugs)
  "realistic"   — bid-ask half-spread + slippage applied at each fill

No synthetic data.  No injected spreads.  Actual exchange prices only.

Credibility fixes applied (FINAL_CREDIBILITY_FIXES.md):
  P1 — No win-rate-by-construction skip (losses are booked)
  P2 — Next-bar execution (fills use bar i+1 prices)
  P3 — Intraday EURUSDT 1m FX (daily ECB fallback tagged in meta)
  P4 — Half-spread + slippage cost model from BT_EXEC_COSTS
  P5 — Sharpe from daily returns on capital, annualised sqrt(365)
  P6 — Dual scenario: upper_bound + realistic
  P8 — Control pair: btc-eur-kraken (Bitstamp EUR vs Kraken EUR, fx=1.0)
"""

import asyncio
from bisect import bisect_left
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BITSTAMP_SYMBOL_MAP = {
    "btc-eur":        "BTC/EUR",
    "eth-eur":        "ETH/EUR",
    "btc-eur-kraken": "BTC/EUR",   # P8 control pair — Venue A = Bitstamp EUR
}
BINANCE_SYMBOL_MAP = {
    "btc-eur":        "BTC/USDT",
    "eth-eur":        "ETH/USDT",
}
KRAKEN_SYMBOL_MAP = {
    "btc-eur-kraken": "BTC/EUR",   # P8 control pair — Venue B = Kraken EUR
}

MAX_DAYS        = 7
CANDLE_TF       = "1m"
CANDLE_MS       = 60_000
ZSCORE_WIN      = 60
ZSCORE_TH       = 1.5
COOLDOWN_MIN    = 30
CHART_MAX_PTS   = 600

# Forward-fill FX gap tolerance: up to 5 minutes
FX_MAX_GAP_MS   = 5 * CANDLE_MS


# ---------------------------------------------------------------------------
# OHLCV fetching
# ---------------------------------------------------------------------------

async def _fetch_ohlcv(exchange_id: str, symbol: str,
                       since_ms: int, until_ms: int) -> List[List]:
    """Paginate 1-min OHLCV [ts, o, h, l, close, vol]. Deduped + sorted."""
    try:
        import ccxt.async_support as ccxt_async
    except ImportError:
        raise RuntimeError("ccxt is not installed. Run: pip install ccxt")

    ex_cls = getattr(ccxt_async, exchange_id)
    ex = ex_cls({"enableRateLimit": True})
    rows: List[List] = []
    try:
        cursor = since_ms
        while cursor < until_ms:
            batch = await ex.fetch_ohlcv(symbol, "1m", since=cursor, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            last_ts = batch[-1][0]
            if last_ts >= until_ms or len(batch) < 50:
                break
            cursor = last_ts + CANDLE_MS
            await asyncio.sleep(0.15)
    finally:
        await ex.close()

    seen: set = set()
    result: List[List] = []
    for c in rows:
        ts = c[0]
        if since_ms <= ts <= until_ms and ts not in seen:
            seen.add(ts)
            result.append(c)
    result.sort(key=lambda c: c[0])
    return result


# ---------------------------------------------------------------------------
# P3 — Intraday FX (Binance EURUSDT 1m primary; Frankfurter daily fallback)
# ---------------------------------------------------------------------------

async def _fetch_eurusdt_ohlcv(since_ms: int, until_ms: int) -> List[List]:
    """Fetch Binance EUR/USDT 1m candles for intraday FX."""
    try:
        return await _fetch_ohlcv("binance", "EUR/USDT", since_ms, until_ms)
    except Exception as e:
        logger.warning(f"[BT-FX] EURUSDT fetch failed ({e})")
        return []


async def _fetch_fx_range(start_date: str, end_date: str) -> Dict[str, float]:
    """Daily USD→EUR from Frankfurter (ECB reference). Returns {date: rate}."""
    url = f"https://api.frankfurter.app/{start_date}..{end_date}?from=USD&to=EUR"
    rates: Dict[str, float] = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json(content_type=None)
        if "rates" in data:
            for date_key, rate_val in data["rates"].items():
                if isinstance(rate_val, dict):
                    rates[date_key] = float(rate_val.get("EUR", 0.92))
                else:
                    rates[date_key] = float(rate_val)
    except Exception as e:
        logger.warning(f"[BT-FX] Frankfurter fetch failed ({e}), using fallback 0.92")
    return rates


def _build_intraday_fx_map(eurusdt_candles: List[List]) -> Dict[int, float]:
    """
    Build ts_ms → USD/EUR rate map from EURUSDT candles.
    rate = 1 / eurusdt_close  (EUR/USDT close → USD→EUR conversion factor)
    """
    fx_map: Dict[int, float] = {}
    for c in eurusdt_candles:
        ts, close = c[0], c[4]
        if close and close > 0:
            fx_map[ts] = 1.0 / float(close)
    return fx_map


def _fx_for_ts(ts_ms: int,
               intraday_map: Dict[int, float],
               daily_map: Dict[str, float],
               fallback: float = 0.92) -> float:
    """
    Intraday FX first (forward-fill up to 5 min); daily ECB as fallback.
    The 1m candle timestamps are aligned to the minute boundary, so we
    snap ts_ms to the nearest prior minute and look within FX_MAX_GAP_MS.
    """
    # Snap to 1-min boundary
    snapped = (ts_ms // CANDLE_MS) * CANDLE_MS
    best_ts = None
    best_rate = None
    for candidate_ts in range(snapped, snapped - FX_MAX_GAP_MS - CANDLE_MS, -CANDLE_MS):
        if candidate_ts in intraday_map:
            best_ts = candidate_ts
            best_rate = intraday_map[candidate_ts]
            break

    if best_rate is not None:
        return best_rate

    # Daily fallback (forward-fill)
    d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    if d in daily_map:
        return daily_map[d]
    for key in sorted(daily_map.keys(), reverse=True):
        if key <= d:
            return daily_map[key]
    return fallback


# ---------------------------------------------------------------------------
# Rolling z-score
# ---------------------------------------------------------------------------

def _rolling_zscore(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    z = np.full(n, np.nan)
    for i in range(window, n):
        w = arr[i - window: i]
        mu, sigma = float(np.mean(w)), float(np.std(w))
        z[i] = (arr[i] - mu) / sigma if sigma > 1e-10 else 0.0
    return z


# ---------------------------------------------------------------------------
# Chart downsampler
# ---------------------------------------------------------------------------

def _downsample(items: list, max_pts: int = CHART_MAX_PTS) -> list:
    if len(items) <= max_pts:
        return items
    step = max(1, len(items) // max_pts)
    return items[::step]


# ---------------------------------------------------------------------------
# P5 — Daily Sharpe
# ---------------------------------------------------------------------------

def _compute_daily_sharpe(
    trades: List[dict],
    capital_eur: float,
    ts_key: str = "ts",
    pnl_key: str = "pnl_eur",
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> Optional[float]:
    """
    Aggregate trade PnL into calendar-day returns on capital_eur.
    sharpe = mean(daily_returns) / std(daily_returns) * sqrt(365).
    Returns None with fewer than 30 trades or 20 days; includes idle days.
    Label in UI: "Sharpe (daily, ann.)"
    """
    if len(trades) < 30 or capital_eur <= 0:
        return None
    start_dt = start_dt or datetime.fromtimestamp(min(t[ts_key] for t in trades) / 1000, timezone.utc)
    end_dt = end_dt or datetime.fromtimestamp(max(t[ts_key] for t in trades) / 1000, timezone.utc)
    if (end_dt - start_dt).total_seconds() < 20 * 86400:
        return None

    daily: Dict[str, float] = defaultdict(float)
    for t in trades:
        ts_ms = t[ts_key]
        day = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[day] += t[pnl_key]

    day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end_dt:
        daily.setdefault(day.strftime("%Y-%m-%d"), 0.0)
        day += timedelta(days=1)

    daily_returns = np.array([v / capital_eur for v in daily.values()])
    mu  = float(np.mean(daily_returns))
    std = float(np.std(daily_returns, ddof=1))
    if std < 1e-10:
        return None
    return float(mu / std * math.sqrt(365))


# ---------------------------------------------------------------------------
# P4 — Cost model application
# ---------------------------------------------------------------------------

def _spread_pct_from_prices(buy_price: float, sell_price: float) -> float:
    """Executable spread % after cost-adjusted leg prices (before fee multiplier)."""
    mid = (buy_price + sell_price) / 2.0
    if mid <= 0:
        return 0.0
    return (sell_price - buy_price) / mid * 100.0


def _resolve_fill_index(i: int, ts_arr: List[int], latency_ms: int) -> Optional[int]:
    """Bar i+1 for candles; earliest index with ts >= ts[i]+latency for quote BT."""
    if latency_ms <= 0:
        j = i + 1
        return j if j < len(ts_arr) else None
    target = ts_arr[i] + latency_ms
    j = bisect_left(ts_arr, target, lo=i + 1)
    return j if j < len(ts_arr) else None


def _apply_exec_costs(
    mid_buy: float,
    mid_sell: float,
    buy_venue: str,          # "venue_a" | "venue_b"
    sell_venue: str,
    capital_eur: float,
    exec_costs: dict,
) -> Tuple[float, float, float]:
    """
    Adjust mid prices to executable buy/sell prices.

    Returns (adj_buy_price, adj_sell_price, slip_bps_applied).
    """
    hs = exec_costs["half_spread_bps"]
    slip_bps = exec_costs["slippage_bps_per_100k"] * (capital_eur / 100_000)

    hs_buy  = hs[buy_venue]
    hs_sell = hs[sell_venue]

    adj_buy  = mid_buy  * (1.0 + (hs_buy  + slip_bps) / 10_000)
    adj_sell = mid_sell * (1.0 - (hs_sell + slip_bps) / 10_000)
    return adj_buy, adj_sell, slip_bps


# ---------------------------------------------------------------------------
# Core simulation loop
# ---------------------------------------------------------------------------

def _simulate(
    ts_arr:       List[int],
    price_a_arr:  List[float],
    price_b_arr:  List[float],
    spreads:      np.ndarray,
    z_scores:     np.ndarray,
    venue_a_taker: float,
    venue_b_taker: float,
    capital_eur:   float,
    apply_exec_costs: bool,
    exec_costs:   dict,
    fill_latency_ms: int = 0,
    fx_cost_bps: Optional[float] = None,
) -> Tuple[List[dict], List[Tuple[int, float]]]:
    """
    Run the arbitrage simulation once.

    F1: Break-even gate uses signal-bar (i) cost-adjusted prices only.
    P2: Fills use bar i+1 (or first snapshot >= i + fill_latency_ms).
    P1: All committed trades are booked — losses at fill included.
    """
    from src.crypto_hft_tool.config import FX_COST_BPS

    fx_cost_rate = (FX_COST_BPS if fx_cost_bps is None else fx_cost_bps) / 10_000.0
    cooldown_ms   = COOLDOWN_MIN * 60_000
    last_trade_ts = 0
    cumulative    = 0.0

    trades:     List[dict] = []
    equity_pts: List[Tuple[int, float]] = [(ts_arr[0], 0.0)] if ts_arr else []

    n = len(ts_arr)
    for i in range(n):
        ts = ts_arr[i]
        z  = float(z_scores[i])
        sp = float(spreads[i])

        equity_pts.append((ts, cumulative))

        if math.isnan(z):
            continue

        fill_i = _resolve_fill_index(i, ts_arr, fill_latency_ms)
        if fill_i is None:
            continue

        # Gate: z-score + cooldown
        if not (abs(z) >= ZSCORE_TH and (ts - last_trade_ts) >= cooldown_ms):
            continue

        pa_sig = price_a_arr[i]
        pb_sig = price_b_arr[i]

        # Direction from signal-bar spread
        if sp > 0:
            mid_buy_sig, mid_sell_sig = pb_sig, pa_sig
            buy_venue, sell_venue = "venue_b", "venue_a"
            fee_buy, fee_sell   = venue_b_taker, venue_a_taker
            direction = "SELL Bitstamp / BUY Binance→EUR"
            buy_ex, sell_ex     = "Binance→EUR", "Bitstamp"
        else:
            mid_buy_sig, mid_sell_sig = pa_sig, pb_sig
            buy_venue, sell_venue = "venue_a", "venue_b"
            fee_buy, fee_sell   = venue_a_taker, venue_b_taker
            direction = "BUY Bitstamp / SELL Binance→EUR"
            buy_ex, sell_ex     = "Bitstamp", "Binance→EUR"

        # F1: break-even gate on signal bar (i) only
        if apply_exec_costs:
            sig_buy, sig_sell, _ = _apply_exec_costs(
                mid_buy_sig, mid_sell_sig, buy_venue, sell_venue, capital_eur, exec_costs
            )
        else:
            sig_buy, sig_sell = mid_buy_sig, mid_sell_sig

        eff_sell_sig = sig_sell * (1.0 - fee_sell)
        eff_buy_sig  = sig_buy  * (1.0 + fee_buy)
        fx_sig = (sig_buy if buy_venue == "venue_b" else sig_sell) * fx_cost_rate
        if eff_sell_sig <= eff_buy_sig + fx_sig:
            continue

        signal_spread_pct = _spread_pct_from_prices(sig_buy, sig_sell)

        # Fill prices from fill bar (committed regardless of fill-time profitability)
        pa_fill, pb_fill = price_a_arr[fill_i], price_b_arr[fill_i]
        mid_buy_fill, mid_sell_fill = ((pb_fill, pa_fill) if sp > 0 else (pa_fill, pb_fill))
        slip_bps_applied = 0.0
        if apply_exec_costs:
            buy_price, sell_price, slip_bps_applied = _apply_exec_costs(
                mid_buy_fill, mid_sell_fill, buy_venue, sell_venue, capital_eur, exec_costs
            )
        else:
            buy_price, sell_price = mid_buy_fill, mid_sell_fill

        realized_spread_pct = _spread_pct_from_prices(buy_price, sell_price)

        amount   = capital_eur / buy_price
        gross    = amount * (sell_price - buy_price)
        fx_cost_eur = amount * (buy_price if buy_venue == "venue_b" else sell_price) * fx_cost_rate
        fees_eur = (
            capital_eur * fee_buy
            + amount * sell_price * fee_sell
            + fx_cost_eur
        )
        pnl      = gross - fees_eur

        cumulative    += pnl
        last_trade_ts  = ts
        equity_pts.append((ts_arr[fill_i], cumulative))

        trades.append({
            "ts":                  ts_arr[fill_i],
            "signal_ts":           ts,
            "fill_ts":             ts_arr[fill_i],
            "fx_cost_eur":         round(fx_cost_eur, 4),
            "ts_str":              datetime.fromtimestamp(ts_arr[fill_i] / 1000, tz=timezone.utc).isoformat(),
            "direction":           direction,
            "spread_pct":          round(sp, 6),
            "signal_spread_pct":   round(signal_spread_pct, 6),
            "realized_spread_pct": round(realized_spread_pct, 6),
            "z_score":             round(z, 4),
            "price_a_eur":         round(pa_sig, 4),
            "price_b_eur":         round(pb_sig, 4),
            "fill_a_eur":          round(pa_fill, 4),
            "fill_b_eur":          round(pb_fill, 4),
            "amount":              round(amount, 6),
            "gross_eur":           round(gross, 4),
            "fees_eur":            round(fees_eur, 4),
            "pnl_eur":             round(pnl, 4),
            "buy_exchange":        buy_ex,
            "sell_exchange":       sell_ex,
            "slip_bps":            round(slip_bps_applied, 3),
        })

    if ts_arr:
        equity_pts.append((ts_arr[-1], cumulative))

    return trades, equity_pts


# ---------------------------------------------------------------------------
# Aggregate stats builder
# ---------------------------------------------------------------------------

def _build_scenario_result(
    trades:       List[dict],
    equity_pts:   List[Tuple[int, float]],
    ts_arr:       List[int],
    spreads:      np.ndarray,
    z_scores:     np.ndarray,
    symbol:       str,
    bs_sym:       str,
    bn_sym:       str,
    start_dt:     datetime,
    end_dt:       datetime,
    venue_a_taker: float,
    venue_b_taker: float,
    capital_eur:  float,
    tier_label:   str,
    apply_exec_costs: bool,
    exec_costs:   dict,
    fx_granularity: str,
    scenario_label: str,
) -> dict:
    n    = len(trades)
    wins = sum(1 for t in trades if t["pnl_eur"] > 0)
    loss = n - wins

    gross_pnl  = sum(t["gross_eur"] for t in trades)
    total_fees = sum(t["fees_eur"]  for t in trades)
    total_pnl  = sum(t["pnl_eur"]   for t in trades)

    # Max drawdown from the equity curve (P1: includes losses)
    max_dd = 0.0
    peak   = 0.0
    run    = 0.0
    for t in trades:
        run  += t["pnl_eur"]
        peak  = max(peak, run)
        max_dd = max(max_dd, peak - run)

    from src.crypto_hft_tool.config import FX_COST_BPS, POOLS, ECB_DFR

    duration_hours = (end_dt - start_dt).total_seconds() / 3600.0
    duration_days  = duration_hours / 24.0

    # P5 / F5: daily Sharpe — hide when sample too small
    sharpe = (
        _compute_daily_sharpe(trades, capital_eur, start_dt=start_dt, end_dt=end_dt)
        if n >= 30 and duration_days >= 20
        else None
    )

    carry_eur = capital_eur * POOLS * ECB_DFR * duration_hours / 8760.0
    net_after_carry = total_pnl - carry_eur

    fx_bps = 0.0 if symbol == "btc-eur-kraken" else FX_COST_BPS
    # Break-even pct: fees + FX desk cost (bps)
    be_fee_pct = (venue_a_taker + venue_b_taker) * 100 + fx_bps / 100.0

    # Exec cost meta for UI display
    slip_bps = exec_costs["slippage_bps_per_100k"] * (capital_eur / 100_000) if apply_exec_costs else 0.0
    spread_model = exec_costs.get("spread_model", "conservative")
    exec_meta = {
        "spread_model":            spread_model,
        "half_spread_bps_venue_a": exec_costs["half_spread_bps"]["venue_a"] if apply_exec_costs else 0.0,
        "half_spread_bps_venue_b": exec_costs["half_spread_bps"]["venue_b"] if apply_exec_costs else 0.0,
        "slippage_bps":            round(slip_bps, 3),
        "fx_cost_bps":             fx_bps,
        "calibration_source": exec_costs.get("calibration_source"),
        "calibration_samples": exec_costs.get("calibration_samples"),
        "carry_eur":               round(carry_eur, 4),
        "net_after_carry_eur":     round(net_after_carry, 4),
        "carry_dfr_source":        "ECB deposit facility 2.50% (16 Sep 2026)",
    }

    # Equity curve (downsampled)
    equity_ds = _downsample([
        {
            "ts_str":         datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
            "cumulative_pnl": round(pnl, 4),
        }
        for ts, pnl in equity_pts
    ])

    # Spread series (downsampled)
    full_spread = [
        {
            "ts_str":     datetime.fromtimestamp(ts_arr[i] / 1000, tz=timezone.utc).isoformat(),
            "spread_pct": round(float(spreads[i]), 6),
            "z_score":    round(float(z_scores[i]), 4) if not math.isnan(z_scores[i]) else None,
            "threshold":  ZSCORE_TH,
        }
        for i in range(len(ts_arr))
    ]
    spread_ds = _downsample(full_spread)

    return {
        "summary": {
            "scenario":             scenario_label,
            "symbol":               symbol.upper(),
            "bitstamp_symbol":      bs_sym,
            "world_symbol":         bn_sym,
            "start_dt":             start_dt.isoformat(),
            "end_dt":               end_dt.isoformat(),
            "duration_hours":       round((end_dt - start_dt).total_seconds() / 3600, 2),
            "candles_processed":    len(ts_arr),
            "total_trades":         n,
            "win_trades":           wins,
            "loss_trades":          loss,
            "win_rate_pct":         round(wins / n * 100, 2) if n > 0 else 0.0,
            "total_pnl_eur":        round(total_pnl,  4),
            "carry_eur": round(carry_eur, 4),
            "net_after_carry_eur": round(net_after_carry, 4),
            "fx_cost_eur": round(sum(t.get("fx_cost_eur", 0) for t in trades), 4),
            "gross_pnl_eur":        round(gross_pnl,  4),
            "total_fees_eur":       round(total_fees, 4),
            "max_drawdown_eur":     round(max_dd,     4),
            "sharpe_daily_ann":     round(sharpe, 4) if sharpe is not None else None,
            "venue_a_taker_pct":    round(venue_a_taker * 100, 4),
            "venue_b_taker_pct":    round(venue_b_taker * 100, 4),
            "breakeven_spread_pct": round(be_fee_pct, 4),
            "capital_eur":          capital_eur,
            "tier_label":           tier_label,
            "zscore_window_min":    ZSCORE_WIN,
            "zscore_threshold":     ZSCORE_TH,
            "trade_cooldown_min":   COOLDOWN_MIN,
            "fx_granularity":       fx_granularity,
            "exec_costs":           exec_meta,
            "data_sources": (
                "Bitstamp public OHLCV (EUR) + Binance public OHLCV (USDT→EUR) | "
                f"FX: Binance EURUSDT 1m ({fx_granularity})"
            ),
        },
        "equity_curve":  equity_ds,
        "spread_series": spread_ds,
        "trades":        trades,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _exec_costs_resolved(spread_model: str, quote_path=None, symbol="btc-eur", before_ts=None) -> dict:
    """Calibrate only from recorded quotes preceding the evaluation window."""
    from .config import BT_EXEC_COSTS
    from .quote_data import read_quotes, midpoint
    if spread_model not in ("conservative", "calibrated"):
        raise ValueError("spread_model must be conservative or calibrated")
    ec = {
        "half_spread_bps": dict(BT_EXEC_COSTS["half_spread_bps"]),
        "slippage_bps_per_100k": BT_EXEC_COSTS["slippage_bps_per_100k"],
        "spread_model": spread_model,
    }
    if spread_model == "calibrated":
        if not quote_path or before_ts is None:
            raise ValueError("Calibrated costs require a quote file/directory with snapshots before the backtest start")
        rows = [r for r in read_quotes(quote_path, symbol) if r["fresh"] and r["ts"] < before_ts]
        if not rows:
            raise ValueError("No valid calibration quotes precede the backtest start")
        ec["half_spread_bps"] = {
            f"venue_{venue}": float(np.median([
                float(min(r[venue]["asks"]) - max(r[venue]["bids"])) / (2 * midpoint(r[venue])) * 10_000
                for r in rows])) for venue in ("a", "b")
        }
        ec["calibration_source"] = str(quote_path)
        ec["calibration_samples"] = len(rows)
    return ec


def run_quote_backtest(
    path=None, latency_ms=300, tier=None, capital=1000, *, quote_path=None,
    symbol="btc-eur", start_dt=None, end_dt=None, venue_a_taker=None,
    venue_b_taker=None, capital_eur=None, tier_label="custom", spread_model="conservative",
) -> dict:
    """Signal on snapshot t; fill fixed quantity on the first later snapshot
    at/after t + latency. Uses executable side-specific FX and full-size VWAP.
    A missing/stale/insufficient first fill is reported, never searched past.
    """
    from .config import FX_COST_BPS, BSDEX_VOLUME_TIERS, BSDEX_DEFAULT_TIER_IDX
    from .quote_data import read_quotes, midpoint, vwap
    if symbol not in BINANCE_SYMBOL_MAP:
        raise ValueError("Recorded quotes support btc-eur and eth-eur")
    if latency_ms < 0:
        raise ValueError("latency_ms must be nonnegative")
    capital_eur = capital if capital_eur is None else capital_eur
    if not math.isfinite(capital_eur) or capital_eur <= 0:
        raise ValueError("capital must be positive and finite")
    if tier is not None and (not isinstance(tier, int) or not 0 <= tier < len(BSDEX_VOLUME_TIERS)):
        raise ValueError("tier must be a valid volume-tier index")
    preset = BSDEX_VOLUME_TIERS[BSDEX_DEFAULT_TIER_IDX if tier is None else tier]
    venue_a_taker = preset["bitstamp_taker"] if venue_a_taker is None else venue_a_taker
    venue_b_taker = preset["lmax_taker"] if venue_b_taker is None else venue_b_taker
    if any(not math.isfinite(f) or f < 0 for f in (venue_a_taker, venue_b_taker)):
        raise ValueError("Fees must be finite and nonnegative")
    if tier is not None:
        tier_label = preset["label"]
    rows = read_quotes(quote_path or path, symbol)
    if not rows:
        raise ValueError("No quotes for selected market")
    def utc(dt):
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    start_dt = utc(start_dt) if start_dt else datetime.fromtimestamp(rows[0]["ts"] / 1000, timezone.utc)
    end_dt = utc(end_dt) if end_dt else datetime.fromtimestamp(rows[-1]["ts"] / 1000, timezone.utc)
    if end_dt <= start_dt:
        raise ValueError("End date must be after start date")
    available_start = datetime.fromtimestamp(rows[0]["ts"] / 1000, timezone.utc).isoformat()
    available_end = datetime.fromtimestamp(rows[-1]["ts"] / 1000, timezone.utc).isoformat()
    rows = [r for r in rows if start_dt.timestamp() * 1000 <= r["ts"] <= end_dt.timestamp() * 1000]
    if len(rows) < 2:
        raise ValueError(f"No usable quotes in the selected dates. Available {symbol} quotes: {available_start} to {available_end}. Select dates inside this range.")
    if rows[-1]["ts"] - rows[0]["ts"] < ZSCORE_WIN * 60_000:
        raise ValueError(f"Recorded quotes need at least {ZSCORE_WIN} minutes for the signal window. Available {symbol} quotes: {available_start} to {available_end}. Keep the backend running to collect more data.")
    ts_arr = [r["ts"] for r in rows]
    a = np.array([midpoint(r["a"]) for r in rows])
    b = np.array([midpoint(r["b"]) for r in rows])
    spreads = (a - b) / b * 100
    # Preserve the 60-minute signal window at a one-second recording cadence.
    # Only earlier snapshots contribute to the rolling mean and variance.
    z_scores = np.full(len(rows), np.nan)
    sums = np.r_[0., np.cumsum(spreads)]
    squares = np.r_[0., np.cumsum(spreads ** 2)]
    for i, ts in enumerate(ts_arr):
        left = bisect_left(ts_arr, ts - ZSCORE_WIN * 60_000)
        count = i - left
        if ts - ts_arr[0] < ZSCORE_WIN * 60_000 or count < 2:
            continue
        mean = (sums[i] - sums[left]) / count
        variance = max(0., (squares[i] - squares[left]) / count - mean * mean)
        z_scores[i] = (spreads[i] - mean) / math.sqrt(variance) if variance > 1e-20 else 0.
    trades, failures = [], []
    equity = [(ts_arr[0], 0.)]
    cumulative, last_signal, busy_until = 0., -float("inf"), -float("inf")
    for i, row in enumerate(rows):
        ts = row["ts"]
        if (not row["fresh"] or not np.isfinite(z_scores[i]) or abs(z_scores[i]) < ZSCORE_TH
                or ts - last_signal < COOLDOWN_MIN * 60_000 or ts <= busy_until):
            continue
        sell_a = spreads[i] > 0
        buy_venue, sell_venue = ("b", "a") if sell_a else ("a", "b")
        fee_buy, fee_sell = (venue_b_taker, venue_a_taker) if sell_a else (venue_a_taker, venue_b_taker)
        amount = capital_eur / float(min(row[buy_venue]["asks"]))
        sig_buy = vwap(row[buy_venue], "buy", amount)
        sig_sell = vwap(row[sell_venue], "sell", amount)
        if sig_buy is None or sig_sell is None:
            continue
        fx_rate = FX_COST_BPS / 10_000
        fx_signal = (sig_buy if sell_a else sig_sell) * fx_rate
        if sig_sell * (1 - fee_sell) <= sig_buy * (1 + fee_buy) + fx_signal:
            continue
        last_signal = ts
        j = bisect_left(ts_arr, ts + latency_ms, lo=i + 1)
        if j == len(rows):
            failures.append({"signal_ts": ts, "reason": "NO_FILL_SNAPSHOT"})
            continue
        fill = rows[j]
        busy_until = fill["ts"]
        if not fill["fresh"] or fill["ts"] - (ts + latency_ms) > 2000:
            failures.append({"signal_ts": ts, "fill_ts": fill["ts"], "reason": "QUOTE_GAP_OR_STALE"})
            continue
        buy = vwap(fill[buy_venue], "buy", amount)
        sell = vwap(fill[sell_venue], "sell", amount)
        if buy is None or sell is None:
            failures.append({"signal_ts": ts, "fill_ts": fill["ts"], "reason": "INSUFFICIENT_DEPTH"})
            continue
        gross = amount * (sell - buy)
        fx_cost = amount * (buy if sell_a else sell) * fx_rate
        fees = amount * (buy * fee_buy + sell * fee_sell) + fx_cost
        pnl = gross - fees
        cumulative += pnl
        equity.append((fill["ts"], cumulative))
        trades.append({
            "ts": fill["ts"], "ts_str": datetime.fromtimestamp(fill["ts"] / 1000, timezone.utc).isoformat(),
            "signal_ts": ts, "fill_ts": fill["ts"], "fill_latency_ms": fill["ts"] - ts,
            "direction": "SELL Bitstamp / BUY Binance→EUR" if sell_a else "BUY Bitstamp / SELL Binance→EUR",
            "buy_exchange": "Binance→EUR" if sell_a else "Bitstamp",
            "sell_exchange": "Bitstamp" if sell_a else "Binance→EUR",
            "spread_pct": float(spreads[i]), "z_score": float(z_scores[i]),
            "signal_spread_pct": _spread_pct_from_prices(sig_buy, sig_sell),
            "realized_spread_pct": _spread_pct_from_prices(buy, sell),
            "price_a_eur": a[i], "price_b_eur": b[i],
            "fill_a_eur": sell if sell_a else buy, "fill_b_eur": buy if sell_a else sell,
            "amount": amount, "gross_eur": gross, "fees_eur": fees, "pnl_eur": pnl,
            "fx_cost_eur": fx_cost, "price_model": "recorded_vwap", "slip_bps": None,
        })
    equity.append((ts_arr[-1], cumulative))
    ec = {"half_spread_bps": {"venue_a": 0., "venue_b": 0.},
          "slippage_bps_per_100k": 0., "spread_model": "recorded executable depth"}
    result = _build_scenario_result(
        trades, equity, ts_arr, spreads, z_scores, symbol, BITSTAMP_SYMBOL_MAP[symbol],
        BINANCE_SYMBOL_MAP[symbol], start_dt, end_dt, venue_a_taker, venue_b_taker,
        capital_eur, tier_label, True, ec, "recorded-quotes-eurusdt-ws", "realistic",
    )
    result["summary"].update({"data_sources": "Recorded Bitstamp + Binance + EURUSDT top-5 WS books",
                              "snapshots_processed": len(rows), "failed_fills": len(failures)})
    result["failed_fills"] = failures
    return {"realistic": result, "upper_bound": None,
            "meta": {"data_source": "recorded_quotes", "quote_path": str(quote_path or path),
                     "fill_latency_ms": latency_ms, "fx_granularity": "recorded-quotes-eurusdt-ws",
                     "spread_model": "recorded executable depth",
                     "scenario_notes": "Full-size VWAP from recorded books; no synthetic spread/slippage surcharge."}}


async def run_historical_backtest(
    symbol:         str,       # "btc-eur" | "eth-eur" | "btc-eur-kraken"
    start_dt:       datetime,
    end_dt:         datetime,
    venue_a_taker:  float,
    venue_b_taker:  float,
    capital_eur:    float,
    tier_label:     str = "custom",
    data_source:    str = "candles",
    quote_path:     Optional[str] = None,
    latency_ms:     int = 300,
    spread_model:   str = "conservative",
) -> dict:
    """
    Full historical backtest returning dual scenarios:
      {
        "upper_bound": { summary, equity_curve, spread_series, trades },
        "realistic":   { summary, equity_curve, spread_series, trades },
        "meta":        { fx_granularity, scenario_notes, ... }
      }

    upper_bound — mid-price fills, exec costs zeroed (shows max theoretical)
    realistic   — bid-ask half-spread + linear slippage applied at each fill
    """
    from src.crypto_hft_tool.config import BT_EXEC_COSTS

    if not math.isfinite(capital_eur) or capital_eur <= 0:
        raise ValueError("capital_eur must be positive and finite")
    if any(not math.isfinite(f) or f < 0 for f in (venue_a_taker, venue_b_taker)):
        raise ValueError("Fees must be finite and nonnegative")
    if data_source not in ("candles", "quotes"):
        raise ValueError("Unknown data source")
    if data_source == "quotes":
        if not quote_path:
            raise ValueError("quote_path is required when data_source='quotes'")
        return await asyncio.to_thread(run_quote_backtest,
            quote_path=quote_path,
            symbol=symbol,
            start_dt=start_dt,
            end_dt=end_dt,
            venue_a_taker=venue_a_taker,
            venue_b_taker=venue_b_taker,
            capital_eur=capital_eur,
            tier_label=tier_label,
            latency_ms=latency_ms,
            spread_model=spread_model,
        )

    # ---- guard rails -------------------------------------------------------
    if not start_dt.tzinfo:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if not end_dt.tzinfo:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    now = datetime.now(tz=timezone.utc)
    if end_dt > now - timedelta(minutes=2):
        end_dt = now - timedelta(minutes=2)

    delta_days = (end_dt - start_dt).total_seconds() / 86400
    if delta_days <= 0:
        raise ValueError("End date must be after start date.")
    if delta_days > MAX_DAYS:
        raise ValueError(
            f"Maximum backtest range is {MAX_DAYS} days "
            f"({MAX_DAYS * 24 * 60:,} candles). Requested: {delta_days:.1f} days."
        )

    since_ms = int(start_dt.timestamp() * 1000)
    until_ms = int(end_dt.timestamp()   * 1000)
    s_date   = start_dt.strftime("%Y-%m-%d")
    e_date   = end_dt.strftime("%Y-%m-%d")

    bs_sym = BITSTAMP_SYMBOL_MAP[symbol]

    # P8 — control pair uses Kraken as Venue B with native EUR (no FX)
    is_control_pair = (symbol == "btc-eur-kraken")

    logger.info(f"[BT] {symbol} | {s_date} → {e_date} | "
                f"fee A={venue_a_taker:.4%} B={venue_b_taker:.4%} "
                f"capital=€{capital_eur} control_pair={is_control_pair}")

    # ---- parallel data fetch -----------------------------------------------
    if is_control_pair:
        # P8: Bitstamp EUR vs Kraken EUR — no FX conversion needed
        bitstamp_task = _fetch_ohlcv("bitstamp", bs_sym, since_ms, until_ms)
        kraken_task   = _fetch_ohlcv("kraken",   KRAKEN_SYMBOL_MAP[symbol], since_ms, until_ms)
        bitstamp_candles, kraken_candles = await asyncio.gather(bitstamp_task, kraken_task)
        binance_candles  = []
        eurusdt_candles  = []
        fx_daily         = {}
        bn_sym           = KRAKEN_SYMBOL_MAP[symbol]
        venue_b_candles  = kraken_candles
        fx_granularity   = "none-eur-native"
    else:
        bn_sym = BINANCE_SYMBOL_MAP[symbol]
        bitstamp_task  = _fetch_ohlcv("bitstamp", bs_sym, since_ms, until_ms)
        binance_task   = _fetch_ohlcv("binance",  bn_sym, since_ms, until_ms)
        eurusdt_task   = _fetch_eurusdt_ohlcv(since_ms, until_ms)
        fx_daily_task  = _fetch_fx_range(s_date, e_date)
        bitstamp_candles, binance_candles, eurusdt_candles, fx_daily = await asyncio.gather(
            bitstamp_task, binance_task, eurusdt_task, fx_daily_task
        )
        venue_b_candles = binance_candles
        fx_granularity  = "1m" if eurusdt_candles else "daily-fallback"
        if not eurusdt_candles:
            logger.warning("[BT-FX] EURUSDT fetch returned empty — using daily ECB fallback. "
                           "tag fx_granularity=daily-fallback")

    logger.info(f"[BT] Bitstamp: {len(bitstamp_candles)} candles | "
                f"VenueB: {len(venue_b_candles)} candles | "
                f"EURUSDT: {len(eurusdt_candles)} candles | "
                f"FX daily: {len(fx_daily)} days | "
                f"fx_granularity: {fx_granularity}")

    if not bitstamp_candles:
        raise RuntimeError("No data returned from Bitstamp. Check date range.")
    if not venue_b_candles:
        raise RuntimeError("No data returned from Venue B. Check date range.")

    # ---- build FX lookup ---------------------------------------------------
    if is_control_pair:
        intraday_fx: Dict[int, float] = {}   # fx = 1.0 everywhere
    else:
        intraday_fx = _build_intraday_fx_map(eurusdt_candles)

    # ---- align candles on common timestamps --------------------------------
    bs_map = {c[0]: c[4] for c in bitstamp_candles}    # ts_ms → close EUR
    vb_map = {c[0]: c[4] for c in venue_b_candles}     # ts_ms → close (USDT or EUR)

    common_ts = sorted(set(bs_map) & set(vb_map))
    if len(common_ts) < ZSCORE_WIN + 2:   # +2 because P2 needs i+1
        raise RuntimeError(
            f"Only {len(common_ts)} overlapping candles — need at least "
            f"{ZSCORE_WIN + 2} to compute a z-score with next-bar execution. "
            f"Try a wider date range."
        )

    # ---- build spread series -----------------------------------------------
    ts_arr:      List[int]   = []
    price_a_arr: List[float] = []
    price_b_arr: List[float] = []
    spread_arr:  List[float] = []

    for ts in common_ts:
        price_a = bs_map[ts]
        if is_control_pair:
            price_b = vb_map[ts]
        else:
            fx      = _fx_for_ts(ts, intraday_fx, fx_daily)
            price_b = vb_map[ts] * fx

        sp = (price_a - price_b) / price_b * 100 if price_b > 0 else 0.0

        ts_arr.append(ts)
        price_a_arr.append(price_a)
        price_b_arr.append(price_b)
        spread_arr.append(sp)

    spreads  = np.array(spread_arr)
    z_scores = _rolling_zscore(spreads, ZSCORE_WIN)

    # ---- P6: run simulation twice ------------------------------------------
    exec_costs = _exec_costs_resolved(spread_model, quote_path, symbol, since_ms)

    trades_real, equity_real = _simulate(
        ts_arr, price_a_arr, price_b_arr, spreads, z_scores,
        venue_a_taker, venue_b_taker, capital_eur,
        apply_exec_costs=True,
        exec_costs=exec_costs,
        fx_cost_bps=0 if is_control_pair else None,
    )
    trades_ub, equity_ub = _simulate(
        ts_arr, price_a_arr, price_b_arr, spreads, z_scores,
        venue_a_taker, venue_b_taker, capital_eur,
        apply_exec_costs=False,
        exec_costs=exec_costs,
        fx_cost_bps=0 if is_control_pair else None,
    )

    common_kwargs = dict(
        ts_arr=ts_arr,
        spreads=spreads,
        z_scores=z_scores,
        symbol=symbol,
        bs_sym=bs_sym,
        bn_sym=bn_sym,
        start_dt=start_dt,
        end_dt=end_dt,
        venue_a_taker=venue_a_taker,
        venue_b_taker=venue_b_taker,
        capital_eur=capital_eur,
        tier_label=tier_label,
        exec_costs=exec_costs,
        fx_granularity=fx_granularity,
    )

    realistic   = _build_scenario_result(
        trades_real, equity_real,
        apply_exec_costs=True,
        scenario_label="realistic",
        **common_kwargs,
    )
    upper_bound = _build_scenario_result(
        trades_ub, equity_ub,
        apply_exec_costs=False,
        scenario_label="upper_bound",
        **common_kwargs,
    )

    return {
        "realistic":   realistic,
        "upper_bound": upper_bound,
        "meta": {
            "fx_granularity":   fx_granularity,
            "is_control_pair":  is_control_pair,
            "scenario_notes":   (
                "realistic: bid-ask half-spread + slippage applied at fill. "
                "upper_bound: mid-price fills only (theoretical maximum)."
            ),
            "exec_costs_applied": {
                "half_spread_bps_venue_a": exec_costs["half_spread_bps"]["venue_a"],
                "half_spread_bps_venue_b": exec_costs["half_spread_bps"]["venue_b"],
                "slippage_bps_per_100k":   exec_costs["slippage_bps_per_100k"],
            },
        },
    }
