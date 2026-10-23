// Six-slide briefing, condensed from reports/tool_briefing/output/Crypto_Arbitrage_Senior_Briefing.pptx
// (11 slides, 12 Oct 2026) and updated with the 14 Oct live run and the 22 Oct EURC test.
// Figures: docs/BSDEX_Explainer_Guide.html, docs/engine-integrity.md, docs/eurc_live_test_results.md.
// Usage: NODE_PATH=<dir with pptxgenjs> node build_deck.js <out.pptx> <apply_theme.js>
const pptxgen = require('pptxgenjs');
const out = process.argv[2];
const { applyTheme } = require(process.argv[3]);

const HEX = {
  ink: '18313B', teal: '173C4A', muted: '53656D', pale: 'EDF3F4', line: 'D6DFE2',
  red: 'A33639', green: '347A78', white: 'FFFFFF', tealSoft: '24525F', paleText: 'C9D8DC',
};
const THEME = {
  name: 'EUR Crypto Arbitrage Briefing',
  headFontFace: 'Arial',
  bodyFontFace: 'Arial',
  colors: {
    dk1: HEX.ink, lt1: HEX.white, dk2: HEX.teal, lt2: HEX.pale,
    accent1: HEX.green, accent2: HEX.red, accent3: HEX.muted, accent4: HEX.line,
    accent5: HEX.tealSoft, accent6: HEX.paleText, hlink: HEX.green, folHlink: HEX.muted,
  },
};

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5 in, same as the original deck
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = 'EUR crypto arbitrage: one year of testing';
pres.author = 'Syed Zee Waqar Hussain';
const C = pres.SchemeColor;

const X = 0.67, W = 12.0;

// ── Layouts ────────────────────────────────────────────────────────────────
pres.defineSlideMaster({
  title: 'CONTENT',
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: 'kicker', type: 'body', x: X, y: 0.36, w: W, h: 0.3,
        fontSize: 14, bold: true, color: C.accent3, margin: 0, valign: 'top' }, text: '' } },
    { placeholder: { options: { name: 'title', type: 'title', x: X, y: 0.72, w: W, h: 0.8,
        fontSize: 34, bold: true, align: 'left', color: C.text2, margin: 0, valign: 'top' }, text: '' } },
    { placeholder: { options: { name: 'source', type: 'body', x: X, y: 6.88, w: 10.9, h: 0.36,
        fontSize: 11, color: C.accent3, margin: 0, valign: 'top' }, text: '' } },
  ],
  slideNumber: { x: 12.17, y: 6.86, w: 0.5, h: 0.3, fontSize: 12, color: C.accent3, align: 'right' },
});
pres.defineSlideMaster({
  title: 'DARK',
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: 'kicker', type: 'body', x: X, y: 0.36, w: W, h: 0.3,
        fontSize: 14, bold: true, color: C.accent6, margin: 0, valign: 'top' }, text: '' } },
    { placeholder: { options: { name: 'title', type: 'title', x: X, y: 0.72, w: W, h: 0.8,
        fontSize: 34, bold: true, align: 'left', color: C.background1, margin: 0, valign: 'top' }, text: '' } },
    { placeholder: { options: { name: 'source', type: 'body', x: X, y: 6.88, w: 10.9, h: 0.36,
        fontSize: 11, color: C.accent6, margin: 0, valign: 'top' }, text: '' } },
  ],
  slideNumber: { x: 12.17, y: 6.86, w: 0.5, h: 0.3, fontSize: 12, color: C.accent6, align: 'right' },
});

function frame(master, section, kicker, title, source, notes) {
  pres.addSection({ title: section });
  const s = pres.addSlide({ masterName: master, sectionTitle: section });
  s.addText(kicker, { placeholder: 'kicker' });
  s.addText(title, { placeholder: 'title' });
  s.addText(source, { placeholder: 'source' });
  s.addNotes(notes);
  return s;
}
function txt(s, text, o) {
  s.addText(text, { isTextBox: true, margin: 0, valign: 'top', fontSize: 16, color: C.text1, ...o });
}
function card(s, x, y, w, h, fill, name) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: name });
}

