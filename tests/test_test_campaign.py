"""Offline checks for scripts/run_test_campaign.py (no network)."""
import importlib.util
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_test_campaign", ROOT / "scripts" / "run_test_campaign.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


class FakeBitstamp:
    connected = True

    def __init__(self, books):
        self.books = books

    def get_book(self, ticker):
        return self.books.get(ticker)

    def age_sec(self, ticker):
        return 0.1


class FakeBinance:
    connected = True

    def __init__(self, books, quotes):
        self.books, self.quotes = books, quotes

    def get_orderbook(self, symbol):
        return self.books.get(symbol)

    def get_quote(self, symbol):
        return self.quotes.get(symbol)


def book(bid, ask, qty=10):
    return {"bids": {Decimal(str(bid)): Decimal(qty)}, "asks": {Decimal(str(ask)): Decimal(qty)}}


def feeds(now, binance_ask=99.9):
    bs = FakeBitstamp({"btceur": book(100.1, 100.2), "etheur": book(100.1, 100.2)})
    bn = FakeBinance(
        {"BTCUSDT": book(99.8, binance_ask), "ETHUSDT": book(99.8, binance_ask)},
        {"BTCUSDT": {"ts": now}, "ETHUSDT": {"ts": now}, "EURUSDT": {"bid": 1.0, "ask": 1.0, "ts": now}},
    )
    return bs, bn


def test_sample_books_measures_both_directions():
    rows = rc.sample_books(*feeds(1000.0), sizes=[100], now=1000.0)
    row = rows[0]
    assert row["ok"] == 1
    # Sell Bitstamp at 100.1, buy Binance at 99.9: +0.2 on a 100.15 mid.
    assert row["s100_sellA"] == pytest.approx(0.2 / 100.15 * 1e4)
    # Buy Bitstamp at 100.2, sell Binance at 99.8: -0.4.
    assert row["s100_buyA"] == pytest.approx(-0.4 / 100.15 * 1e4)
    # Not enough depth for 10,000 EUR (10 units) is reported as missing, not zero.
    big = rc.sample_books(*feeds(1000.0), sizes=[100_000], now=1000.0)[0]
    assert pd.isna(big["s100000_sellA"])


def test_missing_book_is_flagged():
    bs, bn = feeds(1000.0)
    bs.books.pop("btceur")
    rows = rc.sample_books(bs, bn, sizes=[100], now=1000.0)
    assert rows[0]["ok"] == 0 and rows[1]["ok"] == 1


def test_analysis_and_excel(tmp_path):
    rows = []
    for k in range(400):
        now = 1000.0 + k * 0.25
        # A 20 bp gap that exists for one sample in every 100 and vanishes next.
        rows += rc.sample_books(*feeds(now, binance_ask=99.9 if k % 100 == 0 else 100.15), sizes=[100], now=now)
    shadow = pd.DataFrame(rows)
    out = rc.analyse_live(shadow, None, sizes=[100], capital_size=100, sample_ms=250)
    gate = out["Live_Tier_Gate"]
    best = gate[(gate["market"] == "btc-eur") & (gate["tier"].str.startswith("7:"))].iloc[0]
    assert best["episodes"] == 4
    persist = out["Live_Persistence"]
    row = persist[(persist["market"] == "btc-eur") & (persist["trigger"] == "gap > 0 bps")
                  & (persist["lag_ms"] == 250)].iloc[0]
    assert row["events"] == 4 and row["pct_still_above_0"] == 0

    args = rc.parse_args(["--hours", "0", "--quick", "--capital", "100", "--sizes", "100"])
    res = {"errors": [], "shadow": shadow, "analysis": out}
    path = tmp_path / "campaign.xlsx"
    rc.write_excel(path, res, args, rc.environment_rows(args, pd.Timestamp.now(tz="UTC")))
    sheets = pd.read_excel(path, sheet_name=None)
    for name in ("README", "Summary", "Live_Spreads", "Live_Tier_Gate", "Live_Persistence",
                 "Quote_Replay", "Candle_Backtests", "Control_Pair", "Errors"):
        assert name in sheets
