from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
ROOT=Path('/Users/syedzeewaqarhussain/crypto_hft_tool/reports/tool_briefing')
doc=Document(); sec=doc.sections[0]
sec.page_height=Inches(11.7);sec.page_width=Inches(8.3)
sec.top_margin=sec.bottom_margin=Inches(.65);sec.left_margin=sec.right_margin=Inches(.75)
sec.header_distance=sec.footer_distance=Inches(.3)
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
 st=doc.styles[name];st.font.name='Arial';st.font.color.rgb=RGBColor(0,0,0)
 st.paragraph_format.space_after=Pt(7)
doc.styles['Normal'].font.size=Pt(10.5);doc.styles['Normal'].paragraph_format.line_spacing=1.12
for border in list(doc.styles.element.iter(qn('w:pBdr'))): border.getparent().remove(border)
doc.styles['Title'].font.size=Pt(28)
doc.styles['Heading 1'].font.size=Pt(21)
doc.styles['Heading 2'].font.size=Pt(12)
doc.styles['Heading 2'].paragraph_format.space_before=Pt(10)
h=sec.header.paragraphs[0];h.text='CRYPTO ARBITRAGE TOOL     /     EXPLAINER GUIDE';h.style='Normal';h.runs[0].font.size=Pt(8)
f=sec.footer.paragraphs[0];f.alignment=WD_ALIGN_PARAGRAPH.RIGHT
f.add_run('12 October 2026   •   ')
fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');f._p.append(fld)
for r in f.runs:r.font.size=Pt(8)

def p(t,style=None):
 x=doc.add_paragraph(t,style)
 if x._p.getprevious() is not None and x._p.getprevious().tag == qn('w:tbl'): x.paragraph_format.space_before=Pt(5)
 return x
def h2(t):doc.add_heading(t,2)
def page(title):doc.add_page_break();doc.add_heading(title,1)
def source(t):
 x=p(t);x.paragraph_format.space_before=Pt(9)
 for r in x.runs:r.font.size=Pt(8);r.font.color.rgb=RGBColor.from_string('53616B')
def table(headers, rows, widths, size=10):
 t=doc.add_table(rows=1, cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
 for i,w in enumerate(widths):t.columns[i].width=Inches(w)
 for i,h in enumerate(headers):t.rows[0].cells[i].text=h
 for row in rows:
  cells=t.add_row().cells
  for i,v in enumerate(row):cells[i].text=str(v)
 for j,row in enumerate(t.rows):
  for i,c in enumerate(row.cells):
   c.width=Inches(widths[i]);c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   pr=c._tc.get_or_add_tcPr();shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'173C4A' if j==0 else ('F1F5F6' if j%2 else 'FFFFFF'));pr.append(shade)
   margins=OxmlElement('w:tcMar')
   for edge in ['top','left','bottom','right']:
    node=OxmlElement('w:'+edge);node.set(qn('w:w'),'85');node.set(qn('w:type'),'dxa');margins.append(node)
   pr.append(margins)
   borders=OxmlElement('w:tcBorders')
   for edge in ['top','left','bottom','right']:
    b=OxmlElement('w:'+edge);b.set(qn('w:val'),'single');b.set(qn('w:sz'),'4');b.set(qn('w:color'),'D9D9D9');borders.append(b)
   pr.append(borders)
   for pp in c.paragraphs:
    pp.paragraph_format.space_after=Pt(1);pp.paragraph_format.line_spacing=1.05
    for r in pp.runs:r.font.size=Pt(size);r.font.bold=j==0;r.font.color.rgb=RGBColor.from_string('FFFFFF' if j==0 else '182A31')
  trpr=row._tr.get_or_add_trPr();cant=OxmlElement('w:cantSplit');trpr.append(cant)
 repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
 return t

