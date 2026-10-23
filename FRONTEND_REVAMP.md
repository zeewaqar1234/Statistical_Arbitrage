# Frontend revamp: from trading terminal to explainer

> **For:** Codex (or any coding agent).
> **Scope:** `hft-frontend/` only. One optional clean-up outside it (§9.6).
> **Supersedes:** the visual and layout rules in `BLOOMBERG_UI_REVAMP.md` and `UI_AND_PROBE.md`. Keep those files as history, but **do not follow their design rules** (dense, dark, orange, "every gap is a wasted opportunity to show a number"). This document reverses them on purpose.

---

## 0. Read this first

### Why this change

The project is finished. It answered its question: **after every real cost, cross-exchange EUR crypto arbitrage has no tradeable edge.** The owner now shows the tool to senior bankers and market professionals in Frankfurt, often in a 15–30 minute slot.

Today the app is a Bloomberg-style terminal built for a trader watching it all day. A first-time viewer sees jargon (`Z-Score / Threshold`, `B/E`, `VWAP depth`, `Venue A Taker %`), the presenter's own settings, and a live number that changes every 2 seconds. They can't tell what the answer is. The owner loses the room before the point lands.

### What success looks like

1. **Answer first.** A finance professional who has never seen the project understands the conclusion and the three reasons for it within **3 minutes**, using only the new **Findings** view.
2. **Live proof without jargon.** The presenter can then switch to **Live market** and show 60–90 seconds of real data that confirms the story, with no term left unexplained.
3. **Expert depth stays available.** The full backtest tool still exists in **Lab** for anyone who asks "how did you test that?".
4. **Works offline.** Findings needs no backend and no internet. Demos happen on laptops, in meeting rooms, sometimes on a bank network that blocks exchange APIs.

### Hard rules

- **Do not change anything under `src/`** (the Python backend), the API contracts, strategy maths, `scripts/` or `tests/`. This is a frontend-only change. §9.6 is the one exception, and it only deletes unused files.
- **Do not invent numbers or wording.** Every figure in Findings comes from `src/content/findings.js` exactly as given in §7. Every live figure comes from the existing API. If you think a number is wrong, leave it and flag it in your summary; don't "fix" it.
- **Do not add or remove npm dependencies** in this pass. Use what is installed: React 18, Recharts, react-query 3, axios, xlsx. MUI is installed but should no longer be needed. Removing its usage is fine; leave `package.json` as it is.
- **Keep it honest on every screen.** "Simulated · no orders are sent" must be visible on Live and Lab. Every Findings step shows its source line.
- **Keep the Lab's backtest request payload byte-for-byte the same** as today's `api.runHistoricalBacktest` call (see `App.js` lines 333–347), and keep the Excel export working.

---

## 1. Information architecture

Replace the two tabs (`BSDEX vs World`, `Backtest`) with three views in this order:

| Nav label | Hash route | What it is | Needs backend? |
|---|---|---|---|
| **Findings** (default) | `#/findings`, `#/findings/1` … `#/findings/6` | Six-step story of the result. Mirrors the 6-slide deck in `reports/closure/` | **No.** Static content only |
| **Live market** | `#/live` | Simplified live paper engine: "is there a trade right now, and why not?" | Yes |
| **Lab** | `#/lab` | Today's Backtest tab, restyled and relabelled, same functionality | Yes |

