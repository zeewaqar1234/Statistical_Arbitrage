"""Read-only acceptance check against public venue data; no orders are submitted."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.crypto_hft_tool.bsdex_historical_bt import run_historical_backtest
from src.crypto_hft_tool.bsdex_strategy import BSDEXStrategy


async def verify(capital, live_seconds):
    result = await run_historical_backtest(
        "btc-eur", datetime(2026, 9, 24, tzinfo=timezone.utc),
        datetime(2026, 10, 1, tzinfo=timezone.utc), .0005, .0003, capital,
        tier_label="> $250M",
    )
    print(json.dumps(result["realistic"]["summary"], indent=2))
    if live_seconds:
        engine = BSDEXStrategy()
        task = asyncio.create_task(engine.run())
        try:
            await asyncio.sleep(live_seconds)
            print(json.dumps({"live_status": engine.get_status(), "markets": engine.latest}, indent=2))
        finally:
            engine.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--live-seconds", type=float, default=0)
    args = parser.parse_args()
    asyncio.run(verify(args.capital, args.live_seconds))
