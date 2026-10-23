"""Build the one-page research note as HTML with inline SVG charts.

Usage: python build_memo.py <chart_data.json> <out.html>
Then print to A4 PDF with render_pdf.js (Chromium).
All figures come from chart_data.json (see build_chart_data.py for sources).
"""
import io
import json
import sys
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

D = json.load(open(sys.argv[1]))
OUT = sys.argv[2]

INK, TEAL, MUTED, LINE, PALE, RED = "#18313B", "#173C4A", "#53656D", "#D6DFE2", "#EDF3F4", "#A33639"
S1, S2, S3 = "#2F5D8A", "#B7791F", "#2F7D6D"
plt.rcParams.update({
    "font.family": "Inter", "font.size": 6.5, "axes.edgecolor": LINE, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.grid": True, "grid.color": LINE, "grid.linewidth": 0.5,
    "axes.axisbelow": True, "svg.fonttype": "none", "legend.frameon": False,
})


def svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):]


def r1(v):
    """One decimal, half away from zero, matching JavaScript toFixed in the deck."""
    from decimal import Decimal, ROUND_HALF_UP
    return str(Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fmt_signed(v):
    return ("+" if v >= 0 else "") + r1(v).replace("-", "−")


# ── Chart 0: one year on €40k ───────────────────────────────────────────────
def chart_compare():
    rows = D["compare_40k"]
    colors = [TEAL, S1, S2, S3]
    labels = ["Bank deposit, 2.5%", "1  Cross-exchange spot", "2  Perpetual carry", "3  EURC depeg capture"]
    notes = ["€1,000", "€0: no trade clears costs", "€960–1,720 before USD hedge", "€100–300, capacity-capped"]
    fig, ax = plt.subplots(figsize=(3.55, 1.38))
    for i, (r, c) in enumerate(zip(rows, colors)):
        y = len(rows) - 1 - i
        w = max(r["high"] - r["low"], 22)
        ax.barh(y, w, left=r["low"], height=0.5, color=c)
        if i == 2:
            ax.text(r["low"] - 30, y, notes[i], va="center", ha="right", fontsize=6.3, color=MUTED)
        else:
            ax.text(r["low"] + w + 30, y, notes[i], va="center", ha="left", fontsize=6.3, color=MUTED)
    ax.axvline(1000, color=INK, lw=0.9, ls=(0, (3, 2)))
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels[::-1], fontsize=6.8)
    for t, c in zip(ax.get_yticklabels(), colors[::-1]):
        t.set_color(c)
        t.set_fontweight("bold")
    ax.set_xlim(0, 2050)
    ax.set_xticks([0, 500, 1000, 1500, 2000])
    ax.set_xticklabels(["€0", "€500", "€1,000", "€1,500", "€2,000"])
    ax.grid(axis="y", visible=False)
    ax.tick_params(length=0)
    return svg(fig)


# ── Chart 1: gap by order size vs break-even ────────────────────────────────
def chart_s1():
    b = D["s1"]["by_size"]
    x = range(len(b["sizes"]))
    fig, ax = plt.subplots(figsize=(2.25, 1.45))
    ax.bar([i - 0.19 for i in x], b["btc_median"], width=0.38, color=S1, label="BTC median gap")
    ax.bar([i + 0.19 for i in x], b["eth_median"], width=0.38, color="#8FB3D9", label="ETH median gap")
    ax.axhline(17, color=RED, lw=1.1, ls=(0, (4, 2)))
    ax.axhline(9, color="#D98C8E", lw=1.1, ls=(0, (4, 2)))
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.text(3.45, 17.6, "Break-even, default tier 17", ha="right", fontsize=5.8, color=RED)
    ax.text(3.45, 9.6, "> $250M tier 9", ha="right", fontsize=5.8, color="#B5686A")
    ax.set_xticks(list(x))
    ax.set_xticklabels(b["sizes"])
    ax.set_ylim(-10, 21)
    ax.set_ylabel("bps", fontsize=6)
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 0.36), fontsize=5.6, ncol=2, handlelength=1, columnspacing=0.8, borderaxespad=0.1)
    return svg(fig)


