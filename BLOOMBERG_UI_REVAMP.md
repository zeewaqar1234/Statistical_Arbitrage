# Frontend Revamp: Bloomberg Terminal UI

> **For:** Cursor + Sonnet 4.6
> **Scope:** Restyle + restructure the entire frontend (`hft-frontend/src/`) to match the Bloomberg Terminal aesthetic. This is a visual and layout overhaul, not a data/API change. All existing API calls, react-query hooks, state management, and data flow stay exactly as they are. You are re-skinning the car, not replacing the engine.

---

## 0. Study this before touching any code

### What makes Bloomberg look like Bloomberg (not just "dark mode")

Bloomberg Terminal is not a dark dashboard. It is a **dense, information-first, zero-decoration data surface** designed for professionals who stare at it 12 hours a day. Every pixel earns its place. The aesthetic comes from these specific principles:

1. **Information density over whitespace.** Bloomberg packs 10x more data per screen than a typical dashboard. Panels are tight. Padding is minimal. There is no "breathing room" — every gap is a wasted opportunity to show a number.

2. **Orange as the organizing color.** Section headers and labels are orange/amber (#FF8C00). Not decorative — functional. Orange stands out against the dark background without competing with green/red PnL coloring. It says "this is a label, look here to orient yourself."

3. **Green and red are ONLY for data direction.** Green = positive/up, Red = negative/down. Never used decoratively. Never used for buttons or backgrounds. Only for numbers and their immediate context.

4. **White is for primary data values.** The thing you're actually reading — prices, amounts, percentages — is bright white. Everything else (labels, borders, backgrounds) is dimmer.

5. **Monospace for numbers, sans-serif for labels.** Numbers are right-aligned and use a fixed-width font so columns of figures line up perfectly. Labels use a compact sans-serif.

6. **Zero decoration.** No shadows. No gradients. No rounded corners. No hover-lift animations. No glow effects. Borders are 1px solid, very subtle (dark gray on dark background). Panels are rectangles. That's it.

7. **Persistent context strip.** Bloomberg always shows the time (multiple timezones), connection status, and key reference rates at the top or bottom — visible on every screen, every tab.

8. **Blotter at the bottom.** Recent activity / trades are always visible in a dense table at the bottom of the screen, like a ticker tape. Not hidden behind a scroll.

### What to remove from the current design

- All `border-radius` (set to 0 everywhere)
- All `box-shadow` (set to none everywhere)
- All hover lift/glow effects on cards
- The white/light background
- The blue primary color (#0D6EFD) — replaced by orange
- Inter font for numbers — replaced by monospace
- Large padding (16px+) — reduced to 8px or less in most places
- Card hover transitions
- Rounded buttons
- The light gray (#F8F9FA) secondary background

---

## 1. Color system — replace ALL CSS variables

In `index.css`, replace the `:root` block entirely:

```css
:root {
  /* ── Bloomberg dark palette ────────────────────────────── */
  --bg-terminal:    #0A0E17;   /* Deepest background (body)         */
  --bg-panel:       #111620;   /* Panel / card background            */
  --bg-panel-alt:   #161C28;   /* Alternate panel (hover, active)    */
  --bg-input:       #0D1117;   /* Input field background             */
  --bg-row-alt:     #0E1219;   /* Table alternating row              */

  --border:         #1E2736;   /* Panel borders — subtle, not invisible */
  --border-focus:   #2A3A52;   /* Focused / active panel border      */

  --text-primary:   #E8EAED;   /* Main data values — near-white      */
  --text-secondary: #6B7B8D;   /* Labels, captions, secondary info   */
  --text-muted:     #3D4F63;   /* Very dim (timestamps, footnotes)   */

  --accent-orange:  #FF8C00;   /* Section headers, primary accent    */
  --accent-amber:   #FFB020;   /* Highlights, active tab underline   */
  --accent-green:   #00B060;   /* Positive PnL, up-tick, connected   */
  --accent-red:     #FF3B3B;   /* Negative PnL, down-tick, error     */
  --accent-yellow:  #FFD60A;   /* Warnings, gated signals            */
  --accent-blue:    #3B82F6;   /* Links, interactive elements (rare) */

  --shadow: none;  /* Bloomberg has NO shadows */

  /* ── Typography ────────────────────────────────────────── */
  --font-sans:  'IBM Plex Sans', 'SF Pro Text', -apple-system, sans-serif;
  --font-mono:  'IBM Plex Mono', 'JetBrains Mono', 'SF Mono', 'Consolas', monospace;
  --font-size-xs:   11px;
  --font-size-sm:   12px;
  --font-size-md:   13px;
  --font-size-lg:   15px;
  --font-size-xl:   18px;
  --font-size-xxl:  24px;
}
```

Add the font import at the very top of `index.css`, replacing the Inter import:

```css
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
```

Update the `body` rule:

```css
body {
  margin: 0;
  font-family: var(--font-sans);
  font-size: var(--font-size-md);
  line-height: 1.4;
  color: var(--text-primary);
  background: var(--bg-terminal);
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
```

---

## 2. Theme file — dark MUI override

Replace `theme.js` entirely:

```js
import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary:    { main: '#FF8C00' },
    secondary:  { main: '#FFB020' },
    background: { default: '#0A0E17', paper: '#111620' },
    text:       { primary: '#E8EAED', secondary: '#6B7B8D' },
    success:    { main: '#00B060' },
    error:      { main: '#FF3B3B' },
    warning:    { main: '#FFD60A' },
    divider:    '#1E2736',
  },
  typography: {
    fontFamily: "'IBM Plex Sans', -apple-system, sans-serif",
    fontSize: 13,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: { body: { background: '#0A0E17' } },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 0,
          border: '1px solid #1E2736',
          boxShadow: 'none',
          background: '#111620',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'uppercase',
          fontWeight: 600,
          borderRadius: 0,
          letterSpacing: '0.5px',
          fontSize: 11,
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { background: '#161C28', border: '1px solid #1E2736', borderRadius: 0 },
      },
    },
  },
});

export default theme;
```

---

## 3. Global utility classes — add to App.css

Add these at the top of `App.css` (before any component styles). They provide the Bloomberg building blocks every component uses:

```css
/* ── Bloomberg utility classes ─────────────────────────────────── */

/* Monospace numbers — apply to ANY element showing a numeric value */
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

/* PnL coloring */
.pnl-pos { color: var(--accent-green); }
.pnl-neg { color: var(--accent-red); }
.pnl-zero { color: var(--text-secondary); }

/* Section header — orange, uppercase, small, with a bottom border */
.section-header {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--accent-orange);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Panel — the basic Bloomberg container */
.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 0;
  box-shadow: none;
  padding: 8px 10px;
}
.panel:hover { box-shadow: none; } /* kill any inherited hover */

/* Stat cell — a single labeled number */
.stat-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.stat-cell .stat-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}
.stat-cell .stat-value {
  font-family: var(--font-mono);
  font-size: var(--font-size-lg);
  color: var(--text-primary);
  font-weight: 600;
}

/* Dense table */
.dense-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}
.dense-table th {
  font-size: var(--font-size-xs);
  color: var(--accent-orange);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 600;
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.dense-table td {
  padding: 3px 8px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  border-bottom: 1px solid var(--bg-panel-alt);
  white-space: nowrap;
}
.dense-table tr:nth-child(even) td {
  background: var(--bg-row-alt);
}
.dense-table td.text { font-family: var(--font-sans); }
.dense-table td.right { text-align: right; }

/* Tag / badge */
.tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  border: 1px solid;
}
.tag-green  { color: var(--accent-green); border-color: var(--accent-green); }
.tag-red    { color: var(--accent-red);   border-color: var(--accent-red);   }
.tag-yellow { color: var(--accent-yellow); border-color: var(--accent-yellow); }
.tag-orange { color: var(--accent-orange); border-color: var(--accent-orange); }
.tag-muted  { color: var(--text-secondary); border-color: var(--border); }

/* Input fields — Bloomberg style */
.bb-input {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  padding: 4px 8px;
  outline: none;
}
.bb-input:focus { border-color: var(--accent-orange); }

.bb-select {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  padding: 4px 8px;
  outline: none;
  cursor: pointer;
}
.bb-select:focus { border-color: var(--accent-orange); }

/* Primary action button */
.bb-btn {
  background: var(--accent-orange);
  color: #000;
  border: none;
  border-radius: 0;
  padding: 6px 16px;
  font-family: var(--font-sans);
  font-size: var(--font-size-xs);
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: pointer;
}
.bb-btn:hover { background: var(--accent-amber); }
.bb-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Blink animation for live connection dot */
@keyframes blink-live {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.live-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent-green);
  display: inline-block;
  animation: blink-live 2s ease-in-out infinite;
}
.live-dot.disconnected {
  background: var(--accent-red);
  animation: none;
}
```

---

## 4. Layout restructure — the Bloomberg grid

The current layout is single-column cards stacked vertically. Bloomberg uses a **dense multi-panel grid** where multiple data zones are visible simultaneously without scrolling.

### New overall page structure:

```
+======================================================================+
|  TOP BAR: logo | tabs | clocks (Frankfurt London New York) | status  |
+======================================================================+
|            |                              |                           |
|  LEFT      |  CENTER                      |  RIGHT                   |
|  PANEL     |  PANEL                       |  PANEL                   |
|  ~220px    |  flex-grow                   |  ~280px                  |
|            |                              |                           |
|  Venue A   |  Spread chart                |  Session stats           |
|  Venue B   |  (with threshold bands)      |  Signal engine           |
|  Spread    |                              |  Fee config              |
|  Z-score   |                              |                          |
|  Phase     |                              |                          |
|            |                              |                          |
+------------+------------------------------+--------------------------+
|  BOTTOM BLOTTER: Recent trades table (always visible)                |
+----------------------------------------------------------------------+
|  STATUS BAR: Data source | FX source | FX age | Disclaimers          |
+======================================================================+
```

### CSS for this layout:

Replace the `.dashboard` rule in `App.css` with:

```css
.dashboard {
  display: grid;
  grid-template-columns: 220px 1fr 280px;
  grid-template-rows: auto 1fr auto auto;
  grid-template-areas:
    "topbar   topbar   topbar"
    "left     center   right"
    "blotter  blotter  blotter"
    "status   status   status";
  height: 100vh;
  overflow: hidden;
  gap: 0;  /* Bloomberg has zero gap — borders provide separation */
}

.top-bar       { grid-area: topbar; }
.left-panel    { grid-area: left; overflow-y: auto; border-right: 1px solid var(--border); }
.center-panel  { grid-area: center; overflow-y: auto; }
.right-panel   { grid-area: right; overflow-y: auto; border-left: 1px solid var(--border); }
.blotter       { grid-area: blotter; border-top: 1px solid var(--border); max-height: 220px; overflow-y: auto; }
.status-bar    { grid-area: status; }
```

---

## 5. Top bar — multi-clock + tabs

Replace the current header. Key changes: compact height (36px), multi-timezone clocks, tab underline style (not pill/button style), orange active indicator.

### JSX structure:

```jsx
<header className="top-bar">
  <span className="top-bar-logo">STAT ARB</span>
  <div className="top-bar-sep" />
  <div className="tab-nav">
    {/* Each tab: text with orange underline when active */}
    <button className={`tab-link ${activeTab === 'bsdex' ? 'active' : ''}`} onClick={...}>
      BSDEX vs WORLD
    </button>
    <button className={`tab-link ${activeTab === 'backtest' ? 'active' : ''}`} onClick={...}>
      BACKTEST
    </button>
  </div>
  <div className="top-bar-spacer" />
  <div className="top-bar-clocks">
    <Clock label="FRA" offset={2} />
    <Clock label="LDN" offset={1} />
    <Clock label="NYC" offset={-4} />
  </div>
  <div className="top-bar-sep" />
  <span className={`live-dot ${isConnected ? '' : 'disconnected'}`} />
  <span className="top-bar-status mono">{isConnected ? 'LIVE' : 'DISC'}</span>
</header>
```

### Clock component (add in App.js):

```jsx
function Clock({ label, offset }) {
  const [t, setT] = useState('');
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const utc = d.getTime() + d.getTimezoneOffset() * 60000;
      const local = new Date(utc + offset * 3600000);
      setT(local.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [offset]);
  return (
    <div className="clock-cell">
      <span className="clock-label">{label}</span>
      <span className="clock-time mono">{t}</span>
    </div>
  );
}
```

### CSS for top bar:

```css
.top-bar {
  grid-area: topbar;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
  height: 36px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}

.top-bar-logo {
  font-family: var(--font-mono);
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--accent-orange);
  letter-spacing: 2px;
}

.top-bar-sep {
  width: 1px;
  height: 20px;
  background: var(--border);
}

.top-bar-spacer { flex: 1; }

.tab-nav { display: flex; gap: 0; }

.tab-link {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 8px 14px;
  font-family: var(--font-sans);
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 0.15s;
}
.tab-link:hover { color: var(--text-primary); }
.tab-link.active {
  color: var(--accent-orange);
  border-bottom-color: var(--accent-orange);
}

.top-bar-clocks { display: flex; gap: 14px; }

.clock-cell { display: flex; flex-direction: column; align-items: center; line-height: 1.1; }
.clock-label { font-size: 9px; color: var(--text-muted); letter-spacing: 1px; text-transform: uppercase; }
.clock-time { font-size: var(--font-size-sm); color: var(--text-secondary); }

.top-bar-status {
  font-size: var(--font-size-xs);
  letter-spacing: 1px;
}
```

---

## 6. Left panel — live market snapshot

This replaces the scattered price cards. Dense, always-visible, one glance tells you everything about both venues.

### Content:

```
VENUE A — BITSTAMP EUR          ← orange section header
  BID    57,234.12              ← mono, large, white
  ASK    57,240.88
  MID    57,237.50

VENUE B — WORLD (LMAX FEE)     ← orange section header
  BID    57,228.40
  ASK    57,233.16
  MID    57,230.78

SPREAD                          ← orange section header
  EUR      +5.72
  PCT      +0.0100%
  B/E      0.060%               ← break-even line, dimmer

SIGNAL                          ← orange section header
  Z-SCORE     1.423
  THRESHOLD   0.400
  STATE       SIGNAL            ← green tag, or HOLD (gray), GATED (yellow)

PHASE                           ← orange section header
  STATUS    CONTINUOUS          ← green tag
  FX RATE   0.86103             ← mono
  FX AGE    12s
```

Each section is a `.panel` with a `.section-header`. Numbers use `.mono`. PnL-colored where appropriate.

---

## 7. Center panel — the spread chart

This is the hero visual. Dark background, clean grid, orange threshold band.

### Recharts theming:

All Recharts components (`LineChart`, `ComposedChart`, `AreaChart`) should use these overrides:

```jsx
// Chart wrapper: set background to transparent (panel provides the bg)
// Grid lines: subtle dark gray
<CartesianGrid stroke="#1E2736" strokeDasharray="3 3" />

// Axes
<XAxis
  dataKey="time"
  tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
  axisLine={{ stroke: '#1E2736' }}
  tickLine={{ stroke: '#1E2736' }}
/>
<YAxis
  tick={{ fill: '#6B7B8D', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
  axisLine={{ stroke: '#1E2736' }}
  tickLine={{ stroke: '#1E2736' }}
/>

// Spread line: bright cyan or white
<Line dataKey="spreadPct" stroke="#4FC3F7" strokeWidth={1.5} dot={false} />

// Threshold reference lines: orange dashed
<ReferenceLine y={breakeven} stroke="#FF8C00" strokeDasharray="4 4" label={{ value: 'B/E', fill: '#FF8C00', fontSize: 10 }} />
<ReferenceLine y={-breakeven} stroke="#FF8C00" strokeDasharray="4 4" />

// Zero line
<ReferenceLine y={0} stroke="#3D4F63" strokeWidth={0.5} />

// Tooltip: dark panel style
const tooltipStyle = {
  backgroundColor: '#161C28',
  border: '1px solid #1E2736',
  borderRadius: 0,
  padding: '6px 10px',
  fontSize: 11,
  fontFamily: 'IBM Plex Mono',
};
```

### Chart section header above the chart:

```
CROSS-EXCHANGE SPREAD — BTC-EUR        [Market selector dropdown]
```

Orange header, dropdown in `.bb-select` style.

---

## 8. Right panel — session stats + fee config

### Session stats:

Use a vertical stack of `.stat-cell` items inside a `.panel`:

```
SESSION STATS                    ← orange section header
  TOTAL TRADES      5
  WIN RATE          100.0%
  CUM. PNL (EUR)    +0.3955      ← green
  TOTAL FEES (EUR)  3.0010       ← red
  SIGNAL STATE      GATED        ← yellow tag
```

### Fee configuration:

Below the stats. Use `.bb-input`, `.bb-select`, `.bb-btn` classes. Keep it compact — no large padding, no card shadows.

```
FEE CONFIGURATION               ← orange section header
  MODE:  [Volume tier (auto) ▾]
  TIER:  [> $1B — 0.03% / 0.03% ▾]
  A TAKER:  [0.030] %
  B TAKER:  [0.030] %
  B/E SPREAD: 0.060%            ← highlighted in orange border box
  CAPITAL:  [100000] EUR
  [APPLY]                        ← bb-btn
```

---

## 9. Bottom blotter — trade table

The recent-trades table should always be visible at the bottom of the screen (like a Bloomberg blotter). Use the `.dense-table` class. Columns:

```
TIME        MARKET    ROUTE                 AMOUNT       GROSS(EUR)   FEES(EUR)    NET(EUR)     TIER
19:53:07    ETH-EUR   world_lmax→bitstamp   62.29249     65.4457      60.0196      +5.4261      >$1B
```

- TIME: `var(--text-muted)`, mono
- MARKET: `var(--text-primary)`, sans
- ROUTE: `var(--text-secondary)`, sans
- AMOUNT: mono, right-aligned
- GROSS: green, mono, right-aligned
- FEES: red, mono, right-aligned
- NET: green/red by sign, mono, right-aligned, **bold**
- TIER: `var(--text-muted)`

---

## 10. Status bar — persistent footer

A thin bar (24px) at the very bottom of the viewport. Always visible. Contains data provenance and disclaimers.

```css
.status-bar {
  grid-area: status;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 12px;
  height: 24px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  font-size: 10px;
  color: var(--text-muted);
  overflow: hidden;
  white-space: nowrap;
}
.status-bar .status-sep {
  color: var(--border);
}
```

### Content:

```
Venue A: Bitstamp EUR (BSDEX proxy) | Venue B: Binance USDT→EUR (LMAX fee model) | FX: ECB/Frankfurter (60s) | All trades simulated | STAT ARB v1.0
```

---

## 11. Backtest tab — same aesthetic, different content

When `activeTab === 'backtest'`, the grid changes. The left/right panels collapse and the center takes full width. The backtest form and results render in the Bloomberg panel style.

```css
/* When backtest tab is active, override the grid */
.dashboard.tab-backtest {
  grid-template-columns: 1fr;
  grid-template-areas:
    "topbar"
    "center"
    "status";
}
```

Backtest form uses `.bb-input`, `.bb-select`, `.bb-btn`. Results metrics use `.stat-cell` in a horizontal flex row. Equity curve chart uses the same Recharts dark theme. Trade log uses `.dense-table`.

---

## 12. Specific components to restyle

### Metric cards (the current card grid showing Total Trades, Win Rate, PnL, etc.)

Kill the card wrapper. Replace with a horizontal row of `.stat-cell` items inside a `.panel`:

```jsx
<div className="panel" style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
  <div className="stat-cell">
    <span className="stat-label">Total Trades</span>
    <span className="stat-value mono">37</span>
  </div>
  <div className="stat-cell">
    <span className="stat-label">Win Rate</span>
    <span className="stat-value mono pnl-pos">100.0%</span>
  </div>
  {/* ... */}
</div>
```

### Signal state badge

Replace the current text-based signal display with a `.tag`:

```jsx
<span className={`tag ${
  state === 'SIGNAL'   ? 'tag-green' :
  state === 'GATED'    ? 'tag-yellow' :
  state === 'COOLDOWN' ? 'tag-orange' :
  'tag-muted'
}`}>{state}</span>
```

### Break-even spread indicator

Currently a yellow box. Replace with a subtle bordered line:

```jsx
<div style={{
  border: '1px solid var(--accent-orange)',
  padding: '3px 8px',
  display: 'inline-block',
  fontSize: 'var(--font-size-sm)',
  color: 'var(--accent-orange)',
  fontFamily: 'var(--font-mono)',
}}>
  B/E: {breakeven}%
</div>
```

### Dropdown / select elements

Replace all `<select>` with class `bb-select`. Replace all `<input type="number">` and `<input type="text">` with class `bb-input`. Remove any MUI Select/TextField if used.

### Buttons

Replace the current blue "Apply to Strategy" / "Run Backtest" buttons with `bb-btn`. The orange-on-black Bloomberg action button.

---

## 13. Chart tooltip — dark, compact

All custom tooltip components (`PnlTooltip`, `SpreadTooltip`, `BsdexSpreadTooltip`) should use:

```jsx
const tooltipWrapperStyle = {
  background: '#161C28',
  border: '1px solid #1E2736',
  borderRadius: 0,
  padding: '6px 10px',
  boxShadow: 'none',
};

const tooltipLabelStyle = {
  color: '#6B7B8D',
  fontSize: 10,
  fontFamily: "'IBM Plex Mono', monospace",
  marginBottom: 2,
};

const tooltipValueStyle = {
  color: '#E8EAED',
  fontSize: 12,
  fontFamily: "'IBM Plex Mono', monospace",
  fontWeight: 600,
};
```

---

## 14. Checklist before committing

- [ ] Body background is `#0A0E17`, not white
- [ ] Zero `border-radius` on any card, panel, button, or input
- [ ] Zero `box-shadow` anywhere
- [ ] All numbers use `var(--font-mono)` / `IBM Plex Mono`
- [ ] All section headers are orange, uppercase, letter-spaced
- [ ] Green/red used ONLY for positive/negative values, nowhere else
- [ ] Multi-timezone clocks visible in top bar
- [ ] Status bar visible at bottom with data-source disclaimers
- [ ] Trade blotter visible at bottom without scrolling to it
- [ ] Charts have dark background, subtle grid, orange threshold lines
- [ ] No Inter font anywhere
- [ ] No blue primary color anywhere
- [ ] Tab active state uses orange underline, not pill/button background
- [ ] All inputs/selects use dark background with subtle border
- [ ] The layout fills the viewport (100vh) without excessive scrolling

---

## 15. Do NOT

- Do not change any API calls, react-query hooks, state variables, or data flow
- Do not rename state variables or API response field names
- Do not remove any functionality — every number and control that exists today must still be present
- Do not add any new API calls or backend changes
- Do not use MUI's styled-components for the new panels — use plain CSS classes (faster, simpler, more Bloomberg-authentic)
- Do not add rounded corners to anything, even "just a little"
- Do not use gradients or background images
- Do not make the layout responsive/mobile — Bloomberg is desktop-only and so is this tool
