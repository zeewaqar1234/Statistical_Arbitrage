# BSDEX Integration Plan — "Börse Stuttgart vs World" Arbitrage Tab

> **For:** Cursor + Claude Sonnet 4.6, reading this inside the actual repo.
> **Hard rule:** Do NOT modify, break, or change the behaviour of the existing Binance/Kraken simulation. That tab and its code paths stay exactly as they are. Everything here is ADDITIVE — new files, new routes, new frontend tab. When a shared file must be touched (e.g. `config.py`, the FastAPI app, the frontend router), ADD to it, never rewrite or remove existing entries.

---

## 0. Read before coding (discovery step — do this first, do not skip)

Before writing anything, open and read these files in the repo so the plan matches reality. The notes in brackets are what I already know from the backend; verify them and discover the frontend, which I could not see:

- `config.py` — has `SYMBOLS`, `ARBITRAGE_EXCHANGES = {"primary": "binance", "secondary": "kraken"}`, `FEES`, `EXCHANGE_CREDENTIALS`, `TRADE_SETTINGS`, `ZSCORE_SETTINGS`, `ENHANCED_SIGNAL_SETTINGS`, `WS_ENDPOINTS`.
- `data_provider.py` — has `BaseDataProvider` (abstract, method `get_market_data_rest(symbol, exchange_name)` returning a dict with keys `timestamp, bid, ask, mid_price, baseVolume, symbol, exchange`), plus `SimulatedSingleExchangeDataProvider`, `CCXTSingleExchangeDataProvider`, and a legacy `OldDataProvider`. There is also a `get_historical_data(symbol, exchange_name, timeframe, limit)` method.
- `main.py` — the FastAPI app. Has a single global `trading_loop()`, a single `simulator` (`TradeSimulator`), global `enhanced_signal_processors`, `zscore_trackers`, and API routes under `/api/v1/simulation/...` and `/api/v1/market_data/...`. The loop reads `ARBITRAGE_EXCHANGES["primary"]` / `["secondary"]`.
- `simulation.py` — `TradeSimulator` with `simulate_arbitrage_trade(...)` returning `(net_pnl, total_fees)`, plus `trades`, `total_pnl`, `total_fees_paid`, `reset()`, `update_settings(...)`.
- `signals.py` — `RollingZScore(windows, vol_adjustment)`, methods `.add(value, timestamp)` and `.update(value)`.
- `enhanced_signals.py` — `EnhancedSignalProcessor(symbol, volatility_window, correlation_window, momentum_window, signal_threshold, vol_impact)`, method `.update(spread, volume, timestamp)` returning `{window: SignalMetrics}`.
- `fee_manager.py` — `FeeManager`, `get_fees(exchange, is_maker)`.
- `backtest.py` — `Backtester` reading `data/processed/{SYMBOL}.csv` with columns `timestamp, binance_bid, binance_ask, kraken_bid, kraken_ask`.
- **The frontend** (React/Next app served on `localhost:3000`, per the screenshot). FIND where the "Live Monitor / Backtesting" tabs and the data-fetching hooks live. I could not see these files — discover them: look for the tab switcher component, the API client/fetch layer, and the chart components ("Cross-Exchange Spread", "Signal Engine").

Write a one-paragraph summary of what you found (especially the frontend structure) as a comment at the top of the new `bsdex_strategy.py` file before implementing, so there is a record of the assumptions.

---

## 1. The strategy in plain terms (so the code matches the intent)

We are adding a **second, independent arbitrage strategy** that runs alongside the Binance/Kraken one:

- **Venue A = Börse Stuttgart Digital Exchange (BSDEX).** Real, live, EUR-denominated order book via its **free public WebSocket/REST API** (no key needed for public data). Base URL `https://api-public.bsdex.de/`, WS `wss://api-public.bsdex.de/api/v1/ws`. Markets are `btc-eur`, `eth-eur`.
- **Venue B = "World" price (LMAX-proxy).** LMAX Digital has the institutional fee profile we want (maker 0–2 bps, taker 3–6 bps, EUR pairs, no token requirement) BUT no free public API. So venue B's **price feed is sourced from Binance** (free, deep, fast, a good proxy for the global mid), while the **fee schedule applied to venue B is LMAX's**. This is labelled honestly in the UI and code as `world_lmax_proxy` (price = Binance, fees = LMAX). See §6 for the honesty requirements — this must never be presented as a live LMAX connection.
- **The edge:** BSDEX is a regulated MTF with auction phases and lower liquidity, so its EUR price **lags** the global market. When BSDEX has not yet caught up to a move on the world price, the gap is a statistically detectable, mean-reverting spread — exactly what the existing z-score engine measures. We trade the convergence, but only when BSDEX is in a phase where execution is actually possible.