def link(label,url):
 pp=p(''); hyp=OxmlElement('w:hyperlink');hyp.set(qn('r:id'),pp.part.relate_to(url,RT.HYPERLINK,is_external=True))
 rr=OxmlElement('w:r');pr=OxmlElement('w:rPr');sz=OxmlElement('w:sz');sz.set(qn('w:val'),'17');pr.append(sz);rr.append(pr);tt=OxmlElement('w:t');tt.text=label;rr.append(tt);hyp.append(rr);pp._p.append(hyp);pp.paragraph_format.space_after=Pt(3)

p('Crypto arbitrage tool', 'Title')
p('How it works and what the evidence supports', 'Subtitle')
p('This guide explains the current BSDEX vs World paper engine, its trading costs and controls, the backtests, and how a bank could test the idea with its own desks. It reflects the code and saved evidence reviewed on 12 October 2026.')
p('The current evidence does not demonstrate a profitable strategy. The small saved quote sample does not cover trading costs, and the corrected seven-day candle backtest loses money. A bank could improve execution and financing, but it would still need to prove a positive return after every cost.')
h2('What the tool actually does')
p('It compares BTC/EUR and ETH/EUR on Bitstamp with Binance BTC/USDT and ETH/USDT converted through a live EUR/USDT book. It simulates buying the cheaper executable side and selling the dearer side. It sends no real orders from this strategy.')
p('“BSDEX” is the product label; the active full-depth pricing path uses Bitstamp. “World / LMAX” uses Binance prices with an assumed LMAX fee schedule. It is not a test of actual BSDEX or LMAX executions.')
h2('The evidence at a glance')
table(['Measure','Current evidence'],[
('Saved quote period','11 Oct 2026, 21:14:33–21:33:55 UTC; 19.35 minutes'),
('Average best executable spread','BTC −0.22 bps; ETH −0.09 bps, before fees'),
('Largest observed executable spread','BTC 1.60 bps; ETH 2.20 bps'),
('Configured default cost gate','About 17 bps on executable prices'),
('Corrected candle test','24 Sep–1 Oct 2026; 7 trades, 7 losses'),
('Candle net result','−€1,547.98; −€1,739.76 after carry')],[2.2,4.55])
h2('How to read these numbers')
p('The quote statistics use roughly €1,000 per leg, full-size VWAP across recorded top-five levels and the better of the two directions at each usable snapshot. VWAP is the average price across book levels, weighted by coin quantity. These are snapshot averages, not executed-trade averages. BTC has 1,049 usable snapshots and ETH 988, out of 1,077 each; the rest lack enough visible depth. No usable snapshot clears even the lower 9 bps cost gate.')
p('The candle result uses €100,000 per leg, the > $250M fee tier and conservative execution costs. These are different sizes and datasets, so the results must not be combined into a single performance claim.')
source('Evidence: saved data/quotes/2026-10-11.csv.gz; independent snapshot calculations; docs/engine-integrity.md. No current live-session trade rate was available at review.')