- Use hash routing with a tiny hook (`useHashRoute`). No new router dependency. An empty or unknown hash goes to `#/findings/1`.
- **Polling is tied to the view.** Live queries run only while `#/live` is open. The tier list (`/api/v1/bsdex/volume_tiers`) loads only on Live or Lab. **Findings must make zero network requests**; check this in the Network tab.
- Top bar: project name on the left ("EUR Crypto Arbitrage"), the three nav items, and a **"Terms"** button on the right that opens the glossary drawer (§6). Remove the world clocks (§9.1). Show the connection dot only on Live and Lab.

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
  --radius:     4px;
  --font-sans:  'IBM Plex Sans', -apple-system, 'Segoe UI', Arial, sans-serif;
  --font-mono:  'IBM Plex Mono', 'SF Mono', Consolas, monospace;
}
```

- **Colours carry meaning, consistently:** teal means measured or market data, red means a cost, a loss or a fail. No orange anywhere. No decorative colour.
- **Typography:** IBM Plex Sans is already loaded in `index.css`; keep it. Use `font-variant-numeric: tabular-nums` for all numbers. Use Plex Mono **only** in the Lab's dense tables. Sizes: step title 32–36px, stat values 40–56px, body 16–18px, captions and sources 12–13px. Nothing below 12px.
- **Surfaces:** white page, `--pale` cards, 1px `--line` borders, `--radius` corners, no shadows, no glow, no hover-lift.
- **Layout targets:** every Findings step fits **without vertical scrolling at 1280×720** (projector) and 1440×900 (laptop). Everything works at 390px wide (phone) with no horizontal page scroll; columns stack. Max content width 1200px, centred, 32px side padding (16px on phones).
- **Numbers:** show basis points, not percentages with four decimals. `spread_pct` from the API is a percentage, so `bps = spread_pct * 100`. Format bps with one decimal and an explicit sign (`+1.6 bps`, `−2.3 bps`, using U+2212 for the minus sign). Show EUR with two decimals in Live and Lab, and with no decimals in Findings, as given.
- **Accessibility:** WCAG AA contrast, visible focus rings, buttons that are real `<button>`s, charts with an `aria-label` summarising the point (for example "Measured gaps of −2.3 and −4.1 bps against costs of 7 to 47 bps").

---

## 3. Findings view (story mode)

### Behaviour

- Six steps, one per screen, in the order below. Each step has a **kicker**, a **title**, **one visual**, at most **three short text lines**, and a **source line** at the bottom in `--muted` 12–13px.
- Navigation: **Back / Next** buttons bottom-right; **←/→** and **PageUp/PageDown** keys (presentation clickers send these); a progress row of six dots with step titles as tooltips. Each step has its own hash (`#/findings/3`) so the presenter can deep-link. Next on step 6 goes to `#/live`.
- **"Present" toggle** (top-right of Findings, or the `F` key): hides the top bar for a clean full-screen look and uses `document.documentElement.requestFullscreen()` where allowed. `Esc` exits.
- All text and numbers come from `findings.js` (§7). Components render data; they don't contain copy.
- No animation beyond a 150ms fade between steps. Respect `prefers-reduced-motion`.

### Step-by-step

**Step 1 · Answer** (dark panel: `--teal` background, white text)
- Kicker, title, headline, subline and three stat cards from `findings.steps[0]`.
- The three cards sit side by side (stacked on phones), on `--teal-soft`, with the value at 48–56px.
- Footer line: the author and "Paper trading only · public market data · no orders sent".

**Step 2 · How it works**
- A four-box horizontal flow: Watch → Price → Gate → Fill, with numbered circular badges and `›` separators (vertical on phones).
- Below it, a "Three kinds of test" row with three short columns.

**Step 3 · The fee wall** (the key chart)
- Left, about 62% width: a Recharts horizontal `BarChart` (`layout="vertical"`). Seven bars from `feeWall.bars`, in the order given (measured gaps at the top, costs below). Teal for `kind: "measured"`, red for `kind: "cost"`. A zero `ReferenceLine`. Value labels at the bar end (`+47.0`, `−2.3`). Category labels on the left, outside the plot, so negative bars never overlap them. Axis title: "Basis points (1 bp = 0.01%)".
- Right, about 38%: a `--pale` card with the three callouts in order (big "0 trades", the 99.6% / 99.9% line, and the frozen-prices line in `--cost`).
- **Interaction (one, optional for the viewer):** a segmented control "Order size: €1k · €10k · €100k · €250k" under the chart, with nothing selected at first (the chart then matches the deck exactly). Choosing a size swaps the three measured bars for the values in `feeWall.bySize`; the mapping is under §7. The cost bars stay fixed. When the presenter clicks €250k, the gap visibly grows more negative; at €1k the best moments are slightly positive but still far below every cost. Caption below the control: `feeWall.bySizeCaption`.

**Step 4 · The backtest trap**
- Two big cards side by side: **Before fixes** (value in `--profit`) → **After fixes** (value in `--cost`), with an arrow between them.
- Below them, three "bug" cards (title plus one sentence).
- Bottom line in bold `--teal`: the second-week result.

**Step 5 · Live test: EURC euro stablecoin**
- Left, about 62%: the five-row criteria table (criterion / result / verdict). `FAIL` in bold `--cost`; `NOT MET` in bold `--muted`.
- Right, about 38%: three stacked fact cards (big value plus one-line label).
- Below the table, the "only positive result" line in `--muted`.

