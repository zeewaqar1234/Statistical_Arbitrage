"""
Generate a professional PDF documenting all quantitative models
and equations used in the Crypto HFT Tool.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import textwrap

FONT_TITLE = {"fontsize": 22, "fontweight": "bold", "fontfamily": "serif", "color": "#1a1a2e"}
FONT_SECTION = {"fontsize": 15, "fontweight": "bold", "fontfamily": "serif", "color": "#16213e"}
FONT_SUBSECTION = {"fontsize": 12, "fontweight": "bold", "fontfamily": "serif", "color": "#0f3460"}
FONT_BODY = {"fontsize": 9.5, "fontfamily": "serif", "color": "#2c2c2c"}
FONT_EQ_LABEL = {"fontsize": 9, "fontfamily": "serif", "color": "#555555", "style": "italic"}
FONT_FOOTER = {"fontsize": 7.5, "fontfamily": "serif", "color": "#999999"}

PAGE_W, PAGE_H = 8.5, 11
MARGIN_L, MARGIN_R = 0.9, 0.9
MARGIN_T, MARGIN_B = 0.85, 0.7
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R

matplotlib.rcParams["mathtext.fontset"] = "cm"


class PDFWriter:
    def __init__(self, filename):
        self.pdf = PdfPages(filename)
        self.page_num = 0
        self.fig = None
        self.y = 0
        self._new_page()

    def _new_page(self):
        if self.fig is not None:
            self._finish_page()
        self.fig = plt.figure(figsize=(PAGE_W, PAGE_H))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, PAGE_W)
        self.ax.set_ylim(0, PAGE_H)
        self.ax.axis("off")
        self.y = PAGE_H - MARGIN_T
        self.page_num += 1

    def _finish_page(self):
        self.ax.text(
            PAGE_W / 2, 0.35,
            f"— {self.page_num} —",
            ha="center", va="center", **FONT_FOOTER
        )
        self.pdf.savefig(self.fig, dpi=150)
        plt.close(self.fig)

    def _ensure_space(self, needed):
        if self.y - needed < MARGIN_B:
            self._new_page()

    def close(self):
        if self.fig is not None:
            self._finish_page()
        self.pdf.close()

    def add_cover(self):
        self.ax.text(
            PAGE_W / 2, PAGE_H * 0.62,
            "Quantitative Models &\nMathematical Framework",
            ha="center", va="center",
            fontsize=26, fontweight="bold", fontfamily="serif",
            color="#1a1a2e", linespacing=1.6
        )
        self.ax.plot(
            [PAGE_W * 0.25, PAGE_W * 0.75],
            [PAGE_H * 0.535, PAGE_H * 0.535],
            color="#0f3460", linewidth=1.5
        )
        self.ax.text(
            PAGE_W / 2, PAGE_H * 0.49,
            "Crypto HFT Tool",
            ha="center", va="center",
            fontsize=16, fontfamily="serif", color="#0f3460", style="italic"
        )
        self.ax.text(
            PAGE_W / 2, PAGE_H * 0.43,
            "A comprehensive reference of all statistical, financial,\n"
            "and risk models implemented in the trading system.",
            ha="center", va="center",
            fontsize=10, fontfamily="serif", color="#555555", linespacing=1.6
        )
        self.ax.text(
            PAGE_W / 2, PAGE_H * 0.12,
            "Generated from source code analysis  •  March 2026",
            ha="center", va="center",
            fontsize=8.5, fontfamily="serif", color="#999999"
        )
        self._new_page()

    def section(self, title):
        self._ensure_space(0.65)
        self.y -= 0.25
        self.ax.plot(
            [MARGIN_L, PAGE_W - MARGIN_R],
            [self.y + 0.22, self.y + 0.22],
            color="#0f3460", linewidth=0.8, alpha=0.4
        )
        self.ax.text(MARGIN_L, self.y, title, **FONT_SECTION)
        self.y -= 0.35

    def subsection(self, title):
        self._ensure_space(0.55)
        self.y -= 0.12
        self.ax.text(MARGIN_L + 0.05, self.y, title, **FONT_SUBSECTION)
        self.y -= 0.3

    def equation(self, tex, label=None):
        self._ensure_space(0.65)
        self.ax.text(
            PAGE_W / 2, self.y,
            f"${tex}$",
            ha="center", va="top",
            fontsize=13, fontfamily="serif", color="#1a1a2e"
        )
        self.y -= 0.35
        if label:
            self.ax.text(
                PAGE_W - MARGIN_R, self.y + 0.08,
                label, ha="right", va="top", **FONT_EQ_LABEL
            )
        self.y -= 0.1

    def body(self, text, indent=0):
        wrapper = textwrap.TextWrapper(width=88 - int(indent * 8))
        lines = wrapper.wrap(text)
        line_h = 0.19
        self._ensure_space(line_h * len(lines) + 0.05)
        for line in lines:
            self.ax.text(
                MARGIN_L + 0.05 + indent * 0.25, self.y,
                line, **FONT_BODY
            )
            self.y -= line_h
        self.y -= 0.04

    def component(self, symbol, description):
        self._ensure_space(0.22)
        self.ax.text(
            MARGIN_L + 0.25, self.y,
            f"${symbol}$",
            fontsize=10, fontfamily="serif", color="#0f3460",
            va="top"
        )
        wrapper = textwrap.TextWrapper(width=68)
        lines = wrapper.wrap(f"  —  {description}")
        for i, line in enumerate(lines):
            self.ax.text(
                MARGIN_L + 1.05, self.y - i * 0.17,
                line, fontsize=9, fontfamily="serif", color="#444444",
                va="top"
            )
        self.y -= max(0.19, 0.17 * len(lines) + 0.04)

    def vspace(self, h=0.15):
        self.y -= h


def build_pdf():
    w = PDFWriter("Quantitative_Models_Reference.pdf")

    # ── Cover ──
    w.add_cover()

    # ══════════════════════════════════════════════════════════════
    #  1. MEAN-REVERSION SIGNALS
    # ══════════════════════════════════════════════════════════════
    w.section("1.  Statistical Arbitrage — Mean-Reversion Signals")

    w.subsection("1.1  Rolling Z-Score")
    w.body(
        "The core signal measures how far the current cross-exchange spread "
        "deviates from its rolling mean, expressed in standard-deviation units. "
        "A high absolute z-score indicates a potential mean-reversion opportunity."
    )
    w.equation(
        r"z = \frac{x_t \;-\; \bar{x}_w}{\sigma_w}",
        label="(1)"
    )
    w.component(r"x_t", "Current spread observation (bid₁ − ask₂)")
    w.component(r"\bar{x}_w", "Rolling mean of spread over window w")
    w.component(r"\sigma_w", "Rolling sample standard deviation (ddof = 1) over window w")
    w.vspace(0.08)
    w.body(
        "Multiple window lengths are evaluated simultaneously — "
        "w ∈ {15, 60, 180, 360} — to capture signals across time horizons."
    )

    w.subsection("1.2  Volatility-Adjusted Z-Score")
    w.body(
        "The raw z-score is scaled by a volatility adjustment factor that "
        "compares recent volatility to full-window volatility, preventing "
        "false signals during regime changes."
    )
    w.equation(
        r"z_{adj} = \frac{x_t - \bar{x}_w}{\sigma_w \;\cdot\; \alpha_v}",
        label="(2)"
    )
    w.equation(
        r"\alpha_v = \mathrm{clip}\!\left(\frac{\sigma_{30}}{\sigma_w},\;\; 0.5,\;\; 2.0\right)",
        label="(3)"
    )
    w.component(r"\sigma_{30}", "Standard deviation of the most recent 30 observations")
    w.component(r"\alpha_v", "Volatility ratio, clamped to [0.5, 2.0]")

    w.subsection("1.3  Volume-Weighted Z-Score")
    w.body(
        "Incorporates trade volume to weight the signal. High-volume deviations "
        "are more meaningful than low-volume ones."
    )
    w.equation(
        r"z_{vw} = z \;\cdot\; \frac{V_t}{\bar{V}}",
        label="(4)"
    )
    w.component(r"V_t", "Current period trade volume")
    w.component(r"\bar{V}", "Rolling average volume over the lookback window")

    w.subsection("1.4  Spread Returns & Momentum")
    w.body(
        "Spread returns and momentum are computed to capture "
        "directional persistence in the spread series."
    )
    w.equation(
        r"r_t = \frac{s_t - s_{t-1}}{s_{t-1}}",
        label="(5)"
    )
    w.equation(
        r"M = \sum_{i=t-k}^{t} r_i",
        label="(6)"
    )
    w.component(r"s_t", "Spread at time t")
    w.component(r"r_t", "Spread return at time t")
    w.component(r"M", "Momentum score over k recent periods")

    # ══════════════════════════════════════════════════════════════
    #  2. ADAPTIVE THRESHOLD
    # ══════════════════════════════════════════════════════════════
    w.section("2.  Adaptive Signal Thresholds")
    w.body(
        "Rather than static z-score entry/exit thresholds, the system dynamically "
        "adjusts thresholds based on current market conditions across four dimensions."
    )
    w.equation(
        r"\tau = \tau_0 \;\cdot\; A_{vol} \;\cdot\; A_{liq} \;\cdot\; A_{time} \;\cdot\; (1 + A_{mom})",
        label="(7)"
    )
    w.vspace(0.05)

    w.body("Volatility adjustment:")
    w.equation(
        r"A_{vol} = 1 + \sigma_{ann} \;\cdot\; \lambda_v",
        label="(8)"
    )

    w.body("Liquidity (volume) adjustment:")
    w.equation(
        r"A_{liq} = \frac{1}{1 + \ln(1 + V_t\,/\,\bar{V})}",
        label="(9)"
    )

    w.body("Momentum impact:")
    w.equation(
        r"A_{mom} = |M| \;\cdot\; 0.1",
        label="(10)"
    )

    w.component(r"\tau_0", "Base threshold from configuration")
    w.component(r"\lambda_v", "Volatility impact scaling factor")
    w.component(r"A_{time}", "Time-of-day factor (configurable)")
    w.body(
        "The final threshold is clamped: τ ∈ [0.5, 5.0]."
    )

    # ══════════════════════════════════════════════════════════════
    #  3. VOLATILITY & CORRELATION
    # ══════════════════════════════════════════════════════════════
    w.section("3.  Volatility & Correlation Estimation")

    w.subsection("3.1  Annualized Volatility")
    w.body(
        "Return volatility is annualized using the square-root-of-time rule, "
        "assuming 252 trading days per year."
    )
    w.equation(
        r"\sigma_{ann} = \mathrm{std}(r_1, r_2, \ldots, r_n) \;\cdot\; \sqrt{252}",
        label="(11)"
    )
    w.component(r"\sigma_{ann}", "Annualized volatility of price or spread returns")

    w.subsection("3.2  Cross-Asset Correlation")
    w.body(
        "Pearson correlation between return series of different trading pairs "
        "is used for portfolio-level risk management."
    )
    w.equation(
        r"\rho_{ij} = \frac{\mathrm{Cov}(r_i,\, r_j)}{\sigma_i \;\cdot\; \sigma_j}",
        label="(12)"
    )
    w.component(r"\rho_{ij}", "Pearson correlation between assets i and j")
    w.component(r"r_i, r_j", "Return series of the two assets")

    # ══════════════════════════════════════════════════════════════
    #  4. RISK MANAGEMENT
    # ══════════════════════════════════════════════════════════════
    w.section("4.  Risk Management Framework")

    w.subsection("4.1  Position Sizing Model")
    w.body(
        "Position size is dynamically adjusted through a multiplicative model "
        "incorporating four independent risk factors."
    )
    w.equation(
        r"Q = Q_0 \;\cdot\; f_{vol} \;\cdot\; f_{sig} \;\cdot\; f_{heat} \;\cdot\; f_{corr}",
        label="(13)"
    )
    w.vspace(0.05)

    w.body("Volatility factor — reduces size in high-volatility environments:")
    w.equation(
        r"f_{vol} = \frac{1}{1 + \sigma_{ann} \;\cdot\; \kappa}",
        label="(14)"
    )

    w.body("Signal strength factor — square-root scaling for diminishing returns:")
    w.equation(
        r"f_{sig} = \sqrt{S}", label="(15)"
    )

    w.body("Portfolio heat factor — reduces exposure as aggregate risk grows:")
    w.equation(
        r"f_{heat} = \frac{1}{1 + H}", label="(16)"
    )

    w.body("Correlation factor — diversification penalty:")
    w.equation(
        r"f_{corr} = \frac{1}{1 + \bar{\rho}}", label="(17)"
    )

    w.component(r"Q_0", "Base position size from configuration")
    w.component(r"\kappa", "Volatility scaling factor")
    w.component(r"S", "Signal strength ∈ [0, 1]")
    w.component(r"H", "Portfolio heat (defined in §4.2)")
    w.component(r"\bar{\rho}", "Average correlation across active positions")

    w.subsection("4.2  Portfolio Heat")
    w.body(
        "Aggregate portfolio risk exposure, expressed as a fraction of notional "
        "portfolio value."
    )
    w.equation(
        r"H = \frac{\sum_{i}\, |q_i \cdot p_i|}{V_{portfolio}}",
        label="(18)"
    )
    w.component(r"q_i", "Position size in asset i")
    w.component(r"p_i", "Current price of asset i")
    w.component(r"V_{portfolio}", "Base portfolio value")

    w.subsection("4.3  Stop-Loss Trigger")
    w.body(
        "A position is liquidated when the spread moves adversely beyond a "
        "configured percentage threshold."
    )
    w.equation(
        r"\Delta_{stop} = \frac{|s_t - s_{entry}|}{|s_{entry}|} > \theta_{SL}",
        label="(19)"
    )
    w.component(r"s_{entry}", "Spread at position entry")
    w.component(r"\theta_{SL}", "Stop-loss threshold (default 2%)")

    w.subsection("4.4  Drawdown Monitoring")
    w.body(
        "Maximum drawdown tracks the largest peak-to-trough decline in "
        "cumulative PnL, used to halt trading if limits are breached."
    )
    w.equation(
        r"DD_t = \frac{P_t^{peak} - PnL_t^{cum}}{|P_t^{peak}|}",
        label="(20)"
    )
    w.component(r"P_t^{peak}", "Running peak of cumulative PnL up to time t")
    w.component(r"PnL_t^{cum}", "Cumulative realized PnL at time t")

    w.subsection("4.5  Value-at-Risk (VaR) Limit")
    w.body(
        "Before opening a new position, the system verifies that total exposure "
        "does not exceed a 1% daily VaR limit."
    )
    w.equation(
        r"VaR_{limit} = 0.01 \;\cdot\; (V_{portfolio} + V_{new})",
        label="(21)"
    )
    w.component(r"V_{new}", "Notional value of the proposed new position")

    # ══════════════════════════════════════════════════════════════
    #  5. ORDER BOOK & EXECUTION
    # ══════════════════════════════════════════════════════════════
    w.section("5.  Order Book Analytics & Execution")

    w.subsection("5.1  Mid Price & Spread")
    w.body(
        "The mid price and cross-exchange spread form the foundation of all "
        "arbitrage calculations."
    )
    w.equation(
        r"P_{mid} = \frac{P_{bid} + P_{ask}}{2}",
        label="(22)"
    )
    w.equation(
        r"S = P_{bid}^{A} - P_{ask}^{B}",
        label="(23)"
    )
    w.component(r"P_{bid}^{A}", "Best bid on exchange A")
    w.component(r"P_{ask}^{B}", "Best ask on exchange B")

    w.subsection("5.2  Spread Ratio")
    w.body(
        "Normalised spread used for threshold-based filtering."
    )
    w.equation(
        r"R_{spread} = \frac{|S|}{P_{avg}}",
        label="(24)"
    )
    w.component(r"P_{avg}", "Average of bid and ask across exchanges")

    w.subsection("5.3  Liquidity Score")
    w.body(
        "Measures whether sufficient order-book depth exists to fill the "
        "desired trade size."
    )
    w.equation(
        r"L = \min\!\left(1,\;\; \frac{\sum_k d_k}{Q_{desired}}\right)",
        label="(25)"
    )
    w.component(r"d_k", "Quantity available at level k in the order book")
    w.component(r"Q_{desired}", "Target fill quantity")

    w.subsection("5.4  Price Impact (VWAP-Based)")
    w.body(
        "Estimated cost of walking the order book, measured as percentage "
        "deviation from the best available price."
    )
    w.equation(
        r"P_{vwap} = \frac{\sum_k p_k \cdot q_k}{\sum_k q_k}",
        label="(26)"
    )
    w.equation(
        r"I = \frac{|P_{vwap} - P_{best}|}{P_{best}}",
        label="(27)"
    )
    w.component(r"p_k, q_k", "Price and quantity at order-book level k")
    w.component(r"P_{best}", "Best bid or ask (reference price)")
    w.component(r"I", "Fractional price impact")

    w.subsection("5.5  Slippage")
    w.body(
        "Post-execution slippage comparing the expected fill price to the "
        "actual executed price."
    )
    w.equation(
        r"\epsilon = \frac{|P_{exec} - P_{expected}|}{P_{expected}}",
        label="(28)"
    )
    w.component(r"P_{exec}", "Actual volume-weighted execution price")
    w.component(r"P_{expected}", "Expected price at order submission")

    w.subsection("5.6  Iceberg Order Sizing")
    w.body(
        "Large orders are split into smaller chunks to minimise market impact. "
        "Chunk size is the lesser of 20% of the order or 10% of visible book depth."
    )
    w.equation(
        r"C = \min\!\left(0.2 \cdot Q,\;\; 0.1 \cdot D_{total}\right)",
        label="(29)"
    )
    w.component(r"C", "Chunk size per child order")
    w.component(r"D_{total}", "Total visible depth in the order book")

    # ══════════════════════════════════════════════════════════════
    #  6. FEE-ADJUSTED PnL
    # ══════════════════════════════════════════════════════════════
    w.section("6.  Fee-Adjusted PnL Calculation")

    w.subsection("6.1  Effective Price After Fees")
    w.body(
        "Execution prices are adjusted for exchange trading fees to reflect "
        "true cost basis."
    )
    w.equation(
        r"P_{eff}^{buy} = P \cdot (1 + \phi)",
        label="(30)"
    )
    w.equation(
        r"P_{eff}^{sell} = P \cdot (1 - \phi)",
        label="(31)"
    )
    w.component(r"\phi", "Exchange fee rate (maker or taker)")

    w.subsection("6.2  Arbitrage Net PnL")
    w.body(
        "The net profit from a completed arbitrage round-trip after deducting "
        "fees on both legs."
    )
    w.equation(
        r"PnL = Q \cdot P_{sell} - Q \cdot P_{buy} - F_{buy} - F_{sell}",
        label="(32)"
    )
    w.equation(
        r"F = Q \cdot P \cdot \phi",
        label="(33)"
    )
    w.component(r"F_{buy}, F_{sell}", "Fee cost on the buy and sell legs")

    w.subsection("6.3  Position Average Price (VWAP)")
    w.body(
        "When adding to an existing position, the average entry price is "
        "updated as a volume-weighted average."
    )
    w.equation(
        r"\bar{P}_{new} = \frac{q_{old} \cdot \bar{P}_{old} \;+\; q_{add} \cdot P_{add}}{q_{old} + q_{add}}",
        label="(34)"
    )

    # ══════════════════════════════════════════════════════════════
    #  7. PERFORMANCE METRICS
    # ══════════════════════════════════════════════════════════════
    w.section("7.  Backtest Performance Metrics")

    w.subsection("7.1  Win Rate")
    w.equation(
        r"W = \frac{N_{win}}{N_{total}} \times 100\%",
        label="(35)"
    )
    w.component(r"N_{win}", "Number of trades with positive PnL")
    w.component(r"N_{total}", "Total number of closed trades")

    w.subsection("7.2  Annualized Sharpe Ratio")
    w.body(
        "Risk-adjusted return metric assuming zero risk-free rate, annualized "
        "with √252."
    )
    w.equation(
        r"SR = \frac{\bar{r}}{\sigma_r} \;\cdot\; \sqrt{252}",
        label="(36)"
    )
    w.component(r"\bar{r}", "Mean per-trade PnL")
    w.component(r"\sigma_r", "Standard deviation of per-trade PnL")

    w.subsection("7.3  Maximum Drawdown")
    w.body(
        "The largest peak-to-trough percentage decline in the cumulative "
        "equity curve during the backtest period."
    )
    w.equation(
        r"MDD = \min_t \left(\frac{C_t - \max_{\tau \leq t}\, C_\tau}{\max_{\tau \leq t}\, C_\tau}\right)",
        label="(37)"
    )
    w.component(r"C_t", "Cumulative PnL at time t")

    # ══════════════════════════════════════════════════════════════
    #  8. SIMULATED DATA
    # ══════════════════════════════════════════════════════════════
    w.section("8.  Price Simulation (Sample Data Generation)")

    w.subsection("8.1  Geometric Random Walk")
    w.body(
        "Sample price data is generated via a geometric random walk model "
        "with normally distributed log-returns."
    )
    w.equation(
        r"P_t = P_0 \;\prod_{i=1}^{t}\, (1 + \epsilon_i), \quad \epsilon_i \sim \mathcal{N}(0,\; 0.001)",
        label="(38)"
    )

    w.subsection("8.2  Bid-Ask Construction")
    w.body(
        "Simulated bid and ask prices are constructed symmetrically around "
        "a mid price with a configurable half-spread."
    )
    w.equation(
        r"P_{bid} = P_{mid} \cdot \left(1 - \frac{\delta}{2}\right)",
        label="(39)"
    )
    w.equation(
        r"P_{ask} = P_{mid} \cdot \left(1 + \frac{\delta}{2}\right)",
        label="(40)"
    )
    w.component(r"\delta", "Spread percentage parameter")

    w.vspace(0.4)
    w.ax.plot(
        [MARGIN_L, PAGE_W - MARGIN_R],
        [w.y + 0.15, w.y + 0.15],
        color="#0f3460", linewidth=0.6, alpha=0.3
    )
    w.body(
        "This document was auto-generated from static analysis of the "
        "crypto_hft_tool source code. Equations (1)–(40) represent the complete "
        "quantitative framework of the system."
    )

    w.close()
    print("PDF generated: Quantitative_Models_Reference.pdf")


if __name__ == "__main__":
    build_pdf()
