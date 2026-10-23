# Frontend revamp: from trading terminal to explainer

> **For:** Codex (or any coding agent).
> **Scope:** `hft-frontend/` only. One optional clean-up outside it (§9.6).
> **Supersedes:** the visual and layout rules in `BLOOMBERG_UI_REVAMP.md` and `UI_AND_PROBE.md`. Keep those files as history, but **do not follow their design rules** (dense, dark, orange, "every gap is a wasted opportunity to show a number"). This document reverses them on purpose.

---

## 0. Read this first

### Why this change

The project is finished. Over eighteen months (May 2025 – Oct 2026) it tested **three different crypto arbitrage strategies** against one yardstick, a 2.5% EUR bank deposit after every cost:

| # | Strategy | How it makes money | Result |
|---|---|---|---|
| 1 | **Cross-exchange spot arbitrage** (the live engine in this app) | Buy BTC/ETH on the cheaper exchange, sell on the dearer one at the same moment | **No edge.** Gaps are a few bps; costs are 7–47 bps |
| 2 | **Perpetual funding carry** | Hold the coin, short its perpetual future, collect funding | **Edge ≈ deposit rate**, with exchange and regulatory risk |
| 3 | **EURC stablecoin depeg capture** | Rest bids below €1; buy when a holder dumps, sell back near par | **Real edge, tiny capacity** (≈€100–300 a year) |

The owner now shows this work to senior bankers and market professionals in Frankfurt, often in a 15–30 minute slot. Today the app is a Bloomberg-style terminal for strategy 1 only. A first-time viewer sees jargon (`Z-Score / Threshold`, `B/E`, `VWAP depth`, `Venue A Taker %`), the presenter's own settings and a number that changes every 2 seconds, and never learns that there were three strategies or how they compare.

The app must tell the **same story as the deck and memo** in `reports/closure/`: three strategies, kept clearly separate, each with its own chart and numbers, then compared side by side.

### What success looks like

1. **Answer first.** A finance professional who has never seen the project can say, within **3 minutes** of Findings, what the three strategies were, why each fell short, and how they compare against the deposit.
2. **The three never blur.** Each strategy has its own colour, number, step and chart. A viewer can always tell which strategy a figure belongs to.
3. **Live proof without jargon.** The presenter can switch to **Live market** and show 60–90 seconds of strategy 1's engine on real data, with no term left unexplained.
4. **Expert depth stays available.** The backtest tool for strategy 1 stays in **Lab**.
5. **Works offline.** Findings needs no backend and no internet. Demos happen on laptops, in meeting rooms, sometimes on a bank network that blocks exchange APIs.

### Hard rules

- **Do not change anything under `src/`** (the Python backend), the API contracts, strategy maths, `scripts/` or `tests/`. This is a frontend-only change. §9.6 is the one exception, and it only deletes unused files.
- **Do not invent numbers or wording.** Every figure in Findings comes from `src/content/findings.js` (§7) or `src/content/chart_data.json` (a byte-for-byte copy of `reports/closure/data/chart_data.json`; do not edit it). Every live figure comes from the existing API. If you think a number is wrong, leave it and flag it in your summary; don't "fix" it.
- **Do not add or remove npm dependencies** in this pass. Use what is installed: React 18, Recharts, react-query 3, axios, xlsx. MUI is installed but should no longer be needed. Removing its usage is fine; leave `package.json` as it is.
- **Keep it honest on every screen.** "Simulated · no orders are sent" must be visible on Live and Lab. Every Findings step shows its source line.
- **Keep the Lab's backtest request payload byte-for-byte the same** as today's `api.runHistoricalBacktest` call (see `App.js` lines 333–347), and keep the Excel export working.

---

## 1. Information architecture

Replace the two tabs (`BSDEX vs World`, `Backtest`) with three views in this order:

| Nav label | Hash route | What it is | Needs backend? |
|---|---|---|---|
| **Findings** (default) | `#/findings`, `#/findings/1` … `#/findings/6` | Six steps: answer, history, strategy 1, strategy 2, strategy 3, side by side. Mirrors the 6-slide deck in `reports/closure/` | **No.** Static content only |
| **Live market** (subtitle "Strategy 1 engine") | `#/live` | Simplified live paper engine for strategy 1: "is there a trade right now, and why not?" | Yes |
| **Lab** (subtitle "Strategy 1 backtest") | `#/lab` | Today's Backtest tab, restyled and relabelled, same functionality | Yes |

Strategies 2 and 3 have no live engine in this app: strategy 2 was assessed on twelve months of funding history, and strategy 3 was live-tested with a separate script (`scripts/eurc_live_test.py`). Both appear in Findings only. Don't add views or endpoints for them.

- Use hash routing with a tiny hook (`useHashRoute`). No new router dependency. An empty or unknown hash goes to `#/findings/1`.
- **Polling is tied to the view.** Live queries run only while `#/live` is open. The tier list (`/api/v1/bsdex/volume_tiers`) loads only on Live or Lab. **Findings must make zero network requests**; check this in the Network tab.
- Top bar: project name on the left ("Crypto Arbitrage: three strategies"), the three nav items, and a **"Terms"** button on the right that opens the glossary drawer (§6). Remove the world clocks (§9.1). Show the connection dot only on Live and Lab.

---

## 2. Visual system

Match the deck and memo in `reports/closure/` so the app, slides and one-pager look like one piece of work.

### Tokens (replace the `:root` block in `index.css`)