# ── Chart 2: rolling funding ────────────────────────────────────────────────
def chart_s2():
    fig, ax = plt.subplots(figsize=(2.25, 1.45))
    for key, col, lw in (("Kraken BTC", S2, 1.2), ("Deribit BTC", "#E2B66B", 1.0)):
        r = D["s2"]["rolling30"][key]
        ax.plot([date.fromisoformat(d) for d in r["dates"]], r["values"], color=col, lw=lw, label=key)
    ax.axhline(D["s2"]["deposit_pct"], color=INK, lw=0.9)
    ax.axhline(D["s2"]["needed_pct"], color=RED, lw=0.9, ls=(0, (4, 2)))
    first = date.fromisoformat(D["s2"]["rolling30"]["Kraken BTC"]["dates"][0])
    ax.text(first, D["s2"]["needed_pct"] + 0.5, "≈7% needed", fontsize=5.8, color=RED, bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    ax.text(first, D["s2"]["deposit_pct"] - 1.3, "deposit 2.5%", fontsize=5.8, color=INK, bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylim(-5, 10)
    ax.set_yticks([-4, 0, 4, 8])
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    ax.legend(loc="lower right", fontsize=5.6, handlelength=1, borderaxespad=0.1)
    return svg(fig)


# ── Chart 3: EURC daily low ─────────────────────────────────────────────────
def chart_s3():
    k = D["s3"]["kraken_daily"]
    xs = [date.fromisoformat(d) for d in k["dates"]]
    fig, ax = plt.subplots(figsize=(2.25, 1.45))
    ax.fill_between(xs, k["low"], 1.0, color=S3, alpha=0.18, lw=0)
    ax.plot(xs, k["low"], color=S3, lw=0.8)
    ax.axhline(0.9925, color=RED, lw=0.9, ls=(0, (4, 2)))
    ax.text(xs[len(xs) // 2], 0.9605, "bid at 0.9925 (dashed)", ha="center", fontsize=5.8, color=RED, bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    ax.set_ylim(0.95, 1.003)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"€{v:.2f}"))
    ax.grid(axis="x", visible=False)
    ax.tick_params(length=0)
    return svg(fig)


k2 = D["s2"]["stats"]
lad = {f'{r["level"]:.4f}': r for r in D["s3"]["ladder_kraken_fee_020"]}
s3 = D["s3"]

cards = [
    dict(n=1, color=S1, name="Cross-exchange spot arbitrage",
         how="Buy BTC or ETH on the cheaper exchange and sell on the dearer one at the same moment. "
             "Bitstamp (EUR) vs Binance (USDT, in EUR).",
         chart=chart_s1(), cap="Median gap after crossing both books, 4-hour live run, 14 Oct",
         kpis=[("0 trades", "in 4 live hours at €100k per leg"),
               ("0 of 136", "realistic backtest settings made money"),
               ("+€276 → −€1,548", "the “profitable” backtest after fixing look-ahead, FX and fill bugs")],
         verdict="No edge", why="Gaps are a few bps; costs are 7–47 bps. The rare big gaps were frozen prices lasting ≤ 3 s."),
    dict(n=2, color=S2, name="Perpetual funding carry",
         how="Hold the coin and short its perpetual future so price moves cancel; collect the funding leveraged buyers pay.",
         chart=chart_s2(), cap="Funding earned by the short, 30-day average, % a year",
         kpis=[(f'{r1(k2["Kraken BTC"]["mean_ann_pct"])}% vs 2.5%', f'12-month average funding, Kraken BTC (Deribit {r1(k2["Deribit BTC"]["mean_ann_pct"])}%), in USD'),
               (f'{round(k2["Kraken BTC"]["share_negative_pct"])}% of hours', "negative on Kraken: the short pays"),
               ("€960–1,720", "a year on €40k before the USD hedge, vs €1,000 deposit")],
         verdict="Edge ≈ deposit rate", why="Cheapest venues are closed to EU residents; ESMA called perps “likely CFDs”; 100% of capital sits at an exchange."),
    dict(n=3, color=S3, name="EURC stablecoin depeg capture",
         how="Rest bids below €1 for the euro stablecoin; when a holder dumps into a thin book, buy and sell back near par.",
         chart=chart_s3(), cap="EURC/EUR daily low on Kraken, last 12 months",
         kpis=[(f'{s3["kraken_days_below_09925"]} days', f'below €0.9925 on Kraken (low €{s3["kraken_min_low"]})'),
               (f'{fmt_signed(lad["0.9900"]["ann_pct"])}% a year', f'resting bid at 0.99 after fees, {lad["0.9900"]["fills"]} fills (candles: size unproven)'),
               ("€100–300", "a year, realistic: ≈2.5k EURC per sweep on the live tape")],
         verdict="Real edge, tiny capacity", why="Live test 22 Oct: market making −€29, cross-venue −39 bps; the deep bid made +€12 on one sweep."),
]

card_html = ""
for c in cards:
    kp = "".join(f'<div class="kpi"><b style="color:{c["color"]}">{v}</b><span>{t}</span></div>' for v, t in c["kpis"])
    card_html += f"""
    <section class="card">
      <h3><i style="background:{c['color']}">{c['n']}</i>{c['name']}</h3>
      <p class="how">{c['how']}</p>
      <div class="chart">{c['chart']}</div>
      <p class="cap">{c['cap']}</p>
      {kp}
      <p class="verdict"><b style="background:{c['color']}">{c['verdict']}</b></p>
      <p class="why">{c['why']}</p>
    </section>"""

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Three crypto arbitrage strategies against a 2.5% deposit</title>
<style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Inter, Arial, sans-serif; color: {INK}; font-size: 8.4pt; line-height: 1.32; }}
.page {{ width: 210mm; height: 297mm; padding: 11mm 12mm 9mm; display: flex; flex-direction: column; gap: 3.2mm; }}
.kicker {{ font-size: 7.2pt; font-weight: 700; letter-spacing: .06em; color: {MUTED}; }}
h1 {{ font-size: 16.5pt; line-height: 1.12; color: {TEAL}; margin-top: 1mm; letter-spacing: -.01em; }}
.by {{ font-size: 7.6pt; color: {MUTED}; margin-top: 1.2mm; }}
.by b {{ color: {INK}; }}
.intro {{ display: grid; grid-template-columns: 1fr 1.2fr; gap: 5mm; background: {PALE}; padding: 3.5mm 4mm; }}
.intro h2 {{ font-size: 8.6pt; color: {TEAL}; margin-bottom: 1mm; }}
.intro p {{ font-size: 8.2pt; }}
.intro p + p {{ margin-top: 1.4mm; }}
.intro .q {{ font-weight: 700; color: {TEAL}; }}
.compare h2 {{ font-size: 8.6pt; color: {TEAL}; margin-bottom: .6mm; }}
.compare svg {{ width: 100%; height: auto; display: block; }}
.cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 3.5mm; }}
.card {{ border: 1px solid {LINE}; padding: 3mm 3mm 2.6mm; display: flex; flex-direction: column; }}
.card h3 {{ font-size: 9pt; color: {TEAL}; display: flex; align-items: center; gap: 2mm; line-height: 1.15; min-height: 8mm; }}
.card h3 i {{ font-style: normal; color: #fff; font-size: 8pt; width: 5.2mm; height: 5.2mm; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: none; }}
.how {{ font-size: 7.6pt; color: {MUTED}; margin-top: 1mm; min-height: 12mm; }}
.chart svg {{ width: 100%; height: auto; display: block; margin-top: 1mm; }}
.cap {{ font-size: 6.6pt; color: {MUTED}; margin: .4mm 0 1.6mm; }}
.kpi {{ padding: 1.1mm 0; border-top: 1px solid {LINE}; }}
.kpi b {{ display: block; font-size: 10pt; line-height: 1.15; }}
.kpi span {{ display: block; font-size: 7.1pt; line-height: 1.25; }}
.verdict {{ margin-top: 1.8mm; }}
.verdict b {{ color: #fff; font-size: 8pt; padding: .9mm 2.2mm; border-radius: 1mm; display: inline-block; }}
.why {{ font-size: 7.2pt; margin-top: 1.4mm; color: {INK}; }}
.bottom {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }}
.decision {{ background: {TEAL}; color: #fff; padding: 3.2mm 4mm; }}
.decision h2 {{ font-size: 10pt; margin-bottom: 1.2mm; }}
.decision p, .decision li {{ font-size: 7.8pt; color: #DCE7EA; }}
.decision ul {{ margin: 1mm 0 0 3.5mm; }}
.decision li b {{ color: #fff; }}
.useful {{ border: 1px solid {LINE}; padding: 3.2mm 4mm; }}
.useful h2 {{ font-size: 9pt; color: {TEAL}; margin-bottom: 1.2mm; }}
.useful li {{ font-size: 7.8pt; margin: 0 0 1mm 3.5mm; }}
.useful .ask {{ font-weight: 700; color: {TEAL}; margin-top: 1.6mm; font-size: 8pt; }}
.notes {{ font-size: 6.4pt; color: {MUTED}; line-height: 1.3; margin-top: auto; }}
</style></head><body><div class="page">
<header>
  <div class="kicker">RESEARCH NOTE  ·  23 OCTOBER 2026</div>
  <h1>Three crypto arbitrage strategies against a 2.5% deposit.<br>None beats it by enough to justify the risk.</h1>
  <div class="by"><b>Syed Zee Waqar Hussain</b>  ·  personal research, May 2025 – October 2026  ·  paper trading on live public market data, no orders sent</div>
</header>
<div class="intro">
  <div>
    <h2>The question and how it evolved</h2>
    <p class="q">Can any crypto arbitrage beat a 2.5% EUR bank deposit once every fee, spread, currency, funding and idle-capital cost is paid?</p>
    <p>It began in 2025 as a Binance–Kraken prototype with live paper trading. In 2026 it became an institutional model of a German EUR venue (BSDEX, proxied by Bitstamp) against global USDT liquidity, with bank fee tiers, live FX and full-depth pricing. After an audit and a 4-hour live run, I tested the two strongest alternatives: perpetual funding carry and EURC stablecoin depegs.</p>
  </div>
  <div class="compare"><h2>What €40k would have earned in a year</h2>{chart_compare()}</div>
</div>
<div class="cards">{card_html}</div>
<div class="bottom">
  <div class="decision">
    <h2>Decision: deploy none. The €40k stays in the deposit.</h2>
    <p>What would make each worth revisiting:</p>
    <ul>
      <li><b>1</b> A maker-only design with a near-free hedge, e.g. against internal client flow.</li>
      <li><b>2</b> 90-day funding above ≈7%, sustained, plus clarity on ESMA’s CFD view.</li>
      <li><b>3</b> Free par redemption of EURC, or Bitvavo volume above €100k a day.</li>
    </ul>
  </div>
  <div class="useful">
    <h2>Where the work is useful now</h2>
    <ul>
      <li><b>Best execution.</b> MiCA Art. 78 requires firms to check their venues regularly; the tool measures spread, depth, freshness and latency per venue, live.</li>
      <li><b>Euro stablecoins.</b> Evidence of how thin secondary EUR markets are, and how often EURC trades below par.</li>
      <li><b>Model validation.</b> A checklist of the backtest errors that made a losing strategy look perfect.</li>
    </ul>
    <p class="ask">Happy to walk you through the data in 20 minutes.</p>
  </div>
</div>
<p class="notes">Sources and method: cross-exchange figures from the 4-hour live campaign (14 Oct 2026, 49,825 order-book snapshots per coin) and the verified backtest (BTC/EUR, 24 Sep–1 Oct 2026, €100k per leg); Bitstamp stands in for BSDEX and an LMAX fee model is applied; institutional fee tiers are assumptions. Funding: Kraken Futures and Deribit public history to 22 Oct 2026; the €960–1,720 range assumes OKX EEA, maker on both legs and two round trips a year, before hedging the dollar exposure. EURC: Kraken daily candles to 22 Oct 2026; the resting-bid backtest charges 0.20% on both legs and sells at 0.9995; candle lows show that a price printed, not that size was available. Live EURC session: 22 Oct 2026, 2.6 h, Bitvavo, Kraken and Bitstamp. All P&L is simulated. 1 bp = 0.01%.</p>
</div></body></html>"""

open(OUT, "w", encoding="utf-8").write(html)
print("saved", OUT)
