"""One-second quote recording from live caches, shared by backend and CLI."""
import asyncio
import csv
import fcntl
import gzip
import io
import json
import logging
import time
from datetime import datetime, timezone

from .quote_data import resolve_quote_path

log = logging.getLogger(__name__)
FIELDS = ["ts_ms", "market"] + [
    f"{venue}_{field}"
    for venue in ("bs", "bn", "eurusdt")
    for field in ("bids", "asks", "received_ts_ms", "exchange_ts_ms", "update_id")
]


def snapshot_rows(bs, bn, now):
    rows = []
    for market, ticker, symbol in (("btc-eur", "btceur", "BTCUSDT"), ("eth-eur", "etheur", "ETHUSDT")):
        row = {"ts_ms": int(now * 1000), "market": market}
        for prefix, book, received, exchange, update_id in (
            ("bs", bs.get_book(ticker), bs._updated.get(ticker), bs._exchange_ts.get(ticker), None),
            *[(prefix, bn.get_orderbook(sym), (bn.get_quote(sym) or {}).get("ts"),
               (bn.get_quote(sym) or {}).get("exchange_ts_ms"),
               (bn.get_quote(sym) or {}).get("update_id"))
              for prefix, sym in (("bn", symbol), ("eurusdt", "EURUSDT"))],
        ):
            if not book or received is None or now - received > 5:
                break
            for side in ("bids", "asks"):
                row[f"{prefix}_{side}"] = json.dumps([
                    [str(p), str(book[side][p])]
                    for p in sorted(book[side], reverse=side == "bids")[:5]
                ])
            row[f"{prefix}_received_ts_ms"] = int(received * 1000)
            row[f"{prefix}_exchange_ts_ms"] = exchange
            row[f"{prefix}_update_id"] = update_id
        else:
            rows.append(row)
    return rows


class QuoteRecorder:
    def __init__(self, bitstamp, binance, output=None):
        self.bitstamp = bitstamp
        self.binance = binance
        self.output = resolve_quote_path(output)
        self.status = {"state": "starting", "directory": str(self.output), "last_snapshot": None}

    def append(self, rows, now):
        path = self.output / f"{datetime.fromtimestamp(now, timezone.utc):%Y-%m-%d}.csv.gz"
        with path.open("ab") as target:
            # Readers take a shared lock while copying the compressed file so a
            # concurrent backtest never sees a partially written gzip member.
            fcntl.flock(target, fcntl.LOCK_EX)
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=FIELDS)
            if target.tell() == 0:
                writer.writeheader()
            writer.writerows(rows)
            target.write(gzip.compress(buffer.getvalue().encode("utf-8")))
        self.status.update(state="recording", last_snapshot=int(now * 1000))

    async def run(self):
        last_seen, missing = {}, set()
        while True:
            try:
                self.output.mkdir(parents=True, exist_ok=True)
                # One recorder per directory, even with multiple API workers or
                # the standalone CLI running. The OS releases this on exit.
                with (self.output / ".recorder.lock").open("a") as leader:
                    try:
                        fcntl.flock(leader, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        self.status["state"] = "another_worker"
                        await asyncio.sleep(5)
                        continue
                    while True:
                        now = time.time()
                        rows = snapshot_rows(self.bitstamp, self.binance, now)
                        present = {row["market"] for row in rows}
                        for market in ("btc-eur", "eth-eur"):
                            if market not in present and market not in missing:
                                log.warning("Quote gap started: %s (missing/stale book)", market)
                                missing.add(market)
                            elif market in present:
                                gap = now - last_seen.get(market, now)
                                if market in missing or gap > 2:
                                    log.warning("Quote gap ended: %s; %.2fs since previous snapshot", market, gap)
                                missing.discard(market)
                                last_seen[market] = now
                        if rows:
                            # A write is short and has no await boundary: cancellation
                            # cannot release leadership with an append still in flight.
                            self.append(rows, now)
                        else:
                            self.status["state"] = "waiting_for_books"
                        await asyncio.sleep(max(.01, 1 - (time.time() - now)))
            except asyncio.CancelledError:
                self.status["state"] = "stopped"
                raise
            except Exception as exc:
                self.status.update(state="error", error=str(exc))
                log.error("Quote recording failed at %s: %s", self.output, exc)
                await asyncio.sleep(5)