// ── 1 · Answer first ───────────────────────────────────────────────────────
{
  const s = frame('DARK', 'Answer',
    'RESEARCH BRIEFING  ·  OCTOBER 2026',
    'EUR crypto arbitrage: one year of testing',
    'Syed Zee Waqar Hussain  ·  Paper trading only  ·  Public market data  ·  No orders sent',
    'One-sentence answer: after every real cost there was no edge to trade, so I stopped before any capital was at risk. ' +
    'Then give the three numbers. Live run: 14 Oct 2026, 4 hours, EUR 100k per leg, default >$20M fee tier. ' +
    'Median gap after crossing both books: BTC -2.26 bps, ETH -4.10 bps; break-even 17 bps. ' +
    'Backtest sweep: 7-14 Oct 2026, 136 realistic settings, none profitable. Source: docs/BSDEX_Explainer_Guide.html.');
  txt(s, 'After every cost, there was no edge to trade.', { x: X, y: 1.95, w: W, h: 0.7, fontSize: 30, bold: true, color: C.background1 });
  txt(s, 'What remains useful is the data on what EUR crypto execution really costs.', { x: X, y: 2.75, w: W, h: 0.45, fontSize: 18, color: C.accent6 });
  const stats = [
    ['0', 'trades in a 4-hour live paper run at €100k per leg'],
    ['−2.3 bps', 'median BTC price gap, against 17\u00A0bps needed to break even'],
    ['0 of 136', 'realistic backtest settings that made money'],
  ];
  const cw = 3.8, gap = 0.3;
  stats.forEach(([big, label], i) => {
    const x = X + i * (cw + gap);
    card(s, x, 3.95, cw, 2.35, C.accent5, `stat-${i + 1}`);
    txt(s, big, { x: x + 0.3, y: 4.2, w: cw - 0.6, h: 0.9, fontSize: 40, bold: true, color: C.background1, objectName: `stat-${i + 1}-value` });
    txt(s, label, { x: x + 0.3, y: 5.2, w: cw - 0.6, h: 0.9, fontSize: 15, color: C.accent6, objectName: `stat-${i + 1}-label` });
  });
}

