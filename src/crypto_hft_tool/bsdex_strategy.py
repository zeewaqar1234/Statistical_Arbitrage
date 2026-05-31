"""
BSDEX vs World (LMAX-proxy) — Independent Arbitrage Strategy Module.

=== Discovery notes (Step 0 of BSDEX_INTEGRATION_PLAN.md) ===

Frontend (hft-frontend/src/App.js):
  - React app with a top-level `activeTab` state ('live' | 'backtest') rendered as a
    two-button nav strip in the header.  Tab 'live' shows Market Overview, Transaction
    Model, Cross-Exchange Spread chart (recharts AreaChart), Signal Engine chart, Trade
    Activity, System Controls, and Strategy Config panels.  Tab 'backtest' shows a
    Backtesting config form plus results (equity curve + trade log).  API calls use an
    `api` object backed by axios pointing at http://localhost:8000. Data is polled via
    react-query.  We will add a third tab 'bsdex' alongside 'live' and 'backtest'.

Backend (main.py):
  - FastAPI app with a single `trading_loop()` task (Binance/Kraken) and routes under
    /api/v1/simulation/... and /api/v1/market_data/... plus /api/v1/config and
    /api/v1/backtest.  We add /api/v1/bsdex/... without touching any existing routes.

Data providers (data_provider.py):
  - BaseDataProvider, CCXTSingleExchangeDataProvider (CCXT/Binance+Kraken), Simulated.

Signal engine: EnhancedSignalProcessor + RollingZScore — reused with OWN instances.
Simulator: TradeSimulator.simulate_arbitrage_trade() → (pnl, fees) — reused with OWN instance.

=== Key architectural decision ===
BSDEX API (api-public.bsdex.de) requires HMAC authentication for ALL endpoints
including WebSocket — the plan's "no key needed for public data" assumption is
incorrect (verified: HTTP 401 on all unauthenticated requests, May 2026).
Strategy:
  - When BSDEX_API_KEY + BSDEX_API_SECRET are set in .env → connect to real BSDEX WS
    with HMAC auth and receive live quotes + phases.
  - Otherwise → fall back to Bitstamp's truly-public REST API for EUR bid/ask.
    Bitstamp is a regulated EU exchange (comparable liquidity profile), so it is an
    honest proxy.  The UI clearly labels the active source.
  - "World" price (Venue B) = Binance USDT price converted to EUR via a live FX rate.
    Fee schedule applied = LMAX institutional (as described in the plan).
    The UI always shows "World (Binance price · LMAX fee model)" — never "LMAX".
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from email.utils import formatdate
from typing import Dict, List, Optional, Tuple

import aiohttp
import requests

from .config import (
    BSDEX_API_WS,
    BSDEX_CREDENTIALS,
    BSDEX_MARKET_MAP,
    BSDEX_MARKETS,
    BSDEX_BITSTAMP_MAP,
    BSDEX_STRATEGY_FEES,
    BSDEX_FEE_PRESETS,
    BSDEX_ACTIVE_FEE_PRESET,
    FX_RATE_SOURCE,
    FX_REFRESH_SEC,
    ENHANCED_SIGNAL_SETTINGS,
    STRATEGY_DEFAULTS,
)
from .enhanced_signals import EnhancedSignalProcessor
from .simulation import TradeSimulator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BSDEX_PING_INTERVAL_SEC = 20
TRADE_COOLDOWN_SEC = STRATEGY_DEFAULTS.get("trade_cooldown_sec", 30)
SPREAD_BUFFER_SIZE = 500          # rolling points kept for chart endpoint
BITSTAMP_REST_BASE = "https://www.bitstamp.net/api/v2"

# BSDEX phase names (from docs)
PHASE_CONTINUOUS   = "continuous-trading"
PHASE_AUCTION_CALL = "auction-call"
PHASE_AUCTION_PRICE = "auction-price"
PHASE_AUCTION_RECALL = "auction-recall"
PHASE_HALT         = "trading-halt"
PHASE_DOWN         = "system-down"
PHASE_SUSPENDED    = "suspended"
AUCTION_PHASES     = {PHASE_AUCTION_CALL, PHASE_AUCTION_PRICE, PHASE_AUCTION_RECALL}


# ---------------------------------------------------------------------------
# BSDEX HMAC auth helpers
# ---------------------------------------------------------------------------

def _bsdex_auth_headers(api_key: str, secret: str) -> dict:
    """Return the three BSDEX HMAC auth headers required on every request."""
    date_str = formatdate(usegmt=True)
    sig_material = f"date: {date_str}"
    sig = base64.b64encode(
        hmac.new(secret.encode(), sig_material.encode(), hashlib.sha1).digest()
    ).decode()
    return {
        "Date": date_str,
        "ApiKey": api_key,
        "Authorization": (
            f'hmac username="{api_key}", algorithm="hmac-sha1", '
            f'headers="date", signature="{sig}"'
        ),
    }


# ---------------------------------------------------------------------------
# FX Rate cache (USD → EUR)
# ---------------------------------------------------------------------------

class FXRateCache:
    """Thread-safe EUR/USD rate with periodic refresh."""

    def __init__(self, source: str = FX_RATE_SOURCE, refresh_sec: int = FX_REFRESH_SEC):
        self._source = source
        self._refresh_sec = refresh_sec
        self._rate: float = 0.90     # bootstrap default (ECB ~2026 range)
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def age_sec(self) -> float:
        return time.time() - self._fetched_at

    async def maybe_refresh(self) -> float:
        """Return current rate; re-fetch from API if stale."""
        if time.time() - self._fetched_at < self._refresh_sec:
            return self._rate
        async with self._lock:
            if time.time() - self._fetched_at < self._refresh_sec:
                return self._rate
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self._source, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        data = await resp.json()
                        self._rate = float(data["rates"]["EUR"])
                        self._fetched_at = time.time()
                        logger.info(f"[FX] EUR/USD rate refreshed: {self._rate:.5f}")
            except Exception as exc:
                logger.warning(f"[FX] Could not refresh rate: {exc}; using {self._rate:.5f}")
        return self._rate


# ---------------------------------------------------------------------------
# Bitstamp public REST provider (fallback when BSDEX keys absent)
# ---------------------------------------------------------------------------

async def _fetch_bitstamp_quote(ticker: str) -> Optional[dict]:
    """Return {bid, ask, mid_price} from Bitstamp public REST, or None on error."""
    url = f"{BITSTAMP_REST_BASE}/ticker/{ticker}/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                d = await resp.json()
                bid = float(d["bid"])
                ask = float(d["ask"])
                return {
                    "bid": bid,
                    "ask": ask,
                    "mid_price": (bid + ask) / 2.0,
                    "baseVolume": float(d.get("volume", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "bitstamp_rest",
                }
    except Exception as exc:
        logger.debug(f"[Bitstamp] {ticker} fetch error: {exc}")
        return None


# ---------------------------------------------------------------------------
# BSDEX WebSocket provider (authenticated, used when keys present)
# ---------------------------------------------------------------------------

class BSDEXWebSocketProvider:
    """
    Connects to the BSDEX public WS with HMAC auth.
    Maintains in-memory caches for latest quotes and phases per market.
    """

    def __init__(self, api_key: str, secret: str, markets: List[str]):
        self._api_key = api_key
        self._secret = secret
        self._markets = markets
        # quote cache: market -> {bid, ask, mid_price, baseVolume, timestamp, source}
        self._quotes: Dict[str, dict] = {}
        # phase cache: market -> {name, start_ts, changed_at}
        self._phases: Dict[str, dict] = {
            m: {"name": PHASE_CONTINUOUS, "start_ts": None, "changed_at": None}
            for m in markets
        }
        self._running = False
        self._ws = None

    def get_quote(self, market: str) -> Optional[dict]:
        return self._quotes.get(market)

    def get_phase(self, market: str) -> dict:
        return self._phases.get(market, {"name": PHASE_CONTINUOUS, "start_ts": None})

    async def run(self):
        """Connect to BSDEX WS; subscribe; listen forever with reconnect."""
        import websockets

        self._running = True
        while self._running:
            try:
                headers = _bsdex_auth_headers(self._api_key, self._secret)
                async with websockets.connect(
                    BSDEX_API_WS,
                    additional_headers=headers,
                    ping_interval=None,  # we handle ping manually
                ) as ws:
                    self._ws = ws
                    logger.info("[BSDEX-WS] Connected")
                    # Subscribe to quote + phases for each market
                    for market in self._markets:
                        for chan in ("quote", "phases"):
                            await ws.send(json.dumps({
                                "type": "subscribe",
                                "chan_name": chan,
                                "subchan_name": market,
                            }))

                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    try:
                        async for raw in ws:
                            self._handle_message(raw)
                    finally:
                        ping_task.cancel()

            except Exception as exc:
                logger.warning(f"[BSDEX-WS] Disconnected ({exc}); reconnecting in 5s…")
                await asyncio.sleep(5)

    async def _ping_loop(self, ws):
        while True:
            await asyncio.sleep(BSDEX_PING_INTERVAL_SEC)
            try:
                await ws.send(json.dumps({"type": "ping"}))
            except Exception:
                break

    def _handle_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        msg_type = msg.get("type")
        chan = msg.get("chan_name")
        market = msg.get("subchan_name")

        if msg_type == "pong":
            return
        if msg_type == "offline" and market:
            logger.warning(f"[BSDEX-WS] Feed offline for {market}")
            # Mark quote stale by removing it
            self._quotes.pop(market, None)
            return
        if msg_type != "data" or not market:
            return

        data = msg.get("data", {})
        now = datetime.now(timezone.utc).isoformat()

        if chan == "quote":
            bid = float(data.get("buy_price", 0) or 0)
            ask = float(data.get("sell_price", 0) or 0)
            if bid > 0 and ask > 0:
                self._quotes[market] = {
                    "bid": bid,
                    "ask": ask,
                    "mid_price": (bid + ask) / 2.0,
                    "baseVolume": float(data.get("buy_volume", 0) or 0),
                    "timestamp": now,
                    "source": "bsdex_ws",
                }

        elif chan == "phases":
            old_phase = self._phases.get(market, {}).get("name")
            new_phase = data.get("name", PHASE_CONTINUOUS)
            self._phases[market] = {
                "name": new_phase,
                "start_ts": data.get("start_ts"),
                "changed_at": now,
            }
            if old_phase != new_phase:
                logger.info(f"[BSDEX] {market} phase: {old_phase} → {new_phase}")

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# World (LMAX-proxy) price feed — Binance USDT converted to EUR
# ---------------------------------------------------------------------------

async def _fetch_binance_quote_eur(symbol: str, fx_eur_per_usd: float) -> Optional[dict]:
    """
    Fetch best bid/ask from Binance (USDT) and convert to EUR.
    symbol: e.g. "BTC/USDT"  →  ticker pair "BTCUSDT"
    """
    pair = symbol.replace("/", "")
    url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={pair}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                d = await resp.json()
                bid_usdt = float(d["bidPrice"])
                ask_usdt = float(d["askPrice"])
                bid_eur  = bid_usdt * fx_eur_per_usd
                ask_eur  = ask_usdt * fx_eur_per_usd
                return {
                    "bid": bid_eur,
                    "ask": ask_eur,
                    "mid_price": (bid_eur + ask_eur) / 2.0,
                    "baseVolume": float(d.get("bidQty", 0)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "binance_usdt_eur",
                    "fx_rate": fx_eur_per_usd,
                    "bid_usdt": bid_usdt,
                    "ask_usdt": ask_usdt,
                }
    except Exception as exc:
        logger.debug(f"[Binance world feed] {symbol} error: {exc}")
        return None


# ---------------------------------------------------------------------------
# BSDEXStrategy — the self-contained strategy class
# ---------------------------------------------------------------------------

class BSDEXStrategy:
    """
    Independent BSDEX vs World arbitrage strategy.
    All state is local to this instance — zero interference with the
    Binance/Kraken trading_loop in main.py.

    Venue A  = BSDEX (authenticated WS) or Bitstamp (public REST fallback).
               Prices in EUR. Fees = BSDEX schedule.
    Venue B  = "World" — Binance USDT price converted to EUR via live FX rate.
               Fees = LMAX Digital schedule (clearly labelled assumption).
    """

    def __init__(self):
        # --- fee preset -------------------------------------------------------
        self._preset_name: str = BSDEX_ACTIVE_FEE_PRESET
        self._preset: dict     = BSDEX_FEE_PRESETS[self._preset_name]

        # --- own simulator instance -------------------------------------------
        self.simulator = TradeSimulator()

        # --- own signal processors (one per market) ---------------------------
        self.signal_processors: Dict[str, EnhancedSignalProcessor] = {
            m: EnhancedSignalProcessor(
                symbol=m,
                volatility_window=ENHANCED_SIGNAL_SETTINGS["volatility_window"],
                correlation_window=ENHANCED_SIGNAL_SETTINGS["correlation_window"],
                momentum_window=ENHANCED_SIGNAL_SETTINGS["momentum_window"],
                signal_threshold=ENHANCED_SIGNAL_SETTINGS["signal_threshold"],
                vol_impact=ENHANCED_SIGNAL_SETTINGS["vol_impact"],
            )
            for m in BSDEX_MARKETS
        }

        # --- per-market state -------------------------------------------------
        self.last_trade_time: Dict[str, float] = {m: 0.0 for m in BSDEX_MARKETS}
        # Phase tracking: detect auction→continuous edge
        self._last_phase: Dict[str, str] = {m: PHASE_CONTINUOUS for m in BSDEX_MARKETS}
        self._armed: Dict[str, bool] = {m: False for m in BSDEX_MARKETS}
        # rolling spread buffer: market -> deque of dicts
        self._spread_buf: Dict[str, deque] = {
            m: deque(maxlen=SPREAD_BUFFER_SIZE) for m in BSDEX_MARKETS
        }
        # latest computed tick per market
        self.latest: Dict[str, dict] = {}

        # --- FX rate cache ----------------------------------------------------
        self.fx_cache = FXRateCache()

        # --- BSDEX WS provider (created if keys available) -------------------
        self._bsdex_ws: Optional[BSDEXWebSocketProvider] = None
        self._use_real_bsdex = bool(
            BSDEX_CREDENTIALS.get("apiKey") and BSDEX_CREDENTIALS.get("secret")
        )
        if self._use_real_bsdex:
            self._bsdex_ws = BSDEXWebSocketProvider(
                BSDEX_CREDENTIALS["apiKey"],
                BSDEX_CREDENTIALS["secret"],
                BSDEX_MARKETS,
            )
            logger.info("[BSDEX] Authenticated WS provider initialised (real BSDEX data).")
        else:
            logger.info(
                "[BSDEX] No BSDEX API keys found — using Bitstamp EUR as venue-A proxy. "
                "Set BSDEX_API_KEY + BSDEX_API_SECRET in .env for real BSDEX data."
            )

        # Phase simulation for Bitstamp mode (no real phases available)
        # We treat Bitstamp as always "continuous-trading".
        self._bitstamp_phases: Dict[str, dict] = {
            m: {"name": PHASE_CONTINUOUS, "start_ts": None, "changed_at": None}
            for m in BSDEX_MARKETS
        }

        self._running = False

    # ------------------------------------------------------------------
    # Public properties / helpers
    # ------------------------------------------------------------------

    @property
    def venue_a_label(self) -> str:
        return "BSDEX (live)" if self._use_real_bsdex else "BSDEX (Bitstamp proxy)"

    @property
    def venue_b_label(self) -> str:
        return "World (Binance price · LMAX fee model)"

    @property
    def data_source(self) -> str:
        return "bsdex_ws" if self._use_real_bsdex else "bitstamp_rest"

    def set_fee_preset(self, preset_name: str) -> bool:
        if preset_name not in BSDEX_FEE_PRESETS:
            return False
        self._preset_name = preset_name
        self._preset = BSDEX_FEE_PRESETS[preset_name]
        logger.info(f"[BSDEX] Fee preset changed to '{preset_name}'")
        return True

    def _get_fees(self, side: str) -> Tuple[float, float]:
        """Return (venue_a_fee_rate, venue_b_fee_rate) for the given side (maker/taker)."""
        bsdex_fees = BSDEX_STRATEGY_FEES[self._preset["bsdex"]]
        world_fees = BSDEX_STRATEGY_FEES[self._preset["world"]]
        return bsdex_fees[side], world_fees[side]

    def _get_capital(self) -> float:
        return STRATEGY_DEFAULTS.get("capital_per_leg_usdt", 1000.0)

    # ------------------------------------------------------------------
    # Phase helpers
    # ------------------------------------------------------------------

    def _get_phase(self, market: str) -> dict:
        if self._use_real_bsdex and self._bsdex_ws:
            return self._bsdex_ws.get_phase(market)
        return self._bitstamp_phases[market]

    def _is_tradeable(self, phase_name: str) -> bool:
        return phase_name == PHASE_CONTINUOUS

    def _is_auction(self, phase_name: str) -> bool:
        return phase_name in AUCTION_PHASES

    # ------------------------------------------------------------------
    # Venue-A quote
    # ------------------------------------------------------------------

    async def _get_venue_a_quote(self, market: str) -> Optional[dict]:
        if self._use_real_bsdex and self._bsdex_ws:
            q = self._bsdex_ws.get_quote(market)
            if q:
                q = dict(q)
                q["exchange"] = "bsdex"
                return q
            # WS might not have data yet — don't fall through to Bitstamp
            return None
        else:
            bitstamp_ticker = BSDEX_BITSTAMP_MAP.get(market)
            if not bitstamp_ticker:
                return None
            q = await _fetch_bitstamp_quote(bitstamp_ticker)
            if q:
                q["exchange"] = "bitstamp_proxy"
                q["symbol"] = market
            return q

    # ------------------------------------------------------------------
    # Core tick processing
    # ------------------------------------------------------------------

    async def _process_market(self, market: str):
        """One tick for a single market: fetch prices, compute spread, maybe trade."""
        fx_rate = await self.fx_cache.maybe_refresh()

        world_symbol = BSDEX_MARKET_MAP[market]
        venue_a_q = await self._get_venue_a_quote(market)
        venue_b_q = await _fetch_binance_quote_eur(world_symbol, fx_rate)

        if not venue_a_q or not venue_b_q:
            return  # data unavailable — skip tick

        a_bid = venue_a_q["bid"]
        a_ask = venue_a_q["ask"]
        b_bid = venue_b_q["bid"]
        b_ask = venue_b_q["ask"]

        # Spread: BSDEX (A) bid minus world (B) ask — positive means A trades above B.
        spread_eur = a_bid - b_ask
        mid_a = venue_a_q["mid_price"]
        mid_b = venue_b_q["mid_price"]
        spread_pct = (spread_eur / mid_b * 100) if mid_b > 0 else 0.0

        # Feed into signal processor
        volume = venue_a_q.get("baseVolume", 0)
        now_ts = datetime.now(timezone.utc)
        signal_map = self.signal_processors[market].update(spread_eur, volume, now_ts)

        # Compute z-score (use longest window available)
        z_score: Optional[float] = None
        threshold: Optional[float] = None
        for window, metrics in (signal_map or {}).items():
            if metrics and metrics.zscore is not None:
                z_score = metrics.zscore
                threshold = metrics.threshold

        # Phase logic
        phase_info = self._get_phase(market)
        phase_name = phase_info.get("name", PHASE_CONTINUOUS)

        # Detect auction→continuous edge
        prev_phase = self._last_phase[market]
        post_auction = False
        if self._is_auction(prev_phase) and self._is_tradeable(phase_name):
            post_auction = True
            logger.info(f"[BSDEX] {market}: auction ended → continuous (armed signal: {self._armed[market]})")
        if self._is_auction(phase_name):
            self._armed[market] = True   # signal is building during auction
        if self._is_tradeable(phase_name) and not self._is_auction(prev_phase):
            # already in continuous — arm state only resets after a trade or timeout
            pass
        self._last_phase[market] = phase_name

        # Determine signal state
        if not self._is_tradeable(phase_name) and not self._is_auction(phase_name):
            signal_state = "BLOCKED_BY_PHASE"
        elif self._is_auction(phase_name):
            signal_state = "ARMING"
        elif z_score is not None and threshold is not None and abs(z_score) >= threshold:
            signal_state = "SIGNAL"
        else:
            signal_state = "HOLD"

        # Compute fees (taker on both sides for arbitrage)
        fee_a, fee_b = self._get_fees("taker")
        breakeven_spread_pct = (fee_a + fee_b) * 100

        # Trade conditions
        should_trade = (
            self._is_tradeable(phase_name)
            and signal_state == "SIGNAL"
            and (time.time() - self.last_trade_time.get(market, 0)) >= TRADE_COOLDOWN_SEC
        )

        # Direction: if spread_eur > 0 → A is expensive vs B → buy B, sell A
        trade_data = None
        if should_trade and abs(spread_pct) > breakeven_spread_pct:
            capital = self._get_capital()
            if spread_eur > 0:
                # Buy world (B), Sell BSDEX (A)
                buy_price  = b_ask
                sell_price = a_bid
                buy_ex, sell_ex = "world_lmax", "bsdex"
                buy_fee, sell_fee = fee_b, fee_a
            else:
                # Buy BSDEX (A), Sell world (B)
                buy_price  = a_ask
                sell_price = b_bid
                buy_ex, sell_ex = "bsdex", "world_lmax"
                buy_fee, sell_fee = fee_a, fee_b

            if buy_price > 0 and sell_price > 0:
                amount = capital / buy_price
                eff_sell = sell_price * (1 - sell_fee)
                eff_buy  = buy_price  * (1 + buy_fee)
                if eff_sell > eff_buy:
                    pnl, fees_paid = self.simulator.simulate_arbitrage_trade(
                        symbol=market,
                        amount=amount,
                        buy_exchange=buy_ex,
                        buy_price=buy_price,
                        sell_exchange=sell_ex,
                        sell_price=sell_price,
                        buy_fee_rate=buy_fee,
                        sell_fee_rate=sell_fee,
                    )
                    self.last_trade_time[market] = time.time()
                    self._armed[market] = False
                    trade_data = {
                        "pnl": pnl,
                        "fees": fees_paid,
                        "post_auction_convergence": post_auction or self._armed.get(market, False),
                        "fee_preset": self._preset_name,
                        "fx_rate": fx_rate,
                        "phase": phase_name,
                        "amount": amount,
                        "buy_exchange": buy_ex,
                        "sell_exchange": sell_ex,
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                    }
                    logger.info(
                        f"[BSDEX] Trade {market}: {amount:.6f} BUY@{buy_price:.2f} ({buy_ex}), "
                        f"SELL@{sell_price:.2f} ({sell_ex}), PnL={pnl:.4f} EUR, "
                        f"post_auction={trade_data['post_auction_convergence']}"
                    )

        # Store in rolling spread buffer
        tick = {
            "ts": now_ts.isoformat(),
            "spread_eur": round(spread_eur, 4),
            "spread_pct": round(spread_pct, 6),
            "z_score": round(z_score, 4) if z_score is not None else None,
            "threshold": round(threshold, 4) if threshold is not None else None,
            "phase": phase_name,
            "signal_state": signal_state,
            "a_bid": round(a_bid, 4),
            "a_ask": round(a_ask, 4),
            "b_bid": round(b_bid, 4),
            "b_ask": round(b_ask, 4),
            "fx_rate": round(fx_rate, 6),
            "trade": trade_data,
        }
        self._spread_buf[market].append(tick)

        # Update latest tick
        self.latest[market] = {
            **tick,
            "venue_a_source": venue_a_q.get("source", self.data_source),
            "venue_b_source": venue_b_q.get("source", "binance_usdt_eur"),
            "breakeven_spread_pct": round(breakeven_spread_pct, 6),
            "fee_preset": self._preset_name,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        """Start the BSDEX strategy loop (and WS provider if authenticated)."""
        self._running = True

        # Launch BSDEX WS listener if authenticated
        if self._use_real_bsdex and self._bsdex_ws:
            asyncio.create_task(self._bsdex_ws.run())
            await asyncio.sleep(2)  # allow WS to connect + receive first quotes

        while self._running:
            for market in BSDEX_MARKETS:
                try:
                    await self._process_market(market)
                except Exception as exc:
                    logger.warning(f"[BSDEX] Error processing {market}: {exc}")
            await asyncio.sleep(1)

    def stop(self):
        self._running = False
        if self._bsdex_ws:
            self._bsdex_ws.stop()

    # ------------------------------------------------------------------
    # API-facing read methods
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """PnL summary — mirrors main.py's _compute_performance_metrics shape."""
        trades = self.simulator.trades
        n = len(trades)
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total_pnl = self.simulator.total_pnl
        total_fees = self.simulator.total_fees_paid
        win_rate = (wins / n * 100) if n > 0 else 0.0
        fx_rate = self.fx_cache.rate
        return {
            "total_pnl_eur": round(total_pnl, 4),
            "total_trades": n,
            "win_rate_pct": round(win_rate, 2),
            "total_fees_eur": round(total_fees, 4),
            "fee_preset": self._preset_name,
            "fx_rate_usd_eur": round(fx_rate, 6),
            "fx_age_sec": round(self.fx_cache.age_sec, 1),
            "venue_a": self.venue_a_label,
            "venue_b": self.venue_b_label,
            "data_source": self.data_source,
        }

    def get_recent_trades(self, limit: int = 50) -> List[dict]:
        """Return the most recent simulated trades with BSDEX-specific fields."""
        raw = self.simulator.trades[-limit:]
        result = []
        for t in reversed(raw):
            ts = t.get("timestamp")
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            result.append({
                "timestamp": ts_str,
                "market": t.get("symbol"),
                "buy_exchange": t.get("buy_exchange"),
                "sell_exchange": t.get("sell_exchange"),
                "buy_price_eur": round(t.get("buy_price", 0), 4),
                "sell_price_eur": round(t.get("sell_price", 0), 4),
                "amount": round(t.get("amount", 0), 8),
                "pnl_eur": round(t.get("pnl", 0), 4),
                "fees_eur": round(t.get("fees", 0), 4),
                "phase": t.get("phase", "unknown"),
                "post_auction_convergence": t.get("post_auction_convergence", False),
                "fee_preset": t.get("fee_preset", self._preset_name),
                "fx_rate": t.get("fx_rate", self.fx_cache.rate),
            })
        return result

    def get_latest_market(self, market: str) -> Optional[dict]:
        """Latest spread / z / phase for the chart endpoint."""
        return self.latest.get(market)

    def get_spread_series(self, market: str, n: int = 200) -> List[dict]:
        """Last n ticks from the rolling spread buffer."""
        buf = list(self._spread_buf.get(market, []))
        return buf[-n:]

    def get_phase(self, market: str) -> dict:
        return self._get_phase(market)


# ---------------------------------------------------------------------------
# Module-level singleton (imported by main.py)
# ---------------------------------------------------------------------------
bsdex_strategy = BSDEXStrategy()
