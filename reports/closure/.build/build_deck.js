// Six-slide briefing: three crypto arbitrage strategies, one yardstick (a 2.5% EUR deposit).
// Data: reports/closure/data/chart_data.json (built by build_chart_data.py from the repo docs
// and from public exchange history in data/eurc_daily.csv and data/perp_funding.csv).
// Usage: NODE_PATH=<dir with pptxgenjs> node build_deck.js <chart_data.json> <out.pptx> <apply_theme.js>
const fs = require('fs');
const pptxgen = require('pptxgenjs');
const D = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = process.argv[3];
const { applyTheme } = require(process.argv[4]);

const HEX = {
  ink: '18313B', teal: '173C4A', tealSoft: '24525F', muted: '53656D', pale: 'EDF3F4', line: 'D6DFE2',
  white: 'FFFFFF', red: 'A33639', s1: '2F5D8A', s2: 'B7791F', s3: '2F7D6D', lightText: 'C9D8DC',
};
const THEME = {
  name: 'Crypto Arbitrage Closure', headFontFace: 'Arial', bodyFontFace: 'Arial',
  colors: {
    dk1: HEX.ink, lt1: HEX.white, dk2: HEX.teal, lt2: HEX.pale,
    accent1: HEX.s1, accent2: HEX.s2, accent3: HEX.s3, accent4: HEX.red,
    accent5: HEX.muted, accent6: HEX.tealSoft, hlink: HEX.s1, folHlink: HEX.muted,
  },
};
const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.theme = { headFontFace: 'Arial', bodyFontFace: 'Arial' };
pres.title = 'Three crypto arbitrage strategies against a 2.5% deposit';
pres.author = 'Syed Zee Waqar Hussain';
const C = pres.SchemeColor;
const SC = { 1: C.accent1, 2: C.accent2, 3: C.accent3 };
const SH = { 1: HEX.s1, 2: HEX.s2, 3: HEX.s3 };
const X = 0.67, W = 12.0;

// ── Layouts ──────────────────────────────────────────────────────────────
function master(title, bg, kickerColor, titleColor, srcColor) {
  pres.defineSlideMaster({
    title, background: { color: bg },
    objects: [
      { placeholder: { options: { name: 'kicker', type: 'body', x: X, y: 0.34, w: W, h: 0.3, fontSize: 14, bold: true, color: kickerColor, margin: 0, valign: 'top' }, text: '' } },
      { placeholder: { options: { name: 'title', type: 'title', x: X, y: 0.68, w: W, h: 0.7, fontSize: 32, bold: true, align: 'left', color: titleColor, margin: 0, valign: 'top' }, text: '' } },
      { placeholder: { options: { name: 'source', type: 'body', x: X, y: 6.95, w: 11.0, h: 0.32, fontSize: 10, color: srcColor, margin: 0, valign: 'top' }, text: '' } },
    ],
    slideNumber: { x: 12.17, y: 6.93, w: 0.5, h: 0.3, fontSize: 11, color: srcColor, align: 'right' },
  });
}
master('LIGHT', C.background1, C.accent5, C.text2, C.accent5);
master('DARK', C.text2, C.background2, C.background1, C.background2);
master('S1', C.background1, C.accent1, C.text2, C.accent5);
master('S2', C.background1, C.accent2, C.text2, C.accent5);
master('S3', C.background1, C.accent3, C.text2, C.accent5);

