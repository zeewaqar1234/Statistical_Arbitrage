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
from decimal import Decimal
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
    BSDEX_FEE_PRESETS,
    BSDEX_STRATEGY_FEES,
    BSDEX_VOLUME_TIERS,
    BSDEX_DEFAULT_TIER_IDX,
    FX_RATE_SOURCE,
    FX_REFRESH_SEC,
    ENHANCED_SIGNAL_SETTINGS,
    STRATEGY_DEFAULTS,
)
from .enhanced_signals import EnhancedSignalProcessor
from .simulation import TradeSimulator

logger = logging.getLogger(__name__)


def _system_dns_connector() -> aiohttp.TCPConnector:
    """
    Use the OS/system resolver instead of aiohttp's async resolver.

    On some macOS/VPN setups, aiohttp + aiodns/pycares fails with
    "Could not contact DNS servers" while curl/browser resolution works.
    ThreadedResolver delegates to the same system resolver path and fixes
    those false DNS failures.
    """
    return aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

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
        self._rate: float = 0.90         # bootstrap default (ECB ~2026 range)
        # Force one immediate refresh on startup, but keep the age around the
        # normal refresh interval (not Unix epoch) so staleness warnings do not
        # explode before the first attempt.
        self._fetched_at: float = time.time() - refresh_sec
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
            # Double-checked locking: another coroutine may have refreshed already
            if time.time() - self._fetched_at < self._refresh_sec:
                return self._rate
            try:
                async with aiohttp.ClientSession(connector=_system_dns_connector()) as session:
                    async with session.get(self._source, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        data = await resp.json()
                        self._rate = float(data["rates"]["EUR"])
                        self._fetched_at = time.time()
                        logger.info(f"[FX] EUR/USD rate refreshed: {self._rate:.5f}")
            except Exception as exc:
                # Back off: retry after 30 s (half the normal interval) instead of
                # re-attempting on every tick, which would spam the log at 2 lines/s.
                self._fetched_at = time.time() - self._refresh_sec + 30
                logger.warning(
                    f"[FX] Could not refresh rate: {exc}; "
                    f"using bootstrap {self._rate:.5f}, retrying in ~30 s"
                )
        return self._rate


# ---------------------------------------------------------------------------
# Bitstamp public REST provider (fallback when BSDEX keys absent)
# ---------------------------------------------------------------------------

async def _fetch_bitstamp_quote(ticker: str) -> Optional[dict]:
    """Return {bid, ask, mid_price} from Bitstamp public REST, or None on error."""
    url = f"{BITSTAMP_REST_BASE}/ticker/{ticker}/"
    try:
        async with aiohttp.ClientSession(connector=_system_dns_connector()) as session:
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
        async with aiohttp.ClientSession(connector=_system_dns_connector()) as session:
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
# FX staleness guard
# ---------------------------------------------------------------------------
MAX_FX_AGE_SEC = 300          # 5 minutes; beyond this, FX is too stale to trade
FX_WARN_AGE_SEC = 120         # log a warning after 2 minutes of staleness

# ---------------------------------------------------------------------------
# Bitstamp order-book REST (cached; for VWAP price-impact estimation)
# ---------------------------------------------------------------------------

class BitstampOrderbookCache:
    """
    Caches Bitstamp's full bid/ask depth (top-20) with a short TTL.
    Used by _estimate_price_impact to compute VWAP clearing prices.
    REST is fine here: order-book depth changes slowly vs. top-of-book.
    """
    _TTL_SEC = 5.0

    def __init__(self):
        self._books: Dict[str, dict] = {}       # ticker → {"bids":..., "asks":..., "ts":...}

    async def get(self, ticker: str) -> Optional[Dict]:
        """Return cached book or re-fetch if stale."""
        cached = self._books.get(ticker)
        if cached and (time.time() - cached["ts"]) < self._TTL_SEC:
            return cached["book"]
        url = f"{BITSTAMP_REST_BASE}/order_book/{ticker}/?group=1"
        try:
            async with aiohttp.ClientSession(connector=_system_dns_connector()) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    d = await resp.json()
                    # Bitstamp returns lists of ["price", "amount", count]
                    book = {
                        "bids": {Decimal(row[0]): Decimal(row[1]) for row in d.get("bids", [])[:20]},
                        "asks": {Decimal(row[0]): Decimal(row[1]) for row in d.get("asks", [])[:20]},
                    }
                    self._books[ticker] = {"book": book, "ts": time.time()}
                    return book
        except Exception as exc:
            logger.debug(f"[BitstampOB] {ticker} fetch error: {exc}")
            return cached["book"] if cached else None

# Module-level singleton (shared across all BSDEXStrategy instances)
_bitstamp_ob_cache = BitstampOrderbookCache()


# ---------------------------------------------------------------------------
# Binance WebSocket depth-20 cache — replaces per-tick REST calls
# ---------------------------------------------------------------------------

class BinanceDepthCache:
    """
    Subscribes to Binance combined depth-20 stream (100 ms snapshots).
    Provides:
      • get_quote(symbol)     → {bid, ask, mid_price} for top-of-book (replaces REST)
      • get_orderbook(symbol) → {bids: {Decimal: Decimal}, asks: ...} for VWAP

    Using depth20@100ms (snapshot mode) avoids delta-management complexity:
    every message is a complete top-20 book, no sequence-number reconciliation needed.
    """
    _BINANCE_WS = "wss://stream.binance.com:9443/stream"

    def __init__(self, symbols: List[str]):
        # symbols in Binance format: ["BTCUSDT", "ETHUSDT"]
        self._symbols    = [s.upper() for s in symbols]
        self._quotes:    Dict[str, dict]              = {}
        self._orderbooks: Dict[str, Dict[str, Dict]]  = {}
        self._running    = False
        self._connected  = False

    @property
    def connected(self) -> bool:
        return self._connected

    def get_quote(self, symbol: str) -> Optional[dict]:
        """Best bid/ask from the depth cache. Returns None until first WS message."""
        return self._quotes.get(symbol.upper())

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """Full top-20 order book in {Decimal: Decimal} format."""
        return self._orderbooks.get(symbol.upper())

    def _process_depth(self, data: dict, stream: Optional[str] = None):
        """Parse a depth20 snapshot message and update caches."""
        # depth20 snapshots in Binance combined streams do not include "s".
        # The symbol is carried in the wrapper stream name, e.g.
        # "btcusdt@depth20@100ms".
        sym = data.get("s", "").upper()
        if not sym and stream:
            sym = stream.split("@", 1)[0].upper()
        if not sym:
            return
        raw_bids = data.get("bids", [])
        raw_asks = data.get("asks", [])
        if not raw_bids or not raw_asks:
            return

        bids = {Decimal(p): Decimal(a) for p, a in raw_bids}
        asks = {Decimal(p): Decimal(a) for p, a in raw_asks}

        best_bid = float(max(bids.keys()))
        best_ask = float(min(asks.keys()))
        self._quotes[sym]     = {
            "bid":       best_bid,
            "ask":       best_ask,
            "mid_price": (best_bid + best_ask) / 2.0,
            "ts":        time.time(),
            "source":    "binance_ws_depth",
        }
        self._orderbooks[sym] = {"bids": bids, "asks": asks}

    async def run(self):
        """
        Connect to the combined depth20@100ms stream for all tracked symbols.
        Reconnects automatically on disconnect — no manual intervention needed.
        """
        import websockets

        stream_names = "/".join(f"{s.lower()}@depth20@100ms" for s in self._symbols)
        url = f"{self._BINANCE_WS}?streams={stream_names}"
        self._running = True

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._connected = True
                    logger.info(f"[BinanceDepthWS] Connected → {self._symbols}")
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            outer = json.loads(raw)
                            # Combined stream wraps payload:
                            # {"stream":"btcusdt@depth20@100ms","data":{...}}
                            data = outer.get("data", outer)
                            self._process_depth(data, outer.get("stream"))
                        except Exception as exc:
                            logger.debug(f"[BinanceDepthWS] Parse error: {exc}")
            except Exception as exc:
                self._connected = False
                if self._running:
                    logger.warning(
                        f"[BinanceDepthWS] Connection lost ({type(exc).__name__}: {exc}); "
                        "reconnecting in 3 s"
                    )
                    await asyncio.sleep(3)

    def stop(self):
        self._running    = False
        self._connected  = False


# ---------------------------------------------------------------------------
# Lightweight VWAP helper (mirrors ExecutionManager._estimate_price_impact)
# ---------------------------------------------------------------------------

def _vwap_clearing_price(
    orderbook: Dict[str, Dict[Decimal, Decimal]],
    side: str,
    amount_base: float,
) -> Optional[float]:
    """
    Walk the order book to find the volume-weighted average clearing price
    for a market order of `amount_base` units.

    side = 'buy'  → walk asks (ascending)
    side = 'sell' → walk bids (descending)

    Returns None if the book lacks sufficient depth.
    """
    if not orderbook:
        return None
    try:
        book_side = orderbook["bids"] if side == "sell" else orderbook["asks"]
        prices = sorted(book_side.keys(), reverse=(side == "sell"))
        remaining   = amount_base
        total_cost  = 0.0
        for price in prices:
            available = float(book_side[price])
            taken     = min(remaining, available)
            total_cost += taken * float(price)
            remaining  -= taken
            if remaining <= 0:
                break
        if remaining > 1e-10:   # insufficient depth
            return None
        return total_cost / amount_base
    except Exception as exc:
        logger.debug(f"[VWAP] Error: {exc}")
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
               Prices in EUR. Fees = Bitstamp fee schedule (volume-tier based).
    Venue B  = "World" — Binance USDT price converted to EUR via live FX rate.
               Fees = LMAX Digital fee schedule (volume-tier based, labelled assumption).

    Phase/auction logic is intentionally absent: Bitstamp has no auction phases
    and we run in continuous-trading mode only. When real BSDEX auth keys are
    provided (BSDEX_API_KEY / BSDEX_API_SECRET in .env) the WS provider connects
    and delivers live BSDEX quotes + phases, which re-activates phase logic.
    """

    def __init__(self):
        # --- fee rates stored directly (decimal; e.g. 0.0012 = 0.12 %) ----------
        _default_tier = BSDEX_VOLUME_TIERS[BSDEX_DEFAULT_TIER_IDX]
        self._venue_a_taker: float = _default_tier["bitstamp_taker"]
        self._venue_b_taker: float = _default_tier["lmax_taker"]
        self._tier_label:    str   = _default_tier["label"]
        self._tier_idx:      int   = BSDEX_DEFAULT_TIER_IDX
        self._fee_mode:      str   = "auto"   # "auto" (tier-based) | "manual"

        # --- capital (EUR per leg) --------------------------------------------
        self._capital_eur: float = float(STRATEGY_DEFAULTS.get("capital_per_leg_usdt", 1000.0))

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
        self._spread_buf: Dict[str, deque] = {
            m: deque(maxlen=SPREAD_BUFFER_SIZE) for m in BSDEX_MARKETS
        }
        self.latest: Dict[str, dict] = {}

        # --- FX rate cache ----------------------------------------------------
        self.fx_cache = FXRateCache()

        # --- Binance WebSocket depth cache (eliminates per-tick REST calls) --
        # Maps BSDEX market names to Binance symbols (e.g. "btc-eur" → "BTCUSDT")
        _binance_symbols = list({v.replace("/", "") for v in BSDEX_MARKET_MAP.values()})
        self._binance_ws = BinanceDepthCache(_binance_symbols)

        # --- Bitstamp order book cache (VWAP for venue A) --------------------
        self._bitstamp_ob = _bitstamp_ob_cache

        # --- BSDEX WS provider (created only if API keys are present) --------
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
                "[BSDEX] No BSDEX API keys — using Bitstamp EUR as venue-A proxy "
                "(continuous trading only, no auction phases). "
                "Set BSDEX_API_KEY + BSDEX_API_SECRET in .env for live BSDEX data."
            )

        self._running = False

    # ------------------------------------------------------------------
    # Public properties
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

    @property
    def breakeven_spread_pct(self) -> float:
        return (self._venue_a_taker + self._venue_b_taker) * 100

    # ------------------------------------------------------------------
    # Runtime config setters
    # ------------------------------------------------------------------

    def set_fees(
        self,
        venue_a_taker: float,
        venue_b_taker: float,
        tier_label: str = "manual",
        tier_idx: int = -1,
        mode: str = "manual",
    ) -> None:
        """Set fee rates directly (from volume-tier selection or manual entry)."""
        self._venue_a_taker = max(0.0, venue_a_taker)
        self._venue_b_taker = max(0.0, venue_b_taker)
        self._tier_label    = tier_label
        self._tier_idx      = tier_idx
        self._fee_mode      = mode
        logger.info(
            f"[BSDEX] Fees updated: A={venue_a_taker:.4%} B={venue_b_taker:.4%} "
            f"tier='{tier_label}' mode={mode}"
        )

    def set_capital(self, capital_eur: float) -> None:
        """Set capital deployed per venue per trade (EUR)."""
        if capital_eur > 0:
            self._capital_eur = capital_eur
            logger.info(f"[BSDEX] Capital updated: €{capital_eur:,.2f}")

    # Legacy preset setter (kept for backward compat with old API route)
    def set_fee_preset(self, preset_name: str) -> bool:
        from .config import BSDEX_STRATEGY_FEES
        if preset_name not in BSDEX_FEE_PRESETS:
            return False
        preset = BSDEX_FEE_PRESETS[preset_name]
        self.set_fees(
            venue_a_taker=BSDEX_STRATEGY_FEES[preset["bsdex"]]["taker"],
            venue_b_taker=BSDEX_STRATEGY_FEES[preset["world"]]["taker"],
            tier_label=preset_name,
            mode="auto",
        )
        return True

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
            return None
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
        """
        One evaluation tick.

        Price sources (in priority order):
          Venue B (Binance world-leg):
            1. BinanceDepthCache WS — real-time depth20 snapshot, zero REST overhead
            2. Bitstamp REST bookTicker — fallback for the first few seconds before WS connects
          Venue A (BSDEX / Bitstamp proxy):
            - BSDEXWebSocketProvider when API keys are present
            - BitstampOrderbookCache (5s REST TTL) for VWAP; direct REST for top-of-book

        FX: ECB rate via Frankfurter. Trades are gated if rate is older than MAX_FX_AGE_SEC.
        Spread: VWAP clearing price when order-book depth is available; top-of-book otherwise.
        """
        # ── 1. FX rate (refresh if stale) ─────────────────────────────────────
        fx_rate  = await self.fx_cache.maybe_refresh()
        fx_age   = self.fx_cache.age_sec

        if fx_age > FX_WARN_AGE_SEC:
            logger.warning(
                f"[FX] Rate is {fx_age:.0f}s old (limit={MAX_FX_AGE_SEC}s). "
                "Intraday EUR/USD drift may invalidate spread readings."
            )

        world_symbol = BSDEX_MARKET_MAP[market]   # e.g. "BTC/USDT"
        bn_sym       = world_symbol.replace("/", "")   # "BTCUSDT"

        # ── 2. Venue B (Binance world-leg) — prefer WS, fallback REST ─────────
        ws_quote_b = self._binance_ws.get_quote(bn_sym)
        if ws_quote_b:
            # BinanceDepthCache stores native USDT prices from depth20 snapshots.
            # Apply the FX rate here to convert to EUR.
            venue_b_q = {
                "bid":       ws_quote_b["bid"] * fx_rate,
                "ask":       ws_quote_b["ask"] * fx_rate,
                "mid_price": ws_quote_b["mid_price"] * fx_rate,
                "source":    "binance_ws_depth",
                "fx_rate":   fx_rate,
            }
        else:
            # WS not yet connected (first ~1 s after startup) — fall back to REST
            venue_b_q = await _fetch_binance_quote_eur(world_symbol, fx_rate)

        # ── 3. Venue A (BSDEX proxy / Bitstamp) ──────────────────────────────
        venue_a_q = await self._get_venue_a_quote(market)

        if not venue_a_q or not venue_b_q:
            return

        a_mid = venue_a_q["mid_price"]
        b_mid = venue_b_q["mid_price"]

        # ── 4. VWAP clearing prices (replaces top-of-book illusion) ─────────
        #   amount_base: how many BTC/ETH units €capital buys at mid
        amount_base = (self._capital_eur / a_mid) if a_mid > 0 else 0.0

        # Venue A VWAP — Bitstamp order book (5 s REST cache)
        bs_ticker   = BSDEX_BITSTAMP_MAP.get(market)
        book_a      = await self._bitstamp_ob.get(bs_ticker) if bs_ticker else None

        # Venue B VWAP — Binance WS depth cache
        book_b = self._binance_ws.get_orderbook(bn_sym)
        # Convert Binance book prices from USDT → EUR
        if book_b and fx_rate:
            book_b = {
                "bids": {p * Decimal(str(fx_rate)): q for p, q in book_b["bids"].items()},
                "asks": {p * Decimal(str(fx_rate)): q for p, q in book_b["asks"].items()},
            }

        # Compute VWAP prices (fall back to top-of-book if depth unavailable)
        vwap_a_bid = _vwap_clearing_price(book_a, "sell", amount_base) if book_a and amount_base > 0 else None
        vwap_b_ask = _vwap_clearing_price(book_b, "buy",  amount_base) if book_b and amount_base > 0 else None

        a_bid_eff = vwap_a_bid if vwap_a_bid else venue_a_q["bid"]
        b_ask_eff = vwap_b_ask if vwap_b_ask else venue_b_q["ask"]
        a_ask_eff = venue_a_q["ask"]   # buying on A uses ask
        b_bid_eff = venue_b_q["bid"]   # selling on B uses bid

        price_model = "vwap" if (vwap_a_bid and vwap_b_ask) else "top_of_book"

        # ── 5. Spread on VWAP-adjusted prices ────────────────────────────────
        spread_eur = a_bid_eff - b_ask_eff          # Positive → A expensive
        spread_pct = (spread_eur / b_mid * 100) if b_mid > 0 else 0.0

        # ── 6. Signal engine ──────────────────────────────────────────────────
        volume     = venue_a_q.get("baseVolume", 0)
        now_ts     = datetime.now(timezone.utc)
        signal_map = self.signal_processors[market].update(spread_eur, volume, now_ts)

        z_score: Optional[float]   = None
        threshold: Optional[float] = None
        for _, metrics in (signal_map or {}).items():
            if metrics and metrics.zscore is not None:
                z_score   = metrics.zscore
                threshold = metrics.threshold

        # ── 7. Gate logic ─────────────────────────────────────────────────────
        # Fees defined first (be_pct used below)
        fee_a  = self._venue_a_taker
        fee_b  = self._venue_b_taker
        be_pct = self.breakeven_spread_pct   # (fee_a + fee_b) × 100

        z_triggered  = (z_score is not None and threshold is not None and abs(z_score) >= threshold)
        spread_ok    = abs(spread_pct) > be_pct
        cooldown_ok  = (time.time() - self.last_trade_time.get(market, 0)) >= TRADE_COOLDOWN_SEC
        # FX staleness gate: if ECB rate is > MAX_FX_AGE_SEC old, the EUR/USD basis
        # risk may eclipse the spread signal — block trades but continue monitoring.
        fx_ok        = fx_age <= MAX_FX_AGE_SEC

        if z_triggered and spread_ok and cooldown_ok and fx_ok:
            signal_state = "SIGNAL"
        elif z_triggered and not fx_ok:
            signal_state = "SIGNAL_GATED"   # FX rate too stale
        elif z_triggered and not spread_ok:
            signal_state = "SIGNAL_GATED"   # spread doesn't cover fees
        elif z_triggered and not cooldown_ok:
            signal_state = "SIGNAL_COOLDOWN"
        else:
            signal_state = "HOLD"

        should_trade = signal_state == "SIGNAL"

        # ── 8. Simulated trade execution (VWAP prices used as clearing prices) ─
        trade_data = None
        if should_trade:
            if spread_eur > 0:
                # Venue A expensive → SELL A (use VWAP bid on A), BUY B (use VWAP ask on B)
                buy_price, sell_price = b_ask_eff, a_bid_eff
                buy_ex,    sell_ex    = "world_lmax", "bitstamp"
                buy_fee,   sell_fee   = fee_b, fee_a
            else:
                # Venue B expensive → BUY A (use VWAP ask on A), SELL B (use VWAP bid on B)
                buy_price, sell_price = a_ask_eff, b_bid_eff
                buy_ex,    sell_ex    = "bitstamp", "world_lmax"
                buy_fee,   sell_fee   = fee_a, fee_b

            if buy_price > 0 and sell_price > 0:
                eff_sell = sell_price * (1 - sell_fee)
                eff_buy  = buy_price  * (1 + buy_fee)
                if eff_sell > eff_buy:
                    amount = self._capital_eur / buy_price
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
                    trade_data = {
                        "pnl": pnl, "fees": fees_paid,
                        "tier": self._tier_label,
                        "fee_mode": self._fee_mode,
                        "fx_rate": fx_rate,
                        "amount": amount,
                        "buy_exchange": buy_ex,
                        "sell_exchange": sell_ex,
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "price_model": price_model,
                    }
                    logger.info(
                        f"[BSDEX] Trade {market}: {amount:.6f} BUY@{buy_price:.2f} ({buy_ex}), "
                        f"SELL@{sell_price:.2f} ({sell_ex}), PnL=€{pnl:.4f} | "
                        f"tier={self._tier_label} feeA={fee_a:.4%} feeB={fee_b:.4%} "
                        f"model={price_model} ws={'✓' if self._binance_ws.connected else '✗'}"
                    )

        # ── 9. Rolling spread buffer ──────────────────────────────────────────
        tick = {
            "ts":           now_ts.isoformat(),
            "spread_eur":   round(spread_eur, 4),
            "spread_pct":   round(spread_pct, 6),
            "z_score":      round(z_score, 4)   if z_score   is not None else None,
            "threshold":    round(threshold, 4) if threshold is not None else None,
            "signal_state": signal_state,
            "a_bid":        round(a_bid_eff, 4),
            "a_ask":        round(a_ask_eff, 4),
            "b_bid":        round(b_bid_eff, 4),
            "b_ask":        round(b_ask_eff, 4),
            "fx_rate":      round(fx_rate, 6),
            "fx_age_sec":   round(fx_age, 1),
            "price_model":  price_model,
            "binance_ws":   self._binance_ws.connected,
            "trade":        trade_data,
        }
        self._spread_buf[market].append(tick)

        self.latest[market] = {
            **tick,
            "venue_a_source":       venue_a_q.get("source", self.data_source),
            "venue_b_source":       venue_b_q.get("source", "binance_ws_depth"),
            "breakeven_spread_pct": round(be_pct, 6),
            "venue_a_taker_pct":    round(fee_a * 100, 4),
            "venue_b_taker_pct":    round(fee_b * 100, 4),
            "tier_label":           self._tier_label,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        """Start the BSDEX strategy loop (and WS providers)."""
        self._running = True

        # Launch Binance depth WebSocket (eliminates REST calls for world-leg prices)
        asyncio.create_task(self._binance_ws.run())

        # Launch BSDEX WS listener if authenticated
        if self._use_real_bsdex and self._bsdex_ws:
            asyncio.create_task(self._bsdex_ws.run())
            await asyncio.sleep(2)  # allow WS to connect + receive first quotes
        else:
            await asyncio.sleep(1)  # give Binance WS a moment to connect

        while self._running:
            for market in BSDEX_MARKETS:
                try:
                    await self._process_market(market)
                except Exception as exc:
                    logger.warning(f"[BSDEX] Error processing {market}: {exc}")
            await asyncio.sleep(1)

    def stop(self):
        self._running = False
        self._binance_ws.stop()
        if self._bsdex_ws:
            self._bsdex_ws.stop()

    # ------------------------------------------------------------------
    # API-facing read methods
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Session summary including current fee config."""
        trades     = self.simulator.trades
        n          = len(trades)
        wins       = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total_pnl  = self.simulator.total_pnl
        total_fees = self.simulator.total_fees_paid
        win_rate   = (wins / n * 100) if n > 0 else 0.0
        fx_rate    = self.fx_cache.rate
        return {
            "total_pnl_eur":       round(total_pnl, 4),
            "total_trades":        n,
            "win_rate_pct":        round(win_rate, 2),
            "total_fees_eur":      round(total_fees, 4),
            "fx_rate_usd_eur":     round(fx_rate, 6),
            "fx_age_sec":          round(self.fx_cache.age_sec, 1),
            "venue_a":             self.venue_a_label,
            "venue_b":             self.venue_b_label,
            "data_source":         self.data_source,
            # fee config
            "venue_a_taker_pct":   round(self._venue_a_taker * 100, 4),
            "venue_b_taker_pct":   round(self._venue_b_taker * 100, 4),
            "combined_taker_pct":  round(self.breakeven_spread_pct, 4),
            "breakeven_spread_pct": round(self.breakeven_spread_pct, 4),
            "tier_label":          self._tier_label,
            "tier_idx":            self._tier_idx,
            "fee_mode":            self._fee_mode,
            "capital_eur":         self._capital_eur,
        }

    def get_recent_trades(self, limit: int = 50) -> List[dict]:
        """Return the most recent simulated trades."""
        raw    = self.simulator.trades[-limit:]
        result = []
        for t in reversed(raw):
            ts     = t.get("timestamp")
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            result.append({
                "timestamp":      ts_str,
                "market":         t.get("symbol"),
                "buy_exchange":   t.get("buy_exchange"),
                "sell_exchange":  t.get("sell_exchange"),
                "buy_price_eur":  round(t.get("buy_price", 0), 4),
                "sell_price_eur": round(t.get("sell_price", 0), 4),
                "amount":         round(t.get("amount", 0), 8),
                "pnl_eur":        round(t.get("pnl", 0), 4),
                "fees_eur":       round(t.get("fees", 0), 4),
                "tier":           t.get("tier", self._tier_label),
                "fx_rate":        t.get("fx_rate", self.fx_cache.rate),
            })
        return result

    def get_latest_market(self, market: str) -> Optional[dict]:
        """Latest spread / z-score tick for chart polling."""
        return self.latest.get(market)

    def get_spread_series(self, market: str, n: int = 200) -> List[dict]:
        """Last n ticks from the rolling spread buffer."""
        return list(self._spread_buf.get(market, []))[-n:]

    # Legacy — kept so the old API route doesn't 500
    def get_phase(self, market: str) -> dict:
        return {"name": "continuous-trading", "note": "Bitstamp has no auction phases."}


# ---------------------------------------------------------------------------
# Module-level singleton (imported by main.py)
# ---------------------------------------------------------------------------
bsdex_strategy = BSDEXStrategy()