**Step 6 · Decision and what remains** (dark panel, like step 1)
- Left column: "Decision", the decision line, the reason, then "What would reopen it" with three bullets.
- Right column: a `--teal-soft` card titled "Where the data helps now" with four numbered items.
- Footer: the contact line, plus a primary button **"See it live →"** to `#/live`.

---

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

## 7. `src/content/findings.js` (use verbatim)

Every value below is sourced. Don't round, rephrase or "improve" anything. If a value looks inconsistent, flag it and keep it.

```js
// Single source of truth for the Findings view. Mirrors reports/closure/ (memo and 6-slide deck).
// Sources: docs/BSDEX_Explainer_Guide.html (live run 14 Oct 2026; backtests 7–14 Oct 2026),
// docs/engine-integrity.md (24 Sep–1 Oct 2026), docs/eurc_live_test_results.md (22 Oct 2026).
const findings = {
  meta: {
    author: 'Syed Zee Waqar Hussain',
    period: 'May 2025 – October 2026',
    honesty: 'Paper trading only · public market data · no orders sent',
    contact: 'Happy to walk through the data in 15 minutes · Syed Zee Waqar Hussain',
  },
  steps: [
    {
      id: 'answer',
      kicker: 'Research briefing · October 2026',
      title: 'EUR crypto arbitrage: one year of testing',
      headline: 'After every cost, there was no edge to trade.',
      subline: 'What remains useful is the data on what EUR crypto execution really costs.',
      stats: [
        { value: '0', label: 'trades in a 4-hour live paper run at €100k per leg' },
        { value: '−2.3 bps', label: 'median BTC price gap, against 17 bps needed to break even' },
        { value: '0 of 136', label: 'realistic backtest settings that made money' },
      ],
      source: 'Live run 14 Oct 2026, 4 h, €100k per leg, > $20M fee tier. Backtest sweep 7–14 Oct 2026.',
    },
    {
      id: 'setup',
      kicker: '01 · The question and the set-up',
      title: 'Do price gaps between exchanges survive costs?',
      flow: [
        { n: 1, head: 'Watch', body: 'BTC and ETH: Bitstamp (EUR) vs Binance (USDT, in EUR). EURC: Bitvavo, Kraken, Bitstamp.' },
        { n: 2, head: 'Price', body: 'Measure the gap for the full order size, after crossing both order books.' },
        { n: 3, head: 'Gate', body: 'Trade only if the gap beats both exchange fees plus a 1 bp FX cost.' },
        { n: 4, head: 'Fill', body: 'Fill both legs 300 ms later. Book losses; count failed fills.' },
      ],
      testsTitle: 'Three kinds of test',
      tests: [
        { head: 'Backtests', body: 'One-minute candles, every fee tier, 136 parameter settings' },
        { head: 'Replays', body: 'Recorded order books, fills at 300 / 1,000 / 2,000 ms' },
        { head: 'Live paper runs', body: 'BTC/ETH on 14 Oct (4 h) and EURC on 22 Oct (2.6 h), pass/fail rules set in advance' },
      ],
      source: 'Bitstamp stands in for BSDEX (its API needs keys); LMAX fees are modelled.',
    },
    {
      id: 'fee-wall',
      kicker: '02 · The fee wall',
      title: 'Price gaps are a few bps; costs are 7 to 47 bps',
      callouts: [
        { big: '0 trades', text: 'in 4 hours of live paper trading at €100k per leg' },
        { text: 'At €100k the gap was negative 99.6% (BTC) and 99.9% (ETH) of the time.' },
        { text: 'The 14 moments that beat break-even lasted 3 s at most, and only while one venue’s prices froze.', tone: 'cost' },
      ],
      source: 'Live paper run, 14 Oct 2026, 11:04–15:04 UTC, 49,825 snapshots per coin. Gap after crossing both books, before fees. Fee tiers are assumptions.',
    },
    {
      id: 'backtest-trap',
      kicker: '03 · The backtest trap',
      title: 'The profitable backtest was three bugs',
      before: { label: 'Before fixes', value: '+€276', detail: '5 trades · 100% winners · no drawdown' },
      after: { label: 'After fixes', value: '−€1,548', detail: '7 trades · 0 winners · −€1,740 after funding cost' },
      bugs: [
        { head: 'Look-ahead', body: 'The entry rule read the bar it would be filled on, so it only took trades it already knew would win.' },
        { head: 'Wrong FX rate', body: 'The daily ECB rate sat 44 bps away from live EUR/USDT, which created gaps that did not exist.' },
        { head: 'Instant fills', body: 'Paper fills had no delay, so they could never lose. Now: 300 ms and full-depth prices.' },
      ],
      bottomLine: 'On a second week of data, 0 of 136 realistic settings made money.',
      source: 'BTC/EUR, 24 Sep–1 Oct 2026, €100k per leg, > $250M tier (docs/engine-integrity.md). Second week: 7–14 Oct 2026, 1-minute candles, all fee tiers.',
    },
    {
      id: 'eurc',
      kicker: '04 · Live test: EURC euro stablecoin',
      title: 'Stablecoin test: every pre-set criterion failed',
      criteria: [
        { criterion: 'Net profit after exit costs above zero', result: 'about −€29', verdict: 'FAIL' },
        { criterion: 'Market-making P&L at mid of at least zero', result: '−€2.48', verdict: 'FAIL' },
        { criterion: 'Median 60 s markout of at least −1 bp', result: '−34 bps', verdict: 'FAIL' },
        { criterion: 'Our fills below 20% of venue volume', result: '35%', verdict: 'FAIL' },
        { criterion: 'At least 3 sessions, including a weekend', result: '1 session, 2.6 h', verdict: 'NOT MET' },
      ],
      facts: [
        { big: '2 vs 20 bps', text: 'Kraken’s spread against its maker fee: never worth quoting' },
        { big: '≈6,500 EURC', text: 'Bitvavo’s median daily volume over the last 366 days' },
        { big: '−39 bps', text: 'best cross-venue trade at €10k, after fees' },
      ],
      footnote: 'The only positive result, a deep bid absorbing one seller sweep, is worth about €100–300 a year.',
      source: 'Session 22 Oct 2026, 19:48–22:25 UTC; Bitvavo, Kraken, Bitstamp; €40k per market-making instance. Criteria fixed in docs/eurc_live_test.md before the run.',
    },
    {
      id: 'decision',
      kicker: '05 · Decision and what remains',
      title: 'Not deployed. The measurements are the asset.',
      decision: 'Keep the €40k in the 2.5% deposit.',
      reason: 'The market is arbitraged to within a few bps. Paying spreads and fees cannot win; only earning them might.',
      reopenTitle: 'What would reopen it',
      reopen: [
        'BTC funding above about 7% a year, sustained',
        'Free, practical par redemption of EURC',
        'Bitvavo EURC volume above €100k a day',
      ],
      usesTitle: 'Where the data helps now',
      uses: [
        { head: 'Best execution', body: 'Live spread, depth, freshness and latency per venue (MiCA Art. 78).' },
        { head: 'Euro stablecoins', body: 'EURC traded below 0.9925 on 28 of 366 days on Bitvavo.' },
        { head: 'Model validation', body: 'A checklist of the errors that made losses look like profit.' },
        { head: 'Next test worth running', body: 'Passive quotes with a near-free internal hedge, at real institutional fees.' },
      ],
      source: 'Triggers from docs/eurc_live_test_results.md. MiCA Art. 78: best execution for crypto-asset service providers.',
    },
  ],
  feeWall: {
    // Order matters: rendered top to bottom.
    bars: [
      { key: 'btcMedian', label: 'BTC median gap, €100k', value: -2.3, kind: 'measured' },
      { key: 'ethMedian', label: 'ETH median gap, €100k', value: -4.1, kind: 'measured' },
      { key: 'btcBest',   label: 'Best 1% of moments, BTC €1k', value: 1.6, kind: 'measured' },
      { key: 'tier1b',    label: '> $1B tier', value: 7, kind: 'cost' },
      { key: 'tier250m',  label: '> $250M tier', value: 9, kind: 'cost' },
      { key: 'tier20m',   label: '> $20M tier (default)', value: 17, kind: 'cost' },
      { key: 'retail',    label: 'Retail fees', value: 47, kind: 'cost' },
    ],
    // Live run 14 Oct 2026: tradeable gap after crossing both books, before fees (bps).
    // median = typical moment; p99 = best 1% of moments; positiveShare = share of time the gap was above zero.
    bySize: {
      '€1k':   { btc: { median: -0.37, p99: 1.55, positiveShare: '27.9%' }, eth: { median: -0.52, p99: 1.57, positiveShare: '25.4%' } },
      '€10k':  { btc: { median: -0.58, p99: 1.35, positiveShare: '21.0%' }, eth: { median: -0.75, p99: 1.42, positiveShare: '18.4%' } },
      '€100k': { btc: { median: -2.26, p99: -0.24, positiveShare: '0.44%' }, eth: { median: -4.10, p99: -1.12, positiveShare: '0.09%' } },
      '€250k': { btc: { median: -4.99, p99: -2.44, positiveShare: '0.05%' }, eth: { median: -8.47, p99: -4.35, positiveShare: '0.02%' } },
    },
    bySizeCaption: 'Bigger orders eat deeper into the order book, so the gap shrinks. Even the best 1% of moments never reaches the cheapest fee tier.',
  },
};

export default findings;
```

