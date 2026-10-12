# Engine integrity fixes

The BSDEX paper engine now uses Binance EURUSDT WebSocket bid/ask FX, checks
freshness against the last WS receipt (5 seconds maximum), and commits a fixed
quantity on the signal. Fills walk both books on the first evaluation tick at or
after 300 ms. A losing fill is booked. Stale books or insufficient fill depth are
reported as failed executions; the engine does not wait for a profitable price.
The evaluation loop runs every 50 ms and preserves the existing one-second
signal sampling. Restarting the backend starts a fresh paper-trading session.
ECB fixing and its publication date are display references only.

Candle backtests gate on signal-bar prices, then book the next bar's fill of
either sign. The unused legacy `bsdex_backtest` module/CLI has been removed.
The candle strategy parameters remain 60 minutes, 1.5 sigma, 30-minute cooldown.
The separate Binance/Kraken engine was not changed.

## Recording and replaying quotes

The backend now records automatically from its existing live WebSocket books.
Keep it running for at least 60 minutes before replaying the recorded period.
Relative paths resolve from the project root, regardless of the launch directory.
`QUOTE_DATA_DIR` can select another storage directory. The default `data/quotes`
input resolves to that configured directory too. Multiple backend workers and the
standalone CLI elect one recorder using a directory lock; readers are protected
from partially written gzip members.

To record without the backend, run from the repository root:

```sh
venv/bin/python scripts/record_quotes.py --output data/quotes
```

The recorder reconnects its feeds, logs missing/stale books and gaps, and appends
one-second snapshots to UTC daily `YYYY-MM-DD.csv.gz` files. Each row stores five
bid and ask levels for Bitstamp, Binance crypto/USDT, and EURUSDT, with local
receipt times. Bitstamp includes an exchange timestamp. Binance partial-depth
messages do not supply one: that field is empty, and the exchange update ID is
retained. SIGINT/SIGTERM stops cleanly. The backend owns its recorder task; the
standalone command can alternatively run under a process supervisor. Use durable
storage for recordings you need to keep across deployments. The backtest UI shows
recorder status and reports available dates if the selected period has no quotes.
Historical order books cannot be reconstructed from candles.

In the backtest tab choose **Recorded quotes**, enter a server-side file or
directory path, UTC dates within the recorded period, market, fees, capital and latency. Alternatively:

```python
from src.crypto_hft_tool.bsdex_historical_bt import run_quote_backtest
result = run_quote_backtest("data/quotes", latency_ms=300, tier=6, capital=100_000)
```

Replay preserves the 60-minute window, uses only earlier snapshots for its
z-score, and fills at the first subsequent snapshot at/after the latency target.
At one-second recording resolution, a 300 ms latency normally fills one second
later. Fixed-size VWAP uses recorded bids/asks and per-side EURUSDT conversion;
it does not charge another synthetic half-spread. It reports failed fills for
stale data, insufficient depth, a missing final snapshot or a gap more than two
seconds beyond the target. Replay never searches past an unfillable snapshot.

Candle costs default to **conservative** (venue A half-spread 5 bps). The
**calibrated** option requires a supplied quote file/directory and uses median
half-spreads measured strictly before the backtest start. There is no invented
calibration fallback. Recorded-quote runs show “recorded executable depth”.

FX desk cost is 1 bp of the actual USDT leg's EUR notional in both the signal gate
and P&L. Carry is reported separately using four capital pools, the specified
2.50% DFR assumption, and elapsed hours / 8760. Sharpe is unavailable below 30
trades or 20 days and includes idle calendar days when calculated.

## Verification on 11 October 2026

Public candle data fetched for 24 September–1 October 2026 UTC, BTC/EUR,
> $250M tier, €100,000 per leg, conservative costs:

| Result | Value |
|---|---:|
| Trades | 7 |
| Wins / losses | 0 / 7 |
| Net after fees and FX cost | −€1,547.9764 |
| FX cost included in fees | €69.9898 |
| Carry | €191.7808 |
| Net after carry | −€1,739.7572 |
| Sharpe | n/a |

This verifies negative net and seven losses; it is not an exact reproduction of
the audit's −€1,423.92 estimate. The original export and its complete inputs were
not supplied. No strategy parameters were tuned to reproduce that estimate.

A ten-second live public-feed smoke check received fresh EURUSDT updates
(~0.3–0.4 seconds old), with executable spreads around −0.0042% BTC and −0.0059%
ETH and no trades. This short check does not establish long-run behavior.

Focused regressions cover next-bar losses/winners, FX costs in gating,
side-specific FX, live latency with fixed quantity, stale FX, depth failure,
quote replay, recording round trips, calibration and Sharpe thresholds.
The frontend production build passes. The full legacy suite has failures in
unchanged Binance/Kraken backtest, live trader, signal and simulator interfaces
(14 failures and 7 teardown errors in the initial full run).

To repeat the public-data acceptance check:

```sh
venv/bin/python scripts/verify_engine_integrity.py --capital 100000 --live-seconds 10
```
