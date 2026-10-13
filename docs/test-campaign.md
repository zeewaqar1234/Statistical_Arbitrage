# Test campaign

`scripts/run_test_campaign.py` runs one long, read-only measurement session and
writes everything to a single Excel file. It never sends orders.

| Phase | What it measures |
|---|---|
| Network | REST round-trip time to Bitstamp, Binance and Kraken from your machine |
| Live (default 8 h) | The real paper engine at the chosen tier and size, plus a 4 Hz shadow sampler on the same books: executable gap for €1k/€10k/€100k/€250k in both directions, time above every tier's break-even, how long gaps last, whether a gap survives 250 ms–30 s, maker edge, spreads, depth, feed age, hourly pattern, engine states and trades |
| Quote replay | The quotes recorded during the run, replayed for every tier, plus latency 300/1000/2000 ms × window 10/60 min × threshold 1.0/1.5/2.5 × cooldown 1/30 min |
| Candles | Last 7 days of 1-minute candles, every tier, plus window 30/60/240 × threshold 1.0–3.0 × cooldown 5/30 min, with and without bid/ask costs |
| Control pair | Bitstamp EUR vs Kraken EUR (no FX leg), last ~12 h, every tier |

## Run it

```sh
git pull origin claude/trading-tool-docs-4684tx
venv/bin/pip install -r requirements.txt
caffeinate -i venv/bin/python scripts/run_test_campaign.py --hours 8
```

Stop the backend first. `caffeinate -i` (macOS) keeps the machine awake. Ctrl+C
ends the live phase early and still runs the backtests and writes the file.
The last line printed is the path of the `.xlsx` to share.

Useful options: `--capital 100000` (EUR per leg), `--tier 2` (fee tier index),
`--quick` (no parameter sweeps, for a short trial), `--hours 0.1` (6-minute trial).
