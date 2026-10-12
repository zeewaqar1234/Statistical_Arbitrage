import csv
import gzip
import json
import math
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.crypto_hft_tool import bsdex_strategy as live
from src.crypto_hft_tool.bsdex_historical_bt import run_quote_backtest, _exec_costs_resolved


def book(bid, ask, quantity=1000):
    return {"bids": {Decimal(str(bid)): Decimal(str(quantity))},
            "asks": {Decimal(str(ask)): Decimal(str(quantity))}}


def live_engine(monkeypatch):
    clock = [1_790_000_000.0]
    monkeypatch.setattr(live.time, "time", lambda: clock[0])
    engine = live.BSDEXStrategy()
    engine._bitstamp_depth_ws = live.BitstampDepthWsCache(["btceur"])
    engine._bitstamp_depth_ws._books["btceur"] = book(105, 106)
    engine._bitstamp_depth_ws._updated["btceur"] = clock[0]
    for symbol, bid, ask in (("BTCUSDT", 100, 101), ("EURUSDT", 1, 1)):
        engine._binance_ws._process_depth({"bids": [[str(bid), "1000"]], "asks": [[str(ask), "1000"]]}, f"{symbol.lower()}@depth20@100ms")
    engine.signal_processors["btc-eur"] = SimpleNamespace(update=lambda *args: {"signal": SimpleNamespace(zscore=2., threshold=1.5)})
    return engine, clock


@pytest.mark.asyncio
async def test_live_fill_uses_later_full_size_books_and_can_lose(monkeypatch):
    engine, clock = live_engine(monkeypatch)
    await engine._process_market("btc-eur")
    pending = dict(engine._pending["btc-eur"])
    assert not engine.simulator.trades
    clock[0] += .299
    await engine._process_market("btc-eur")
    assert not engine.simulator.trades
    engine._bitstamp_depth_ws._books["btceur"] = book(98, 99)
    clock[0] += .002
    engine.set_capital(5000)  # does not resize an already committed order
    await engine._process_market("btc-eur")
    trade, = engine.simulator.trades
    assert trade["pnl"] < 0
    assert trade["amount"] == pending["amount"]
    assert trade["signal_spread_pct"] > 0 > trade["realized_spread_pct"]
    assert trade["buy_price"] == pytest.approx(101)
    assert trade["sell_price"] == pytest.approx(98)
    assert trade["fx_cost_eur"] == pytest.approx(trade["amount"] * 101 * .0001)
    assert engine.get_recent_trades()[0]["market"] == "btc-eur"


@pytest.mark.asyncio
async def test_stale_fx_never_uses_ecb(monkeypatch):
    engine, clock = live_engine(monkeypatch)
    engine.fx_cache._rate = 123
    clock[0] += 5.01
    await engine._process_market("btc-eur")
    assert engine.latest["btc-eur"]["signal_state"] == "FX_STALE"
    assert not engine.simulator.trades
    assert engine._pending["btc-eur"] is None
    assert "EURUSDT" in engine._binance_ws._symbols


@pytest.mark.asyncio
async def test_live_insufficient_fill_is_reported_not_retried(monkeypatch):
    engine, clock = live_engine(monkeypatch)
    await engine._process_market("btc-eur")
    clock[0] += .301
    engine._bitstamp_depth_ws._books["btceur"] = book(110, 111, quantity=.0001)
    await engine._process_market("btc-eur")
    assert engine._pending["btc-eur"] is None
    assert not engine.simulator.trades
    assert engine.execution_failures[-1]["reason"] == "INSUFFICIENT_DEPTH"


def test_fx_conversion_is_side_specific_for_every_depth_level():
    converted = live._binance_book_usdt_to_eur(book(110, 111), 1.1, 1.2)
    assert float(max(converted["bids"])) == pytest.approx(110 / 1.2)
    assert float(min(converted["asks"])) == pytest.approx(111 / 1.1)