function frame(layout, section, kicker, title, source, notes) {
  pres.addSection({ title: section });
  const s = pres.addSlide({ masterName: layout, sectionTitle: section });
  s.addText(kicker, { placeholder: 'kicker' });
  s.addText(title, { placeholder: 'title' });
  s.addText(source, { placeholder: 'source' });
  s.addNotes(notes);
  return s;
}
const txt = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, valign: 'top', fontSize: 15, color: C.text1, ...o });
const box = (s, x, y, w, h, fill, name) => s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: name });
function badge(s, n, x, y, d, fill, textColor) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: `badge-${n}` });
  s.addText(String(n), { isTextBox: true, x, y, w: d, h: d, margin: 0, align: 'center', valign: 'middle', fontSize: Math.round(d * 30), bold: true, color: textColor || C.background1 });
}
function kpi(s, x, y, w, h, value, label, color, name) {
  box(s, x, y, w, h, C.background2, name);
  txt(s, value, { x: x + 0.22, y: y + 0.14, w: w - 0.44, h: 0.55, fontSize: 26, bold: true, color, fit: 'shrink' });
  txt(s, label, { x: x + 0.22, y: y + 0.7, w: w - 0.44, h: h - 0.8, fontSize: 12.5, color: C.text1 });
}
function verdict(s, n, label, text) {
  box(s, X, 6.2, W, 0.58, C.background2, 'verdict');
  s.addText([
    { text: `Verdict: ${label}.  `, options: { bold: true, color: SC[n] } },
    { text, options: { color: C.text1 } },
  ], { isTextBox: true, x: X + 0.25, y: 6.2, w: W - 0.5, h: 0.58, margin: 0, valign: 'middle', fontSize: 14 });
}
const chartBase = (extra) => ({
  catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontSize: 11, valAxisLabelFontSize: 11,
  catAxisLabelFontFace: '+mn-lt', valAxisLabelFontFace: '+mn-lt', legendFontFace: '+mn-lt', legendFontSize: 11, legendColor: HEX.ink,
  valGridLine: { color: HEX.line, size: 0.75 }, catGridLine: { style: 'none' }, catAxisLineColor: HEX.line, valAxisLineShow: false,
  showTitle: true, titleFontSize: 13, titleColor: HEX.ink, titleFontFace: '+mn-lt', titleBold: true, titleAlign: 'left',
  ...extra,
});
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
// Daily series: label only the first day of every second month, so the axis stays readable.
function sparseMonthLabels(dates) {
  let last = null;
  return dates.map((d) => {
    const [y, m] = d.split('-');
    const key = y + m;
    if (key === last) return '';
    last = key;
    return (+m % 2 === 1) ? `${MONTHS[+m - 1]} ${y.slice(2)}` : '';
  });
}

const k2 = D.s2.stats;
const lad = Object.fromEntries(D.s3.ladder_kraken_fee_020.map((r) => [r.level.toFixed(4), r]));

// ── 1 · Answer ───────────────────────────────────────────────────────────
{
  const s = frame('DARK', 'Answer', 'RESEARCH BRIEFING  ·  OCTOBER 2026',
    'Three crypto arbitrage strategies against a 2.5% deposit',
    'Syed Zee Waqar Hussain  ·  May 2025 – Oct 2026  ·  Paper trading on live public market data  ·  No orders sent',
    'Open with the question that drove the whole project: can any crypto arbitrage beat a plain 2.5% EUR deposit once every cost is paid? ' +
    'I tested three different ways of making money. Each card gives the mechanism in one line and the single number that decides it. ' +
    'Cross-exchange: the price gap is smaller than the cost. Perpetual carry: the yield exists but is roughly the deposit rate, with more risk. ' +
    'EURC depeg capture: a real edge, but only a few thousand euros of capacity per event. So none was deployed.');
  txt(s, 'The question: can any of them beat a 2.5% EUR bank deposit after every cost?', { x: X, y: 1.5, w: W, h: 0.45, fontSize: 19, color: C.background2 });
  const cards = [
    [1, 'Cross-exchange spot arbitrage', 'Buy BTC or ETH on the cheaper exchange and sell on the dearer one at the same moment.', 'No edge', '−2.3 bps', 'median price gap at €100k, against a 17 bps cost'],
    [2, 'Perpetual funding carry', 'Buy spot and short the perpetual future; collect the funding that leveraged longs pay.', 'Edge ≈ deposit rate', `${k2['Kraken BTC'].mean_ann_pct.toFixed(1)}%`, 'a year of funding (Kraken BTC, 12 months), before hedge and risk'],
    [3, 'EURC depeg capture', 'Rest bids below €1 for the euro stablecoin; buy when a seller dumps, sell back near par.', 'Real edge, tiny capacity', '€100–300', 'a year, realistic, on a €5k sleeve'],
  ];
  const cw = 3.8, gap = 0.3, y = 2.2, h = 3.85;
  cards.forEach(([n, name, how, v, big, lbl], i) => {
    const x = X + i * (cw + gap);
    box(s, x, y, cw, h, C.accent6, `card-${n}`);
    badge(s, n, x + 0.3, y + 0.3, 0.5, SC[n]);
    txt(s, name, { x: x + 0.95, y: y + 0.3, w: cw - 1.2, h: 0.55, fontSize: 16, bold: true, color: C.background1, valign: 'middle' });
    txt(s, how, { x: x + 0.3, y: y + 1.0, w: cw - 0.6, h: 0.95, fontSize: 13, color: C.background2 });
    txt(s, big, { x: x + 0.3, y: y + 2.0, w: cw - 0.6, h: 0.65, fontSize: 32, bold: true, color: C.background1 });
    txt(s, lbl, { x: x + 0.3, y: y + 2.65, w: cw - 0.6, h: 0.5, fontSize: 12, color: C.background2 });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.3, y: y + 3.2, w: cw - 0.6, h: 0.42, rectRadius: 0.08, fill: { color: SC[n] }, line: { color: SC[n], width: 0 }, objectName: `verdict-${n}` });
    s.addText(v, { isTextBox: true, x: x + 0.3, y: y + 3.2, w: cw - 0.6, h: 0.42, margin: 0, align: 'center', valign: 'middle', fontSize: 14, bold: true, color: C.background1 });
  });
  txt(s, 'Decision: deploy none. The €40k test capital stays in the 2.5% deposit.', { x: X, y: 6.3, w: W, h: 0.45, fontSize: 17, bold: true, color: C.background1 });
}