```css
:root {
  color-scheme: light;
  --ink:        #18313B;  /* body text */
  --teal:       #173C4A;  /* headings, primary buttons, dark panels */
  --teal-soft:  #24525F;  /* cards on dark panels */
  --muted:      #53656D;  /* labels, captions, sources */
  --pale:       #EDF3F4;  /* card backgrounds */
  --line:       #D6DFE2;  /* borders, grid lines */
  --bg:         #FFFFFF;
  --measured:   #347A78;  /* what the market offered (gaps) */
  --cost:       #A33639;  /* costs, losses, FAIL */
  --profit:     #347A78;  /* rare: positive P&L. Same hue as measured on purpose */
  --warn:       #9A6B00;  /* stale data, paused states */
  --s1:         #2F5D8A;  /* strategy 1: cross-exchange spot */
  --s1-light:   #8FB3D9;
  --s2:         #B7791F;  /* strategy 2: perpetual funding carry */
  --s2-light:   #E2B66B;
  --s3:         #2F7D6D;  /* strategy 3: EURC depeg capture */
  --deposit:    #18313B;  /* the 2.5% deposit yardstick, always a solid dark line */
  --radius:     4px;
  --font-sans:  'IBM Plex Sans', -apple-system, 'Segoe UI', Arial, sans-serif;
  --font-mono:  'IBM Plex Mono', 'SF Mono', Consolas, monospace;
}
```

- **Colours carry meaning, consistently.** Each strategy owns its colour everywhere: badge, kicker, KPI values and main chart series (`--s1` blue, `--s2` ochre, `--s3` green). Red (`--cost`) means a cost, a loss or a fail. The deposit yardstick is always `--deposit`, solid or dashed. No other decorative colour. The old terminal orange (`#FF8C00`) must not appear anywhere; `--s2` is a muted ochre, not that orange.
- **Typography:** IBM Plex Sans is already loaded in `index.css`; keep it. Use `font-variant-numeric: tabular-nums` for all numbers. Use Plex Mono **only** in the Lab's dense tables. Sizes: step title 32–36px, stat values 40–56px, body 16–18px, captions and sources 12–13px. Nothing below 12px.
- **Surfaces:** white page, `--pale` cards, 1px `--line` borders, `--radius` corners, no shadows, no glow, no hover-lift.
- **Layout targets:** every Findings step fits **without vertical scrolling at 1280×720** (projector) and 1440×900 (laptop). Everything works at 390px wide (phone) with no horizontal page scroll; columns stack. Max content width 1200px, centred, 32px side padding (16px on phones).
- **Numbers:** show basis points, not percentages with four decimals. `spread_pct` from the API is a percentage, so `bps = spread_pct * 100`. Format bps with one decimal and an explicit sign (`+1.6 bps`, `−2.3 bps`, using U+2212 for the minus sign). Show EUR with two decimals in Live and Lab, and with no decimals in Findings, as given.
- **Accessibility:** WCAG AA contrast, visible focus rings, buttons that are real `<button>`s, charts with an `aria-label` summarising the point (for example "Measured gaps of −2.3 and −4.1 bps against costs of 7 to 47 bps").

---

## 3. Findings view (story mode)

### Behaviour

- Six steps, one per screen, in the order below. Each step has a **kicker**, a **title**, one or two **charts**, at most **three KPI tiles**, a **verdict line** where relevant, and a **source line** at the bottom in `--muted` 12–13px.
- **Strategy steps (3, 4, 5) share one template** so they can be compared at a glance. All three put the same parts in the same places:
  - kicker in the strategy colour
  - a one-line title stating the finding
  - a "How it makes money" subtitle
  - the chart on the left, about 62% of the width
  - three KPI tiles on the right
  - a verdict band across the bottom: "Verdict: {label}." in the strategy colour, then one sentence
- Navigation: **Back / Next** buttons bottom-right; **←/→** and **PageUp/PageDown** keys (presentation clickers send these); a progress row of six dots with step titles as tooltips. Dots 3–5 use their strategy colour. Each step has its own hash (`#/findings/3`) so the presenter can deep-link. Next on step 6 goes to `#/live`.
- **"Present" toggle** (top-right of Findings, or the `F` key): hides the top bar for a clean full-screen look and uses `document.documentElement.requestFullscreen()` where allowed. `Esc` exits.
- All text comes from `findings.js` and all chart data from `chart_data.json`. Components render data; they don't contain copy or numbers.
- No animation beyond a 150ms fade between steps. Respect `prefers-reduced-motion`.

### Step-by-step

**Step 1 · Answer** (dark panel: `--teal` background, white text)
- Kicker, title and question from `steps[0]`.
- Three strategy cards side by side (stacked on phones) on `--teal-soft`. Each card has:
  - a numbered circular badge in the strategy colour, plus the strategy name
  - the mechanism line
  - a big number at 40–48px, with its label
  - a verdict pill in the strategy colour
- Bottom line: the decision. Footer: author, period, honesty line.

**Step 2 · History and method**
- A horizontal timeline of five milestones: dots on a line, date, head, one-line body. The last dot is `--cost`.
- Below it, a three-row evidence table (strategy / venues / evidence / live test). The strategy names are in their colours.
- Bottom box, the yardstick: "Same yardstick for all three: …".

**Step 3 · Strategy 1: cross-exchange spot** (template above)
- **Chart:** a Recharts `ComposedChart`. Grouped bars of the median tradeable gap by order size, from `chart_data.s1.by_size`: BTC in `--s1`, ETH in `--s1-light`, four groups €1k / €10k / €100k / €250k. Two horizontal dashed `ReferenceLine`s: 9 bps (light red, "Break-even, > $250M tier") and 17 bps (`--cost`, "Break-even, default > $20M tier"). Y axis −10 to 20 bps. Value labels on the bars (`−2.3`).
- **Toggle under the chart** "Median / Best 1% of moments": swaps the bars to `btc_p99` / `eth_p99`. Even the best moments stay far below the lines; that's the point.

