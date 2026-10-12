#!/usr/bin/env python3
"""Record one-second top-five WS snapshots. Run from the repository root.

    venv/bin/python scripts/record_quotes.py --output data/quotes

Binance Spot partial-depth messages have no exchange timestamp: record null,
the exchange update ID and the local receipt time explicitly (never invent one).
"""
import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crypto_hft_tool.bsdex_strategy import BinanceDepthCache, BitstampDepthWsCache

from src.crypto_hft_tool.quote_recorder import QuoteRecorder, snapshot_rows, FIELDS


async def record(output):
    bs = BitstampDepthWsCache(["btceur", "etheur"])
    bn = BinanceDepthCache(["BTCUSDT", "ETHUSDT", "EURUSDT"])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    recorder = QuoteRecorder(bs, bn, output)
    tasks = [asyncio.create_task(bs.run()), asyncio.create_task(bn.run()), asyncio.create_task(recorder.run())]
    try:
        await stop.wait()
    finally:
        bs.stop()
        bn.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(record(args.output))
