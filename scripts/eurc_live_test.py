#!/usr/bin/env python3
"""EURC/EUR live paper test: passive market making + cross-venue arbitrage, net of every cost.

No orders are ever sent. Only public market data is read (no API keys needed).

What runs, side by side, for --hours (default 4):

  Market making (one instance per venue x fill model)
      Quotes EURC/EUR on both sides at (or one tick inside) the best bid/ask, never
      bids above --max-bid (par), never sells below its own average cost + fees, and
      keeps inventory between --min-eurc-frac and --max-eurc-frac of equity.
      fill model "queue":   FIFO queue position. When the order goes live it sits
                            behind the size already shown at its price; it fills
                            only after that much volume trades at its price, or
                            when the market trades through it.
      fill model "through": conservative. Fills only when a trade prints strictly
                            through the price (or the book crosses it).
  Cross-venue arbitrage (one instance per ordered venue pair)
      Buys EURC with a market order on one venue and sells on another when the
      executable VWAP gap beats both taker fees and the pro-rata cost of moving
      the inventory back (EURC withdrawal + SEPA withdrawal).
  History (downloaded once at start-up)
      Daily candles per venue: how often EURC trades below par and what a resting
      dip-buy ladder would have earned. Wicks in candles do not prove size.

No look-ahead / realistic latency:
  * Every decision uses only books and trades already received.
  * Every order (post, cancel, market order) takes effect --latency-ms (+/- jitter)
    after the decision. A cancelled order can still be filled during that window.
  * Market orders walk the book received at decision time + latency (VWAP), so
    latency slippage, depth slippage and leg risk come out of the data.
  * Resting orders fill only from trades received after the order was live.

Net PnL deducts maker/taker fees (FEES table below; override with --fee),
transfer costs, the one-off cost of building the inventory, and the capital
opportunity cost at --hurdle (default 2.5 %/yr) on the whole capital for the
whole session (money at an exchange is not in the bank).

Output: reports/eurc_<UTC>/  CSVs written while running + eurc_<UTC>.xlsx at the end.
Ctrl+C stops early and still writes the workbook. If the process dies, rebuild it:
    python scripts/eurc_live_test.py --rebuild reports/eurc_<UTC>

Examples (from the repository root):
    python scripts/eurc_live_test.py --check          # 30 s connectivity check
    python scripts/eurc_live_test.py --minutes 5      # smoke test
    python scripts/eurc_live_test.py --hours 4        # the real run
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import random
import signal
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "EURC/EUR"
YEAR_MS = 365 * 86400 * 1000
EPS = 1e-12

log = logging.getLogger("eurc")

# ---------------------------------------------------------------------------
# Cost tables. Entry (lowest) volume tier of an EU retail account, checked
# 2026-10-22. "status" says how solid each number is. Override at run time with
# --fee venue:maker:taker (fractions, e.g. --fee kraken:0.002:0.002).
# ---------------------------------------------------------------------------
FEES = {
    "bitvavo": {
        "maker": 0.0000, "taker": 0.0001,
        "tier": "EURC/EUR 'Category D', EUR 0+ 30-day volume",
        "source": "https://bitvavo.com/en/fees",
        "status": "official fee page (search extract, 2026-10); confirm in the app before trading",
    },
    "kraken": {
        "maker": 0.0020, "taker": 0.0020,
        "tier": "Stablecoin & FX pairs, lowest tier (maker = taker)",
        "source": "https://support.kraken.com/articles/360039299431-how-do-stablecoin-fx-fees-work-",
        "status": "maker = taker confirmed by Kraken; the 0.20% level comes from third-party sources",
    },
    "bitstamp": {
        "maker": 0.0030, "taker": 0.0040,
        "tier": "Base tier, no stablecoin discount assumed",
        "source": "https://www.bitstamp.net/fee-schedule/",
        "status": "UNVERIFIED: an 80% stablecoin discount is reported; conservative default",
    },
}

# EUR cost of one inventory transfer leaving each venue. EURC withdraws on
# Ethereum only at Kraken and Bitstamp (gas is cents, the exchange fee is not).
# EURC withdrawal fees were not published on pages we could reach: 5 EUR is a
# placeholder, override with --transfer venue:eurc_fee:sepa_fee.
TRANSFER = {
    "bitvavo": {"eurc_withdraw": 5.0, "sepa_withdraw": 0.0},
    "kraken": {"eurc_withdraw": 5.0, "sepa_withdraw": 1.0},
    "bitstamp": {"eurc_withdraw": 5.0, "sepa_withdraw": 3.0},
}
TRANSFER_SOURCES = (
    "Kraken SEPA withdrawal EUR 1: support.kraken.com/articles/360000423043; "
    "Kraken/Bitstamp EURC on Ethereum only: support.kraken.com/articles/stablecoins-supported-on-kraken, "
    "bitstamp.net/api/v2/currencies; Bitstamp SEPA EUR 3 vs 0.90 conflicting; Bitvavo SEPA free (third-party); "
    "EURC withdrawal fees not found -> 5 EUR placeholder"
)

DEFAULT_VENUES = ["bitvavo", "kraken", "bitstamp"]
LADDER_LEVELS = [0.9990, 0.9975, 0.9950, 0.9900, 0.9800, 0.9700]
LADDER_TARGET = 0.9995
MARKOUTS_S = (5, 60)


def now_ms() -> float:
    return time.time() * 1000.0


def iso(ts_ms: float | None) -> str:
    if ts_ms is None:
        return ""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# Market data containers and helpers
# ---------------------------------------------------------------------------
@dataclass
class Book:
    bids: list            # [[price, qty], ...] best first
    asks: list
    ex_ts: float | None   # exchange timestamp (ms) if the venue sends one
    recv_ts: float        # local receive time (ms)

    @property
    def best_bid(self):
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self):
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self):
        if not self.bids or not self.asks:
            return None
        return (self.bids[0][0] + self.asks[0][0]) / 2

    def size_at(self, side: str, price: float, tick: float) -> float | None:
        levels = self.bids if side == "buy" else self.asks
        for p, q in levels:
            if abs(p - price) < tick / 2:
                return q
        return None


@dataclass
class Trade:
    price: float
    amount: float
    side: str | None      # taker side as reported by the venue
    ex_ts: float | None
    recv_ts: float


def walk(levels: list, qty: float) -> tuple[float | None, float]:
    """VWAP for taking qty from levels (best first). Returns (vwap, filled_qty)."""
    left, cost = qty, 0.0
    for p, q in levels:
        take = min(left, q)
        cost += take * p
        left -= take
        if left <= EPS:
            break
    filled = qty - max(left, 0.0)
    return (cost / filled if filled > EPS else None), filled


def make_tick_fn(exchange, market):
    """Price tick as a function of price (handles significant-digit venues like Bitvavo)."""
    try:
        from ccxt.base.decimal_to_precision import DECIMAL_PLACES, SIGNIFICANT_DIGITS
    except Exception:  # pragma: no cover
        DECIMAL_PLACES, SIGNIFICANT_DIGITS = 2, 3
    p = (market or {}).get("precision", {}).get("price")
    mode = getattr(exchange, "precisionMode", None)
    if p is None:
        return lambda px: 0.0001
    if mode == SIGNIFICANT_DIGITS:
        digits = int(p)
        return lambda px: 10 ** (math.floor(math.log10(max(px, 1e-9))) - digits + 1)
    if mode == DECIMAL_PLACES:
        return lambda px: 10 ** -int(p)
    return lambda px: float(p)


def floor_tick(px: float, tick: float) -> float:
    return round(math.floor(px / tick + 1e-9) * tick, 10)


def ceil_tick(px: float, tick: float) -> float:
    return round(math.ceil(px / tick - 1e-9) * tick, 10)


# ---------------------------------------------------------------------------
# CSV recorder (append-only, crash-safe)
# ---------------------------------------------------------------------------
CSV_COLUMNS = {
    "market_1s": ["ts", "venue", "feed_mode", "best_bid", "bid_qty", "best_ask", "ask_qty", "mid",
                  "spread_bps", "book_age_ms", "healthy"],
    "tape": ["recv_ts", "ex_ts", "venue", "side", "price", "amount", "notional_eur"],
    "mm_fills": ["fill_ts", "instance", "venue", "fill_model", "side", "price", "qty", "notional_eur",
                 "fee_eur", "reason", "queue_ahead_at_live", "posted_ts", "live_ts", "time_to_fill_s",
                 "mid_at_fill", "markout_5s_bps", "markout_60s_bps", "eur_after", "eurc_after",
                 "avg_cost_after", "realized_eur_cum"],
    "quotes": ["ts", "instance", "action", "side", "price", "qty", "order_id"],
    "arb_trades": ["trade_id", "instance", "buy_venue", "sell_venue", "decision_ts", "buy_fill_ts",
                   "sell_fill_ts", "qty", "decision_buy_px", "decision_sell_px", "decision_edge_bps",
                   "buy_vwap", "sell_vwap", "gross_eur", "buy_fee_eur", "sell_fee_eur",
                   "transfer_cost_eur", "latency_slippage_eur", "net_eur", "net_bps"],
    "equity": ["ts", "instance", "kind", "elapsed_h", "capital_eur", "eur", "eurc", "mid",
               "equity_mid_eur", "pnl_mid_eur", "realized_eur", "fees_eur", "inventory_drift_eur",
               "mm_pnl_mid_eur", "mm_pnl_liq_eur", "opp_cost_eur", "net_eur", "net_ann_pct_naive", "fills", "volume_eur",
               "posts", "cancels", "quote_uptime_pct", "setup_cost_eur", "trades", "arb_signals",
               "best_edge_bps", "extra"],
    "errors": ["ts", "where", "error"],
}


class Recorder:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.files, self.writers = {}, {}
        for name, cols in CSV_COLUMNS.items():
            path = out_dir / f"{name}.csv"
            new = not path.exists()
            fh = open(path, "a", newline="", encoding="utf-8")
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            self.files[name], self.writers[name] = fh, w

    def row(self, name: str, **values):
        self.writers[name].writerow(values)

    def error(self, where: str, err):
        msg = f"{type(err).__name__}: {err}" if isinstance(err, BaseException) else str(err)
        log.warning("%s: %s", where, msg[:300])
        self.row("errors", ts=iso(now_ms()), where=where, error=msg[:2000])

    def flush(self):
        for fh in self.files.values():
            fh.flush()

    def close(self):
        for fh in self.files.values():
            fh.close()


# ---------------------------------------------------------------------------
# Live feed per venue (ccxt.pro WebSocket with REST fallback)
# ---------------------------------------------------------------------------
class VenueFeed:
    def __init__(self, venue: str, exchange=None, market=None, depth: int | None = None):
        self.venue = venue
        self.ex = exchange
        self.market = market or {}
        self.depth = depth
        self.tick = make_tick_fn(exchange, market) if exchange is not None else (lambda px: 0.0001)
        self.min_qty = ((self.market.get("limits") or {}).get("amount") or {}).get("min") or 0.0
        self.book: Book | None = None
        self.mode = "ws"
        self.last_error_ts = 0.0
        self.book_updates = 0
        self.trades_seen = 0
        self.trade_volume_eur = 0.0
        self.buy_volume_eur = 0.0
        self.errors = 0
        self.mode_switches = 0
        self.max_gap_ms = 0.0
        self.delays = deque(maxlen=2000)
        self._seen = deque(maxlen=5000)
        self._seen_set = set()
        self.last_trade_ts = None
        self.created_ts = now_ms()   # prints older than this are history, not session flow
        self.trade_listeners = []
        self.book_listeners = []

    # -- state ------------------------------------------------------------
    @property
    def delay_ms(self) -> float:
        """Median (receive - exchange) delay, used to place trades on our clock."""
        if len(self.delays) < 5:
            return 0.0
        return min(max(statistics.median(self.delays), 0.0), 2000.0)

    def healthy(self, t: float, rest_poll_ms: float = 1000.0) -> bool:
        if self.book is None or not self.book.bids or not self.book.asks:
            return False
        if self.book.best_bid >= self.book.best_ask:
            return False
        if self.mode == "ws":
            # A quiet EURC book can go minutes without an update; that is fine on a
            # live socket. An error after the last update means we can't trust it.
            return self.last_error_ts <= self.book.recv_ts
        return t - self.book.recv_ts <= 4 * rest_poll_ms

    # -- ingestion -----------------------------------------------------------
    def on_book(self, ob: dict, recv: float):
        cs = 1.0
        bids = [[float(l[0]), float(l[1]) * cs] for l in ob.get("bids", [])[:25] if float(l[1]) > 0]
        asks = [[float(l[0]), float(l[1]) * cs] for l in ob.get("asks", [])[:25] if float(l[1]) > 0]
        ex_ts = ob.get("timestamp")
        if self.book is not None:
            self.max_gap_ms = max(self.max_gap_ms, recv - self.book.recv_ts)
        self.book = Book(bids, asks, float(ex_ts) if ex_ts else None, recv)
        self.book_updates += 1
        for cb in self.book_listeners:
            cb(self, recv)

    def on_trades(self, trades: list, recv: float, rec: Recorder | None = None):
        for t in trades:
            key = t.get("id") or (t.get("timestamp"), t.get("price"), t.get("amount"), t.get("side"))
            if key in self._seen_set:
                continue
            self._seen.append(key)
            self._seen_set.add(key)
            if len(self._seen_set) > len(self._seen):
                self._seen_set = set(self._seen)
            ex_ts = t.get("timestamp")
            if ex_ts and (ex_ts < self.created_ts - 5_000
                          or (self.last_trade_ts and ex_ts < self.last_trade_ts - 60_000)):
                self.last_trade_ts = max(self.last_trade_ts or 0, ex_ts)
                continue  # REST backfill from before the session: not session volume
            tr = Trade(float(t["price"]), float(t["amount"]), t.get("side"),
                       float(ex_ts) if ex_ts else None, recv)
            if ex_ts:
                if abs(recv - ex_ts) < 60_000:      # skip REST backfill when estimating feed delay
                    self.delays.append(recv - ex_ts)
                self.last_trade_ts = max(self.last_trade_ts or 0, ex_ts)
            self.trades_seen += 1
            self.trade_volume_eur += tr.price * tr.amount
            if tr.side == "buy":
                self.buy_volume_eur += tr.price * tr.amount
            if rec is not None:
                rec.row("tape", recv_ts=iso(recv), ex_ts=iso(tr.ex_ts), venue=self.venue, side=tr.side,
                        price=tr.price, amount=tr.amount, notional_eur=round(tr.price * tr.amount, 4))
            for cb in self.trade_listeners:
                cb(self, tr)


async def book_loop(feed: VenueFeed, args, rec: Recorder, stop: asyncio.Event):
    fails, ws_retry_at = 0, 0.0
    while not stop.is_set():
        if feed.mode == "ws":
            try:
                ob = await feed.ex.watch_order_book(SYMBOL, feed.depth)
                feed.on_book(ob, now_ms())
                fails = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fails += 1
                feed.errors += 1
                feed.last_error_ts = now_ms()
                rec.error(f"{feed.venue} book ws", e)
                if fails >= args.ws_fail_limit:
                    feed.mode, ws_retry_at = "rest", now_ms() + 300_000
                    feed.mode_switches += 1
                    log.warning("%s: WebSocket failing, falling back to REST polling", feed.venue)
                else:
                    await asyncio.sleep(min(2 ** fails, 20))
        else:
            if now_ms() >= ws_retry_at and not args.rest_only:
                feed.mode, fails = "ws", args.ws_fail_limit - 1
                feed.mode_switches += 1
                continue
            try:
                ob = await feed.ex.fetch_order_book(SYMBOL, 25 if feed.venue != "bitvavo" else 25)
                feed.on_book(ob, now_ms())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                feed.errors += 1
                feed.last_error_ts = now_ms()
                rec.error(f"{feed.venue} book rest", e)
                await asyncio.sleep(2)
            await asyncio.sleep(args.rest_poll_ms / 1000)


async def trades_loop(feed: VenueFeed, args, rec: Recorder, stop: asyncio.Event):
    fails = 0
    while not stop.is_set():
        if feed.mode == "ws":
            try:
                trades = await feed.ex.watch_trades(SYMBOL)
                feed.on_trades(trades, now_ms(), rec)
                fails = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fails += 1
                feed.errors += 1
                feed.last_error_ts = now_ms()
                rec.error(f"{feed.venue} trades ws", e)
                await asyncio.sleep(min(2 ** fails, 20))
        else:
            try:
                since = int(feed.last_trade_ts) if feed.last_trade_ts else None
                trades = await feed.ex.fetch_trades(SYMBOL, since=since, limit=200)
                feed.on_trades(trades, now_ms(), rec)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                feed.errors += 1
                rec.error(f"{feed.venue} trades rest", e)
                await asyncio.sleep(2)
            await asyncio.sleep(max(args.rest_poll_ms, 2000) / 1000)


# ---------------------------------------------------------------------------
# Order simulation
# ---------------------------------------------------------------------------
@dataclass
class RestingOrder:
    oid: int
    owner: object
    side: str             # "buy" (bid) or "sell" (ask)
    price: float
    qty: float
    posted_ts: float      # decision time
    live_ts: float        # decision time + latency
    model: str            # "queue" or "through"
    remaining: float = 0.0
    queue_ahead: float | None = None
    queue_at_live: float | None = None
    cancel_ts: float | None = None  # cancel takes effect here (still fillable before)

    def __post_init__(self):
        self.remaining = self.qty

    def live_at(self, t: float) -> bool:
        return (t >= self.live_ts and self.remaining > EPS
                and (self.cancel_ts is None or t < self.cancel_ts))

    def done(self, t: float) -> bool:
        return self.remaining <= EPS or (self.cancel_ts is not None and t >= self.cancel_ts)


class FillSimulator:
    """Resting-order fills for one venue, driven only by data received after the order is live."""

    _next_id = 1

    def __init__(self, feed: VenueFeed):
        self.feed = feed
        self.orders: list[RestingOrder] = []
        feed.trade_listeners.append(self._on_trade)
        feed.book_listeners.append(self._on_book)

    def post(self, owner, side, price, qty, t, latency_ms, model) -> RestingOrder:
        o = RestingOrder(FillSimulator._next_id, owner, side, price, qty, t, t + latency_ms, model)
        FillSimulator._next_id += 1
        self.orders.append(o)
        return o

    def cancel(self, order: RestingOrder, t: float, latency_ms: float):
        if order.cancel_ts is None:
            order.cancel_ts = t + latency_ms

    def _activate(self, o: RestingOrder):
        if o.queue_ahead is None:
            b = self.feed.book
            tick = self.feed.tick(o.price)
            shown = b.size_at(o.side, o.price, tick) if b else None
            o.queue_ahead = shown or 0.0
            o.queue_at_live = o.queue_ahead

    def _fill(self, o: RestingOrder, qty: float, t: float, reason: str):
        qty = min(qty, o.remaining)
        if qty <= EPS:
            return
        o.remaining -= qty
        o.owner.on_fill(o, qty, t, reason)

    def _on_trade(self, feed: VenueFeed, tr: Trade):
        # Place the print on our clock; only prints after the order went live count.
        # Exchange time is used when sane (assumes an NTP-synced local clock), else
        # receive time minus the median feed delay.
        if tr.ex_ts is not None and abs(tr.recv_ts - tr.ex_ts) < 60_000:
            t_event = tr.ex_ts
        else:
            t_event = tr.recv_ts - feed.delay_ms
        tick = feed.tick(tr.price)
        for o in list(self.orders):
            if not o.live_at(t_event):
                continue
            self._activate(o)
            if o.side == "buy":
                if tr.side == "buy":
                    continue  # buyer-initiated prints lift asks, not our bid
                if tr.price < o.price - tick / 2:
                    self._fill(o, o.remaining, tr.recv_ts, "trade_through")
                elif o.model == "queue" and abs(tr.price - o.price) < tick / 2:
                    self._consume(o, tr, tick)
            else:
                if tr.side == "sell":
                    continue
                if tr.price > o.price + tick / 2:
                    self._fill(o, o.remaining, tr.recv_ts, "trade_through")
                elif o.model == "queue" and abs(tr.price - o.price) < tick / 2:
                    self._consume(o, tr, tick)
        self._prune(tr.recv_ts)

    def _consume(self, o: RestingOrder, tr: Trade, tick: float):
        amt = tr.amount
        ahead = o.queue_ahead or 0.0
        if ahead >= amt:
            o.queue_ahead = ahead - amt
            return
        o.queue_ahead = 0.0
        self._fill(o, amt - ahead, tr.recv_ts, "queue")

    def _on_book(self, feed: VenueFeed, t: float):
        b = feed.book
        for o in list(self.orders):
            if not o.live_at(t):
                continue
            self._activate(o)
            tick = feed.tick(o.price)
            # A resting ask at our bid (or bid at our ask) means that order would have
            # matched us. The conservative model only accepts a book strictly through us.
            slack = tick / 2 if o.model == "queue" else -tick / 2
            if o.side == "buy":
                if b.best_ask is not None and b.best_ask <= o.price + slack:
                    self._fill(o, o.remaining, t, "book_cross")
                    continue
            else:
                if b.best_bid is not None and b.best_bid >= o.price - slack:
                    self._fill(o, o.remaining, t, "book_cross")
                    continue
            if o.model == "queue":
                shown = b.size_at(o.side, o.price, tick)
                best = b.best_bid if o.side == "buy" else b.best_ask
                behind_best = best is not None and ((o.side == "buy" and best < o.price)
                                                    or (o.side == "sell" and best > o.price))
                if shown is None and behind_best:
                    o.queue_ahead = 0.0      # everyone ahead of us left the level
                elif shown is not None and shown < (o.queue_ahead or 0.0):
                    o.queue_ahead = shown    # cancellations ahead of us
        self._prune(t)

    def tick(self, t: float):
        """Activate orders whose latency has elapsed (queue snapshot at live time)."""
        for o in self.orders:
            if o.queue_ahead is None and o.live_at(t):
                self._activate(o)
        self._prune(t)

    def _prune(self, t: float):
        self.orders = [o for o in self.orders if not o.done(t)]


class TakerDesk:
    """Market orders: decided now, executed against the book seen at now + latency."""

    def __init__(self):
        self.pending = []  # (exec_ts, feed, side, qty, callback)

    def submit(self, feed: VenueFeed, side: str, qty: float, t: float, latency_ms: float, cb):
        self.pending.append((t + latency_ms, feed, side, qty, cb))

    def process(self, t: float):
        due = [p for p in self.pending if p[0] <= t]
        self.pending = [p for p in self.pending if p[0] > t]
        for exec_ts, feed, side, qty, cb in due:
            b = feed.book
            levels = (b.asks if side == "buy" else b.bids) if b else []
            vwap, filled = walk(levels, qty)
            cb(vwap, filled, t, b)


# ---------------------------------------------------------------------------
# Strategy 1: passive market maker on one venue
# ---------------------------------------------------------------------------
class MarketMaker:
    kind = "market_maker"

    def __init__(self, feed: VenueFeed, sim: FillSimulator, model: str, args, rec: Recorder,
                 rng: random.Random, fees: dict):
        self.feed, self.sim, self.model, self.args, self.rec, self.rng = feed, sim, model, args, rec, rng
        self.name = f"mm|{feed.venue}|{model}"
        self.maker = fees["maker"]
        self.taker = fees["taker"]
        self.capital = args.capital_eur
        self.started = False
        self.bid: RestingOrder | None = None
        self.ask: RestingOrder | None = None
        self.cancelling: list[RestingOrder] = []
        self.last_quote = {"buy": -1e18, "sell": -1e18}
        self.realized = self.fees_paid = self.volume = 0.0
        self.fills = self.posts = self.cancels = 0
        self.quoted_ms = self.alive_ms = 0.0
        self.last_step = None
        self.pending_markouts = []
        self.min_eurc = self.max_eurc = None

    # -- lifecycle ---------------------------------------------------------
    def start(self, t: float):
        b = self.feed.book
        self.mid0 = b.mid
        eurc_value = self.capital * self.args.init_eurc_frac
        self.eurc = self.eurc0 = eurc_value / self.mid0
        self.eur = self.capital - eurc_value
        self.avg_cost = self.mid0
        self.start_ts = t
        self.equity0 = self.eur + self.eurc * self.mid0
        vwap, got = walk(b.asks, self.eurc)
        # One-off: what buying the starting inventory with a market order would cost now.
        self.setup_cost = ((vwap - self.mid0) * got + vwap * got * self.taker) if vwap else float("nan")
        if got < self.eurc - EPS:
            self.rec.error(self.name, f"book too thin to buy starting inventory ({got:.0f}/{self.eurc:.0f} EURC)")
        self.min_eurc = self.max_eurc = self.eurc
        self.started = True

    def _reserved(self, t: float):
        eur = eurc = 0.0
        for o in [self.bid, self.ask] + self.cancelling:
            if o is None or o.done(t):
                continue
            if o.side == "buy":
                eur += o.remaining * o.price * (1 + self.maker)
            else:
                eurc += o.remaining
        return eur, eurc

    def _cancel(self, o: RestingOrder, t: float):
        self.sim.cancel(o, t, self._lat())
        self.cancelling.append(o)
        self.cancels += 1
        self.rec.row("quotes", ts=iso(t), instance=self.name, action="cancel", side=o.side,
                     price=o.price, qty=o.remaining, order_id=o.oid)

    def _post(self, side: str, px: float, qty: float, t: float) -> RestingOrder:
        o = self.sim.post(self, side, px, qty, t, self._lat(), self.model)
        self.posts += 1
        self.last_quote[side] = t
        self.rec.row("quotes", ts=iso(t), instance=self.name, action="post", side=side,
                     price=px, qty=qty, order_id=o.oid)
        return o

    def _lat(self) -> float:
        j = self.args.latency_jitter_ms
        return max(0.0, self.args.latency_ms + self.rng.uniform(-j, j))

    def cancel_all(self, t: float):
        for o in (self.bid, self.ask):
            if o is not None and not o.done(t) and o.cancel_ts is None:
                self._cancel(o, t)
        self.bid = self.ask = None

    # -- decision ------------------------------------------------------------
    def step(self, t: float, accepting: bool = True):
        if not self.started:
            return
        if self.last_step is not None:
            dt = t - self.last_step
            self.alive_ms += dt
            if (self.bid and self.bid.live_at(t)) or (self.ask and self.ask.live_at(t)):
                self.quoted_ms += dt
        self.last_step = t
        self.cancelling = [o for o in self.cancelling if not o.done(t)]
        self._markouts(t)
        if not accepting or not self.feed.healthy(t, self.args.rest_poll_ms):
            self.cancel_all(t)
            return
        b = self.feed.book
        bb, ba = b.best_bid, b.best_ask
        tick = self.feed.tick(bb)
        improve = self.args.improve and (ba - bb) >= 3 * tick - EPS
        mid = b.mid
        equity = self.eur + self.eurc * mid
        res_eur, res_eurc = self._reserved(t)
        min_qty = max(self.feed.min_qty, self.args.min_order_eurc)

        # Bid: join (or improve) the best bid, never above par, never crossing.
        bid_px = floor_tick(min(bb + tick if improve else bb, self.args.max_bid), tick)
        if bid_px >= ba - tick / 2:
            bid_px = floor_tick(ba - tick, tick)
        room = (self.args.max_eurc_frac * equity - self.eurc * mid) / bid_px
        own_bid = self.bid.remaining if self.bid and not self.bid.done(t) else 0.0
        free_eur = self.eur - res_eur + own_bid * (self.bid.price if self.bid else 0) * (1 + self.maker)
        # Inventory skew: quote size shrinks linearly to 0 as EURC share approaches its bound.
        frac = self.eurc * mid / equity
        tgt = self.args.init_eurc_frac
        bid_scale = min(1.0, max(0.0, (self.args.max_eurc_frac - frac) / max(self.args.max_eurc_frac - tgt, EPS)))
        ask_scale = min(1.0, max(0.0, (frac - self.args.min_eurc_frac) / max(tgt - self.args.min_eurc_frac, EPS)))
        bid_qty = max(0.0, min(self.args.quote_eur * bid_scale / bid_px,
                               free_eur / (bid_px * (1 + self.maker)), room))
        if bid_px < self.args.min_bid:
            bid_qty = 0.0
        # Only buy if a resting exit can cover both maker fees + the minimum edge.
        exit_ref = max(ba, self.args.max_bid) if self.args.exit_ref == "par" else ba
        if bid_px * (1 + 2 * self.maker) + self.args.min_edge_bps / 1e4 > exit_ref + EPS:
            bid_qty = 0.0

        # Ask: join (or improve) the best ask, never below own average cost + round-trip maker fees.
        floor = ceil_tick(self.avg_cost * (1 + 2 * self.maker) + self.args.min_edge_bps / 1e4, tick)
        ask_px = max(ceil_tick(ba - tick if improve else ba, tick), floor)
        if ask_px <= bid_px + tick / 2:
            ask_px = ceil_tick(bid_px + tick, tick)
        own_ask = self.ask.remaining if self.ask and not self.ask.done(t) else 0.0
        free_eurc = self.eurc - res_eurc + own_ask
        sellable = self.eurc - self.args.min_eurc_frac * equity / mid
        ask_qty = max(0.0, min(self.args.quote_eur * ask_scale / ask_px, free_eurc, sellable))

        self.bid = self._manage("buy", self.bid, bid_px, bid_qty, min_qty, t, tick)
        self.ask = self._manage("sell", self.ask, ask_px, ask_qty, min_qty, t, tick)

    def _manage(self, side, order, px, qty, min_qty, t, tick):
        if order is not None and order.done(t):
            order = None
        if order is not None:
            same_px = abs(order.price - px) < tick / 2
            if same_px and 0.5 * qty <= order.remaining <= qty + EPS and qty >= min_qty:
                return order
            if t - self.last_quote[side] < self.args.requote_ms:
                return order
            self._cancel(order, t)
            order = None
        if qty >= min_qty and t - self.last_quote[side] >= self.args.requote_ms:
            return self._post(side, px, qty, t)
        return None

    # -- fills ----------------------------------------------------------------
    def on_fill(self, o: RestingOrder, qty: float, t: float, reason: str):
        px = o.price
        notional = px * qty
        fee = notional * self.maker
        if o.side == "buy":
            self.eur -= notional + fee
            self.avg_cost = (self.avg_cost * self.eurc + notional + fee) / (self.eurc + qty)
            self.eurc += qty
        else:
            self.eur += notional - fee
            self.realized += (px - self.avg_cost) * qty - fee
            self.eurc -= qty
        self.fees_paid += fee
        self.volume += notional
        self.fills += 1
        self.min_eurc, self.max_eurc = min(self.min_eurc, self.eurc), max(self.max_eurc, self.eurc)
        mid = self.feed.book.mid if self.feed.book else None
        row = dict(fill_ts=iso(t), instance=self.name, venue=self.feed.venue, fill_model=self.model,
                   side=o.side, price=px, qty=round(qty, 6), notional_eur=round(notional, 4),
                   fee_eur=round(fee, 6), reason=reason, queue_ahead_at_live=o.queue_at_live,
                   posted_ts=iso(o.posted_ts), live_ts=iso(o.live_ts),
                   time_to_fill_s=round((t - o.live_ts) / 1000, 3), mid_at_fill=mid,
                   eur_after=round(self.eur, 4), eurc_after=round(self.eurc, 6),
                   avg_cost_after=round(self.avg_cost, 6), realized_eur_cum=round(self.realized, 4))
        self.pending_markouts.append({"row": row, "t": t, "side": o.side, "px": px, "marks": {}})

    def _markouts(self, t: float, final: bool = False):
        """Adverse-selection markout: mid N seconds after the fill vs fill price (+ = good for us)."""
        keep = []
        mid = self.feed.book.mid if self.feed.book else None
        for m in self.pending_markouts:
            for s in MARKOUTS_S:
                if s not in m["marks"] and mid is not None and t - m["t"] >= s * 1000:
                    sign = 1 if m["side"] == "buy" else -1
                    m["marks"][s] = round(sign * (mid - m["px"]) / m["px"] * 1e4, 3)
            if len(m["marks"]) == len(MARKOUTS_S) or final:
                row = m["row"]
                row["markout_5s_bps"] = m["marks"].get(5)
                row["markout_60s_bps"] = m["marks"].get(60)
                self.rec.row("mm_fills", **row)
            else:
                keep.append(m)
        self.pending_markouts = keep

    # -- reporting -------------------------------------------------------------
    def snapshot(self, t: float, final: bool = False) -> dict:
        if not self.started:
            return {}
        if final:
            self._markouts(t, final=True)
        b = self.feed.book
        mid = b.mid if b and b.mid else self.mid0
        equity = self.eur + self.eurc * mid
        pnl_mid = equity - self.equity0
        drift = self.eurc0 * (mid - self.mid0)            # what simply holding the start inventory did
        # Liquidation basis: rebalance back to the starting EURC with a market order now.
        delta = self.eurc - self.eurc0
        liq_eur = self.eur
        if b and delta > EPS:
            vwap, got = walk(b.bids, delta)
            liq_eur += (vwap or mid) * delta * (1 - self.taker) if got >= delta - EPS else mid * delta * 0.99
        elif b and delta < -EPS:
            vwap, got = walk(b.asks, -delta)
            liq_eur -= (vwap or mid) * (-delta) * (1 + self.taker) if got >= -delta - EPS else mid * -delta * 1.01
        liq_equity = liq_eur + self.eurc0 * mid
        mm_pnl_liq = liq_equity - self.equity0 - drift     # quoting edge, after exit costs, ex drift
        mm_pnl_mid = pnl_mid - drift                         # same, inventory marked at mid (no exit cost)
        elapsed = max(t - self.start_ts, 1.0)
        opp = self.capital * self.args.hurdle * elapsed / YEAR_MS
        net = mm_pnl_liq - opp
        ann = (mm_pnl_liq / self.capital) * (YEAR_MS / elapsed) * 100
        return dict(ts=iso(t), instance=self.name, kind=self.kind, elapsed_h=round(elapsed / 3.6e6, 4),
                    capital_eur=self.capital, eur=round(self.eur, 4), eurc=round(self.eurc, 6), mid=mid,
                    equity_mid_eur=round(equity, 4), pnl_mid_eur=round(pnl_mid, 4),
                    realized_eur=round(self.realized, 4), fees_eur=round(self.fees_paid, 4),
                    inventory_drift_eur=round(drift, 4), mm_pnl_mid_eur=round(mm_pnl_mid, 4),
                    mm_pnl_liq_eur=round(mm_pnl_liq, 4),
                    opp_cost_eur=round(opp, 4), net_eur=round(net, 4), net_ann_pct_naive=round(ann, 3),
                    fills=self.fills, volume_eur=round(self.volume, 2), posts=self.posts,
                    cancels=self.cancels,
                    quote_uptime_pct=round(100 * self.quoted_ms / self.alive_ms, 2) if self.alive_ms else 0.0,
                    setup_cost_eur=round(self.setup_cost, 4),
                    extra=json.dumps({"eurc_min": round(self.min_eurc, 2), "eurc_max": round(self.max_eurc, 2),
                                      "eurc_start": round(self.eurc0, 2), "mid_start": self.mid0,
                                      "avg_cost": round(self.avg_cost, 6), "maker_fee": self.maker,
                                      "taker_fee": self.taker}))


# ---------------------------------------------------------------------------
# Strategy 2: cross-venue taker arbitrage
# ---------------------------------------------------------------------------
class CrossArb:
    kind = "cross_arb"

    def __init__(self, buy: VenueFeed, sell: VenueFeed, desk: TakerDesk, args, rec: Recorder,
                 rng: random.Random, fees: dict):
        self.buy, self.sell, self.desk, self.args, self.rec, self.rng = buy, sell, desk, args, rec, rng
        self.name = f"arb|buy:{buy.venue}|sell:{sell.venue}"
        self.fb = fees[buy.venue]["taker"]
        self.fs = fees[sell.venue]["taker"]
        tr = args.transfer
        # Each round trip moves EURC buy->sell venue and EUR back; pro-rata per EUR traded.
        self.transfer_per_eur = (tr[buy.venue]["eurc_withdraw"] + tr[sell.venue]["sepa_withdraw"]) / args.rebalance_eur
        self.capital = 2 * args.arb_eur
        self.eur_on_buy = args.arb_eur
        self.eurc_on_sell = args.arb_eur
        self.busy = False
        self.cooldown_until = 0.0
        self.trades = []
        self.signals = 0
        self.gross_cross_ms = 0.0
        self.best_edge_bps = -1e9
        self.last_t = None
        self.start_ts = None
        self._tid = 0

    def start(self, t: float):
        self.start_ts = t

    def step(self, t: float, accepting: bool = True):
        if self.start_ts is None:
            return
        dt = t - self.last_t if self.last_t is not None else 0.0
        self.last_t = t
        if not (self.buy.healthy(t, self.args.rest_poll_ms) and self.sell.healthy(t, self.args.rest_poll_ms)):
            return
        ba, bb = self.buy.book.best_ask, self.sell.book.best_bid
        if bb > ba:
            self.gross_cross_ms += dt
        if self.busy or not accepting or t < self.cooldown_until:
            return
        qty = min(self.args.arb_eur / ba, self.eur_on_buy / (ba * (1 + self.fb)), self.eurc_on_sell)
        if qty < max(self.buy.min_qty, self.sell.min_qty, self.args.min_order_eurc):
            return
        bv, gb = walk(self.buy.book.asks, qty)
        sv, gs = walk(self.sell.book.bids, qty)
        q = min(gb, gs)
        if q < self.args.min_order_eurc or bv is None or sv is None:
            return
        bv, _ = walk(self.buy.book.asks, q)
        sv, _ = walk(self.sell.book.bids, q)
        edge = sv * (1 - self.fs) - bv * (1 + self.fb) - self.transfer_per_eur * bv
        edge_bps = edge / bv * 1e4
        self.best_edge_bps = max(self.best_edge_bps, edge_bps)
        if edge_bps < self.args.arb_min_edge_bps:
            return
        self.signals += 1
        self.busy = True
        self._tid += 1
        ctx = {"id": f"{self.name}#{self._tid}", "t": t, "q": q, "bv": bv, "sv": sv, "edge_bps": edge_bps}
        lat = lambda: max(0.0, self.args.latency_ms + self.rng.uniform(-self.args.latency_jitter_ms,
                                                                       self.args.latency_jitter_ms))
        self.desk.submit(self.buy, "buy", q, t, lat(), lambda v, f, ts, b: self._leg(ctx, "buy", v, f, ts))
        self.desk.submit(self.sell, "sell", q, t, lat(), lambda v, f, ts, b: self._leg(ctx, "sell", v, f, ts))

    def _leg(self, ctx, side, vwap, filled, ts):
        ctx[side] = (vwap, filled, ts)
        if "buy" not in ctx or "sell" not in ctx:
            return
        (bv, bq, bts), (sv, sq, sts) = ctx["buy"], ctx["sell"]
        q = min(bq, sq)
        # Any size one leg got and the other didn't is unwound at the far side of the
        # book it came from (leg risk); approximated at 1% of notional if unavailable.
        unmatched_cost = 0.0
        if abs(bq - sq) > EPS:
            extra = abs(bq - sq)
            px = bv if bq > sq else sv
            unmatched_cost = extra * (px or 1.0) * 0.01
        if q <= EPS or bv is None or sv is None:
            self.rec.error(self.name, f"leg failed: buy {bq} sell {sq}")
            self.busy = False
            return
        gross = (sv - bv) * q
        fee_b, fee_s = bv * q * self.fb, sv * q * self.fs
        transfer = self.transfer_per_eur * bv * q
        slip = ((ctx["sv"] - sv) + (bv - ctx["bv"])) * q
        net = gross - fee_b - fee_s - transfer - unmatched_cost
        # Inventories are assumed restored by the transfer whose cost is charged pro-rata above.
        self.trades.append(net)
        self.rec.row("arb_trades", trade_id=ctx["id"], instance=self.name, buy_venue=self.buy.venue,
                     sell_venue=self.sell.venue, decision_ts=iso(ctx["t"]), buy_fill_ts=iso(bts),
                     sell_fill_ts=iso(sts), qty=round(q, 6), decision_buy_px=ctx["bv"],
                     decision_sell_px=ctx["sv"], decision_edge_bps=round(ctx["edge_bps"], 3),
                     buy_vwap=bv, sell_vwap=sv, gross_eur=round(gross, 4), buy_fee_eur=round(fee_b, 4),
                     sell_fee_eur=round(fee_s, 4), transfer_cost_eur=round(transfer, 4),
                     latency_slippage_eur=round(slip, 4), net_eur=round(net, 4),
                     net_bps=round(net / (bv * q) * 1e4, 3))
        self.busy = False
        self.cooldown_until = max(bts, sts) + self.args.arb_cooldown_ms

    def snapshot(self, t: float, final: bool = False) -> dict:
        if self.start_ts is None:
            return {}
        elapsed = max(t - self.start_ts, 1.0)
        gross = sum(self.trades)
        opp = self.capital * self.args.hurdle * elapsed / YEAR_MS
        return dict(ts=iso(t), instance=self.name, kind=self.kind, elapsed_h=round(elapsed / 3.6e6, 4),
                    capital_eur=self.capital, mm_pnl_liq_eur=round(gross, 4), opp_cost_eur=round(opp, 4),
                    net_eur=round(gross - opp, 4),
                    net_ann_pct_naive=round(gross / self.capital * YEAR_MS / elapsed * 100, 3),
                    trades=len(self.trades), arb_signals=self.signals,
                    best_edge_bps=round(self.best_edge_bps, 3) if self.best_edge_bps > -1e9 else None,
                    extra=json.dumps({"gross_cross_time_pct": round(100 * self.gross_cross_ms / elapsed, 4),
                                      "taker_fee_buy": self.fb, "taker_fee_sell": self.fs,
                                      "transfer_cost_bps": round(self.transfer_per_eur * 1e4, 3)}))


# ---------------------------------------------------------------------------
# History: how often EURC trades below par, and a resting dip-buy ladder
# ---------------------------------------------------------------------------
def ladder_backtest(candles: pd.DataFrame, maker_fee: float, levels=LADDER_LEVELS,
                    target=LADDER_TARGET) -> list[dict]:
    """Resting bid at each level; filled only if a later candle's low trades strictly below it;
    sold at target only on a strictly later candle whose high trades strictly above it."""
    out = []
    if candles.empty:
        return out
    lows, highs, closes = candles["low"].tolist(), candles["high"].tolist(), candles["close"].tolist()
    days = len(candles)
    for lvl in levels:
        i, cycles, pnl_bps, holds, open_pos = 0, 0, 0.0, [], None
        while i < days:
            if open_pos is None:
                if lows[i] < lvl:
                    open_pos = i
            elif highs[i] > target:
                cycles += 1
                pnl_bps += (target * (1 - maker_fee) - lvl * (1 + maker_fee)) / lvl * 1e4
                holds.append(i - open_pos)
                open_pos = None
            i += 1
        open_mtm = ((closes[-1] - lvl) / lvl * 1e4) if open_pos is not None else 0.0
        out.append(dict(level=lvl, target=target, cycles=cycles, realized_bps_total=round(pnl_bps, 2),
                        open_at_end=open_pos is not None, open_mtm_bps=round(open_mtm, 2),
                        avg_hold_days=round(statistics.mean(holds), 2) if holds else None,
                        days=days,
                        ann_return_pct_on_committed=round((pnl_bps + open_mtm) / 1e4 * 365 / days * 100, 3)))
    return out


async def fetch_history(feeds: dict, fees: dict, out_dir: Path, rec: Recorder):
    rows, ladder = [], []
    since = int(now_ms() - 730 * 86400 * 1000)
    for venue, feed in feeds.items():
        try:
            data = await asyncio.wait_for(feed.ex.fetch_ohlcv(SYMBOL, "1d", since=since, limit=1000), 60)
        except Exception as e:
            rec.error(f"{venue} history", e)
            continue
        df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.date.astype(str)
        df["venue"] = venue
        rows.append(df)
        for r in ladder_backtest(df, fees[venue]["maker"]):
            ladder.append({"venue": venue, "from": df["date"].iloc[0], "to": df["date"].iloc[-1], **r})
    if rows:
        pd.concat(rows)[["venue", "date", "open", "high", "low", "close", "volume"]].to_csv(
            out_dir / "history_daily.csv", index=False)
    if ladder:
        pd.DataFrame(ladder).to_csv(out_dir / "ladder_backtest.csv", index=False)


# ---------------------------------------------------------------------------
# Excel workbook (built only from the CSVs + meta.json, so --rebuild works)
# ---------------------------------------------------------------------------
def _read(out_dir: Path, name: str) -> pd.DataFrame:
    p = out_dir / f"{name}.csv"
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


def build_excel(out_dir: Path) -> Path:
    meta = json.loads((out_dir / "meta.json").read_text()) if (out_dir / "meta.json").exists() else {}
    equity = _read(out_dir, "equity")
    summary = pd.DataFrame()
    if not equity.empty:
        summary = equity.sort_values("ts").groupby("instance", as_index=False).last()
        if "extra" in summary.columns:
            extra = summary["extra"].fillna("{}").apply(lambda s: json.loads(s) if isinstance(s, str) else {})
            summary = pd.concat([summary.drop(columns=["extra"]), pd.json_normalize(extra)], axis=1)
        summary = summary.dropna(axis=1, how="all")
        summary["beats_hurdle"] = summary["net_eur"] > 0

    market = _read(out_dir, "market_1s")
    tape = _read(out_dir, "tape")
    venue_stats = []
    if not market.empty:
        for venue, g in market.groupby("venue"):
            g = g[g["healthy"] == True]  # noqa: E712
            row = {"venue": venue, "seconds_sampled": len(g)}
            if not g.empty:
                row.update(spread_bps_median=g["spread_bps"].median(), spread_bps_p90=g["spread_bps"].quantile(0.9),
                           mid_min=g["mid"].min(), mid_max=g["mid"].max(), mid_median=g["mid"].median(),
                           top_bid_qty_median=g["bid_qty"].median(), top_ask_qty_median=g["ask_qty"].median())
            if not tape.empty:
                tv = tape[tape["venue"] == venue]
                hours = max(len(g), 1) / 3600
                row.update(trades=len(tv), volume_eur=tv["notional_eur"].sum(),
                           volume_eur_per_hour=tv["notional_eur"].sum() / hours,
                           buy_share_pct=100 * tv.loc[tv["side"] == "buy", "notional_eur"].sum()
                           / max(tv["notional_eur"].sum(), EPS))
            venue_stats.append(row)

    assumptions = [{"item": k, "value": v} for k, v in (meta.get("params") or {}).items()]
    fee_rows = [{"venue": v, **d} for v, d in (meta.get("fees") or {}).items()]
    tr_rows = [{"venue": v, **d} for v, d in (meta.get("transfer") or {}).items()]

    readme = [
        ("What", "EURC/EUR live paper test: passive market making per venue + cross-venue taker arbitrage."),
        ("Run", f"{meta.get('started', '')} -> {meta.get('ended', 'not finished')}  ({meta.get('status', '')})"),
        ("Capital", f"EUR {meta.get('params', {}).get('capital_eur', '')} per market-making instance; "
                    f"arbitrage uses 2 x arb_eur of inventory."),
        ("Headline column", "Summary.net_eur = quoting/arbitrage PnL after every fee, exit cost and transfer cost, "
                            "minus the opportunity cost of the capital at the hurdle rate. > 0 beats the bank."),
        ("mm_pnl_liq_eur", "Market maker: equity change if the inventory were put back to its starting EURC amount "
                           "with a market order at the end (taker fee + book walk), excluding inventory_drift_eur."),
        ("mm_pnl_mid_eur", "Same as mm_pnl_liq_eur but inventory marked at mid with no exit cost: the optimistic "
                           "bound. A real desk works inventory out passively; truth sits between the two."),
        ("Bid rule", "A bid is only posted if the current best ask (or par with --exit-ref par) covers both "
                     "maker fees + min_edge_bps; this is why a 0.20%-fee venue rarely quotes."),
        ("inventory_drift_eur", "What simply holding the starting EURC did while the price moved. Not skill; "
                                "shown separately. pnl_mid_eur includes it."),
        ("setup_cost_eur", "One-off cost of buying the starting EURC with a market order. Not in net_eur."),
        ("net_ann_pct_naive", "Session return scaled to a year. One session is not a year: treat as indicative."),
        ("Fill models", "queue = FIFO behind the size shown at our price when the order went live; "
                        "through = only when a trade prints through our price (conservative). Truth is in between."),
        ("Markouts", "mm_fills.markout_*_bps: mid 5 s / 60 s after each fill vs fill price, signed so + is good "
                     "for us. Persistently negative = adverse selection."),
        ("No look-ahead", "Decisions use only data already received; every order takes effect after the simulated "
                          "latency; market orders fill against the book at decision + latency."),
        ("Caveats", "Our simulated orders are not in the real book, so they never move the market or take "
                    "queue from real traders. Wicks in daily candles do not prove size was available."),
    ]
    xlsx = out_dir / f"{out_dir.name}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        pd.DataFrame(readme, columns=["topic", "explanation"]).to_excel(xw, sheet_name="README", index=False)
        (summary if not summary.empty else pd.DataFrame({"note": ["no snapshots recorded"]})).to_excel(
            xw, sheet_name="Summary", index=False)
        pd.DataFrame(venue_stats).to_excel(xw, sheet_name="Venues", index=False)
        pd.DataFrame(fee_rows).to_excel(xw, sheet_name="Fees", index=False)
        pd.DataFrame(tr_rows + [{"venue": "sources", "eurc_withdraw": TRANSFER_SOURCES}]).to_excel(
            xw, sheet_name="TransferCosts", index=False)
        pd.DataFrame(assumptions).to_excel(xw, sheet_name="Parameters", index=False)
        for name, sheet in [("mm_fills", "MM_Fills"), ("arb_trades", "Arb_Trades"), ("equity", "Equity"),
                            ("ladder_backtest", "Ladder_Backtest"), ("history_daily", "History_Daily"),
                            ("feed_health", "FeedHealth"), ("errors", "Errors"), ("tape", "Tape"),
                            ("market_1s", "Market_1s"), ("quotes", "Quotes")]:
            df = _read(out_dir, name)
            if len(df) > 1_000_000:
                df = df.tail(1_000_000)
            (df if not df.empty else pd.DataFrame({"note": ["no rows"]})).to_excel(xw, sheet_name=sheet, index=False)
    return xlsx


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def make_exchange(venue: str, args):
    import ccxt.pro as ccxtpro
    cfg = {"enableRateLimit": True, "timeout": 20000}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy and not args.no_env_proxy:
        cfg.update(aiohttp_trust_env=True, wssProxy=proxy)
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        cfg["cafile"] = ca
    return getattr(ccxtpro, venue)(cfg)


def parse_overrides(args):
    fees = {v: dict(FEES[v]) for v in FEES}
    for f in args.fee or []:
        v, mk, tk = f.split(":")
        fees.setdefault(v, {"tier": "override", "source": "command line", "status": "user override"})
        fees[v].update(maker=float(mk), taker=float(tk), status="user override (--fee)")
    transfer = {v: dict(TRANSFER[v]) for v in TRANSFER}
    for f in args.transfer_override or []:
        v, ew, sw = f.split(":")
        transfer[v] = {"eurc_withdraw": float(ew), "sepa_withdraw": float(sw)}
    for v in args.venues:
        if v not in fees:
            raise SystemExit(f"No fee schedule for venue '{v}'. Add one with --fee {v}:maker:taker")
        transfer.setdefault(v, {"eurc_withdraw": 5.0, "sepa_withdraw": 3.0})
    return fees, transfer


async def check(args):
    """Connectivity check: markets, one REST book, one WebSocket book and trade per venue."""
    ok = True
    for v in args.venues:
        ex = make_exchange(v, args)
        try:
            await ex.load_markets()
            m = ex.market(SYMBOL)
            ob = await ex.fetch_order_book(SYMBOL)
            print(f"[{v}] markets OK, REST book bid {ob['bids'][0] if ob['bids'] else None} "
                  f"ask {ob['asks'][0] if ob['asks'] else None}, price precision {m['precision']['price']}")
            try:
                ob = await asyncio.wait_for(ex.watch_order_book(SYMBOL), 15)
                print(f"[{v}] WebSocket book OK")
            except Exception as e:
                print(f"[{v}] WebSocket book FAILED ({type(e).__name__}: {str(e)[:120]}) -> REST fallback")
            try:
                tr = await asyncio.wait_for(ex.watch_trades(SYMBOL), 15)
                print(f"[{v}] WebSocket trades OK ({len(tr)} received)")
            except asyncio.TimeoutError:
                print(f"[{v}] no trade within 15 s (quiet market, not an error)")
            except Exception as e:
                print(f"[{v}] WebSocket trades FAILED ({type(e).__name__}: {str(e)[:120]})")
        except Exception as e:
            ok = False
            print(f"[{v}] FAILED: {type(e).__name__}: {str(e)[:200]}")
        finally:
            await ex.close()
    return 0 if ok else 1


async def run(args) -> Path:
    fees, transfer = parse_overrides(args)
    args.transfer = transfer
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "reports" / f"eurc_{stamp}"
    rec = Recorder(out_dir)
    fh = logging.FileHandler(out_dir / "run.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    rng = random.Random(args.seed)
    duration_ms = (args.minutes if args.minutes else args.hours * 60) * 60_000

    meta = {"started": iso(now_ms()), "status": "running", "symbol": SYMBOL,
            "fees": {v: fees[v] for v in args.venues}, "transfer": {v: transfer[v] for v in args.venues},
            "params": {k: v for k, v in vars(args).items() if k not in ("transfer",)}}

    def write_meta(**kw):
        meta.update(kw)
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))

    try:
        import ccxt
        meta["ccxt_version"] = ccxt.__version__
    except Exception:
        pass
    write_meta()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: Ctrl+C arrives as KeyboardInterrupt, handled in main()

    feeds, exchanges = {}, {}
    for v in args.venues:
        ex = make_exchange(v, args)
        try:
            await ex.load_markets()
            market = ex.market(SYMBOL)
            feeds[v] = VenueFeed(v, ex, market, depth=10 if v == "kraken" else None)
            if args.rest_only:
                feeds[v].mode = "rest"
            exchanges[v] = ex
            log.info("%s: %s loaded", v, SYMBOL)
        except Exception as e:
            rec.error(f"{v} load_markets", e)
            await ex.close()
    if not feeds:
        write_meta(status="failed: no venue reachable")
        rec.close()
        raise SystemExit("No venue reachable; nothing to test. Run with --check to diagnose.")

    log.info("Downloading daily history for the dip-ladder study ...")
    await fetch_history(feeds, fees, out_dir, rec)

    sims = {v: FillSimulator(f) for v, f in feeds.items()}
    desk = TakerDesk()
    tasks = []
    for f in feeds.values():
        tasks.append(asyncio.create_task(book_loop(f, args, rec, stop)))
        tasks.append(asyncio.create_task(trades_loop(f, args, rec, stop)))

    log.info("Waiting for books (max 60 s) ...")
    t0 = now_ms()
    while now_ms() - t0 < 60_000 and not stop.is_set():
        if all(f.book is not None for f in feeds.values()):
            break
        await asyncio.sleep(0.5)
    for v, f in feeds.items():
        if f.book is None:
            rec.error(v, "no order book received in 60 s; venue skipped")
    live = {v: f for v, f in feeds.items() if f.book is not None}
    await asyncio.sleep(min(args.warmup_sec, duration_ms / 4000))  # warm-up: delays, queue sizes

    mms = [MarketMaker(f, sims[v], model, args, rec, rng, fees[v])
           for v, f in live.items() if v in args.mm_venues for model in args.fill_models]
    arbs = [CrossArb(a, b, desk, args, rec, rng, fees)
            for a in live.values() for b in live.values() if a is not b]
    start = now_ms()
    for s in mms + arbs:
        if s.feed.healthy(start, args.rest_poll_ms) if isinstance(s, MarketMaker) else True:
            s.start(start)
        else:
            rec.error(s.name, "venue not healthy at start; instance not started")
    end = start + duration_ms
    log.info("Live test running until %s with %d market-maker and %d arbitrage instances",
             iso(end), len(mms), len(arbs))

    def snapshot_all(t, final=False):
        for s in mms + arbs:
            snap = s.snapshot(t, final)
            if snap:
                rec.row("equity", **snap)

    def feed_health():
        rows = [{"venue": v, "mode_at_end": f.mode, "book_updates": f.book_updates, "trades_seen": f.trades_seen,
                 "trade_volume_eur": round(f.trade_volume_eur, 2), "errors": f.errors,
                 "mode_switches": f.mode_switches, "max_gap_s": round(f.max_gap_ms / 1000, 2),
                 "median_feed_delay_ms": round(f.delay_ms, 1)} for v, f in feeds.items()]
        pd.DataFrame(rows).to_csv(out_dir / "feed_health.csv", index=False)

    next_sample = next_snap = next_flush = next_status = start
    try:
        while not stop.is_set():
            t = now_ms()
            if t >= end:
                break
            desk.process(t)
            for sim in sims.values():
                sim.tick(t)
            for s in mms + arbs:
                s.step(t)
            if t >= next_sample:
                next_sample += 1000
                for v, f in live.items():
                    b = f.book
                    if b is None or b.mid is None:
                        continue
                    rec.row("market_1s", ts=iso(t), venue=v, feed_mode=f.mode, best_bid=b.best_bid,
                            bid_qty=b.bids[0][1], best_ask=b.best_ask, ask_qty=b.asks[0][1], mid=b.mid,
                            spread_bps=round((b.best_ask - b.best_bid) / b.mid * 1e4, 3),
                            book_age_ms=round(t - b.recv_ts), healthy=f.healthy(t, args.rest_poll_ms))
            if t >= next_snap:
                next_snap += 60_000
                snapshot_all(t)
            if t >= next_flush:
                next_flush += 5000
                rec.flush()
            if t >= next_status:
                next_status += args.status_every_s * 1000
                left_min = (end - t) / 60000
                tops = "  ".join(f"{v}:{f.book.best_bid}/{f.book.best_ask}" for v, f in live.items() if f.book)
                pnl = "  ".join(f"{m.name.split('|', 1)[1]}={m.snapshot(t).get('net_eur', 0):+.2f}"
                                for m in mms if m.started)
                arb_n = sum(len(a.trades) for a in arbs)
                log.info("[%5.1f min left] %s | MM net EUR %s | arb trades %d", left_min, tops, pnl, arb_n)
                feed_health()
                write_meta()
            await asyncio.sleep(args.tick_ms / 1000)
    finally:
        status = "finished" if now_ms() >= end else "stopped early"
        t = now_ms()
        for m in mms:
            m.cancel_all(t)
        # let in-flight market orders and cancels complete against live data
        settle_until = t + 3 * (args.latency_ms + args.latency_jitter_ms) + 500
        while now_ms() < settle_until:
            desk.process(now_ms())
            for sim in sims.values():
                sim.tick(now_ms())
            for s in mms + arbs:
                s.step(now_ms(), accepting=False)
            await asyncio.sleep(0.05)
        snapshot_all(now_ms(), final=True)
        feed_health()
        write_meta(ended=iso(now_ms()), status=status)
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for ex in exchanges.values():
            try:
                await ex.close()
            except Exception:
                pass
        rec.flush()
        rec.close()
    return out_dir


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_argument_group("run")
    g.add_argument("--hours", type=float, default=4.0, help="session length (default 4)")
    g.add_argument("--minutes", type=float, default=None, help="session length in minutes (overrides --hours)")
    g.add_argument("--venues", nargs="+", default=DEFAULT_VENUES, help="venues to read (ccxt ids)")
    g.add_argument("--mm-venues", nargs="+", default=DEFAULT_VENUES, help="venues to market-make on")
    g.add_argument("--fill-models", nargs="+", default=["queue", "through"], choices=["queue", "through"])
    g.add_argument("--out", default=None, help="output folder (default reports/eurc_<UTC>)")
    g.add_argument("--check", action="store_true", help="connectivity check only")
    g.add_argument("--rebuild", default=None, help="rebuild the Excel workbook from an output folder")
    g.add_argument("--seed", type=int, default=7, help="RNG seed for latency jitter")
    c = p.add_argument_group("costs")
    c.add_argument("--capital-eur", type=float, default=40_000, help="capital per market-making instance")
    c.add_argument("--hurdle", type=float, default=0.025, help="risk-free EUR rate, annual (default 0.025)")
    c.add_argument("--fee", action="append", help="override fees: venue:maker:taker (fractions)")
    c.add_argument("--transfer-override", action="append",
                   help="override transfer costs: venue:eurc_withdraw_eur:sepa_withdraw_eur")
    c.add_argument("--rebalance-eur", type=float, default=20_000,
                   help="arbitrage: notional moved per inventory transfer (transfer cost is pro-rata)")
    x = p.add_argument_group("execution")
    x.add_argument("--latency-ms", type=float, default=300, help="decision-to-exchange latency per order")
    x.add_argument("--latency-jitter-ms", type=float, default=100, help="uniform +/- jitter on latency")
    x.add_argument("--tick-ms", type=float, default=100, help="decision loop period")
    x.add_argument("--requote-ms", type=float, default=1000, help="min time between quote changes per side")
    x.add_argument("--warmup-sec", type=float, default=30, help="data collection before trading starts")
    x.add_argument("--rest-poll-ms", type=float, default=1000, help="REST fallback polling period")
    x.add_argument("--rest-only", action="store_true", help="skip WebSockets (diagnostics)")
    x.add_argument("--ws-fail-limit", type=int, default=5, help="WebSocket errors before REST fallback")
    x.add_argument("--no-env-proxy", action="store_true", help="ignore HTTPS_PROXY")
    m = p.add_argument_group("market maker")
    m.add_argument("--init-eurc-frac", type=float, default=0.5, help="share of capital held as EURC at start")
    m.add_argument("--min-eurc-frac", type=float, default=0.25, help="lower inventory bound (share of equity)")
    m.add_argument("--max-eurc-frac", type=float, default=0.75, help="upper inventory bound (share of equity)")
    m.add_argument("--quote-eur", type=float, default=2_500,
                   help="max size per quote (EUR); shrinks with inventory skew")
    m.add_argument("--max-bid", type=float, default=1.0000, help="never bid above this (par)")
    m.add_argument("--min-bid", type=float, default=0.97, help="stop bidding below this (depeg stop)")
    m.add_argument("--min-edge-bps", type=float, default=1.0,
                   help="asks at least this far above average cost after maker fees")
    m.add_argument("--exit-ref", choices=["ask", "par"], default="ask",
                   help="exit price a new bid must clear after fees: current best ask (conservative) "
                        "or max(ask, --max-bid) i.e. trust redemption at par")
    m.add_argument("--no-improve", dest="improve", action="store_false",
                   help="always join the best price instead of stepping one tick inside wide spreads")
    m.add_argument("--min-order-eurc", type=float, default=10.0)
    a = p.add_argument_group("arbitrage")
    a.add_argument("--arb-eur", type=float, default=10_000, help="arbitrage order size / inventory per venue")
    a.add_argument("--arb-min-edge-bps", type=float, default=0.5, help="net edge after all costs to fire")
    a.add_argument("--arb-cooldown-ms", type=float, default=2000)
    o = p.add_argument_group("output")
    o.add_argument("--status-every-s", type=float, default=60)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("ccxt", "asyncio", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.rebuild:
        print(build_excel(Path(args.rebuild)))
        return 0
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        import ccxt  # noqa: F401
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"Missing dependency ({e}). Run: pip install -r requirements.txt")
    if args.check:
        return asyncio.run(check(args))
    out_dir = None
    try:
        out_dir = asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning("Interrupted; building the workbook from what was recorded")
        stamp_dirs = sorted((ROOT / "reports").glob("eurc_*"))
        out_dir = Path(args.out) if args.out else (stamp_dirs[-1] if stamp_dirs else None)
    if out_dir is not None:
        xlsx = build_excel(out_dir)
        log.info("Workbook: %s", xlsx)
        print(f"\nDone. Send this file back for the analysis:\n  {xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