// ── 2 · History and method ───────────────────────────────────────────────
{
  const s = frame('LIGHT', 'History and method', '01  ·  HOW THE PROJECT GOT HERE',
    'Eighteen months, three strategies, one yardstick',
    'Sources: git history; docs/BSDEX_Explainer_Guide.html; docs/eurc_live_test.md; data/meta.json. Bitstamp stands in for BSDEX (its API needs keys).',
    'The project started in May 2025 as a Binance-versus-Kraken z-score engine with live paper trading. In May and June 2026 it became an institutional model: ' +
    'a EUR venue (Bitstamp as a stand-in for BSDEX) against global USDT liquidity, with bank fee tiers, live EUR/USDT conversion, full-depth pricing and slippage. ' +
    'In October the backtest was audited, three bugs were fixed, and a 4-hour live campaign showed the gap never covers costs. ' +
    'I then tested the two strongest alternatives: perpetual funding carry with 12 months of funding data, and EURC with a live session plus a year of daily history. ' +
    'Every strategy was judged the same way: net of every cost, against a 2.5% EUR deposit.');
  const ms = [
    ['May 2025', 'Prototype', 'Binance vs Kraken z-score engine, live paper trading, web dashboard'],
    ['May–Jun 2026', 'Institutional model', '"BSDEX vs World": bank fee tiers, live EUR/USDT, full-depth prices, slippage'],
    ['11–15 Oct 2026', 'Audit + live run', 'Three backtest bugs fixed; 4-hour live campaign at €100k per leg'],
    ['13–22 Oct 2026', 'Alternatives', 'Perpetual carry (12 months of funding) and EURC (live test + daily history)'],
    ['22 Oct 2026', 'Decision', 'Deploy none; keep the €40k in the deposit'],
  ];
  const ty = 1.75, step = W / ms.length;
  s.addShape(pres.shapes.LINE, { x: X + 0.15, y: ty + 0.15, w: W - 0.3, h: 0, line: { color: HEX.line, width: 2 }, objectName: 'timeline' });
  ms.forEach(([when, head, body], i) => {
    const x = X + i * step;
    s.addShape(pres.shapes.OVAL, { x: x + 0.05, y: ty + 0.03, w: 0.24, h: 0.24, fill: { color: i === ms.length - 1 ? C.accent4 : C.text2 }, line: { color: C.background1, width: 1.5 }, objectName: `milestone-${i + 1}` });
    txt(s, when, { x, y: ty + 0.42, w: step - 0.2, h: 0.3, fontSize: 12, bold: true, color: C.accent5 });
    txt(s, head, { x, y: ty + 0.72, w: step - 0.2, h: 0.32, fontSize: 15, bold: true, color: C.text2 });
    txt(s, body, { x, y: ty + 1.06, w: step - 0.25, h: 0.85, fontSize: 11.5 });
  });
  const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.teal } } });
  const cell = (t, o = {}) => ({ text: t, options: { color: HEX.ink, ...o } });
  const rows = [
    [hdr('Strategy'), hdr('Venues'), hdr('Evidence'), hdr('Live test')],
    [cell('1  Cross-exchange spot', { bold: true, color: HEX.s1 }), cell('Bitstamp EUR, Binance USDT→EUR, Kraken'), cell('136-setting backtest sweep, order-book replays, verified 1-week backtest'), cell('4 h on 14 Oct, 49,825 snapshots per coin')],
    [cell('2  Perpetual funding carry', { bold: true, color: HEX.s2 }), cell('Kraken, Deribit, OKX perpetuals'), cell('12 months of hourly funding; EU fee schedules and access'), cell('None: profit accrues over months, not hours')],
    [cell('3  EURC depeg capture', { bold: true, color: HEX.s3 }), cell('Bitvavo, Kraken, Bitstamp (EURC/EUR)'), cell('12 months of daily candles; resting-bid ladder backtest'), cell('2.6 h on 22 Oct, three venues, rules set in advance')],
  ];
  s.addTable(rows, { x: X, y: 3.85, w: W, colW: [2.75, 2.85, 3.75, 2.65], rowH: [0.4, 0.55, 0.55, 0.55], fontSize: 12.5, margin: [0, 0.1, 0, 0.1], valign: 'middle', border: { type: 'solid', pt: 0.75, color: HEX.line }, objectName: 'evidence-table' });
  box(s, X, 6.15, W, 0.62, C.background2, 'yardstick');
  s.addText([
    { text: 'Same yardstick for all three:  ', options: { bold: true, color: C.text2 } },
    { text: 'net of every fee, spread, currency, funding and idle-capital cost, measured against a 2.5% EUR deposit.', options: { color: C.text1 } },
  ], { isTextBox: true, x: X + 0.25, y: 6.15, w: W - 0.5, h: 0.62, margin: 0, valign: 'middle', fontSize: 14 });
}