page('Trading costs and break even')
p('One basis point, or bp, is 0.01%. Ten bps is 0.10%. At €100,000 notional, 1 bp costs €10. The engine pays taker fees on both crypto legs and adds 1 bp once on the USDT leg’s EUR value.')
table(['Configured volume tier','Bitstamp','World fee','FX','Approx gate'],[
('Retail below $5M','40 bps','6 bps','1 bp','47 bps'),('> $5M','12 bps','6 bps','1 bp','19 bps'),('> $20M default','10 bps','6 bps','1 bp','17 bps'),('> $50M','8 bps','6 bps','1 bp','15 bps'),('> $100M','6 bps','4 bps','1 bp','11 bps'),('> $200M','6 bps','3 bps','1 bp','10 bps'),('> $250M','5 bps','3 bps','1 bp','9 bps'),('> $1B aspirational','3 bps','3 bps','1 bp','7 bps')],[2.35,1.1,1.1,.75,1.45],9.5)
p('These are settings in the project, not verified quotes for your account. The World leg’s LMAX fee assumption does not establish the fee Binance would charge. Monthly volume eligibility and negotiated bank pricing must be confirmed.')
h2('The gate uses the actual sides of the market')
p('At the signal, the engine requires: sale price after sell fee > purchase price including buy fee + FX cost per coin. This exact euro comparison is slightly different from simply adding rounded basis points. Bid–ask spread and depth impact already sit inside executable VWAP prices; do not charge them again.')
h2('Candles need an extra execution estimate')
p('The conservative candle model adds 5 bps half-spread on Bitstamp and 1.5 bps on the World leg. Slippage is 2 × (capital per leg / €100,000) bps on each leg. Thus, the estimated total hurdle relative to mids is 17 + 6.5 + 0.04 = 23.54 bps at the default €1,000 size; at €100,000 and the > $250M tier it is 9 + 6.5 + 4 = 19.5 bps. These are approximations, before carry.')
p('“Calibrated” half-spreads use medians from recorded quotes strictly before the test begins. Quote replay uses the recorded books directly and adds no synthetic spread or slippage charge.')
h2('Carry is a separate capital cost')
p('Carry = capital per leg × 4 pools × 2.50% × hours / 8,760. For €100,000 over 168 hours this is €191.78. With seven trades, allocating that carry equally gives €27.40 per trade, or 2.74 bps of €100,000. That allocation changes when trade frequency changes.')
p('The four pools are a funding assumption for cash and coin on two venues, not a calculated regulatory capital requirement. The ECB deposit facility rate is an opportunity-cost reference, not an executable borrowing quote or the bank’s full funding cost.')
source('Code: config.py fee tiers and BT_EXEC_COSTS; bsdex_historical_bt.py _apply_exec_costs and _build_scenario_result. ECB decision of 10 Sep 2026 confirms 2.50% from 16 Sep 2026; source link on page 7.')

page('A complete trade cycle')
p('The intended model uses prefunded inventory on both venues. It buys and sells the same coin quantity at nearly the same time. It aims to capture a price difference immediately; it does not open a position and wait for the z-score to return to zero.')
table(['Stage','What happens'],[
('1  Prepare','Hold cash and crypto where needed. Read fresh Bitstamp, Binance and EURUSDT books.'),
('2  Identify','Choose the direction from executable prices. Check statistical trigger, costs, depth and cooldown.'),
('3  Commit','Save direction, coin quantity, signal prices and fees. Start the 300 ms latency clock.'),
('4  Fill','At the first eligible evaluation tick, walk both current books for the fixed quantity. Book profit or loss.'),
('5  Restore capacity','In a real operation, reconcile positions and restore cash and coin balances across venues before repeated trading.')],[1.3,5.45],10)
h2('An illustrative one BTC trade')
p('Assume the > $250M tier: Bitstamp 5 bps, World 3 bps, FX 1 bp. The buy venue is Bitstamp and the sell venue is the World leg. These prices illustrate the arithmetic; they are not a recorded trade.')
table(['Item','At the signal','At the delayed fill'],[
('Buy price','€100,000','€100,040'),('Sell price after FX conversion','€100,150','€100,020'),('Fixed quantity','1 BTC','1 BTC'),('Gross price difference','+€150','−€20'),('Fees plus FX cost','€90.06','€90.028'),('Net before carry','+€59.94 expected','−€110.028 realized')],[2.55,2.1,2.1],10)
p('Fill fees = €100,040 × 0.0005 + €100,020 × 0.0003 + €100,020 × 0.0001. Signal spread is about +14.99 bps; realized spread is about −2.00 bps. The signal qualified, but the later books reversed. The engine must retain the loss.')
h2('FX conversion follows the trade direction')
p('Selling Binance crypto produces USDT: divide the crypto bid in USDT by the EURUSDT ask to express the sale in EUR. Buying crypto uses the Binance ask divided by the EURUSDT bid. For example, 112,168 USDT / 1.12 = €100,150. The same per-side rate applies to each crypto depth level.')
h2('What the paper cycle still omits')
p('The simulator does not debit real venue balances, execute the FX leg, or rebalance inventories. It books the two crypto legs together. If a later book is stale or too shallow, it records a failed fill with no partial-position P&L. A real one-leg fill, hedge cost, settlement delay and transfer cost remain unmodelled.')
source('Code: bsdex_strategy.py _process_market and _binance_book_usdt_to_eur; simulation.py simulate_arbitrage_trade. Example is illustrative; costs exclude carry and rebalancing.')