**Step 4 · Strategy 2: perpetual funding carry**
- **Chart:** a Recharts `LineChart` of `chart_data.s2.rolling30["Kraken BTC"]` (`--s2`) and `["Deribit BTC"]` (`--s2-light`). Join them on date; Deribit starts a few days later, so leave its gap empty rather than drawing it as zero. Add a solid `ReferenceLine` at `s2.deposit_pct` (`--deposit`, "Bank deposit 2.5%") and a dashed one at `s2.needed_pct` (`--cost`, "≈7% needed to justify the risk"). Y axis in % a year. X ticks every second month ("Nov 25").
- **Toggle "BTC / ETH"**: switches both lines to the `… ETH` series.

**Step 5 · Strategy 3: EURC depeg capture**
- **Left chart** (about 55% width): a line or area chart of `chart_data.s3.kraken_daily.low` against date, Y axis €0.95–€1.005, with a dashed `--cost` reference line at 0.9925 ("Bid at 0.9925"). Light `--s3` fill between the line and 1.00 makes the depegs visible.
- **Middle chart** (about 25%): a bar chart of `chart_data.s3.ladder_kraken_fee_020` for levels 0.9975, 0.995, 0.9925, 0.99 and 0.98, value = `ann_pct`. Negative bars in `--cost`, positive in `--s3`. Caption: the fill counts and "Candles prove a price printed, not that size was there."
- **KPI tiles** on the right; the live-test box across under the charts; then the verdict band.

**Step 6 · Side by side**
- **Left: "What €40k would have earned in a year."** A horizontal range chart from `chart_data.compare_40k`, scale €0–€2,000. Each row is a bar from `low` to `high` in its colour, with a minimum visible width for the €0 and €1,000 points. A dashed vertical `--deposit` line at €1,000. Labels sit beside the bars and must never cross the dashed line (put the strategy 2 label to the left of its bar). Build it with plain SVG or divs if Recharts gets in the way; it's four rows.
- **Right:** the scorecard table (strategy / capacity / main risk / worth revisiting if), with strategy numbers in their colours.
- **Bottom** (dark `--teal` box): the decision, "What the work is good for now", the contact line and a **"See strategy 1 live →"** button to `#/live`.

## 4. Live market view

The live engine already works. Here, show what the viewer needs first and put everything else one click away. **Same endpoints, same polling interval (2 s), same data.**

### 4.1 Layout, top to bottom

1. **Status strip** (thin, `--pale`):
   - Connection: green dot "Live" / grey "Offline".
   - "Last update 14:32:05 Frankfurt time", from the newest `ts` in the market payload, formatted with `Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', second: '2-digit' })`.
   - Market selector (BTC/EUR, ETH/EUR).
   - The fixed text "Simulated · no orders are sent".

2. **Hero sentence** (the most important element, 28–32px):
   > **BTC price gap right now: −2.1 bps. A trade needs 17.0 bps.**
   > *No trade: the gap is too small to cover costs.*

   - Gap = `market.spread_pct * 100`, signed, one decimal.
   - Needed = `market.breakeven_spread_pct * 100` (this already includes the 1 bp FX cost; see `bsdex_strategy.py:883`). Fall back to `status.breakeven_spread_pct * 100` if the market payload has no value yet.
   - The second line is the plain-language state from §4.2. Colour: `--measured` for SIGNAL, `--muted` for HOLD or COOLDOWN, `--warn` for the paused states.
   - Under it, small and muted: "Order size €{capital_eur} per side · fee tier {tier_label}", taken from the **market payload** (`capital_eur`, `tier_label`), not from local form state.

3. **Gap-versus-cost gauge** (one horizontal bar, full width, 56px tall): a scale from −10 bps to (needed + 5) bps; a red zone from `needed` upwards labelled "Trade zone"; a teal marker at the current gap. Below it: "The gap would need to be {needed − gap} bps wider." Hide this line while in SIGNAL.

4. **Chart: "Price gap over the last few minutes"**
   - The existing spread series converted to bps (`spread_pct * 100`), the last 150 points.
   - Dashed red lines at ±needed, labelled "Break-even (either direction)". A light zero line.
   - Trade markers as today.
   - Y axis in bps; X axis in Frankfurt time (HH:MM:SS). Height around 300px.
   - Tooltip: "14:32:05 · gap −2.1 bps (−€2.10 on this order size)", using `spread_eur`.

5. **Three summary cards** in a row: "Paper trades this session" (`status.total_trades`), "Paper P&L after fees" (`status.total_pnl_eur`, EUR with 2 decimals, red if negative), "Running since" (`status.session_started_at`, Frankfurt time).

6. **"Technical details"**, a `<details>` element closed by default. Move everything currently on the Live tab that isn't above into it, with relabelled fields (§6 has the wording):
   - z-score and threshold
   - bid/ask per venue
   - depth A/B
   - VWAP slip A/B
   - price model
   - Bitstamp WS status
   - FX rate, FX age and ECB fixing (reference)
   - FX cost
   - fill latency
   - failed fills
   - the full trade blotter, with today's columns (Mono font allowed here)

   Nothing is deleted; it just moves.