// ── 3 · Strategy 1 ───────────────────────────────────────────────────────
{
  const s = frame('S1', 'Cross-exchange', 'STRATEGY 1  ·  CROSS-EXCHANGE SPOT ARBITRAGE',
    'The price gap is smaller than the cost of trading it',
    'Live campaign 14 Oct 2026, 4 h (docs/BSDEX_Explainer_Guide.html); gap after crossing both books, before fees. Backtest: BTC/EUR 24 Sep–1 Oct 2026.',
    'Mechanism: buy on Bitstamp in EUR and sell on Binance in USDT converted at the live EUR/USDT rate, or the reverse, at the same moment. ' +
    'The chart shows the median tradeable gap for four order sizes. It is negative at every size, meaning crossing both books loses money before any fee, and it gets worse with size. ' +
    'The red lines are the cost a trade must clear: 9 bps at an assumed >$250M tier and 17 bps at the default >$20M tier (47 bps at retail). ' +
    'Even the best 1% of moments for a EUR 1k order were only +1.6 bps. The 14 moments that beat break-even lasted 2.8 s at most and happened while one venue\'s prices froze. ' +
    'The backtest that once showed +EUR 275.81 with 100% winners was caused by look-ahead, a stale daily ECB FX rate 44 bps away from EUR/USDT, and zero-delay fills.');
  txt(s, 'Buy on the cheaper exchange, sell on the dearer one, at the same moment. BTC and ETH, Bitstamp (EUR) vs Binance (USDT, in EUR).', { x: X, y: 1.42, w: W, h: 0.4, fontSize: 14, color: C.accent5 });
  const bs = D.s1.by_size;
  const n = bs.sizes.length;
  s.addChart([
    { type: pres.charts.BAR, data: [
      { name: 'BTC median gap', labels: bs.sizes, values: bs.btc_median },
      { name: 'ETH median gap', labels: bs.sizes, values: bs.eth_median },
    ], options: { barGrouping: 'clustered', chartColors: [HEX.s1, '8FB3D9'], showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '+0.0;-0.0;0', dataLabelFontSize: 11, dataLabelColor: HEX.ink, dataLabelFontFace: '+mn-lt', barGapWidthPct: 60 } },
    { type: pres.charts.LINE, data: [
      { name: 'Break-even, > $250M tier (9 bps)', labels: bs.sizes, values: Array(n).fill(9) },
      { name: 'Break-even, default > $20M tier (17 bps)', labels: bs.sizes, values: Array(n).fill(17) },
    ], options: { chartColors: ['D98C8E', HEX.red], lineSize: 2.5, lineDash: 'dash', lineDataSymbol: 'none', showValue: false } },
  ], chartBase({
    x: X, y: 1.95, w: 7.55, h: 4.1, title: 'Median tradeable gap by order size vs cost to break even (bps)',
    valAxisMinVal: -10, valAxisMaxVal: 20, valAxisMajorUnit: 5, valAxisLabelFormatCode: '0',
    showLegend: true, legendPos: 'b', catAxisLabelPos: 'low', objectName: 's1-chart',
  }));
  const kx = 8.5, kw = 4.17;
  kpi(s, kx, 1.95, kw, 1.25, '0 trades', 'in a 4-hour live paper run at €100k per leg; the gap beat 17 bps 0% of the time', C.accent1, 's1-kpi-1');
  kpi(s, kx, 3.33, kw, 1.25, '0 of 136', 'realistic backtest settings made money (7–14 Oct, every fee tier)', C.accent1, 's1-kpi-2');
  kpi(s, kx, 4.71, kw, 1.34, '+€276 → −€1,548', 'the “profitable” backtest once look-ahead, a stale FX rate and instant fills were fixed', C.accent4, 's1-kpi-3');
  verdict(s, 1, 'no edge', 'The market is arbitraged to within a few bps; paying spread and fees on both legs cannot win. The rare big gaps were frozen prices, ≤ 3 s.');
}

