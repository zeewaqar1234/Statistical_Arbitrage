# LIVE UI REDESIGN + REAL-EXECUTION PROBE

Two tasks. Do NOT change strategy math, API contracts, or the backtest tab.
Note: backtest realism fixes (P1-P5) and live VWAP depth pricing are ALREADY
implemented in this codebase. Do not re-implement or "fix" them.

## TASK 1 — Redesign the BSDEX live tab (match backtest tab quality)

Problem: live tab is cluttered, small, hard to read. Backtest tab is the
reference for quality. Restructure the live tab to this hierarchy:

ROW 1 — HERO STRIP (full width, large type)
  4 big stat cells, same component style as backtest result cards:
  SPREAD (EUR + % stacked) | Z-SCORE vs THRESHOLD | SIGNAL STATE (large
  colored tag) | CUMULATIVE PNL (EUR). Font size of values >= backtest
  result cards. This row answers "what is happening right now" in 2 seconds.

ROW 2 — HERO CHART (full width, ~380px tall)
  The spread chart, same axis/tooltip styling as the backtest equity chart.
  Add: break-even band (±B/E as shaded region, not just lines), trade
  markers, and a small badge top-right showing price_model ("VWAP depth"
  green / "top-of-book fallback" yellow) + FX age. Market selector dropdown
  in the chart header, right-aligned.

ROW 3 — TWO COLUMNS
  Left  (60%): trade blotter table, identical styling to the backtest trade
  log table. Columns: time, market, route, amount, gross, fees, net, model
  (vwap/tob). Max ~8 visible rows, scroll inside.
  Right (40%): session stats (trades, win rate, fees, FX rate) as a compact
  2-col grid, SAME stat-cell component as backtest tab.

ROW 4 — COLLAPSED BY DEFAULT: "Fee & Capital Configuration"
  Wrap the entire fee/tier/capital form in a collapsible panel
  (<details>/accordion), header shows current summary inline:
  "Tier: $20M · A 0.12% · B 0.06% · B/E 0.18% · Cap €25,000 [edit]".
  Expanding reveals the existing form unchanged. This removes most clutter.

Rules: reuse backtest tab's existing CSS classes/components wherever
possible (one design system, two tabs). Delete duplicated/legacy card
styles only used by the old live layout. No new dependencies. Data
transparency footer stays, single line at bottom.

## TASK 2 — scripts/execution_probe.py (real micro-trade measurement)

Purpose: measure REAL execution on Bitstamp + Binance with tiny capital:
signal-to-fill latency, realized slippage vs expected price, actual fees.
Standalone script using ccxt. NEVER wire real orders into the main engine.

CLI:
  python scripts/execution_probe.py --mode dry            # default, no orders
  python scripts/execution_probe.py --mode roundtrip --venue bitstamp --notional 15
  python scripts/execution_probe.py --mode roundtrip --venue binance  --notional 15
  python scripts/execution_probe.py --mode arb --notional 15   # needs inventory

Config: read BITSTAMP_API_KEY/SECRET, BINANCE_API_KEY/SECRET from .env.
Hard safety caps in code: MAX_NOTIONAL_EUR = 25 per order, MAX_ORDERS = 4
per run. Refuse to run live modes if caps exceeded.

roundtrip mode (per venue):
  1. t0 = now; fetch order book; record expected_buy = best ask,
     expected VWAP for size, top-of-book depth.
  2. Place MARKET BUY of --notional EUR (Bitstamp BTC/EUR) or equivalent
     USDT (Binance BTC/USDT). Record t_sent, t_ack (response), order id.
  3. Poll/fetch order until filled: record t_filled, avg fill price, fee
     from order response (ccxt order['fee'] / ['fees']).
  4. Wait 2 s, then MARKET SELL the exact filled base amount. Same records.
  5. Compute: latency_ms (t_ack-t_sent, t_filled-t_sent), slippage_bps per
     leg = (fill - expected)/expected * 1e4 signed, total fees, round-trip
     cost EUR and bps, net PnL of the round trip.
arb mode: simultaneous (asyncio.gather) BUY on cheaper venue + SELL on the
other from pre-existing inventory; same measurements per leg; abort sell leg
if buy ack fails. Document inventory prerequisite in --help.

Output: append one row per leg to reports/probe_results.csv (ts, venue,
side, notional, expected_px, vwap_expected_px, fill_px, slippage_bps,
fee_asset, fee_amt, t_ack_ms, t_fill_ms, order_id) and print a summary
block comparing measured slippage/fees vs the model values in
BT_EXEC_COSTS and the active fee tier, with a verdict line per assumption:
MODEL OK / MODEL TOO OPTIMISTIC / MODEL TOO CONSERVATIVE.

dry mode: everything except order placement; prints what WOULD be sent.

Also add: minimum-notional preflight (Bitstamp 10 EUR, Binance 5 USDT;
abort below), balance preflight, and a clear stdout warning that live
modes spend real money.

## Acceptance
- [ ] Live tab visually consistent with backtest tab; config collapsed
- [ ] price_model + FX age badge visible on live chart
- [ ] probe dry mode runs with no keys; live modes refuse without keys
- [ ] probe writes CSV + prints model-vs-measured verdicts
- [ ] No changes to strategy math, endpoints, or backtest tab