7. **"Assumptions: fees and order size"**, a `<details>` element closed by default. It holds today's fee and capital form, with the same logic and the same `POST /api/v1/bsdex/config` payload. Changes:
   - Initialise the form from `GET /api/v1/bsdex/status` on first successful load (`tier_idx`, `fee_mode`, `venue_a_taker_pct / 100`, `venue_b_taker_pct / 100`, `capital_eur`). Today the form starts at hard-coded €1,000 and 0.12%/0.06%, so it can disagree with what the server is actually using.
   - After Apply, refetch status and market so the hero sentence updates.
   - The summary line when closed: "Fee tier > $20M · both fees 0.16% · break-even 17.0 bps · €1,000 per side · Edit".

8. **Footer:** "Venue A: Bitstamp EUR, used as a stand-in for BSDEX · Venue B: Binance USDT converted to EUR, LMAX fee model · Simulated, no orders are sent".

### 4.2 Plain-language signal states

Use this exact mapping (`signal_state` from `/api/v1/bsdex/market/{market}`). Unknown states: show the raw value in Technical details and "Watching" in the hero.

| `signal_state` | Hero second line | Colour |
|---|---|---|
| `HOLD` | Watching: the gap is within its normal range. | `--muted` |
| `SIGNAL_GATED` | No trade: the gap is too small to cover costs. | `--muted` |
| `SIGNAL` | Trade signal: the gap covers all costs. A paper trade fills in 300 ms. | `--measured` |
| `SIGNAL_COOLDOWN` | Pausing for 30 seconds after a trade. | `--muted` |
| `FX_STALE` | Paused: the EUR/USDT rate is out of date. | `--warn` |
| `BOOK_STALE` | Paused: an exchange's prices have stopped updating. | `--warn` |
| `FILL_FAILED` | The last paper trade could not be filled at full size. | `--warn` |

### 4.3 Offline state

If `/api/v1/bsdex/status` fails (react-query `retry: 1` exhausted), replace sections 2–7 with one calm panel:

> **The live feed isn't running.**
> Start the backend with `uvicorn src.crypto_hft_tool.main:app --reload` from the project root, then reload this page.
> The recorded results are in **Findings →**

No red error styling, no stack traces. Keep polling every 10 s while offline, so the view comes back by itself once the backend starts.

---

## 5. Lab view (today's Backtest tab)

The functionality stays exactly as it is: the same request, the same result rendering logic, the same Excel export. The changes are framing and labels.

1. **Intro line** at the top: "Re-run the historical test yourself. Results use real 1-minute exchange data or recorded order books, and include every trading cost."
2. **"Load verified example" button.** It fills the form with: market `btc-eur`, data source `candles`, spread model `conservative`, start `2026-09-24T00:00`, end `2026-10-01T00:00` (UTC), capital `100000`, fee mode `auto`, tier = the entry in `volume_tiers` whose `label === "> $250M"`. Look it up by label, never by a hard-coded index. Next to it, small and muted: "Documented result for these settings: 7 trades, 0 winners, −€1,547.98 after fees and FX (−€1,739.76 after funding cost). Needs internet access to the exchange APIs; small differences are possible if exchange data is revised." It does **not** auto-run.
3. **Form grouping.**
   - "What to test": market, start, end, data source.
   - "Costs": fee tier and order size per side.
   - A closed "Advanced" `<details>` holding fee mode (Auto/Manual), manual fees, spread model, quote path and fill latency. Keep today's conditional visibility rules.
4. **Result headline** above the KPI cards, 22–24px: "Net result after all costs: **−€1,547.98** over 7 trades (0 wins, 7 losses). After funding cost: −€1,739.76." Build it from `realistic.summary` (`total_pnl_eur`, `total_trades`, `win_trades`, `loss_trades`, `net_after_carry_eur`). Red when negative.
5. **KPI cards:** keep the realistic row. Rename the second row to **"Theoretical best case: no trading costs (not achievable)"**, show it collapsed by default and at 75% opacity when open. Never show it without the realistic row.
6. **Charts:** show spread in **bps** with break-even lines in bps; keep the equity curve in EUR. Use the light theme for chart colours (grid `--line`, text `--muted`).
7. **Parameter table and trade log:** move them into a closed "Details" `<details>`. The Mono font is allowed there.
8. **Excel export:** unchanged.

---

## 6. Glossary drawer and relabelling

### 6.1 "Terms" drawer

A right-side drawer (full-screen on phones), opened from the top-bar "Terms" button and closed with Esc. It lists `glossary` from `src/content/glossary.js` (§8) as term plus one sentence. Also, wherever a glossary term appears as a label in Live or Lab, render it with a small dotted underline and a tooltip carrying the same definition (keyboard-focusable; use `title` plus an `aria-describedby` popover).

### 6.2 Label changes (Live and Lab)

| Today | New label (small grey technical term after it, where useful) |
|---|---|
| Spread | Price gap · *spread* |
| B/E, B/E Spread | Break-even (total cost) |
| Z-Score / Threshold | How unusual the gap is · *z-score* |
| Signal State | Engine status |
| Cumulative PnL | Paper P&L after fees |
| WR | Win rate |
| Venue A Taker / Venue B Taker | Bitstamp fee / Global venue fee · *taker fee* |
| Volume Tier | Fee tier (monthly trading volume) |
| Capital (EUR), Capital / leg | Order size per side (EUR) |
| VWAP depth / top-of-book fallback | Priced for full order size / Priced at best quote only |
| Depth A / Depth B | Available at Bitstamp / Available at global venue |
| Slip A / Slip B | Price impact at Bitstamp / at global venue · *slippage* |
| FX Rate / FX Age | EUR/USDT rate / Rate age |
| ECB fixing (reference) | ECB reference rate (display only) |
| Fill latency | Fill delay |
| Half-spread | Cost of crossing bid/ask |
| Spread model: Conservative (A: 5 bps) | Crossing cost: conservative (5 bps at Bitstamp) |
| Spread model: Calibrated… | Crossing cost: measured from recorded order books |
| UPPER BOUND (mid-price fills…) | Theoretical best case: no trading costs (not achievable) |
| REALISTIC (bid-ask + slippage costs applied) | Realistic: all trading costs included |
| Trade Blotter / Trade Log | Paper trades |
| Run Backtest | Run test |