// ── 4 · Strategy 2 ───────────────────────────────────────────────────────
{
  const kr = D.s2.rolling30['Kraken BTC'], db = D.s2.rolling30['Deribit BTC'];
  const labels = sparseMonthLabels(kr.dates);
  const dbMap = Object.fromEntries(db.dates.map((d, i) => [d, db.values[i]]));
  const dbVals = kr.dates.map((d) => (d in dbMap ? dbMap[d] : null));
  const s = frame('S2', 'Perpetual carry', 'STRATEGY 2  ·  PERPETUAL FUNDING CARRY',
    'The yield is real, but it is roughly the deposit rate',
    'Funding: Kraken Futures and Deribit public history to 22 Oct 2026, 30-day average, annualised. Net range and ≈7% level: docs/eurc_live_test.md.',
    'Mechanism: hold the coin and short the perpetual future of the same size, so price moves cancel. When leveraged buyers dominate, longs pay shorts a funding rate every hour or eight hours; the carry trade collects it. ' +
    `Over the last 12 months the average funding was ${k2['Kraken BTC'].mean_ann_pct}% a year on Kraken BTC and ${k2['Deribit BTC'].mean_ann_pct}% on Deribit BTC; OKX BTC averaged ${k2['OKX BTC'].mean_ann_pct}% over its last ${k2['OKX BTC'].window_days} days. ` +
    `On Kraken ${k2['Kraken BTC'].share_negative_pct}% of hours had negative funding, so the short pays. ` +
    'The strategy-selection note puts a realistic EU set-up (OKX EEA, maker on both legs, two round trips a year) at about 2.4-4.3% in USD, i.e. EUR 960-1,720 on EUR 40k, before hedging the dollar exposure, which eats most of the excess over 2.5%. ' +
    'The cheapest venues, Binance and Bybit, do not offer perpetuals to EU residents, and ESMA said in February 2026 that perpetuals are likely CFDs. A 4-hour live test cannot validate carry, so it was assessed on history.');
  txt(s, 'Hold the coin and short its perpetual future so price moves cancel; earn the funding that leveraged buyers pay.', { x: X, y: 1.42, w: W, h: 0.4, fontSize: 14, color: C.accent5 });
  s.addChart(pres.charts.LINE, [
    { name: 'Kraken BTC', labels, values: kr.values },
    { name: 'Deribit BTC', labels, values: dbVals },
    { name: 'Bank deposit 2.5%', labels, values: Array(labels.length).fill(D.s2.deposit_pct) },
    { name: 'Needed to justify the risk ≈ 7%', labels, values: Array(labels.length).fill(D.s2.needed_pct) },
  ], chartBase({
    x: X, y: 1.95, w: 7.55, h: 4.1, title: 'Funding earned by the short, 30-day average (% a year)',
    chartColors: [HEX.s2, 'E2B66B', HEX.ink, HEX.red], lineSize: 2, lineDataSymbol: 'none',
    catAxisLabelPos: 'low', catAxisMajorTickMark: 'none', catAxisLineShow: false, valAxisLabelFormatCode: '0"%"', valAxisMajorUnit: 2,
    showLegend: true, legendPos: 'b', objectName: 's2-chart',
  }));
  const kx = 8.5, kw = 4.17;
  kpi(s, kx, 1.95, kw, 1.25, `${k2['Kraken BTC'].mean_ann_pct.toFixed(1)}% vs 2.5%`, `12-month average funding, Kraken BTC (Deribit ${k2['Deribit BTC'].mean_ann_pct.toFixed(1)}%), in USD`, C.accent2, 's2-kpi-1');
  kpi(s, kx, 3.33, kw, 1.25, `${Math.round(k2['Kraken BTC'].share_negative_pct)}% of hours`, 'had negative funding on Kraken: the short pays instead of earning', C.accent4, 's2-kpi-2');
  kpi(s, kx, 4.71, kw, 1.34, '€960–1,720', 'a year on €40k before the EUR/USD hedge, against €1,000 from the deposit', C.accent2, 's2-kpi-3');
  verdict(s, 2, 'edge ≈ deposit rate', 'Pays only in high-funding regimes, with exchange and ESMA “likely CFD” risk on 100% of capital; cheapest venues are closed to EU residents.');
}

