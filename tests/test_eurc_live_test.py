"""Offline tests for scripts/eurc_live_test.py: fill timing (no look-ahead), queue model, accounting."""
import importlib.util
import random
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location(
    "eurc_live_test", Path(__file__).resolve().parents[1] / "scripts" / "eurc_live_test.py")
E = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = E
SPEC.loader.exec_module(E)


def args(**kw):
    a = E.build_parser().parse_args([])
    a.latency_jitter_ms = 0
    a.transfer = E.TRANSFER
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def feed_with_book(bids, asks, t=0.0, venue="bitvavo"):
    f = E.VenueFeed(venue)
    f.created_ts = -1e9
    f.on_book({"bids": bids, "asks": asks, "timestamp": None}, t)
    return f


class Owner:
    def __init__(self):
        self.fills = []

    def on_fill(self, o, qty, t, reason):
        self.fills.append((qty, t, reason))


def trade(f, px, amt, side, t):
    f.on_trades([{"id": f"{t}-{px}-{amt}", "price": px, "amount": amt, "side": side, "timestamp": t}], t)


def test_walk_vwap_and_depth():
    vwap, got = E.walk([[1.0, 100], [1.01, 100]], 150)
    assert got == 150 and vwap == pytest.approx((100 * 1.0 + 50 * 1.01) / 150)
    vwap, got = E.walk([[1.0, 10]], 50)
    assert got == 10


def test_no_fill_before_order_is_live():
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]])
    sim, own = E.FillSimulator(f), Owner()
    sim.post(own, "buy", 0.9990, 100, t=1000, latency_ms=300, model="through")
    trade(f, 0.9980, 5000, "sell", 1200)        # through our price, but before live (1300)
    assert own.fills == []
    trade(f, 0.9980, 5000, "sell", 1400)        # after live -> filled
    assert own.fills and own.fills[0][0] == 100 and own.fills[0][2] == "trade_through"


def test_queue_model_waits_for_volume_ahead():
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]])
    sim, own = E.FillSimulator(f), Owner()
    sim.post(own, "buy", 0.9990, 100, t=0, latency_ms=300, model="queue")
    sim.tick(400)                               # goes live behind 1000 shown
    trade(f, 0.9990, 600, "sell", 500)
    assert own.fills == []
    trade(f, 0.9990, 450, "sell", 600)          # 1050 traded, 50 past the queue
    assert own.fills[0][0] == pytest.approx(50)
    trade(f, 0.9990, 100, "buy", 700)           # buyer-initiated print does not hit bids
    assert len(own.fills) == 1


def test_through_model_ignores_prints_at_price():
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]])
    sim, own = E.FillSimulator(f), Owner()
    sim.post(own, "buy", 0.9990, 100, t=0, latency_ms=300, model="through")
    sim.tick(400)
    trade(f, 0.9990, 1e6, "sell", 500)
    assert own.fills == []


def test_cancelled_order_can_fill_during_cancel_latency():
    f = feed_with_book([[0.9990, 0]], [[0.9995, 1000]])
    sim, own = E.FillSimulator(f), Owner()
    o = sim.post(own, "sell", 0.9995, 100, t=0, latency_ms=300, model="through")
    sim.tick(400)
    sim.cancel(o, 1000, 300)                    # effective at 1300
    trade(f, 0.9996, 500, "buy", 1200)
    assert own.fills and own.fills[0][0] == 100


def test_taker_fills_at_book_after_latency_not_decision_book():
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]], t=0)
    desk, got = E.TakerDesk(), []
    desk.submit(f, "buy", 100, t=0, latency_ms=300, cb=lambda v, q, t, b: got.append(v))
    desk.process(100)
    assert got == []
    f.on_book({"bids": [[0.9995, 1000]], "asks": [[1.0005, 1000]]}, 250)   # market moved
    desk.process(300)
    assert got == [pytest.approx(1.0005)]


def test_market_maker_round_trip_accounting():
    a = args(capital_eur=10_000, quote_eur=1_000, improve=False, min_edge_bps=0)
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]])
    sim = E.FillSimulator(f)
    rec = types.SimpleNamespace(row=lambda *x, **k: None, error=lambda *x, **k: None)
    mm = E.MarketMaker(f, sim, "through", a, rec, random.Random(1), {"maker": 0.0, "taker": 0.0001})
    mm.start(0)
    eur0, eurc0 = mm.eur, mm.eurc
    mm.step(1000)
    assert mm.bid.price == 0.9990 and mm.ask.price >= 0.9995
    q = mm.bid.qty
    trade(f, 0.9985, 1e5, "sell", 2000)          # bid filled
    assert mm.eurc == pytest.approx(eurc0 + q)
    assert mm.eur == pytest.approx(eur0 - q * 0.9990)
    assert mm.avg_cost < mm.mid0


def test_ladder_backtest_needs_later_candle_to_exit():
    c = pd.DataFrame({"low": [0.995, 0.999, 0.999], "high": [1.001, 0.9990, 1.0],
                      "close": [0.998, 0.999, 0.9998]})
    res = {r["level"]: r for r in E.ladder_backtest(c, 0.0, levels=[0.996], target=0.9995)}
    assert res[0.996]["cycles"] == 1           # bought day 0, sold day 2 (not day 0's high)


def test_significant_digit_tick():
    ex = types.SimpleNamespace(precisionMode=3)    # SIGNIFICANT_DIGITS
    tick = E.make_tick_fn(ex, {"precision": {"price": 5}})
    assert tick(0.99876) == pytest.approx(1e-5)
    assert tick(1.0001) == pytest.approx(1e-4)


def test_through_model_needs_book_strictly_through():
    f = feed_with_book([[0.9985, 1000]], [[0.9995, 1000]])
    sim, own = E.FillSimulator(f), Owner()
    sim.post(own, "buy", 0.9990, 100, t=0, latency_ms=300, model="through")
    sim.tick(400)
    f.on_book({"bids": [[0.9985, 1000]], "asks": [[0.9990, 1000]]}, 500)    # locked at our price
    assert own.fills == []
    f.on_book({"bids": [[0.9980, 1000]], "asks": [[0.9989, 1000]]}, 600)    # through us
    assert own.fills and own.fills[0][2] == "book_cross"


def test_inventory_skew_stops_bidding_at_upper_bound():
    a = args(capital_eur=10_000, quote_eur=1_000, improve=False, min_edge_bps=0)
    f = feed_with_book([[0.9990, 1000]], [[0.9995, 1000]])
    rec = types.SimpleNamespace(row=lambda *x, **k: None, error=lambda *x, **k: None)
    mm = E.MarketMaker(f, E.FillSimulator(f), "queue", a, rec, random.Random(1), {"maker": 0.0, "taker": 0.0})
    mm.start(0)
    mm.eurc, mm.eur = 7_600 / 0.99925, 2_400            # 76% EURC > 75% bound
    mm.step(1000)
    assert mm.bid is None and mm.ask is not None


def test_pre_session_trades_do_not_count_as_volume():
    f = E.VenueFeed("kraken")
    f.created_ts = 1_000_000
    f.on_trades([{"id": "old", "price": 1.0, "amount": 500, "side": "buy", "timestamp": 100_000}], 1_000_100)
    f.on_trades([{"id": "new", "price": 1.0, "amount": 7, "side": "buy", "timestamp": 1_000_050}], 1_000_100)
    assert f.trades_seen == 1 and f.trade_volume_eur == 7