---

## 7. Content and data files (use verbatim)

### 7.1 `src/content/chart_data.json`

Copy `reports/closure/data/chart_data.json` into `hft-frontend/src/content/chart_data.json` unchanged, and import it statically (`import chartData from './chart_data.json'`). It is about 64 KB. It holds:
- `s1.by_size` and `s1.breakeven_bps` (strategy 1 chart)
- `s2.rolling30[...]`, `s2.stats[...]`, `s2.deposit_pct` and `s2.needed_pct` (strategy 2 chart and KPIs)
- `s3.kraken_daily`, `s3.ladder_kraken_fee_020`, `s3.kraken_days_below_09925` and `s3.kraken_min_low` (strategy 3 charts and KPIs)
- `compare_40k` (step 6)

It's produced by `reports/closure/.build/build_chart_data.py`. If the data needs refreshing, re-run that script and copy the file again; never edit numbers by hand.

### 7.2 `src/content/findings.js`

Display rounding rule: one decimal, half away from zero (e.g. 2.25 → "2.3"), matching the deck. Use `formatPct1` from `lib/format.js`, not `toFixed` on raw floats you have computed yourself.

```js
// Copy for the Findings view. Mirrors reports/closure/ (memo and 6-slide deck).
// Numbers that come from chart_data.json are referenced by path in {braces}; render them with lib/format.js.
const findings = {
  meta: {
    author: 'Syed Zee Waqar Hussain',
    period: 'May 2025 – October 2026',
    honesty: 'Paper trading on live public market data · No orders sent',
    contact: 'Happy to walk through the data in 15 minutes · Syed Zee Waqar Hussain',
  },
  strategies: {
    1: { name: 'Cross-exchange spot arbitrage', short: 'Cross-exchange spot', color: 'var(--s1)',
         how: 'Buy BTC or ETH on the cheaper exchange and sell on the dearer one at the same moment.' },
    2: { name: 'Perpetual funding carry', short: 'Perpetual carry', color: 'var(--s2)',
         how: 'Buy spot and short the perpetual future; collect the funding that leveraged longs pay.' },
    3: { name: 'EURC depeg capture', short: 'EURC depeg capture', color: 'var(--s3)',
         how: 'Rest bids below €1 for the euro stablecoin; buy when a seller dumps, sell back near par.' },
  },
  steps: [
    {
      id: 'answer',
      kicker: 'Research briefing · October 2026',
      title: 'Three crypto arbitrage strategies against a 2.5% deposit',
      question: 'The question: can any of them beat a 2.5% EUR bank deposit after every cost?',
      cards: [
        { strategy: 1, value: '−2.3 bps', label: 'median price gap at €100k, against a 17 bps cost', verdict: 'No edge' },
        { strategy: 2, value: '{s2.stats["Kraken BTC"].mean_ann_pct}%', label: 'a year of funding (Kraken BTC, 12 months), before hedge and risk', verdict: 'Edge ≈ deposit rate' },
        { strategy: 3, value: '€100–300', label: 'a year, realistic, on a €5k sleeve', verdict: 'Real edge, tiny capacity' },
      ],
      decision: 'Decision: deploy none. The €40k test capital stays in the 2.5% deposit.',
      source: 'Syed Zee Waqar Hussain · May 2025 – Oct 2026 · Paper trading on live public market data · No orders sent',
    },
    {
      id: 'history',
      kicker: '01 · How the project got here',
      title: 'Eighteen months, three strategies, one yardstick',
      timeline: [
        { when: 'May 2025', head: 'Prototype', body: 'Binance vs Kraken z-score engine, live paper trading, web dashboard' },
        { when: 'May–Jun 2026', head: 'Institutional model', body: '"BSDEX vs World": bank fee tiers, live EUR/USDT, full-depth prices, slippage' },
        { when: '11–15 Oct 2026', head: 'Audit + live run', body: 'Three backtest bugs fixed; 4-hour live campaign at €100k per leg' },
        { when: '13–22 Oct 2026', head: 'Alternatives', body: 'Perpetual carry (12 months of funding) and EURC (live test + daily history)' },
        { when: '22 Oct 2026', head: 'Decision', body: 'Deploy none; keep the €40k in the deposit' },
      ],
      evidence: [
        { strategy: 1, venues: 'Bitstamp EUR, Binance USDT→EUR, Kraken', evidence: '136-setting backtest sweep, order-book replays, verified 1-week backtest', live: '4 h on 14 Oct, 49,825 snapshots per coin' },
        { strategy: 2, venues: 'Kraken, Deribit, OKX perpetuals', evidence: '12 months of hourly funding; EU fee schedules and access', live: 'None: profit accrues over months, not hours' },
        { strategy: 3, venues: 'Bitvavo, Kraken, Bitstamp (EURC/EUR)', evidence: '12 months of daily candles; resting-bid ladder backtest', live: '2.6 h on 22 Oct, three venues, rules set in advance' },
      ],
      yardstick: 'Same yardstick for all three: net of every fee, spread, currency, funding and idle-capital cost, measured against a 2.5% EUR deposit.',
      source: 'Sources: git history; docs/BSDEX_Explainer_Guide.html; docs/eurc_live_test.md; reports/closure/data/meta.json. Bitstamp stands in for BSDEX (its API needs keys).',
    },
    {
      id: 's1', strategy: 1,
      kicker: 'Strategy 1 · Cross-exchange spot arbitrage',
      title: 'The price gap is smaller than the cost of trading it',
      subtitle: 'Buy on the cheaper exchange, sell on the dearer one, at the same moment. BTC and ETH, Bitstamp (EUR) vs Binance (USDT, in EUR).',
      chartTitle: 'Median tradeable gap by order size vs cost to break even (bps)',
      kpis: [
        { value: '0 trades', label: 'in a 4-hour live paper run at €100k per leg; the gap beat 17 bps 0% of the time' },
        { value: '0 of 136', label: 'realistic backtest settings made money (7–14 Oct, every fee tier)' },
        { value: '+€276 → −€1,548', label: 'the “profitable” backtest once look-ahead, a stale FX rate and instant fills were fixed', tone: 'cost' },
      ],
      verdict: { label: 'no edge', text: 'The market is arbitraged to within a few bps; paying spread and fees on both legs cannot win. The rare big gaps were frozen prices, ≤ 3 s.' },
      source: 'Live campaign 14 Oct 2026, 4 h (docs/BSDEX_Explainer_Guide.html); gap after crossing both books, before fees. Backtest: BTC/EUR 24 Sep–1 Oct 2026.',
    },
    {
      id: 's2', strategy: 2,
      kicker: 'Strategy 2 · Perpetual funding carry',
      title: 'The yield is real, but it is roughly the deposit rate',
      subtitle: 'Hold the coin and short its perpetual future so price moves cancel; earn the funding that leveraged buyers pay.',
      chartTitle: 'Funding earned by the short, 30-day average (% a year)',
      kpis: [
        { value: '{s2.stats["Kraken BTC"].mean_ann_pct}% vs 2.5%', label: '12-month average funding, Kraken BTC (Deribit {s2.stats["Deribit BTC"].mean_ann_pct}%), in USD' },
        { value: '{s2.stats["Kraken BTC"].share_negative_pct|round0}% of hours', label: 'had negative funding on Kraken: the short pays instead of earning', tone: 'cost' },
        { value: '€960–1,720', label: 'a year on €40k before the EUR/USD hedge, against €1,000 from the deposit' },
      ],
      verdict: { label: 'edge ≈ deposit rate', text: 'Pays only in high-funding regimes, with exchange and ESMA “likely CFD” risk on 100% of capital; cheapest venues are closed to EU residents.' },
      source: 'Funding: Kraken Futures and Deribit public history to 22 Oct 2026, 30-day average, annualised. Net range and ≈7% level: docs/eurc_live_test.md.',
    },
    {
      id: 's3', strategy: 3,
      kicker: 'Strategy 3 · EURC stablecoin depeg capture',
      title: 'A real edge, but each depeg is small and brief',
      subtitle: 'Rest bids below €1 for the euro stablecoin; when a holder dumps into a thin book, buy and sell back near par.',
      chartTitle: 'EURC/EUR daily low on Kraken, last 12 months',
      ladderTitle: 'Resting-bid backtest after fees (% a year)',
      ladderCaption: 'Fills over the year: {fills joined by " · "}. Candles prove a price printed, not that size was there.',
      kpis: [
        { value: '{s3.kraken_days_below_09925} days', label: 'below €0.9925 on Kraken in 12 months (low €{s3.kraken_min_low})' },
        { value: '≈2.5k EURC', label: 'per seller sweep on the live tape: +€12 on one event' },
        { value: '€100–300', label: 'a year, realistic, on a €5k sleeve' },
      ],
      liveBox: { head: 'Live test, 22 Oct (2.6 h):', text: 'market making −€29 and failed all 4 pre-set criteria; cross-venue arbitrage −39 bps at €10k. Kraken’s 2 bps spread sits under a 20 bps fee.' },
      verdict: { label: 'real edge, tiny capacity', text: 'Deep bids do catch depegs, but each sweep is a few thousand EURC: too small to move €40k, and it needs two venues and on-chain transfers.' },
      source: 'Kraken EURC/EUR daily candles to 22 Oct 2026. Ladder: rule in scripts/eurc_live_test.py, 0.20% fee each side, exit 0.9995. Live test: docs/eurc_live_test_results.md.',
    },
    {
      id: 'compare',
      kicker: '02 · Side by side',
      title: 'None beats the deposit by enough to justify the risk',
      chartTitle: 'What €40k would have earned in a year',
      rangeLabels: ['€1,000', '€0: no trade clears', '€960–1,720 before hedge', '€100–300, capped'],
      scorecard: [
        { strategy: 1, capacity: 'None: no edge', risk: 'Fees on both legs; frozen prices', revisit: 'A maker-only design with a near-free hedge' },
        { strategy: 2, capacity: 'Large (millions)', risk: 'Negative funding; exchange and ESMA risk', revisit: '90-day funding above ≈7%, sustained, and EU rules clarified' },
        { strategy: 3, capacity: '≈2.5k EURC per event', risk: 'Thin books; transfer costs', revisit: 'Free par redemption, or Bitvavo volume above €100k a day' },
      ],
      decision: 'Decision: deploy none. The €40k stays in the 2.5% deposit.',
      useful: 'What the work is good for now: live venue-quality data for best execution (MiCA Art. 78), euro-stablecoin liquidity evidence, and a checklist of the backtest errors that make losses look like profit.',
      source: 'Ranges: 1 from the live run; 2 from docs/eurc_live_test.md, before the EUR/USD hedge; 3 from docs/eurc_live_test_results.md, €5k sleeve.',
    },
  ],
};

export default findings;
```