// ── 5 · Strategy 3 ───────────────────────────────────────────────────────
{
  const kd = D.s3.kraken_daily;
  const labels = sparseMonthLabels(kd.dates);
  const s = frame('S3', 'EURC depeg', 'STRATEGY 3  ·  EURC STABLECOIN DEPEG CAPTURE',
    'A real edge, but each depeg is small and brief',
    'Kraken EURC/EUR daily candles to 22 Oct 2026. Ladder: rule in scripts/eurc_live_test.py, 0.20% fee each side, exit 0.9995. Live test: docs/eurc_live_test_results.md.',
    'Mechanism: EURC is designed to be worth one euro and Circle redeems at par. When a holder dumps EURC into a thin book, the price briefly drops; a resting bid below par buys it and sells back near par. ' +
    `On Kraken the daily low fell below 0.9925 on ${D.s3.kraken_days_below_09925} days in the last year, with a low of ${D.s3.kraken_min_low}. ` +
    `The right-hand chart replays the script's resting-bid ladder on those candles after Kraken's 0.20% maker fee on both legs: bids just under par lose to fees; a bid at 0.99 filled ${lad['0.9900'].fills} times and earned about ${lad['0.9900'].ann_pct}% a year on the capital reserved for it. ` +
    'But a candle low proves a price printed, not that size was available. On the live tape on 22 Oct, one seller sweep offered roughly 2.5k EURC; the deep bid made +EUR 12.2 on it. ' +
    'Market making failed all four pre-set criteria (about -EUR 29 after liquidation; 60-second markout -54 and -13 bps) and cross-venue taker arbitrage netted -39 bps at EUR 10k. Realistic value: EUR 100-300 a year on a EUR 5k sleeve.');
  txt(s, 'Rest bids below €1 for the euro stablecoin; when a holder dumps into a thin book, buy and sell back near par.', { x: X, y: 1.42, w: W, h: 0.4, fontSize: 14, color: C.accent5 });
  s.addChart(pres.charts.LINE, [
    { name: 'Kraken daily low', labels, values: kd.low },
    { name: 'Bid at 0.9925', labels, values: Array(labels.length).fill(0.9925) },
  ], chartBase({
    x: X, y: 1.95, w: 5.0, h: 2.95, title: 'EURC/EUR daily low on Kraken, last 12 months',
    chartColors: [HEX.s3, HEX.red], lineSize: 1.5, lineDataSymbol: 'none', valAxisMinVal: 0.95, valAxisMaxVal: 1.005, valAxisMajorUnit: 0.01,
    valAxisLabelFormatCode: '0.00', catAxisLabelPos: 'low', catAxisMajorTickMark: 'none', catAxisLineShow: false, showLegend: true, legendPos: 'b', objectName: 's3-price-chart',
  }));
  const levels = ['0.9975', '0.9950', '0.9925', '0.9900', '0.9800'];
  const vals = levels.map((l) => lad[l].ann_pct);
  s.addChart(pres.charts.BAR, [{ name: '% a year', labels: levels.map((l) => `Bid ${l.replace(/0+$/, '')}`), values: vals }], chartBase({
    x: 5.85, y: 1.95, w: 3.75, h: 2.95, title: 'Resting-bid backtest after fees (% a year)',
    chartColors: vals.map((v) => (v < 0 ? HEX.red : HEX.s3)), showValue: true, dataLabelPosition: 'outEnd', dataLabelFormatCode: '+0.0;-0.0;0',
    dataLabelFontSize: 11, dataLabelColor: HEX.ink, dataLabelFontFace: '+mn-lt', valAxisHidden: true, valGridLine: { style: 'none' },
    valAxisMinVal: -12, valAxisMaxVal: 15, showLegend: false, catAxisLabelPos: 'low', barGapWidthPct: 40, catAxisLabelFontSize: 10, objectName: 's3-ladder-chart',
  }));
  txt(s, `Fills over the year: ${levels.map((l) => lad[l].fills).join(' · ')}. Candles prove a price printed, not that size was there.`, { x: 5.85, y: 4.92, w: 3.75, h: 0.55, fontSize: 10.5, color: C.accent5 });
  const kx = 9.85, kw = 2.82;
  kpi(s, kx, 1.95, kw, 1.25, `${D.s3.kraken_days_below_09925} days`, `below €0.9925 on Kraken in 12 months (low €${D.s3.kraken_min_low})`, C.accent3, 's3-kpi-1');
  kpi(s, kx, 3.33, kw, 1.25, '≈2.5k EURC', 'per seller sweep on the live tape: +€12 on one event', C.accent3, 's3-kpi-2');
  kpi(s, kx, 4.71, kw, 1.34, '€100–300', 'a year, realistic, on a €5k sleeve', C.accent3, 's3-kpi-3');
  box(s, X, 5.42, 9.0, 0.63, C.background2, 's3-live-box');
  s.addText([
    { text: 'Live test, 22 Oct (2.6 h):  ', options: { bold: true, color: C.text2 } },
    { text: 'market making −€29 and failed all 4 pre-set criteria; cross-venue arbitrage −39 bps at €10k. Kraken’s 2 bps spread sits under a 20 bps fee.', options: { color: C.text1 } },
  ], { isTextBox: true, x: X + 0.2, y: 5.42, w: 8.6, h: 0.63, margin: 0, valign: 'middle', fontSize: 12.5 });
  verdict(s, 3, 'real edge, tiny capacity', 'Deep bids do catch depegs, but each sweep is a few thousand EURC: too small to move €40k, and it needs two venues and on-chain transfers.');
}