**How the order-size control maps onto the bars:** before the presenter touches the control, render `feeWall.bars` exactly as listed, matching slide 3 of the deck (third bar +1.6 = BTC best 1% at €1k). The control starts with no segment selected and the caption "Try another order size". Once a size *S* is chosen, all three measured bars follow it:
- `btcMedian` = `bySize[S].btc.median`, labelled `BTC median gap, ${S}`
- `ethMedian` = `bySize[S].eth.median`, labelled `ETH median gap, ${S}`
- third bar = `bySize[S].btc.p99`, labelled `Best 1% of moments, BTC ${S}`

Show the values with one decimal. A "Reset" link returns to the deck view. Cost bars never change.

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
  views/findings/StepAnswer.jsx, StepSetup.jsx, StepFeeWall.jsx, StepBacktestTrap.jsx, StepEurc.jsx, StepDecision.jsx
  views/LiveView.jsx
  views/LabView.jsx
  components/TopBar.jsx, GlossaryDrawer.jsx, Term.jsx, StatCard.jsx, Details.jsx
  index.css              # tokens + base
  App.css                # layout + components (rewrite; delete terminal-only rules)
```

The current `theme.js` (MUI dark theme) is no longer needed once `ThemeProvider` and `CssBaseline` are removed from `App.js`. Delete the file and its import; leave the package installed.

### 9.5 Page metadata
In `public/index.html`, set `<title>EUR Crypto Arbitrage · Findings</title>` and the meta description "One year of testing cross-exchange EUR crypto arbitrage: after every cost, no tradeable edge."

### 9.6 Optional, outside `hft-frontend/`: the orphan Next.js frontend
`src/crypto_hft_tool/frontend/` holds five `.tsx` files from an earlier Next.js prototype, with no `package.json` and no references. Before deleting, confirm with `grep -rn "crypto_hft_tool/frontend" --include=*.py --include=*.js --include=*.json --include=*.toml --include=*.yaml --include=*.sh .` (excluding `node_modules`). Delete it only if that returns nothing apart from the folder itself, in its own commit titled "Remove unused Next.js prototype frontend".

---

## 10. Tests

Replace the CRA placeholder `App.test.js` (it looks for "learn react" and fails) with:

1. **Findings renders offline:** mock `axios` to reject every call; render `App` at `#/findings/1`; assert the headline "After every cost, there was no edge to trade." is present and that **axios was never called**.
2. **Step navigation:** pressing → three times from step 1 lands on step 4 (title "The profitable backtest was three bugs") and updates `location.hash` to `#/findings/4`.
3. **Order-size control:** on step 3, choosing €250k changes the BTC median bar label to `−5.0`.
4. **Formatting:** `formatBps(-2.26) === '−2.3 bps'`; `formatBps(1.55) === '+1.6 bps'`; `pctToBps(-0.0226) === -2.26` (within floating-point tolerance).
5. **Signal states:** every key in §4.2 maps to the exact sentence; an unknown key maps to "Watching".
6. **Live offline panel:** with `/api/v1/bsdex/status` rejected, `#/live` shows "The live feed isn't running."
7. **Lab payload unchanged:** clicking "Run test" with the default form posts a body with exactly these keys: `symbol, data_source, quote_path, latency_ms, spread_model, start_dt, end_dt, venue_a_taker, venue_b_taker, capital_eur, tier_label`.

---

## 11. Work order (one commit per phase)

1. **Structure, no visual change:** split files (§9.4), remove dead code (§9.2, §9.3), add the hash router with the three routes (Findings can be a placeholder). The app works exactly as before under Live and Lab.
2. **Design tokens and base styles** (§2). Live and Lab adopt the light theme.
3. **Findings view** (§3, §7), including keyboard navigation, the Present toggle and the order-size control.
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
- [ ] Every number on Findings matches `findings.js`; no other hard-coded numbers in view components.
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
- README rewrite (separate task).