**Placeholders:** `{path}` placeholders in strings are resolved against `chart_data.json` by a small `fill(template, data)` helper in `lib/format.js`. Numbers render with `formatPct1` (one decimal, half away from zero); `|round0` means a whole number. `{fills joined by " · "}` means the `fills` of the five ladder bars shown, in order. The rendered text must equal the deck exactly: "3.3% vs 2.5%", "Deribit 2.3%", "31% of hours", "20 days", "low €0.953", "41 · 19 · 15 · 13 · 6".

---

## 8. `src/content/glossary.js` (use verbatim)

```js
const glossary = [
  { term: 'Price gap (spread)', def: 'How much more you could sell a coin for on one exchange than you pay for it on the other, after crossing both order books.' },
  { term: 'Basis point (bp)', def: 'One hundredth of a percent. 1 bp on a €100,000 order is €10.' },
  { term: 'Break-even', def: 'The gap needed just to pay both exchange fees and the 1 bp currency cost. Below it, every trade loses money.' },
  { term: 'Fee tier', def: 'Exchanges charge less to firms that trade more each month. Tiers above $20M are assumptions, not quoted rates.' },
  { term: 'Taker fee', def: 'The fee for trading immediately against prices already in the order book.' },
  { term: 'Order book', def: 'The list of prices at which people are currently willing to buy and sell, with the size at each price.' },
  { term: 'Priced for full order size (VWAP)', def: 'The average price you would actually get for the whole order, walking through the order book, not just the best quote.' },
  { term: 'Price impact (slippage)', def: 'How much worse the average price gets because the order is larger than the best quote.' },
  { term: 'How unusual the gap is (z-score)', def: 'How far today’s gap is from its recent average, in units of its normal variation. It finds unusual gaps, not profitable ones.' },
  { term: 'Fill delay', def: 'Time between deciding to trade and the trade happening. The engine uses 300 ms; prices can move against you meanwhile.' },
  { term: 'EUR/USDT rate', def: 'The live exchange rate used to convert Binance’s USDT prices into euros. Its age is shown because a stale rate creates fake gaps.' },
  { term: 'Funding cost (carry)', def: 'Interest the cash and coins sitting on both exchanges could have earned elsewhere, at 2.5% a year.' },
  { term: 'Look-ahead bias', def: 'A backtest error where the rule uses information it would not have had at the time. It makes results look far better than reality.' },
  { term: 'Markout', def: 'How the price moved after a fill. A negative 60-second markout means the market moved against the trade within a minute.' },
  { term: 'Paper trading', def: 'Simulated trading on live market data. No orders are sent and no money is at risk.' },
  { term: 'EURC', def: 'A euro stablecoin issued by Circle, designed to be worth €1.' },
  { term: 'BSDEX (proxy)', def: 'A German regulated crypto exchange. Its API needs keys, so Bitstamp’s EUR market stands in for it here.' },
  { term: 'Perpetual future (perp)', def: 'A futures contract with no expiry. A funding payment between buyers and sellers keeps its price close to the coin’s spot price.' },
  { term: 'Funding rate', def: 'The periodic payment between perp buyers and sellers. When it is positive, buyers pay sellers; the carry trade is the seller.' },
  { term: 'Cash-and-carry (funding carry)', def: 'Holding the coin and shorting the same amount of its perpetual, so price moves cancel and only the funding is earned.' },
  { term: 'Depeg', def: 'When a stablecoin trades below (or above) the currency it tracks, e.g. EURC at €0.99 instead of €1.00.' },
  { term: 'Par redemption', def: 'Exchanging a stablecoin with its issuer for exactly one unit of the currency. Under MiCA, Circle redeems EURC at par.' },
  { term: 'Resting-bid ladder', def: 'Buy orders left in the book at several prices below €1, which only fill when a seller pushes the price down to them.' },
];

export default glossary;
```

