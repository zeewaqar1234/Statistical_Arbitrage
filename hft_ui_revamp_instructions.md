# HFT Tool UI/UX Revamp — Instructions for Gemini Agent

## Context
This is a React frontend (in /hft-frontend) for a Crypto Statistical Arbitrage system. It connects to a FastAPI backend. The tool identifies cross-exchange price inefficiencies between Binance and Kraken using z-score based mean reversion signals.

Current problems: dark theme looks amateurish, layout is cluttered, not presentable to finance professionals in interviews. Needs to look like a Bloomberg terminal alternative, not a hacker tool.

---

## TASK 1: Switch to Light Theme

### Global Theme Changes

1. Open `hft-frontend/src/` and find the main CSS file (likely `App.css` or `index.css` or a theme file).

2. Replace ALL dark background colors with light equivalents:
   - `#000000`, `#111`, `#1a1a2e`, `#0a0a0a` → `#FFFFFF` (main background)
   - `#1e1e2e`, `#2a2a3e`, `#16213e` → `#F8F9FA` (card/panel backgrounds)
   - `#0f3460` → `#E9ECEF` (secondary panels)

3. Replace ALL light text colors with dark equivalents:
   - `#FFFFFF`, `#fff`, `#e0e0e0` → `#212529` (primary text)
   - `#b0b0b0`, `#888`, `#aaa` → `#6C757D` (secondary text)
   - Any neon green (#00ff00, #39ff14) → `#198754` (muted professional green)
   - Any neon red (#ff0000, #ff4444) → `#DC3545` (standard red)

4. Set the meta theme-color in `public/index.html` to `#FFFFFF`.

5. If there's a ThemeProvider or theme object, update it globally. If using CSS variables, change them at `:root`.

### Color Palette to Use Throughout

```
--bg-primary: #FFFFFF;
--bg-secondary: #F8F9FA;
--bg-card: #FFFFFF;
--border: #DEE2E6;
--text-primary: #212529;
--text-secondary: #6C757D;
--accent-blue: #0D6EFD;
--accent-green: #198754;
--accent-red: #DC3545;
--accent-yellow: #FFC107;
--shadow: 0 1px 3px rgba(0,0,0,0.08);
```

---

## TASK 2: Rename the Tool

Change all references from "Crypto HFT Tool" or "High Frequency Trading" to:
**"Cross-Exchange Statistical Arbitrage System"**

This includes:
- `public/index.html` title tag
- Any header/navbar component text
- README.md title
- Any meta descriptions

Reason: "HFT" implies millisecond latency infrastructure which this isn't. "Statistical Arbitrage" is accurate and sounds more professional to finance people.

---

## TASK 3: Layout Restructure

The dashboard should have a clean layout with clear visual hierarchy. Reorganize into this structure:

### Top Bar (Fixed)
- Left: Tool name "Cross-Exchange Statistical Arbitrage System"
- Right: Connection status indicator (green dot = connected, red = disconnected) + current time

### Main Content — 3 Sections

#### Section 1: Market Overview (Top, full width)
A clean horizontal strip showing:
- BTC/USDT price on Binance (large font)
- BTC/USDT price on Kraken (large font)
- Spread (difference) in both absolute and percentage
- Z-Score value with color coding: green if within threshold, yellow if approaching, red if signal triggered

Style: White cards with subtle border (#DEE2E6), light shadow, 16px padding, rounded corners (8px).

#### Section 2: Charts (Middle, 2 columns)

Left column (60% width): Price chart
- Line chart showing Binance and Kraken prices over time
- Two lines: blue for Binance, orange for Kraken
- Clean grid lines in #F0F0F0
- White background
- Axis labels in #6C757D
- Use recharts or whatever charting library is already installed

Right column (40% width): Z-Score chart
- Line chart showing z-score over time
- Horizontal dashed lines at +2 and -2 (signal thresholds)
- Area fill: green when z-score is between thresholds, red when outside
- White background

#### Section 3: Activity & Controls (Bottom, 2 columns)

Left column: Signal Log / Trade History
- Clean table with alternating row colors (#FFFFFF and #F8F9FA)
- Columns: Timestamp, Signal Type (BUY/SELL), Exchange, Price, Z-Score
- BUY signals in green text, SELL in red
- Most recent at top
- Maximum 20 rows visible, scrollable

Right column: System Controls & Stats
- Connection controls (Start/Stop buttons)
- Trading pair selector
- Key statistics in a clean grid:
  - Total signals generated
  - Current position
  - Cumulative PnL
  - Sharpe ratio (if calculated)
  - Max drawdown (if calculated)

---

## TASK 4: Typography

Use a professional font stack. Add to the top of the main CSS:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px;
  line-height: 1.5;
  color: #212529;
  background: #F8F9FA;
}

h1, h2, h3 {
  font-weight: 600;
  color: #212529;
}
```

### Font Sizes
- Page title: 20px, font-weight 700
- Section headers: 16px, font-weight 600
- Card titles: 14px, font-weight 600
- Body text: 14px, font-weight 400
- Secondary/label text: 12px, font-weight 400, color #6C757D
- Large numbers (prices): 28px, font-weight 700, font-family: 'Inter'
- Z-score display: 24px, font-weight 700

---

## TASK 5: Chart Improvements

### If using Recharts:

Price Chart:
```jsx
<LineChart>
  <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
  <XAxis stroke="#6C757D" fontSize={11} />
  <YAxis stroke="#6C757D" fontSize={11} />
  <Tooltip 
    contentStyle={{ 
      background: '#FFFFFF', 
      border: '1px solid #DEE2E6',
      borderRadius: '6px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
    }} 
  />
  <Line type="monotone" dataKey="binance" stroke="#0D6EFD" dot={false} strokeWidth={2} />
  <Line type="monotone" dataKey="kraken" stroke="#FD7E14" dot={false} strokeWidth={2} />
  <Legend />
</LineChart>
```

Z-Score Chart:
```jsx
<AreaChart>
  <CartesianGrid strokeDasharray="3 3" stroke="#F0F0F0" />
  <XAxis stroke="#6C757D" fontSize={11} />
  <YAxis stroke="#6C757D" fontSize={11} domain={[-4, 4]} />
  <ReferenceLine y={2} stroke="#DC3545" strokeDasharray="5 5" label="Upper" />
  <ReferenceLine y={-2} stroke="#DC3545" strokeDasharray="5 5" label="Lower" />
  <ReferenceLine y={0} stroke="#6C757D" strokeDasharray="3 3" />
  <Area type="monotone" dataKey="zscore" stroke="#0D6EFD" fill="#0D6EFD" fillOpacity={0.1} />
  <Tooltip />
</AreaChart>
```

### If using a different charting library:
Apply the same color scheme and styling principles.

---

## TASK 6: Card Component Style

Every data panel should use this consistent card style:

```css
.card {
  background: #FFFFFF;
  border: 1px solid #DEE2E6;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  margin-bottom: 16px;
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  color: #6C757D;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.card-value {
  font-size: 28px;
  font-weight: 700;
  color: #212529;
}

.card-value.positive {
  color: #198754;
}

.card-value.negative {
  color: #DC3545;
}
```

---

## TASK 7: Remove / Clean Up

1. Remove any "HFT" branding or hacker-style elements (matrix effects, terminal fonts, blinking cursors)
2. Remove console.log statements
3. Remove the backend.log file from the repo (it's committed by accident)
4. Remove .DS_Store from the repo
5. If there are unused components or debug panels, remove them
6. Clean up any inline styles and move to CSS classes

---

## TASK 8: Add These Missing Features (If Not Present)

### 8a. Spread Percentage Display
In the Market Overview section, calculate and display:
```
Spread % = ((Binance Price - Kraken Price) / Kraken Price) * 100
```
Show with 4 decimal places. Color: green if positive, red if negative.

### 8b. Signal History Export
Add a small "Export CSV" button below the Signal Log table that downloads the trade signals as a CSV file.

### 8c. PnL Chart
If cumulative PnL data is available from the backend, add a small area chart showing PnL over time. Green fill when positive, red when negative. Place this in the bottom-right stats section.

### 8d. Loading States
Add skeleton loading placeholders for charts and data while WebSocket connection is establishing. Use light gray animated pulse:
```css
.skeleton {
  background: linear-gradient(90deg, #F0F0F0 25%, #E0E0E0 50%, #F0F0F0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

---

## TASK 9: Responsive Layout

Use CSS Grid for the main layout:

```css
.dashboard {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
  padding: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

.market-overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.charts-section {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
}

.bottom-section {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
}
```

---

## TASK 10: Final Polish

1. Add subtle hover effects on cards: `transition: box-shadow 0.2s; &:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }`
2. Ensure all numbers use tabular-nums for aligned digits: `font-variant-numeric: tabular-nums;`
3. Add a favicon — use a simple chart icon or the letter "S" (for Statistical Arbitrage)
4. Set page title to "Cross-Exchange Statistical Arbitrage System"
5. Ensure the app looks clean at 1920x1080, 1440x900, and 1366x768 resolutions

---

## Execution Order

Do these tasks in this exact order:
1. Task 2 (Rename) — quickest, sets the tone
2. Task 1 (Light theme) — biggest visual impact
3. Task 4 (Typography) — immediate readability improvement  
4. Task 6 (Card style) — consistent component look
5. Task 3 (Layout restructure) — major layout work
6. Task 5 (Charts) — visual polish
7. Task 7 (Cleanup) — remove junk
8. Task 8 (New features) — add value
9. Task 9 (Responsive) — ensure it works at all sizes
10. Task 10 (Final polish) — finishing touches

After each task, run `npm start` and verify the changes look correct before moving to the next task.
