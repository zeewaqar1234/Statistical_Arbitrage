# ENGINE INTEGRITY FIXES (read fully, then implement in order)

Context: an external audit rebuilt bsdex_historical_bt.py in Python, matched all
exported backtests to the cent, and found two defects that create the profits the
tool currently shows. Fix these before anything else. Do not change strategy
parameters (z window 60, threshold 1.5, cooldown 30) or the Binance/Kraken tab.

## F1 (CRITICAL) Backtest look-ahead: break-even gate reads the fill bar
File: src/crypto_hft_tool/bsdex_historical_bt.py, function _simulate.
Today: prices from bar i+1 are adjusted, then
    if eff_sell <= eff_buy: continue
Since amount = capital/buy_price, `eff_sell > eff_buy` is algebraically identical
to `pnl > 0`. The engine only books trades whose future fill is profitable, which
is why every export shows 100% wins and zero drawdown.
Fix:
1. Compute direction AND the break-even gate from signal-bar prices (bar i),
   using the same cost adjustment (_apply_exec_costs on price_a_arr[i],
   price_b_arr[i]). Skip if not profitable on bar i.
2. Once the gate passes, the trade is committed: compute fill prices from bar
   i+1 (cost-adjusted), then gross/fees/pnl, and book it whatever the sign.
3. Add to each trade: "signal_spread_pct" (bar i, after costs) and
   "realized_spread_pct" (bar i+1, after costs).
4. Same pattern exists in src/crypto_hft_tool/bsdex_backtest.py (~line 208,
   same-bar fills). Either apply the same fix or delete that file and its CLI
   if nothing imports it (main.py uses bsdex_historical_bt only).
5. Add tests/test_no_lookahead.py: a synthetic series where every dislocation
   fully reverses at i+1 must produce ONLY losing trades. A second series where
   the dislocation persists must produce winners. Both must pass.
Expected effect: on the 24 Sep to 1 Oct 2026 window, BTC-EUR > $250M realistic
goes from +275.81 EUR (5 trades, 100%) to about -1,423.92 EUR (7 trades, 0%).
That is the correct result; do not tune it away.

## F2 (CRITICAL) Live engine FX uses the ECB daily fixing
Files: config.py (FX_RATE_SOURCE, FX_REFRESH_SEC), bsdex_strategy.py
(FXRateCache, _process_market, MAX_FX_AGE_SEC, BinanceDepthCache init ~line 780).
Today: Frankfurter "latest" = ECB reference rate, published once per business
day. Re-downloading it every 60 s returns the same number, and fx_age measures
time since download, not age of the rate. Measured 2 Oct 2026: ECB 1.1225 vs
tradeable EUR/USDT 1.1267 makes the world leg look 0.37% rich, so the live tab
trades a currency gap (every row bitstamp -> world_lmax, 100% wins).
Fix:
1. Add "EURUSDT" to the BinanceDepthCache symbol list (same depth20@100ms
   stream already used for BTCUSDT/ETHUSDT).
2. Convert executable prices, not mids:
     b_bid_eur = b_bid_usdt / eurusdt_ask   (selling BTC, USDT -> EUR)
     b_ask_eur = b_ask_usdt / eurusdt_bid   (buying BTC, EUR -> USDT)
   Apply the same per-side rate when converting Binance depth levels for VWAP.
3. fx_age = seconds since the last EURUSDT WebSocket update. MAX_FX_AGE_SEC = 5.
   If stale: signal_state = "FX_STALE", no trades.
4. Keep Frankfurter only as a display reference ("ECB fixing") never used in
   pricing. Update the status bar text to "FX: Binance EUR/USDT live (WS)".
5. Reset session stats on deploy; old live trades were priced with the wrong FX.

## F3 (HIGH) Live paper fills are instantaneous, so they cannot lose
bsdex_strategy.py ~line 1106 books a trade only if `eff_sell > eff_buy` on the
same instant's books, with zero latency and no leg risk.
Fix: add LIVE_FILL_LATENCY_MS to config (default 300). On SIGNAL, store a pending
trade (direction, size, signal prices). Price both legs from the order books at
the first tick >= signal_time + latency, VWAP for the full size, and book the
result whatever the sign. Blotter shows signal spread and realized spread.

## F4 (HIGH) Backtest needs quotes, not last-trade candles
Bitstamp BTC/EUR has no trades in ~30% of minutes (ETH ~53%); about half of all
signals fire on those stale minutes. Minute closes cannot test this strategy.
Fix:
1. New scripts/record_quotes.py: subscribe to the existing Bitstamp depth WS,
   Binance depth20 WS (BTCUSDT, ETHUSDT, EURUSDT); every 1 s append top-5 levels
   per book with exchange timestamps to data/quotes/YYYY-MM-DD.parquet (or csv.gz).
   Run continuously; handle reconnects; log gaps.
2. New function run_quote_backtest(path, latency_ms, tier, capital) reusing the
   F1 logic: signal on snapshot t, fill on the first snapshot >= t + latency.
   Add a "Data source: Candles | Recorded quotes" selector to the backtest tab.

## F5 (MEDIUM) Missing costs and statistics hygiene
1. Add to config and to break-even + P&L: FX_COST_BPS = 1.0 (bank FX desk, per
   trade on the USDT leg). Show it as its own line in the cost display.
2. Backtest summary: add carry = capital_eur * POOLS(4) * DFR(0.025) *
   hours / 8760 and "net after carry". Label DFR source: ECB deposit facility
   2.50% from 16 Sep 2026.
3. BT_EXEC_COSTS venue_a half-spread: 5.0 bps is ~10x the measured Bitstamp
   median (~0.5 bps). Keep 5.0 as "conservative", add "calibrated" values from
   recorded quotes, and say which was used in the summary.
4. Return sharpe_daily_ann = None when trades < 30 or days < 20; UI shows "n/a".

## F6 (LOW) Live blotter readability (frontend only, App.js ~line 610)
Columns: Time | Market | Buy venue | Buy price | Sell venue | Sell price |
Quantity | Notional EUR | Signal % | Realized % | Gross | Fees | Net | Model.
Bring back Market. Quantity shows the asset suffix (BTC / ETH).

## Acceptance
- [ ] tests/test_no_lookahead.py passes; no gate anywhere reads bar i+1 prices
- [ ] Re-running the 24 Sep to 1 Oct BTC export at > $250M shows negative net
- [ ] Live tab spread with EUR/USDT WS is near zero; no persistent one-way trades
- [ ] Live trades can lose (latency model active); blotter shows both spreads
- [ ] Cost display includes FX cost and carry; Sharpe hidden below thresholds
