"""Build the one-page research memo (DOCX). Convert to PDF with LibreOffice.

Every figure below comes from docs/BSDEX_Explainer_Guide.html (4-hour live test,
14 Oct 2026; integrity before/after, 24 Sep-1 Oct 2026; backtest sweep 7-14 Oct
2026) or docs/eurc_live_test_results.md (EURC session, 22 Oct 2026).
"""
import sys
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x18, 0x31, 0x3B)
TEAL = RGBColor(0x17, 0x3C, 0x4A)
MUTED = RGBColor(0x53, 0x65, 0x6D)
RED = RGBColor(0xA3, 0x36, 0x39)
PALE = "EDF3F4"
LINE = "D6DFE2"

out = sys.argv[1]
doc = Document()

sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
sec.top_margin = sec.bottom_margin = Cm(1.4)
sec.left_margin = sec.right_margin = Cm(1.8)

normal = doc.styles["Normal"]
normal.font.name = "Arial"
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
normal.font.size = Pt(10)
normal.font.color.rgb = INK
normal.paragraph_format.space_after = Pt(0)
normal.paragraph_format.line_spacing = 1.12

doc.core_properties.title = "Can EUR crypto price gaps be traded at a profit?"
doc.core_properties.author = "Syed Zee Waqar Hussain"