**Why this is different from Binance/Kraken (and why it can work):** the competition on BSDEX is mostly retail + a few desks, not colocated HFT; the lag is structural (auctions, lower volume); and at institutional BSDEX fees + LMAX fees the combined barrier is far lower than retail Binance/Kraken.

---

## 2. Currency handling (do not skip — this is the #1 source of fake spreads)

BSDEX is **EUR**. Binance BTC is **USDT**. Comparing them directly fabricates a spread that is really just the EUR/USD rate. You MUST convert to a common currency before computing any spread.

- Convert the Binance (world) price into EUR using a live EUR/USD (treat USDT ≈ USD) rate.
- Source the FX rate from a free endpoint. Options, in order of preference:
  1. ECB daily reference rate (free, official, but daily granularity): `https://api.frankfurter.app/latest?from=USD&to=EUR` (Frankfurter wraps ECB).
  2. A crypto-native cross: pull Binance `EUR/USDT` (or `BTC/EUR` if available on Binance) and derive the rate live.
- Cache the FX rate and refresh it on a sensible interval (e.g. every 60s). Store the rate used on each tick in the trade log for auditability.
- **All spreads, z-scores, fees, and PnL for this tab are computed in EUR.**

State the FX source and refresh interval in the UI footer of the BSDEX tab.

---

## 3. Backend — new isolated strategy module

Create `src/crypto_hft_tool/bsdex_strategy.py`. This is a SELF-CONTAINED strategy that reuses the existing building blocks (`RollingZScore`, `EnhancedSignalProcessor`, `TradeSimulator`, `FeeManager`) but with its OWN instances, so it cannot interfere with the Binance/Kraken globals in `main.py`.

### 3.1 BSDEX data provider

Add a new provider class. Put it either in `data_provider.py` (as a new `BSDEXDataProvider(BaseDataProvider)` subclass, matching the existing interface) or inside `bsdex_strategy.py` if you prefer full isolation. It must:

- Connect to `wss://api-public.bsdex.de/api/v1/ws` and subscribe to:
  - `quote` channel for `btc-eur` and `eth-eur` (top of book: `buy_price`, `buy_volume`, `sell_price`, `sell_volume`).
  - `phases` channel for the same markets (so we know the current trading phase — critical, see §4).
- Maintain an in-memory latest-quote cache and latest-phase cache per market.
- Expose `get_market_data_rest(symbol, exchange_name)` returning the same dict shape the rest of the code expects: `{timestamp, bid, ask, mid_price, baseVolume, symbol, exchange, phase}`. Add `phase` as an extra key.
- Public data needs NO authentication. Do NOT add API keys for the read path. (Auth is only needed later for placing real orders — out of scope for this task.)
- Handle reconnects, `ping`/`pong` keep-alive (send `{"type":"ping"}`, expect `{"type":"pong"}`), and the `online`/`offline` feed status messages. On `offline`, mark the quote stale and stop emitting signals for that market.

Reference message shapes (from BSDEX docs):
```
# subscribe
{"type":"subscribe","chan_name":"quote","subchan_name":"btc-eur"}
{"type":"subscribe","chan_name":"phases","subchan_name":"btc-eur"}

# quote data
{"chan_name":"quote","subchan_name":"btc-eur","type":"data",
 "data":{"buy_price":"48649.27","buy_volume":"0.01","sell_price":"48701.74","sell_volume":"0.01","market":"btc-eur"}}

# phase data
{"chan_name":"phases","subchan_name":"btc-eur","type":"data",
 "data":{"name":"continuous-trading","start_ts":1723456449279064870}}
```

### 3.2 World (LMAX-proxy) price feed