---

## 9. Clean-up and structure

### 9.1 World clocks
Remove the FRA/LDN/NYC clocks from the top bar. They use hard-coded UTC offsets (`App.js:445–447`) and go wrong after daylight-saving changes. The only clock left is the Live view's "Last update … Frankfurt time" (§4.1), using `Intl` with `timeZone: 'Europe/Berlin'`.

### 9.2 Dead layout
Delete the empty `<aside className="left-panel" />`, `<aside className="right-panel" />` and `<div className="blotter" />`, plus the CSS grid areas and rules that exist only for them (`.dashboard` grid with 220px/280px columns, `.tab-backtest` and `.tab-bsdex-live` overrides).

### 9.3 Unused frontend API calls
Remove `getMarketData`, `getSimulationStatus`, `getRecentTrades`, `getConfig` and `updateConfig` from the frontend API object. They belong to the retired Binance/Kraken view. **Do not touch the backend routes.**

### 9.4 File structure
Split the 1,158-line `App.js`:

```
hft-frontend/src/
  App.js                 # providers, top bar, route switch only
  api.js                 # the remaining bsdex* calls and runHistoricalBacktest, unchanged signatures
  hooks/useHashRoute.js
  content/findings.js    # §7
  content/glossary.js    # §8
  lib/format.js          # formatBps, formatEur, formatFrankfurtTime, pctToBps
  lib/signalStates.js    # §4.2 mapping
  views/FindingsView.jsx
  views/findings/StepAnswer.jsx, StepHistory.jsx, StrategyStep.jsx (shared template),
                 S1Chart.jsx, S2Chart.jsx, S3Charts.jsx, StepCompare.jsx
  content/chart_data.json   # copy of reports/closure/data/chart_data.json, unchanged
  views/LiveView.jsx
  views/LabView.jsx
  components/TopBar.jsx, GlossaryDrawer.jsx, Term.jsx, StatCard.jsx, Details.jsx
  index.css              # tokens + base
  App.css                # layout + components (rewrite; delete terminal-only rules)
```