// ── 2 · Question and set-up ────────────────────────────────────────────────
{
  const s = frame('CONTENT', 'Set-up',
    '01  ·  THE QUESTION AND THE SET-UP',
    'Do price gaps between exchanges survive costs?',
    'Sources: bsdex_strategy.py; bsdex_historical_bt.py; scripts/eurc_live_test.py. Bitstamp stands in for BSDEX (its API needs keys); LMAX fees are modelled.',
    'The idea is simple: buy where the coin is cheap, sell where it is dear, at the same moment. ' +
    'The engine prices the gap for the full order size, trades only if the gap beats both taker fees plus 1 bp FX cost, ' +
    'and fills both legs 300 ms later with losses booked. Markets: BTC and ETH on Bitstamp EUR vs Binance USDT converted at live EUR/USDT; ' +
    'Bitstamp vs Kraken as a no-FX control; EURC on Bitvavo, Kraken and Bitstamp.');
  const steps = [
    ['1', 'Watch', 'BTC and ETH: Bitstamp (EUR) vs Binance (USDT, in EUR). EURC: Bitvavo, Kraken, Bitstamp.'],
    ['2', 'Price', 'Measure the gap for the full order size, after crossing both order books.'],
    ['3', 'Gate', 'Trade only if the gap beats both exchange fees plus a 1 bp FX cost.'],
    ['4', 'Fill', 'Fill both legs 300 ms later. Book losses; count failed fills.'],
  ];
  const cw = 2.76, gap = 0.32, y = 1.9, h = 2.75;
  steps.forEach(([n, head, body], i) => {
    const x = X + i * (cw + gap);
    card(s, x, y, cw, h, C.background2, `step-${n}`);
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.55, h: 0.55, fill: { color: C.text2 }, line: { color: C.text2, width: 0 }, objectName: `step-${n}-badge` });
    s.addText(n, { isTextBox: true, x: x + 0.25, y: y + 0.25, w: 0.55, h: 0.55, margin: 0, align: 'center', valign: 'middle', fontSize: 18, bold: true, color: C.background1 });
    txt(s, head, { x: x + 0.25, y: y + 1.0, w: cw - 0.5, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
    txt(s, body, { x: x + 0.25, y: y + 1.5, w: cw - 0.5, h: 1.15, fontSize: 14 });
    if (i < steps.length - 1) {
      s.addText('›', { isTextBox: true, x: x + cw, y: y + h / 2 - 0.3, w: gap, h: 0.6, margin: 0, align: 'center', valign: 'middle', fontSize: 28, bold: true, color: C.accent3 });
    }
  });
  txt(s, 'Three kinds of test', { x: X, y: 5.0, w: W, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
  const tests = [
    ['Backtests', 'One-minute candles, every fee tier, 136 parameter settings'],
    ['Replays', 'Recorded order books, fills at 300 / 1,000 / 2,000 ms'],
    ['Live paper runs', 'BTC/ETH on 14 Oct (4 h) and EURC on 22 Oct (2.6 h), pass/fail rules set in advance'],
  ];
  const tw = [3.6, 3.6, 4.2];
  let tx = X;
  tests.forEach(([head, body], i) => {
    s.addText([
      { text: head, options: { bold: true, color: C.text2, breakLine: true } },
      { text: body, options: { color: C.text1 } },
    ], { isTextBox: true, x: tx, y: 5.45, w: tw[i] - 0.3, h: 1.1, margin: 0, valign: 'top', fontSize: 14 });
    tx += tw[i];
  });
}

// ── 3 · Fee wall ───────────────────────────────────────────────────────────
{
  const s = frame('CONTENT', 'Fee wall',
    '02  ·  THE FEE WALL',
    'Price gaps are a few bps; costs are 7 to 47 bps',
    'Live paper run, 14 Oct 2026, 11:04–15:04 UTC, 49,825 snapshots per coin. Gap after crossing both books, before fees. Fee tiers are assumptions.',
    'Read the chart from the top. The teal bars are what the market offered: at EUR 100k the median gap was negative, ' +
    'meaning that crossing both order books already loses money before any fee. Even the best 1% of moments for a EUR 1k order was only +1.6 bps. ' +
    'The red bars are what a trade must clear: 47 bps at retail fees, 17 bps at the default >$20M tier, 9 bps above $250M and 7 bps at an aspirational >$1B tier. ' +
    'Only 14 moments in 4 hours beat break-even (6 BTC, 8 ETH); the longest lasted 2.8 s, and they happened only while one venue\'s prices froze during a fast move. ' +
    'Source: docs/BSDEX_Explainer_Guide.html sections 06 and 08.');
  const labels = ['Retail fees', '>$20M tier (default)', '>$250M tier', '>$1B tier', 'Best 1% of moments, BTC €1k', 'ETH median gap, €100k', 'BTC median gap, €100k'];
  const values = [47, 17, 9, 7, 1.6, -4.1, -2.3];
  const colors = [HEX.red, HEX.red, HEX.red, HEX.red, HEX.green, HEX.green, HEX.green];
  s.addChart(pres.charts.BAR, [{ name: 'bps', labels, values }], {
    x: X, y: 1.75, w: 7.6, h: 4.85, barDir: 'bar', chartColors: colors,
    showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '+0.0;-0.0;0', dataLabelFontSize: 13,
    dataLabelColor: HEX.ink, dataLabelFontFace: '+mn-lt',
    catAxisLabelColor: HEX.ink, catAxisLabelFontSize: 13, catAxisLabelFontFace: '+mn-lt', catAxisLineShow: false, catAxisLabelPos: 'low',
    valAxisHidden: true, valGridLine: { style: 'none' }, catGridLine: { style: 'none' },
    valAxisMinVal: -10, valAxisMaxVal: 52, showLegend: false, barGapWidthPct: 45,
    showTitle: true, title: 'Basis points (1 bp = 0.01%)', titleFontSize: 13, titleColor: HEX.muted, titleFontFace: '+mn-lt',
    objectName: 'fee-wall-chart',
  });
  const rx = 8.75, rw = 3.92;
  card(s, rx, 1.85, rw, 4.65, C.background2, 'fee-wall-callouts');
  txt(s, '0 trades', { x: rx + 0.3, y: 2.1, w: rw - 0.6, h: 0.75, fontSize: 36, bold: true, color: C.text2 });
  txt(s, 'in 4 hours of live paper trading at €100k per leg', { x: rx + 0.3, y: 2.85, w: rw - 0.6, h: 0.65, fontSize: 14 });
  txt(s, 'At €100k the gap was negative 99.6% (BTC) and 99.9% (ETH) of the time.', { x: rx + 0.3, y: 3.75, w: rw - 0.6, h: 1.0, fontSize: 15 });
  txt(s, 'The 14 moments that beat break-even lasted 3 s at most, and only while one venue’s prices froze.', { x: rx + 0.3, y: 4.95, w: rw - 0.6, h: 1.3, fontSize: 15, bold: true, color: C.accent2 });
}

// ── 4 · Backtest trap ──────────────────────────────────────────────────────
{
  const s = frame('CONTENT', 'Backtest trap',
    '03  ·  THE BACKTEST TRAP',
    'The profitable backtest was three bugs',
    'BTC/EUR, 24 Sep–1 Oct 2026, €100k per leg, >$250M tier (docs/engine-integrity.md). Second week: 7–14 Oct 2026, 1-minute candles, all fee tiers.',
    'Before the fixes the backtest looked perfect: 5 trades, every one a winner, +EUR 275.81 and no drawdown. That is the warning sign. ' +
    'Three errors produced it. Look-ahead: the entry rule read the bar it would be filled on, so it only took trades it already knew would win. ' +
    'Wrong FX: the live engine used the once-a-day ECB rate; on 14 Oct EUR/USDT and ECB EUR/USD were 44 bps apart, which creates gaps that do not exist. ' +
    'Instant fills: paper fills had zero delay, so they could never lose; now 300 ms and full-depth VWAP. ' +
    'After the fixes, the same period gives 7 trades, 0 winners, -EUR 1,547.98 after fees and FX, -EUR 1,739.76 after EUR 191.78 carry. ' +
    'On a second week (7-14 Oct), 0 of 136 realistic settings made money.');
  const y = 1.8, h = 1.95, cw = 5.55;
  card(s, X, y, cw, h, C.background2, 'before-card');
  txt(s, 'BEFORE FIXES', { x: X + 0.35, y: y + 0.25, w: cw - 0.7, h: 0.3, fontSize: 14, bold: true, color: C.accent3 });
  txt(s, '+€276', { x: X + 0.35, y: y + 0.6, w: cw - 0.7, h: 0.8, fontSize: 44, bold: true, color: C.accent1 });
  txt(s, '5 trades  ·  100% winners  ·  no drawdown', { x: X + 0.35, y: y + 1.45, w: cw - 0.7, h: 0.35, fontSize: 15 });
  s.addText('→', { isTextBox: true, x: X + cw, y: y + h / 2 - 0.35, w: 0.9, h: 0.7, margin: 0, align: 'center', valign: 'middle', fontSize: 32, bold: true, color: C.accent3 });
  const ax = X + cw + 0.9;
  card(s, ax, y, cw, h, C.background2, 'after-card');
  txt(s, 'AFTER FIXES', { x: ax + 0.35, y: y + 0.25, w: cw - 0.7, h: 0.3, fontSize: 14, bold: true, color: C.accent3 });
  txt(s, '−€1,548', { x: ax + 0.35, y: y + 0.6, w: cw - 0.7, h: 0.8, fontSize: 44, bold: true, color: C.accent2 });
  txt(s, '7 trades  ·  0 winners  ·  −€1,740 after funding cost', { x: ax + 0.35, y: y + 1.45, w: cw - 0.7, h: 0.35, fontSize: 15 });

  const bugs = [
    ['Look-ahead', 'The entry rule read the bar it would be filled on, so it only took trades it already knew would win.'],
    ['Wrong FX rate', 'The daily ECB rate sat 44 bps away from live EUR/USDT, which created gaps that did not exist.'],
    ['Instant fills', 'Paper fills had no delay, so they could never lose. Now: 300 ms and full-depth prices.'],
  ];
  const bw = 3.8, bgap = 0.3, by = 4.15;
  bugs.forEach(([head, body], i) => {
    const x = X + i * (bw + bgap);
    s.addText([
      { text: `Bug ${i + 1}  ·  ${head}`, options: { bold: true, color: C.text2, fontSize: 17, breakLine: true } },
      { text: body, options: { color: C.text1, fontSize: 14 } },
    ], { isTextBox: true, x, y: by, w: bw, h: 1.55, margin: 0, valign: 'top', paraSpaceAfter: 4 });
  });
  txt(s, 'On a second week of data, 0 of 136 realistic settings made money.', { x: X, y: 5.95, w: W, h: 0.45, fontSize: 18, bold: true, color: C.text2 });
}

// ── 5 · EURC live test ─────────────────────────────────────────────────────
{
  const s = frame('CONTENT', 'Stablecoin test',
    '04  ·  LIVE TEST: EURC EURO STABLECOIN',
    'Stablecoin test: every pre-set criterion failed',
    'Session 22 Oct 2026, 19:48–22:25 UTC; Bitvavo, Kraken, Bitstamp; €40k per market-making instance. Criteria fixed in docs/eurc_live_test.md before the run.',
    'This test asked whether a euro stablecoin offers easier money: market making, or buying on one venue and selling on another. ' +
    'The pass/fail rules were written before the session. Market making on Bitvavo, the only zero-fee venue, bought into a seller sweep: 60-second markout -54 and -13 bps, ' +
    'about -EUR 29 after liquidating the extra 2,704 EURC. Kraken never quoted, correctly, because its 0.20% maker fee is ten times its 2 bps spread. ' +
    'Cross-venue taker arbitrage found one second at +1.5 bps (EUR 0.03) in 9,387 seconds; at EUR 10k the best net edge was -39 bps. ' +
    'The only positive result, a deep bid that absorbed one seller sweep, is worth roughly EUR 100-300 a year. Source: docs/eurc_live_test_results.md.');
  const rows = [
    [{ text: 'Criterion set in advance' }, { text: 'Result' }, { text: 'Verdict' }],
    ['Net profit after exit costs above zero', 'about −€29', 'FAIL'],
    ['Market-making P&L at mid of at least zero', '−€2.48', 'FAIL'],
    ['Median 60 s markout of at least −1 bp', '−34 bps', 'FAIL'],
    ['Our fills below 20% of venue volume', '35%', 'FAIL'],
    ['At least 3 sessions, including a weekend', '1 session, 2.6 h', 'NOT MET'],
  ].map((r, i) => r.map((c, j) => {
    const text = typeof c === 'string' ? c : c.text;
    const head = i === 0;
    const verdict = j === 2 && !head;
    return { text, options: {
      bold: head || verdict, fontSize: 14,
      color: head ? HEX.white : verdict ? (text === 'FAIL' ? HEX.red : HEX.muted) : HEX.ink,
      fill: { color: head ? HEX.teal : (i % 2 ? HEX.pale : HEX.white) },
    } };
  }));
  s.addTable(rows, { x: X, y: 1.85, w: 7.55, colW: [4.35, 1.85, 1.35], rowH: 0.62, margin: [0, 0.12, 0, 0.12],
    valign: 'middle', border: { type: 'solid', pt: 0.75, color: HEX.line }, objectName: 'criteria-table' });
  const facts = [
    ['2 vs 20 bps', 'Kraken’s spread against its maker fee: never worth quoting'],
    ['≈6,500 EURC', 'Bitvavo’s median daily volume over the last 366 days'],
    ['−39 bps', 'best cross-venue trade at €10k, after fees'],
  ];
  const fx = 8.75, fw = 3.92;
  facts.forEach(([big, label], i) => {
    const y = 1.85 + i * 1.55;
    card(s, fx, y, fw, 1.35, C.background2, `fact-${i + 1}`);
    txt(s, big, { x: fx + 0.3, y: y + 0.15, w: fw - 0.6, h: 0.6, fontSize: 28, bold: true, color: C.text2 });
    txt(s, label, { x: fx + 0.3, y: y + 0.75, w: fw - 0.6, h: 0.55, fontSize: 13 });
  });
  txt(s, 'The only positive result, a deep bid absorbing one seller sweep, is worth about €100–300 a year.', { x: X, y: 5.95, w: 7.55, h: 0.75, fontSize: 15, color: C.accent3 });
}

// ── 6 · Decision and value ─────────────────────────────────────────────────
{
  const s = frame('DARK', 'Decision',
    '05  ·  DECISION AND WHAT REMAINS',
    'Not deployed. The measurements are the asset.',
    'Happy to walk through the data in 15 minutes  ·  Syed Zee Waqar Hussain',
    'Close with the decision and the reason: the market is already arbitraged to within a few basis points, so a strategy that pays spreads and fees cannot win; only one that earns them might. ' +
    'Then say what the work is good for now. MiCA Article 78 requires firms executing client crypto orders to seek the best result and to assess their venues regularly; the tool measures spread, depth, freshness and latency per venue. ' +
    'For euro stablecoins, EURC on Bitvavo traded below 0.9925 on 28 of the last 366 days. ' +
    'Triggers that would reopen the decision come from docs/eurc_live_test_results.md: sustained Kraken BTC funding above about 7% a year with regulatory clarity on retail perps; free, practical par redemption of EURC; Bitvavo EURC volume above EUR 100k a day for a month.');
  const lw = 5.3;
  txt(s, 'Decision', { x: X, y: 1.85, w: lw, h: 0.45, fontSize: 20, bold: true, color: C.accent6 });
  txt(s, 'Keep the €40k in the 2.5% deposit.', { x: X, y: 2.35, w: lw, h: 0.55, fontSize: 22, bold: true, color: C.background1 });
  txt(s, 'The market is arbitraged to within a few bps. Paying spreads and fees cannot win; only earning them might.', { x: X, y: 3.0, w: lw, h: 1.0, fontSize: 16, color: C.background1 });
  txt(s, 'What would reopen it', { x: X, y: 4.3, w: lw, h: 0.4, fontSize: 16, bold: true, color: C.accent6 });
  s.addText([
    { text: 'BTC funding above about 7% a year, sustained', options: { bullet: true, breakLine: true } },
    { text: 'Free, practical par redemption of EURC', options: { bullet: true, breakLine: true } },
    { text: 'Bitvavo EURC volume above €100k a day', options: { bullet: true } },
  ], { isTextBox: true, x: X, y: 4.75, w: lw, h: 1.4, margin: 0, valign: 'top', fontSize: 15, color: C.background1, paraSpaceAfter: 4 });

  const rx = 6.55, rw = 6.12;
  card(s, rx, 1.85, rw, 4.7, C.accent5, 'uses-card');
  txt(s, 'Where the data helps now', { x: rx + 0.35, y: 2.05, w: rw - 0.7, h: 0.45, fontSize: 20, bold: true, color: C.background1 });
  const uses = [
    ['Best execution', 'Live spread, depth, freshness and latency per venue (MiCA Art. 78).'],
    ['Euro stablecoins', 'EURC traded below 0.9925 on 28 of 366 days on Bitvavo.'],
    ['Model validation', 'A checklist of the errors that made losses look like profit.'],
    ['Next test worth running', 'Passive quotes with a near-free internal hedge, at real institutional fees.'],
  ];
  uses.forEach(([head, body], i) => {
    const y = 2.65 + i * 0.95;
    s.addShape(pres.shapes.OVAL, { x: rx + 0.35, y: y + 0.05, w: 0.42, h: 0.42, fill: { color: C.background1 }, line: { color: C.background1, width: 0 }, objectName: `use-${i + 1}-badge` });
    s.addText(String(i + 1), { isTextBox: true, x: rx + 0.35, y: y + 0.05, w: 0.42, h: 0.42, margin: 0, align: 'center', valign: 'middle', fontSize: 14, bold: true, color: C.text2 });
    s.addText([
      { text: head, options: { bold: true, color: C.background1, breakLine: true } },
      { text: body, options: { color: C.accent6 } },
    ], { isTextBox: true, x: rx + 0.95, y, w: rw - 1.3, h: 0.85, margin: 0, valign: 'top', fontSize: 14 });
  });
}

(async () => {
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log('saved', out);
})();