page('The quantitative framework in plain language')
p('A z-score asks how unusual the current spread is relative to its recent history. It does not tell you the probability of a profitable fill. A small spread can have a large z-score if recent spreads barely moved.')
p('z = (s − μ) / σ', 'Heading 2')
p('s is the current spread. μ (“mu”) is its recent average. σ (“sigma”) is the typical variation, measured by standard deviation. z is measured in standard deviations. For example, a €5 spread versus a €1 average and €2 standard deviation gives z = 2. The absolute value |z| allows unusual moves in either direction.')
h2('How the live threshold adjusts')
p('θ = clip[0.4 × (1 + 0.05 × v) × 1 / (1 + ln(2)) × (1 + 0.1 × |m|), 0.3, 2.0]')
p('θ (“theta”) is the entry threshold. clip limits it to 0.3–2.0. v is the standard deviation of spread changes divided by the standard deviation of spread levels. m is the sum of the latest five spread changes, in EUR per coin. ln is the natural logarithm. The time-of-day multiplier is 1, so it has no effect.')
table(['Value or term','Meaning in the active live code'],[
('0.4','Base entry threshold before adjustments'),('0.05','Sensitivity to the volatility measure v'),('0.1','Sensitivity to absolute momentum m'),('1 / (1 + ln(2)) ≈ 0.5906','Volume adjustment; the live engine supplies constant volume 1, so this factor is constant'),('0.3 and 2.0','Minimum and maximum permitted threshold'),('10, 30 and 5 samples','Configured volatility, correlation and momentum windows. The processor retains their maximum, 30 samples'),('At least 2 samples','Live statistics begin after two observations; there is no full 30-sample warm-up gate')],[2.35,4.4],9.5)
h2('The rationale and the present limitations')
p('The intended rationale is to demand a more unusual signal when the spread is unstable or moving persistently. This can reduce entries into a moving market. With little volatility or momentum, 0.4 × 0.5906 is below the floor, so the threshold becomes 0.3.')
p('The current volume input contains no observed trading volume. Correlation is returned as zero and does not filter trades. Momentum uses raw EUR values, so BTC and ETH can receive different adjustments solely because their price scales differ. The live mean includes the current observation, while the backtest uses earlier observations only. These choices need validation; “adaptive” is not evidence of predictive value.')
source('Code: enhanced_signals.py update and _calculate_adaptive_threshold; config.py ENHANCED_SIGNAL_SETTINGS; bsdex_strategy.py supplies volume = 1.0. Generic 60-window / 1.2 settings elsewhere do not define this live signal path.')

