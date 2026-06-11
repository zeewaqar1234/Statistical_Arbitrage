# FINAL CREDIBILITY FIXES — bsdex_historical_bt.py + bsdex_backtest.py

Goal: remove selection bias, look-ahead bias, FX artifact, and missing trading
costs so backtest results are defensible to a quant audience. No new features.
Do NOT touch the Binance/Kraken tab or live BSDEX strategy loop.

## P1 — Remove the win-rate-by-construction bug (CRITICAL)
File: src/crypto_hft_tool/bsdex_historical_bt.py, trade loop.
Current code skips losing trades:
    if pnl <= 0: continue
Fix: DELETE this skip. Once the gate (z-score + |spread|>break-even + cooldown)
fires, the trade is committed and its pnl (positive OR negative) is booked,
added to cumulative_pnl, appended to trades, and counts toward win/loss stats.
Add wins/losses counters and report real win_rate = wins/(wins+losses).
Max drawdown must be computed from the equity curve including losses.

## P2 — Next-bar execution (kill look-ahead)
Same file. Signal is evaluated on bar i, but fills MUST use bar i+1 prices:
    pa_fill = price_a_arr[i+1]; pb_fill = price_b_arr[i+1]
Recompute direction-dependent buy/sell prices from the i+1 values. Skip signal
if i+1 == len. Comment: "execution lag = 1 bar (1 min), conservative".

## P3 — Intraday FX (kill the FX artifact)
Same file, replace daily Frankfurter as PRIMARY source:
- Fetch Binance EURUSDT 1m klines over the same range via the existing ccxt/
  REST helper used for BTCUSDT (symbol "EUR/USDT" in ccxt, "EURUSDT" raw).
- fx_for_ts(ts) = 1 / eurusdt_close_at(ts)  (USD->EUR). Align on the same
  minute index as the other feeds; forward-fill gaps up to 5 min.
- Keep Frankfurter daily as FALLBACK only if EURUSDT fetch fails; log a
  warning and tag result meta {"fx_granularity": "daily-fallback"} so the UI
  can show it. Normal path tags {"fx_granularity": "1m"}.

## P4 — Real spread + slippage cost model
Same file. Candle closes are MID prices; trading crosses the spread. Add
config (config.py, additive):
    BT_EXEC_COSTS = {
      "half_spread_bps": {"venue_a": 5.0, "venue_b": 1.5},  # Bitstamp wider
      "slippage_bps_per_100k": 2.0,   # linear impact per 100k EUR notional
    }
Apply at fill time:
    buy_price  = mid_buy  * (1 + (half_spread_bps_buy  + slip_bps)/10000)
    sell_price = mid_sell * (1 - (half_spread_bps_sell + slip_bps)/10000)
    slip_bps   = slippage_bps_per_100k * (capital_eur/100000)
Break-even check must use the SAME adjusted prices (gate on executable
spread, not mid spread). Expose these three numbers in the result meta and
show them in the backtest UI near break-even.

## P5 — Fix Sharpe
File: src/crypto_hft_tool/bsdex_backtest.py line ~278 and any duplicate in
bsdex_historical_bt.py. Replace sqrt(365*24*60) annualization:
- Aggregate trade pnl into DAILY returns on capital_eur.
- sharpe = mean(daily)/std(daily) * sqrt(365), guard std==0 -> None (display
  "n/a", never 0.00 or a huge number). Label in UI: "Sharpe (daily, ann.)".

## P6 — Honest dual-scenario output
bsdex_historical_bt.py: run the simulation TWICE per request:
  scenario "upper_bound": P4 costs zeroed (old behaviour minus P1/P2 bugs)
  scenario "realistic":   P4 costs applied
Return both in the response: {"upper_bound": {...}, "realistic": {...}}.
Frontend backtest tab: show "Realistic" as the headline cards; show
"Upper bound (mid-price fills)" as a smaller secondary row. Never present
upper_bound alone.

## P7 — Default fee tier
Default tier index for both live tab and backtest = the $20M tier, not >$1B.
Keep >$1B selectable, label it "(aspirational)". Headline numbers a manager
sees first must not assume the most optimistic tier.

## P8 (optional, ~30 min) — FX-free control pair
Add market option "btc-eur-kraken" : Venue A = Bitstamp BTC/EUR, Venue B =
Kraken BTC/EUR (ccxt, native EUR, fx=1.0 constant). Same engine, zero FX.
Purpose: validation pair proving the framework measures pure venue basis.
Label in UI: "Control pair (no FX leg)".

## Acceptance
- [ ] Win rate < 100% on a 7-day BTC backtest; max drawdown > 0
- [ ] Fills use bar i+1; no same-bar execution remains
- [ ] FX meta shows "1m" granularity on normal runs
- [ ] Realistic scenario headline; upper bound secondary
- [ ] Sharpe shows plausible value (|S| < 10) or "n/a"
- [ ] Default tier = $20M; >$1B labeled aspirational
- [ ] Binance/Kraken tab and live BSDEX loop untouched

## Do NOT
- Reintroduce `if pnl <= 0: continue` in any form
- Use daily FX as primary
- Show any result without stating scenario + tier + costs applied