// ── 6 · Comparison and decision ──────────────────────────────────────────
{
  const s = frame('LIGHT', 'Decision', '02  ·  SIDE BY SIDE',
    'None beats the deposit by enough to justify the risk',
    'Ranges: 1 from the live run; 2 from docs/eurc_live_test.md, before the EUR/USD hedge; 3 from docs/eurc_live_test_results.md, €5k sleeve.',
    'This slide puts the three on one scale: what each would have earned on the EUR 40k test capital in a year, against EUR 1,000 from a 2.5% deposit. ' +
    'Cross-exchange spot earns nothing because no trade clears costs, and forced trades lose. Perpetual carry lands around the deposit, EUR 960-1,720 before the dollar hedge, with exchange, regulatory and negative-funding risk on all the capital. ' +
    'EURC depeg capture is the only genuine edge but is capacity-capped at roughly EUR 100-300 a year. ' +
    'The table says what each needs before it is worth revisiting. Close with the decision and the offer to walk through the data.');
  // Range chart drawn with shapes: €0 to €2,000 scale.
  const cx = X + 2.75, cw = 4.25, cy = 1.95, rowH = 0.78, maxV = 2000;
  const xv = (v) => cx + (v / maxV) * cw;
  txt(s, 'What €40k would have earned in a year', { x: X, y: 1.5, w: 7.4, h: 0.35, fontSize: 14, bold: true, color: C.text2 });
  [0, 500, 1000, 1500, 2000].forEach((v) => {
    s.addShape(pres.shapes.LINE, { x: xv(v), y: cy, w: 0, h: rowH * 4, line: { color: HEX.line, width: 0.75 } });
    txt(s, `€${v.toLocaleString('en-GB')}`, { x: xv(v) - 0.4, y: cy + rowH * 4 + 0.05, w: 0.8, h: 0.25, fontSize: 10, color: C.accent5, align: 'center' });
  });
  s.addShape(pres.shapes.LINE, { x: xv(1000), y: cy - 0.05, w: 0, h: rowH * 4 + 0.1, line: { color: HEX.ink, width: 1.5, dashType: 'dash' }, objectName: 'deposit-line' });
  const rowsC = [
    ['Bank deposit, 2.5%', 1000, 1000, C.text2, '€1,000'],
    ['1  Cross-exchange spot', 0, 0, C.accent1, '€0: no trade clears'],
    ['2  Perpetual carry', 960, 1720, C.accent2, '€960–1,720 before hedge'],
    ['3  EURC depeg capture', 100, 300, C.accent3, '€100–300, capped'],
  ];
  rowsC.forEach(([name, lo, hi, col, lbl], i) => {
    const y = cy + i * rowH;
    txt(s, name, { x: X, y: y + 0.2, w: 2.65, h: 0.4, fontSize: 13, bold: true, color: col, valign: 'middle' });
    const x0 = xv(lo), w0 = Math.max(xv(hi) - x0, 0.09);
    s.addShape(pres.shapes.RECTANGLE, { x: x0, y: y + 0.22, w: w0, h: 0.34, fill: { color: col }, line: { color: col, width: 0 }, objectName: `range-${i}` });
    if (i === 2) {  // the wide bar: label to its left, clear of the deposit line
      txt(s, lbl, { x: x0 - 2.05, y: y + 0.22, w: 1.95, h: 0.34, fontSize: 11, color: C.accent5, align: 'right', valign: 'middle' });
    } else {
      txt(s, lbl, { x: x0 + w0 + 0.12, y: y + 0.22, w: 1.75, h: 0.34, fontSize: 11, color: C.accent5, valign: 'middle' });
    }
  });
  const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.teal } } });
  const c = (t, o = {}) => ({ text: t, options: { color: HEX.ink, ...o } });
  const tbl = [
    [hdr(''), hdr('Capacity'), hdr('Main risk'), hdr('Worth revisiting if')],
    [c('1', { bold: true, color: HEX.s1, align: 'center' }), c('None: no edge'), c('Fees on both legs; frozen prices'), c('A maker-only design with a near-free hedge')],
    [c('2', { bold: true, color: HEX.s2, align: 'center' }), c('Large (millions)'), c('Negative funding; exchange and ESMA risk'), c('90-day funding above ≈7%, sustained, and EU rules clarified')],
    [c('3', { bold: true, color: HEX.s3, align: 'center' }), c('≈2.5k EURC per event'), c('Thin books; transfer costs'), c('Free par redemption, or Bitvavo volume above €100k a day')],
  ];
  s.addTable(tbl, { x: 8.2, y: 1.95, w: 4.47, colW: [0.37, 1.1, 1.4, 1.6], rowH: [0.38, 0.92, 0.92, 0.92], fontSize: 11, margin: [0.03, 0.07, 0.03, 0.07], valign: 'middle', border: { type: 'solid', pt: 0.75, color: HEX.line }, objectName: 'scorecard' });
  box(s, X, 5.6, W, 1.17, C.text2, 'decision-box');
  s.addText([
    { text: 'Decision: deploy none.  ', options: { bold: true, color: C.background1, fontSize: 17 } },
    { text: 'The €40k stays in the 2.5% deposit.', options: { color: C.background1, fontSize: 17, breakLine: true } },
    { text: 'What the work is good for now: live venue-quality data for best execution (MiCA Art. 78), euro-stablecoin liquidity evidence, and a checklist of the backtest errors that make losses look like profit.', options: { color: C.background2, fontSize: 12.5 } },
  ], { isTextBox: true, x: X + 0.3, y: 5.6, w: W - 0.6, h: 1.17, margin: 0, valign: 'middle', paraSpaceAfter: 4 });
}

(async () => {
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log('saved', out);
})();