page('Trade gates and trading frequency')
p('Trades are event-driven. Checking a book frequently does not mean trading frequently. The live loop evaluates about every 50 ms, while the signal statistics update about once a second. Actual frequency depends on all gates passing.')
table(['Gate','What must be true'],[
('Fresh FX and crypto books','EURUSDT and both crypto books must be no older than 5 seconds, measured from local receipt.'),
('Statistical trigger','The absolute live z-score must reach the current adaptive threshold.'),
('Economic edge','Expected executable sale proceeds must exceed purchase cost, both taker fees and the FX cost.'),
('Full-size depth','The chosen buy and sell sides must both fill the proposed coin quantity using visible depth.'),
('Cooldown and pending order','At least 30 seconds since the last live signal for that market; only one pending order per market.'),
('Delayed execution','Fill after at least 300 ms. Stale or insufficient depth produces an explicit failed fill; a negative price outcome still books.')],[2.1,4.65],9.8)
h2('The live engine and backtests are different models')
table(['Setting','Live paper','Candle backtest','Quote backtest'],[
('Signal history','Up to 30 samples\nabout 30 seconds','60 earlier\none-minute bars','Earlier snapshots\nover 60 minutes'),
('Entry threshold','Adaptive\n0.3–2.0','Fixed 1.5','Fixed 1.5'),
('Cooldown','30 seconds','30 minutes','30 minutes'),
('Fill timing','First tick ≥ 300 ms','Next minute bar','First later snapshot\n≥ chosen latency'),
('Execution prices','WS depth VWAP','Closes plus model\nspread and slippage','Recorded top-five\nVWAP')],[1.45,1.7,1.8,1.8],9.3)
p('The live cooldown permits at most about 120 signals per hour per market, as a theoretical ceiling, not a forecast. The backtest cooldown permits at most two per hour per market. Both are much slower in actual trading when the cost gate fails.')
p('The documented seven-day candle test averages one trade per day. The 19-minute quote sample has zero snapshots above even the 9 bps gate, so it offers no qualifying economic opportunity at the measured size. It is too short to run the quote backtest’s 60-minute window or estimate a representative trade rate.')
p('The website’s “same logic” wording should not be read as parameter equivalence. Replay should match the live model before its result is used to forecast live performance. This is a prototype using frequent data updates, not demonstrated high-frequency trading performance.')
source('Code: bsdex_strategy.py; enhanced_signals.py; bsdex_historical_bt.py constants, _rolling_zscore and run_quote_backtest. Failed execution counts are distinct from completed trades.')

page('What the backtests say')
p('The corrected engine decides whether to trade using signal-time information, then books the later fill regardless of profit or loss. The old candle gate read the future fill and filtered out losses. Earlier 100% win-rate results are therefore invalid evidence of profitability.')
table(['Seven-day candle test','Result'],[
('Period and market','24 Sep–1 Oct 2026 UTC; BTC/EUR'),('Assumptions','€100,000 per leg; > $250M tier; conservative costs'),('Completed trades','7; zero winners and seven losers'),('Gross after model execution prices','−€918.4255'),('Venue fees plus FX cost','€629.5510, including €69.9898 FX cost'),('Net before carry','−€1,547.9764'),('Carry / net after carry','€191.7808 / −€1,739.7572'),('Max drawdown / Sharpe','€1,547.9764 / n/a')],[2.7,4.05],10)
p('These figures come from the project’s documented public-data verification on 11 October. They are model results, not account statements. They differ from the external audit estimate. The original audit export was not available for an exact reconciliation.')
h2('Why it is not generating money')
p('First, the observed executable price differences are too small for the configured fees. The quote sample averages below zero before fees, and its maxima of 1.60 and 2.20 bps are below even the aspirational 7 bps tier. Lowering the z-score threshold cannot change this arithmetic.')
p('Second, an apparent edge can disappear during execution. The seven-day candle test already has negative gross results before exchange fees and FX cost. Cheaper fees alone would not turn that particular run profitable. The one-minute fill lag is much longer than the live 300 ms model, so it diagnoses sensitivity rather than predicting exact live losses.')
p('Third, previous profit claims benefited from the future-price gate and an ECB daily FX reference used as though it were executable. Fresh EURUSDT sides remove that currency-price distortion. A statistical outlier still needs a tradeable, persistent edge.')
h2('How to interpret the two backtest sources')
p('Candles are an approximation: last-trade closes can be stale and do not show tradeable depth. Quote replay is more relevant, but one-second recording cannot reproduce a 300 ms path. It normally fills one second later and reports large data gaps or missing depth as failures. The saved 19-minute dataset is insufficient for a quote performance conclusion.')
p('Sharpe = average daily return / daily-return standard deviation × √365. √365 annualises daily variability. The report includes idle days and hides Sharpe below 30 trades or 20 days. A seven-day test cannot support an annualised performance claim.')
source('Evidence: docs/engine-integrity.md; ENGINE_INTEGRITY_FIXES.md; bsdex_historical_bt.py; recorded-quote calculations. Rounding can create a €0.0001 difference between displayed gross minus fees and net.')