def para(text="", size=9.5, color=INK, bold=False, after=0, before=0, italic=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    if text:
        r = p.add_run(text)
        r.font.size, r.font.color.rgb, r.bold, r.italic = Pt(size), color, bold, italic
    return p


def run(p, text, bold=False, color=INK, size=10):
    r = p.add_run(text)
    r.bold, r.font.color.rgb, r.font.size = bold, color, Pt(size)
    return r


def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def borders(table, color=LINE, inside=True):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    edges = ["top", "left", "bottom", "right"] + (["insideH", "insideV"] if inside else [])
    for edge in edges:
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def cell_margins(table, top=60, bottom=60, left=100, right=100):
    tblPr = table._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for k, v in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        e = OxmlElement(f"w:{k}")
        e.set(qn("w:w"), str(v))
        e.set(qn("w:type"), "dxa")
        m.append(e)
    tblPr.append(m)


# ── Header ────────────────────────────────────────────────────────────────
para("RESEARCH NOTE  ·  23 OCTOBER 2026", size=8, color=MUTED, bold=True, after=3)
para("Can EUR crypto price gaps be traded at a profit?", size=17, color=TEAL, bold=True, after=1)
para("One year of testing says no. The measurements are still useful.", size=11.5, color=MUTED, after=3)
p = para(after=7)
run(p, "Syed Zee Waqar Hussain", bold=True, size=8.5)
run(p, "  ·  personal research, May 2025 – Oct 2026  ·  paper trading only, public market data, "
       "no orders sent", color=MUTED, size=8.5)

# ── Bottom line box ───────────────────────────────────────────────────────
box = doc.add_table(rows=1, cols=1)
box.alignment = WD_TABLE_ALIGNMENT.CENTER
cell_margins(box, 110, 110, 160, 160)
c = box.rows[0].cells[0]
shade(c, PALE)
cp = c.paragraphs[0]
run(cp, "Bottom line. ", bold=True, color=TEAL)
run(cp, "I built and tested a system that buys a coin on one exchange and sells it on another "
        "when their prices differ. After every real cost (fees on both trades, crossing the "
        "bid-ask spread, the EUR/USDT conversion, a 300 ms fill delay and idle capital) there was "
        "no edge to trade. I stopped before any capital was at risk. What remains useful is the "
        "data on what EUR crypto execution really costs.")

# ── What I tested ─────────────────────────────────────────────────────────
para("What I tested", size=10.5, color=TEAL, bold=True, before=8, after=2)
para("BTC and ETH on Bitstamp (EUR, as a stand-in for a German EUR venue such as BSDEX) against "
     "Binance (USDT, converted to EUR at the live rate), with a Bitstamp–Kraken control pair; and the "
     "EURC euro stablecoin on Bitvavo, Kraken and Bitstamp. Methods: one-minute backtests, replays of "
     "recorded order books, and two live paper sessions with pass/fail rules written in advance.")

# ── Findings table ────────────────────────────────────────────────────────
para("Four findings", size=10.5, color=TEAL, bold=True, before=8, after=3)
rows = [
    ("1  The gap is smaller than the cost",
     "Live paper run, 4 h on 14 Oct, €100k per leg: the median gap after crossing both order books was "
     "−2.3 bps (BTC) and −4.1 bps (ETH). Break-even is 17 bps at the default fee tier, 9 bps above "
     "$250M monthly volume and 47 bps at retail fees. Result: 0 trades."),
    ("2  The big gaps were not real",
     "The 14 moments that beat break-even lasted 3 seconds at most (0.05% of the time). They appeared "
     "only while one venue's prices froze during a fast move."),
    ("3  The profitable backtest was three bugs",
     "Before fixes: 5 trades, 100% winners, +€276. After fixing look-ahead, the FX source (the daily ECB "
     "rate was 44 bps away from live EUR/USDT) and instant fills: 7 trades, 0 winners, −€1,548 "
     "(−€1,740 after funding cost). On a second week, 0 of 136 realistic settings made money."),
    ("4  Euro stablecoin markets are thin; fees dominate",
     "EURC session, 22 Oct: Kraken's 2 bps spread sits under a 20 bps fee; Bitvavo trades a median of "
     "about 6,500 EURC a day; the best cross-venue trade at €10k netted −39 bps. It failed every "
     "pre-set criterion it could be judged on."),
]
t = doc.add_table(rows=len(rows), cols=2)
t.alignment = WD_TABLE_ALIGNMENT.CENTER
t.autofit = False
borders(t)
cell_margins(t, 70, 70, 110, 110)
widths = (Cm(4.6), Cm(12.8))
grid = t._tbl.tblGrid
for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
    gc.set(qn("w:w"), str(int(w.twips)))
for i, (head, body) in enumerate(rows):
    a, b = t.rows[i].cells
    a.width, b.width = widths
    shade(a, PALE)
    run(a.paragraphs[0], head, bold=True, color=TEAL, size=9.5)
    run(b.paragraphs[0], body, size=9.5)

# ── Decision ──────────────────────────────────────────────────────────────
p = para(before=8, after=0)
run(p, "Decision: not deployed. ", bold=True, color=RED, size=10)
run(p, "The test capital stays in a 2.5% deposit. The market is already arbitraged to within a few "
       "basis points: a strategy that pays spreads and fees cannot win; only one that earns them might.")

# ── Where it is useful ────────────────────────────────────────────────────
para("Where this is useful now", size=10.5, color=TEAL, bold=True, before=8, after=2)
uses = [
    ("Execution quality. ",
     "MiCA (Art. 78) requires firms executing client crypto orders to seek the best result and to check "
     "their venues regularly. The tool measures each venue's spread, depth, freshness and latency live."),
    ("Euro stablecoins. ",
     "As banks prepare euro stablecoins, EURC shows how thin secondary EUR markets can be: on 28 of the "
     "last 366 days, Bitvavo traded below 0.9925."),
    ("Model validation. ",
     "A short checklist of the backtest errors that made a losing strategy look perfect."),
    ("The one design worth testing next. ",
     "Quoting passively and hedging at near-zero cost, for example against internal client flow. That "
     "needs an institution's real fees and flows."),
]
for head, body in uses:
    bp = doc.add_paragraph(style="List Bullet")
    bp.paragraph_format.space_after = Pt(2)
    bp.paragraph_format.left_indent = Cm(0.55)
    bp.paragraph_format.first_line_indent = Cm(-0.4)
    run(bp, head, bold=True)
    run(bp, body)

p = para(before=7, after=0)
run(p, "I'd value 20 minutes to walk you through the data, or to hear where it could help your work.",
    bold=True, color=TEAL)

# ── Method notes ──────────────────────────────────────────────────────────
para("Method notes: Bitstamp is a proxy for BSDEX (its API needs keys); the global leg uses Binance prices "
     "with an LMAX fee model; institutional fee tiers are assumptions, not quoted rates. The live sessions "
     "ran 4 h (14 Oct) and 2.6 h (22 Oct): the direction is clear, exact figures are not final. All P&L is "
     "simulated. 1 bp = 0.01%.", size=7.5, color=MUTED, before=9)

doc.save(out)
print("saved", out)