- Reuse the existing CCXT path or a lightweight Binance WS/REST read to get BTC and ETH prices. Symbol mapping: BSDEX `btc-eur` ↔ Binance `BTC/USDT` (then convert to EUR per §2), `eth-eur` ↔ `ETH/USDT`.
- This feed's PRICE comes from Binance. Its FEES come from the LMAX preset (see §5). Keep these two facts separate in code and clearly commented.

### 3.3 The BSDEX trading loop

Write an independent async loop `bsdex_trading_loop()` (do NOT reuse or modify `main.py`'s `trading_loop`). For each market (`btc-eur`, `eth-eur`):

1. Read latest BSDEX quote (EUR) and latest world price (convert to EUR).
2. **Check the BSDEX phase. Only proceed to signal/execution logic if phase is `continuous-trading`.** In any auction or halt phase, still compute and display the spread/z-score (for the chart and "would-have" analysis) but mark signals as `BLOCKED_BY_PHASE` and do not simulate a fill. See §4 for the smart phase logic.
3. Compute spread in EUR: define it consistently, e.g. `spread = bsdex_bid - world_ask_eur` for one direction and `world_bid_eur - bsdex_ask` for the other. Pick the convention used in the existing engine and mirror it so the sign meaning matches the current "Cross-Exchange Spread" chart.
4. Feed the spread + volume + timestamp into a DEDICATED `EnhancedSignalProcessor` instance (separate from the global one).
5. On a valid signal during `continuous-trading`, and if profit after fees exceeds the per-symbol minimum, call a DEDICATED `TradeSimulator` instance's `simulate_arbitrage_trade(...)` with buy/sell prices in EUR and the correct fee rates (BSDEX fee for the BSDEX leg, LMAX fee for the world leg).
6. Respect a cooldown (own `last_trade_time` dict).
7. Sleep ~1s, like the existing loop.

Keep ALL state for this strategy in its own module-level objects or, cleaner, inside a `BSDEXStrategy` class instance:
```python
class BSDEXStrategy:
    def __init__(self):
        self.simulator = TradeSimulator()
        self.signal_processors = { ... per market ... }
        self.last_trade_time = { ... }
        self.latest = {}     # latest computed spread/z/phase per market, for the API
        self.fx_rate = None
        ...
    async def run(self): ...   # the loop
    def get_status(self): ...  # PnL, trades, win rate (mirror main.py's _compute_performance_metrics)
    def get_recent_trades(self, limit): ...
    def get_latest_market(self, market): ...  # spread, z, phase, prices for the chart
```

---

## 4. Smart execution around BSDEX phases (the core "capture max spread" logic)

BSDEX is not continuous like Binance. It moves through phases: `continuous-trading`, `auction-call`, `auction-price`, `auction-recall`, `trading-halt`, `system-down`, `suspended`. (Definitions are in the BSDEX docs.) The smart logic:

- **`continuous-trading`** → normal operation. Orders match immediately. This is the ONLY phase where we simulate a real fill.
- **`auction-call` / `auction-price` / `auction-recall`** → the book may be crossed, orders queue but do not match until the auction resolves. During these phases:
  - Keep computing and charting the spread/z-score (the world price keeps moving, BSDEX is frozen → the gap often WIDENS here, which is the signal building up).
  - Mark the state as "auction — signal arming". Record what the spread WAS at the moment the auction ends, because the first `continuous-trading` tick after an auction is the convergence opportunity.
  - Do NOT count a simulated fill during the auction.
- **First tick back in `continuous-trading` after an auction** → this is the highest-value moment. The lagged BSDEX price snaps toward the world price. If the armed signal is still valid, this is where the simulated trade fires. Flag these trades in the log as `post_auction_convergence = true` so they can be highlighted in the demo.
- **`trading-halt` / `system-down`** → cancel/withhold, compute nothing executable, show a "halted" badge.
- **`suspended`** → feed is down, show "suspended", do not trade.

Subscribe to the `phases` channel and drive a small state machine. Track `(market, phase, phase_start_ts)` and detect the auction→continuous transition edge. This phase-aware execution is the genuinely novel part of the strategy and should be visible in the UI (a phase badge + a marker on the chart at each auction boundary).

---

## 5. Fees — add presets without touching existing FEES

In `config.py`, ADD a new dict next to the existing `FEES` (do not modify `FEES`, the Binance/Kraken tab depends on it):

```python
# Fees for the BSDEX vs World (LMAX-proxy) strategy. Decimals (0.0020 = 0.20%).
# BSDEX retail published: maker 0.20%, taker 0.35% (source: bsdex.de/en/fees, verified).
# BSDEX institutional/MTF: negotiated, NOT public -> represented as a separate, clearly-labelled assumption.
# LMAX Digital: maker 0-2 bps, taker 3-6 bps (source: public reviews; CONFIRM against an LMAX rate card before external use).
BSDEX_STRATEGY_FEES = {
    "bsdex_retail":        {"maker": 0.0020,  "taker": 0.0035},
    "bsdex_institutional": {"maker": 0.0010,  "taker": 0.0015},   # ASSUMPTION — label as such in UI
    "lmax_low":            {"maker": 0.0000,  "taker": 0.0003},   # 0 bps / 3 bps
    "lmax_high":           {"maker": 0.0002,  "taker": 0.0006},   # 2 bps / 6 bps
}

# Selectable combined presets for the BSDEX tab fee dropdown
BSDEX_FEE_PRESETS = {
    "retail_demo":        {"bsdex": "bsdex_retail",        "world": "lmax_high"},
    "institutional_best": {"bsdex": "bsdex_institutional", "world": "lmax_low"},
    "institutional_mid":  {"bsdex": "bsdex_institutional", "world": "lmax_high"},
}
```

The BSDEX tab gets its own fee-tier dropdown (default `retail_demo`). Selecting a preset re-runs the PnL math. Mirror the fee-tier-selector idea from the earlier backtesting plan, but scoped to this tab only. Every result displayed MUST state which preset produced it.

---

## 6. Honesty requirements (non-negotiable — protects your credibility with managers)

The world feed is Binance price wearing LMAX fees. This is a legitimate modelling choice for a proof-of-concept, but it must be labelled, never hidden:

- In the UI, the venue is named **"World (Binance price · LMAX fee model)"**, not "LMAX".
- A short tooltip/footnote on the BSDEX tab explains: *"Live LMAX market data requires an institutional account and is not publicly available. As a proxy, the global price is sourced from Binance (a close proxy for LMAX's mid given comparable latency and liquidity on majors), while the LMAX institutional fee schedule is applied. BSDEX prices and phases are live and real."*
- The `bsdex_institutional` fee row is labelled **"assumed — negotiated rate, not public"** wherever it appears.
- The backtest report (see §8) repeats these caveats in a "What this does and does not represent" section.

Do not let the demo imply a live LMAX connection or a confirmed Deka fee. The strength of the pitch is honesty about what is real (BSDEX live data + phases) and what is modelled (world price proxy + fee assumptions).

---

## 7. Backend API — new routes, separate namespace

In the FastAPI app, ADD a new route group under `/api/v1/bsdex/...`. Do NOT alter the existing `/api/v1/simulation/...` or `/api/v1/market_data/...` routes. Wire the `BSDEXStrategy` loop into startup with its OWN `asyncio.create_task(...)`, separate from the existing `trading_loop` task.

New endpoints (mirror the existing simulation endpoints' response shapes so the frontend client is easy to reuse):

- `GET /api/v1/bsdex/status` → PnL, total trades, win rate, total fees, current fee preset, FX rate in use.
- `GET /api/v1/bsdex/trades?limit=N` → recent simulated trades (include `phase`, `post_auction_convergence`, `fx_rate`, `fee_preset` fields).
- `GET /api/v1/bsdex/market/{market}` → latest spread (EUR), z-score, threshold, signal state (`HOLD`/`SIGNAL`/`BLOCKED_BY_PHASE`/`ARMING`), current BSDEX phase, BSDEX bid/ask, world bid/ask in EUR.
- `GET /api/v1/bsdex/spread_series/{market}?n=...` → recent spread/z-score time series for the chart (keep a rolling buffer in the strategy object).
- `POST /api/v1/bsdex/fee_preset` → set the active fee preset (body: `{"preset": "institutional_best"}`), recompute displayed PnL.
- `GET /api/v1/bsdex/phase/{market}` → current phase + last auction-transition timestamp (for the chart marker).

Use the existing logging, error-handling middleware, and Pydantic-model patterns already in the app.

---

## 8. Backtesting for the BSDEX strategy (historical data)

Create `src/crypto_hft_tool/bsdex_backtest.py` and a downloader `scripts/download_bsdex_data.py`. Do NOT modify the existing `backtest.py`.

### 8.1 Data sources for historical backtest

- **BSDEX historical:** use the **Chart Data API** documented at `https://docs.bsdex.de/` → "Chart Data API / TradingView Data / Get historical data". This returns historical OHLC for BSDEX markets (`btc-eur`, `eth-eur`). Pull as fine a granularity as the endpoint allows (1m if available). This is REAL BSDEX history.
  - If the chart endpoint's granularity is too coarse for a convincing backtest, document that limitation and fall back to recording live WS data into a CSV over a few sessions (a `--record` mode on the downloader) so you accumulate genuine high-resolution BSDEX data over time.
- **World (LMAX-proxy) historical:** Binance OHLCV via ccxt (`fetch_ohlcv('BTC/USDT','1m',...)`), converted to EUR per-row using a historical EUR/USD series (Frankfurter supports historical: `https://api.frankfurter.app/{date}?from=USD&to=EUR`, or pull a daily series and forward-fill).
- Merge on timestamp into `data/processed/bsdex_{SYMBOL}.csv` with columns:
  `timestamp, bsdex_bid, bsdex_ask, world_bid_eur, world_ask_eur, fx_rate, phase`
  (phase may be unavailable historically from the chart endpoint; if so, leave blank for historical rows and only populate it in the live-recorded data — note this in the meta file).
- Write a `.meta.json` next to each CSV: sources, date range, FX source, granularity, and the honesty caveats from §6.

### 8.2 The backtester

- Reuse `RollingZScore` / `EnhancedSignalProcessor` / `TradeSimulator` / the new `BSDEX_STRATEGY_FEES`.
- Replay the merged CSV row by row, compute EUR spread + z-score, apply the §4 phase logic where phase data exists, simulate fills via `simulate_arbitrage_trade` with the selected fee preset.
- Add a `--fee-preset` CLI flag (choices from `BSDEX_FEE_PRESETS`) and a comparison mode that runs all presets and prints a side-by-side table: trades, gross PnL (EUR), fees (EUR), net PnL (EUR), win rate, Sharpe, max drawdown.
- Write artifacts to `reports/`: trade log CSV, summary TXT, and (if matplotlib is available) an equity-curve PNG. Highlight `post_auction_convergence` trades separately in the summary.

### 8.3 Fix-forward note

The existing `backtest.py` had a method-signature bug (`simulate_trade` called with arbitrage kwargs) and a fee mismatch (`config.FEES` near-zero takers vs realistic `fee_manager` fees). Do not fix those inside the Binance/Kraken code as part of THIS task (out of scope, and we must not touch that tab). But in the NEW `bsdex_backtest.py`, call `simulate_arbitrage_trade` correctly (it returns `(pnl, fees)` — unpack it) and use realistic fees from the new presets from the start, so the new code is clean.

---

## 9. Frontend — new tab, existing tab untouched

From the screenshot, the app has a top-level switch ("Live Monitor | Backtesting") and a header ("Cross-Exchange Statistical Arbitrage System"). Discover the actual frontend structure in step §0, then:

- Add a NEW top-level tab/section labelled **"BSDEX vs World"** (alongside the existing Binance/Kraken view). The existing view's components, hooks, and routes are not modified.
- The new tab reuses the existing chart/card components where possible, pointed at the new `/api/v1/bsdex/...` endpoints. It should show:
  - A header strip with: BSDEX taker, World (LMAX) taker, **break-even spread**, and the active **fee preset dropdown**.
  - A **BSDEX phase badge** (continuous-trading / auction / halted) with colour coding, updating live.
  - The **Cross-Exchange Spread** chart (EUR), with vertical markers at each auction→continuous transition and highlighted points for `post_auction_convergence` trades.
  - A **Signal Engine** card: z-score, threshold, signal state (HOLD / SIGNAL / ARMING / BLOCKED_BY_PHASE).
  - A PnL/metrics card reading `/api/v1/bsdex/status`.
  - A recent-trades table reading `/api/v1/bsdex/trades`.
  - A footer with the §6 honesty note and the FX source/refresh interval.
- Keep styling consistent with the existing grayscale-friendly, clean look (the user prints in black & white; avoid colour-only encodings — use labels/shapes too).

---

## 10. Config additions (summary — all ADDITIVE)

In `config.py`, ADD (do not modify existing keys):

```python
# --- BSDEX strategy config (additive; does not affect Binance/Kraken) ---
BSDEX_API_REST = "https://api-public.bsdex.de"
BSDEX_API_WS   = "wss://api-public.bsdex.de/api/v1/ws"
BSDEX_MARKETS  = ["btc-eur", "eth-eur"]
BSDEX_MARKET_MAP = {            # BSDEX market -> Binance world symbol
    "btc-eur": "BTC/USDT",
    "eth-eur": "ETH/USDT",
}
FX_RATE_SOURCE   = "https://api.frankfurter.app/latest?from=USD&to=EUR"
FX_REFRESH_SEC   = 60
BSDEX_ACTIVE_FEE_PRESET = "retail_demo"
# BSDEX_STRATEGY_FEES and BSDEX_FEE_PRESETS as defined in §5
```

---

## 11. Acceptance checklist

- [ ] Existing Binance/Kraken tab behaves EXACTLY as before (run it, confirm unchanged PnL/UI).
- [ ] New `BSDEXDataProvider` connects to the live BSDEX public WS, receives quotes + phases for `btc-eur` and `eth-eur`.
- [ ] World price is converted to EUR using a live FX rate; the rate is logged per tick.
- [ ] Spread, z-score, and PnL are all computed in EUR.
- [ ] During auctions, no simulated fill is recorded; the spread still charts; signals show `ARMING`/`BLOCKED_BY_PHASE`.
- [ ] First `continuous-trading` tick after an auction can fire a trade flagged `post_auction_convergence`.
- [ ] `/api/v1/bsdex/...` routes return data; `/api/v1/simulation/...` routes are untouched.
- [ ] Fee preset dropdown changes the displayed PnL; every result states its preset.
- [ ] `scripts/download_bsdex_data.py` produces `data/processed/bsdex_BTC_EUR.csv` (+ ETH) with a `.meta.json`.
- [ ] `bsdex_backtest.py` runs, supports `--fee-preset`, and writes trade log + summary (+ equity PNG if matplotlib present).
- [ ] New frontend tab renders, shows the phase badge, EUR spread chart, signal card, PnL, trades table, and the honesty footer.
- [ ] Nothing anywhere presents the world feed as a live LMAX connection; all assumptions are labelled.

---

## 12. Do NOT

- Do not touch the Binance/Kraken `trading_loop`, its `simulator`, its signal processors, or its routes.
- Do not modify the existing `FEES` dict or `ARBITRAGE_EXCHANGES`.
- Do not add API keys for BSDEX public data (not needed for read-only quotes/phases/history).
- Do not present Binance-as-LMAX without the §6 labels.
- Do not invent BSDEX institutional fees as if confirmed — keep them labelled as assumptions.
- Do not fabricate a cross-exchange offset anywhere; the spread must come from real BSDEX vs real (converted) world prices.

---

## 13. Suggested commit sequence

1. `bsdex: add config (api urls, markets, fx, fee presets)`
2. `bsdex: add BSDEXDataProvider (live WS quotes + phases)`
3. `bsdex: add world LMAX-proxy feed + EUR FX conversion`
4. `bsdex: add BSDEXStrategy loop with phase-aware execution`
5. `bsdex: add /api/v1/bsdex API routes + startup task`
6. `bsdex: add historical data downloader`
7. `bsdex: add bsdex_backtest with fee-preset comparison`
8. `bsdex: add frontend BSDEX-vs-World tab`
9. `bsdex: docs + honesty notes + meta files`

Run the app after steps 5 and 8 to confirm the existing tab still works and the new one renders.