page('What a bank could improve')
p('A bank can reduce some frictions, share infrastructure and manage risks the prototype omits. These are capabilities to test with the relevant desks, not benefits already secured or guarantees of profit.')
table(['Desk or team','Potential improvement','Constraint that remains'],[
('Digital assets and electronic execution','Use actual institutional quotes and contracted fees; direct connectivity; measure latency, rejects and one-leg fills.','Small or fleeting spreads may still have no edge. Better access has a cost.'),
('FX desk','Quote executable currency conversion, net currency flows and test native-EUR routes where available.','EUR/USD is not EUR/USDT. Stablecoin basis, liquidity and counterparty risk remain.'),
('Treasury and money markets','Pool funding, set real transfer prices and manage cash buffers and collateral.','Bank funding is not free; regulatory, liquidity and balance-sheet charges need allocation.'),
('Financing and hedging desks','Where permitted, arrange crypto inventory or approved hedges and plan rebalancing.','Borrow availability, basis, funding rates and hedge slippage can consume the spread.'),
('Custody and operations with risk','Control venue exposure, reconcile balances and manage settlement, transfers and kill switches.','Settlement and venue failure cannot be removed by internal accounting.')],[1.5,2.8,2.45],9.3)
h2('A decision rule for further investment')
p('Continue as a measured paper pilot. Use the same signal, timing and sizing rules in replay and live. Collect a longer, gap-audited quote history and measure signal-to-fill decay with actual institutional venue and FX prices. Add inventory, partial fills, rebalancing and funding costs before risking capital.')
p('Proceed only if net results remain positive out of sample after contracted fees, execution shortfall, FX, funding and rebalancing, with acceptable loss and failed-fill limits. Do not lower gates simply to manufacture trades. In the observed quote sample, faster execution alone cannot overcome a 9–17 bps fee hurdle.')
h2('Sources and scope')
p('Project sources: config.py; bsdex_strategy.py; enhanced_signals.py; simulation.py; bsdex_historical_bt.py; quote_data.py and quote_recorder.py; docs/engine-integrity.md; ENGINE_INTEGRITY_FIXES.md. Active code takes precedence over outdated comments and older reports. Source snapshot and calculations accompany the private build record.')
link('ECB monetary policy decision, 10 September 2026 — 2.50% deposit facility rate', 'https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html')
link('BIS supervisory guidance — FX settlement risk and payment versus payment', 'https://www.bis.org/publ/bcbs241.pdf')
link('LMAX Digital — institutional trading model and venue access', 'https://www.lmaxdigital.com/trading/')
p('The ECB reference supports the carry assumption, not a bank funding quote. BIS guidance supports controlling settlement exposure; it does not imply that a crypto or USDT trade qualifies for conventional FX payment-versus-payment services. Bank improvements above are proposals, not verified arrangements.')
source('Prepared from the current workspace on 12 October 2026. The local backend was not reachable during this review; saved quote evidence ends at 21:33:55 UTC on 11 October. No new live P&L or long-run quote result is claimed.')

doc.core_properties.title='Crypto arbitrage tool explainer guide'
doc.core_properties.subject='Operating model, quantitative framework, evidence and bank implementation options'
doc.core_properties.author=''
out=ROOT/'output/Crypto_Arbitrage_Explainer_Guide.docx';doc.save(out);print(out)