def quote_file(tmp_path, persists=False, thin_fill=False):
    path = tmp_path / "quotes.csv.gz"
    keys = ["ts_ms", "market"] + [f"{v}_{k}" for v in ("bs", "bn", "eurusdt") for k in ("bids", "asks", "received_ts_ms")]
    with gzip.open(path, "wt", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for i in range(5603):
            ts = 1_790_000_000_000 + i * 1000
            price = 100 + math.sin(i) * .001
            if i in (3601, 5501):
                price += 3
            if i in (3602, 5502):
                price += 3 if persists else -3
            row = {"ts_ms": ts, "market": "btc-eur"}
            for venue, bid, ask in (("bs", price, price + .01), ("bn", 100, 100.01), ("eurusdt", 1, 1)):
                quantity = .00001 if thin_fill and i in (3602, 5502) else 1000
                row.update({f"{venue}_bids": json.dumps([[bid, quantity]]),
                            f"{venue}_asks": json.dumps([[ask, quantity]]), f"{venue}_received_ts_ms": ts})
            writer.writerow(row)
    return path


@pytest.mark.parametrize("persists", [False, True])
def test_quote_replay_signals_then_fills_next_snapshot(tmp_path, persists):
    result = run_quote_backtest(quote_file(tmp_path, persists), 300, 0, 1000)
    trades = result["realistic"]["trades"]
    assert len(trades) == 2
    assert all((t["pnl_eur"] > 0) == persists for t in trades)
    assert all(t["fill_ts"] - t["signal_ts"] == 1000 for t in trades)
    summary = result["realistic"]["summary"]
    assert summary["sharpe_daily_ann"] is None
    assert summary["net_after_carry_eur"] < summary["total_pnl_eur"]
    assert summary["exec_costs"]["spread_model"] == "recorded executable depth"


def test_quote_replay_reports_unfillable_first_tick(tmp_path):
    result = run_quote_backtest(quote_file(tmp_path, thin_fill=True), 300, 0, 1000)
    assert not result["realistic"]["trades"]
    assert len(result["realistic"]["failed_fills"]) == 2


def test_calibration_requires_real_preperiod_quotes(tmp_path):
    path = quote_file(tmp_path)
    with pytest.raises(ValueError, match="precede"):
        _exec_costs_resolved("calibrated", path, before_ts=1)
    costs = _exec_costs_resolved("calibrated", path, before_ts=1_790_000_060_000)
    assert costs["calibration_samples"] == 60
    assert costs["half_spread_bps"]["venue_a"] == pytest.approx(.5, abs=.001)


def test_recorder_preserves_exchange_time_and_receipt_time(tmp_path, monkeypatch):
    from scripts.record_quotes import snapshot_rows, FIELDS
    from src.crypto_hft_tool.quote_data import read_quotes
    engine, clock = live_engine(monkeypatch)
    engine._bitstamp_depth_ws._exchange_ts["btceur"] = int(clock[0] * 1000) - 200
    rows = snapshot_rows(engine._bitstamp_depth_ws, engine._binance_ws, clock[0])
    assert len(rows) == 1
    row = rows[0]
    assert row["bs_exchange_ts_ms"] == row["ts_ms"] - 200
    assert row["bn_exchange_ts_ms"] is None  # not included in partial-depth feed
    assert row["bn_received_ts_ms"] == row["ts_ms"]
    path = tmp_path / "recorded.csv.gz"
    with gzip.open(path, "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    loaded, = read_quotes(path, "btc-eur")
    assert loaded["fresh"]
    assert loaded["a"] == engine._bitstamp_depth_ws.get_book("btceur")
    clock[0] += 6
    assert snapshot_rows(engine._bitstamp_depth_ws, engine._binance_ws, clock[0]) == []


def test_sharpe_thresholds_include_idle_calendar_days():
    from datetime import datetime, timedelta, timezone
    from src.crypto_hft_tool.bsdex_historical_bt import _compute_daily_sharpe
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=20)
    trades = [{"ts": int(start.timestamp() * 1000), "pnl_eur": 1.} for _ in range(30)]
    assert _compute_daily_sharpe(trades[:29], 1000, start_dt=start, end_dt=end) is None
    assert _compute_daily_sharpe(trades, 1000, start_dt=start, end_dt=end - timedelta(days=1)) is None
    # One active day and 19 idle days still has a meaningful calendar-day variance.
    assert _compute_daily_sharpe(trades, 1000, start_dt=start, end_dt=end) is not None


def test_quote_default_path_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    from pathlib import Path
    from src.crypto_hft_tool.config import PROJECT_ROOT
    from src.crypto_hft_tool.quote_data import resolve_quote_path
    monkeypatch.chdir(tmp_path)
    assert resolve_quote_path("data/quotes") == Path(PROJECT_ROOT) / "data/quotes"


def test_empty_quote_folder_explains_how_to_collect_data(tmp_path):
    from src.crypto_hft_tool.quote_data import read_quotes
    with pytest.raises(ValueError, match="60 minutes of recording"):
        read_quotes(tmp_path, "btc-eur")


@pytest.mark.asyncio
async def test_automatic_recorder_writes_replayable_snapshots_and_releases_lock(tmp_path, monkeypatch):
    import asyncio
    import fcntl
    from src.crypto_hft_tool.quote_recorder import QuoteRecorder
    from src.crypto_hft_tool.quote_data import read_quotes
    engine, clock = live_engine(monkeypatch)
    recorder = QuoteRecorder(engine._bitstamp_depth_ws, engine._binance_ws, tmp_path)
    task = asyncio.create_task(recorder.run())
    await asyncio.sleep(.02)
    try:
        assert recorder.status["state"] == "recording"
        rows = read_quotes(tmp_path, "btc-eur")
        assert len(rows) == 1
        assert rows[0]["ts"] == int(clock[0] * 1000)
        with (tmp_path / ".recorder.lock").open("a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    with (tmp_path / ".recorder.lock").open("a") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # The same day can be appended without a duplicate header or broken gzip stream.
    from src.crypto_hft_tool.quote_recorder import snapshot_rows
    clock[0] += 1
    recorder.append(snapshot_rows(engine._bitstamp_depth_ws, engine._binance_ws, clock[0]), clock[0])
    assert len(read_quotes(tmp_path, "btc-eur")) == 2


def test_quote_replay_reports_available_dates_and_warmup(tmp_path):
    from datetime import datetime, timedelta, timezone
    path = quote_file(tmp_path)
    start = datetime.fromtimestamp(1_790_000_000, timezone.utc)
    with pytest.raises(ValueError, match="Available btc-eur quotes"):
        run_quote_backtest(path, start_dt=start-timedelta(days=2), end_dt=start-timedelta(days=1))
    with pytest.raises(ValueError, match="at least 60 minutes"):
        run_quote_backtest(path, start_dt=start, end_dt=start+timedelta(minutes=5))