The current `theme.js` (MUI dark theme) is no longer needed once `ThemeProvider` and `CssBaseline` are removed from `App.js`. Delete the file and its import; leave the package installed.

### 9.5 Page metadata
In `public/index.html`, set `<title>Crypto Arbitrage · Three Strategies</title>` and the meta description "Three crypto arbitrage strategies tested against a 2.5% EUR deposit: cross-exchange spot, perpetual funding carry and EURC depeg capture."

### 9.6 Optional, outside `hft-frontend/`: the orphan Next.js frontend
`src/crypto_hft_tool/frontend/` holds five `.tsx` files from an earlier Next.js prototype, with no `package.json` and no references. Before deleting, confirm with `grep -rn "crypto_hft_tool/frontend" --include=*.py --include=*.js --include=*.json --include=*.toml --include=*.yaml --include=*.sh .` (excluding `node_modules`). Delete it only if that returns nothing apart from the folder itself, in its own commit titled "Remove unused Next.js prototype frontend".

---

## 10. Tests

Replace the CRA placeholder `App.test.js` (it looks for "learn react" and fails) with:

1. **Findings renders offline:** mock `axios` to reject every call; render `App` at `#/findings/1`; assert the title "Three crypto arbitrage strategies against a 2.5% deposit" and all three verdict pills are present, and that **axios was never called**.
2. **Step navigation:** pressing → three times from step 1 lands on step 4 (title "The yield is real, but it is roughly the deposit rate") and updates `location.hash` to `#/findings/4`.
3. **Data-driven copy:** on step 4 the first KPI renders exactly "3.3% vs 2.5%" and its label contains "Deribit 2.3%"; on step 5 the ladder caption contains "41 · 19 · 15 · 13 · 6". This proves the `fill()` helper and the half-up rounding.
4. **Formatting:** `formatBps(-2.26) === '−2.3 bps'`; `formatBps(1.55) === '+1.6 bps'`; `pctToBps(-0.0226) === -2.26` (within floating-point tolerance).
5. **Signal states:** every key in §4.2 maps to the exact sentence; an unknown key maps to "Watching".
6. **Live offline panel:** with `/api/v1/bsdex/status` rejected, `#/live` shows "The live feed isn't running."
7. **Lab payload unchanged:** clicking "Run test" with the default form posts a body with exactly these keys: `symbol, data_source, quote_path, latency_ms, spread_model, start_dt, end_dt, venue_a_taker, venue_b_taker, capital_eur, tier_label`.

---

## 11. Work order (one commit per phase)

1. **Structure, no visual change:** split files (§9.4), remove dead code (§9.2, §9.3), add the hash router with the three routes (Findings can be a placeholder). The app works exactly as before under Live and Lab.
2. **Design tokens and base styles** (§2). Live and Lab adopt the light theme.
3. **Findings view** (§3, §7): the shared strategy template, all six steps with their charts, keyboard navigation, the Present toggle and the two chart toggles.
4. **Live view** simplification (§4), the offline panel and form initialisation from status.
5. **Lab** framing (§5): the verified-example button and the result headline.
6. **Glossary drawer and relabelling** (§6, §8).
7. **Tests** (§10), metadata (§9.5), and finally the optional §9.6 in its own commit.

---

## 12. Acceptance checklist (all must pass)

- [ ] `CI=true npm run build` succeeds (CRA treats warnings as errors under `CI=true`).
- [ ] `CI=true npm test -- --watchAll=false` passes.
- [ ] With the backend **stopped**, Findings works fully, and the Network tab shows **no** requests while on Findings.
- [ ] Each Findings step fits without vertical scroll at **1280×720** and **1440×900**. No horizontal scroll at **390px** wide.
- [ ] ←/→ and PageUp/PageDown move between steps; deep links `#/findings/1` to `#/findings/6` work; Present mode hides the top bar and Esc exits.
- [ ] Every number on Findings comes from `findings.js` or `chart_data.json`, and matches the deck (`reports/closure/Crypto_Arbitrage_Three_Strategies_Briefing.pdf`) slide for slide; no other hard-coded numbers in view components.
- [ ] The three strategies are visually separate: each uses only its own colour, and steps 3–5 share one layout.
- [ ] Live: the hero sentence shows gap and break-even in bps from the API, the right sentence for each `signal_state`, and order size and tier from the market payload.
- [ ] Live: everything that was on the old Live tab is still reachable under "Technical details" or "Assumptions".
- [ ] Live: the assumptions form starts from the server's current settings; Apply posts the same payload as before.
- [ ] Lab: the request payload keys are unchanged; Excel export still works; "Load verified example" fills the form without running.
- [ ] "Simulated · no orders are sent" is visible on Live and Lab.
- [ ] No orange, no dark terminal styling left (search the CSS for `#FF8C00`, `--accent-orange`, `IBM Plex Mono` outside Lab tables).
- [ ] No console errors or React key warnings.
- [ ] Nothing under `src/` (backend), `scripts/` or `tests/` changed, except the optional §9.6 deletion.

---

## 13. Out of scope

- Backend, API or strategy changes, new endpoints, new data.
- New npm packages, a TypeScript migration, a state-library change.
- Dark mode.
- Re-running the experiments or changing any reported number.
- Live views for strategies 2 and 3 (they live in Findings only).
- README rewrite (separate task).
