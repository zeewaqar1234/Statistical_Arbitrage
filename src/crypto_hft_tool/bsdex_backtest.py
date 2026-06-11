"""
BSDEX vs World backtester.

Replays the merged CSV produced by scripts/download_bsdex_data.py row-by-row,
computing the EUR spread, running the z-score signal engine, applying the §4
phase logic (where phase column is populated), and simulating fills via
TradeSimulator.simulate_arbitrage_trade() with realistic fees from
BSDEX_FEE_PRESETS.

Usage
-----
  python3 -m src.crypto_hft_tool.bsdex_backtest [options]

  --market   btc-eur | eth-eur  (default: both)
  --fee-preset  retail_demo | institutional_best | institutional_mid
                (default: all presets side-by-side)
  --compare  run all presets and print a comparison table
  --out-dir  where to save artifacts (default: reports/)

Design notes
------------
- Does NOT import or touch backtest.py (Binance/Kraken backtester).
- Calls simulate_arbitrage_trade correctly: returns (pnl, fees).
- Uses realistic fees from BSDEX_STRATEGY_FEES, not config.FEES.
- post_auction_convergence trades are flagged and listed separately.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.crypto_hft_tool.config import (
    BSDEX_FEE_PRESETS,
    BSDEX_MARKETS,
    BSDEX_STRATEGY_FEES,
    ENHANCED_SIGNAL_SETTINGS,
    STRATEGY_DEFAULTS,
)
from src.crypto_hft_tool.enhanced_signals import EnhancedSignalProcessor
from src.crypto_hft_tool.simulation import TradeSimulator

# ---------------------------------------------------------------------------
DATA_DIR  = PROJECT_ROOT / "data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"

MARKET_FILE = {
    "btc-eur": "bsdex_BTC_EUR.csv",
    "eth-eur": "bsdex_ETH_EUR.csv",
}

PHASE_CONTINUOUS = "continuous-trading"
AUCTION_PHASES   = {"auction-call", "auction-price", "auction-recall"}
TRADE_COOLDOWN_SEC = STRATEGY_DEFAULTS.get("trade_cooldown_sec", 30)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BSDEXBacktester:
    """Run a single preset/market backtest."""

    def __init__(
        self,
        market: str,
        preset_name: str,
        capital_per_leg_eur: float = STRATEGY_DEFAULTS.get("capital_per_leg_usdt", 1000.0),
    ):
        if market not in BSDEX_MARKETS:
            raise ValueError(f"Unknown market '{market}'. Options: {BSDEX_MARKETS}")
        if preset_name not in BSDEX_FEE_PRESETS:
            raise ValueError(f"Unknown preset '{preset_name}'. Options: {list(BSDEX_FEE_PRESETS)}")

        self.market = market
        self.preset_name = preset_name
        self.preset = BSDEX_FEE_PRESETS[preset_name]
        self.capital_per_leg_eur = capital_per_leg_eur

        self.simulator = TradeSimulator()
        self.signal_processor = EnhancedSignalProcessor(
            symbol=market,
            volatility_window=ENHANCED_SIGNAL_SETTINGS["volatility_window"],
            correlation_window=ENHANCED_SIGNAL_SETTINGS["correlation_window"],
            momentum_window=ENHANCED_SIGNAL_SETTINGS["momentum_window"],
            signal_threshold=ENHANCED_SIGNAL_SETTINGS["signal_threshold"],
            vol_impact=ENHANCED_SIGNAL_SETTINGS["vol_impact"],
        )

        self.trades: List[dict] = []
        self.equity_curve: List[dict] = []
        self._last_trade_ts: Optional[pd.Timestamp] = None
        self._last_phase: str = PHASE_CONTINUOUS
        self._armed: bool = False

    # ------------------------------------------------------------------

    def _get_fees(self) -> Tuple[float, float]:
        """Return (venue_a taker, venue_b taker)."""
        fee_a = BSDEX_STRATEGY_FEES[self.preset["bsdex"]]["taker"]
        fee_b = BSDEX_STRATEGY_FEES[self.preset["world"]]["taker"]
        return fee_a, fee_b

    def _load_data(self) -> pd.DataFrame:
        path = DATA_DIR / MARKET_FILE[self.market]
        if not path.exists():
            raise FileNotFoundError(
                f"Data file not found: {path}\n"
                "Run:  python3 scripts/download_bsdex_data.py  first."
            )
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df = df.set_index("timestamp").sort_index()
        # fill missing phase column
        if "phase" not in df.columns:
            df["phase"] = ""
        df["phase"] = df["phase"].fillna("").astype(str)
        return df

    # ------------------------------------------------------------------

    def run(self) -> dict:
        df = self._load_data()
        print(f"[Backtest] {self.market} | preset={self.preset_name} | {len(df)} rows")

        fee_a, fee_b = self._get_fees()
        breakeven_pct = (fee_a + fee_b) * 100
        running_pnl = 0.0
        post_auction_trades = []

        for ts, row in df.iterrows():
            bsdex_bid = float(row.get("bsdex_bid", 0) or 0)
            bsdex_ask = float(row.get("bsdex_ask", 0) or 0)
            world_bid = float(row.get("world_bid_eur", 0) or 0)
            world_ask = float(row.get("world_ask_eur", 0) or 0)

            if not all([bsdex_bid, bsdex_ask, world_bid, world_ask]):
                continue

            # --- spread & signal ---
            spread_eur = bsdex_bid - world_ask
            mid_world  = (world_bid + world_ask) / 2.0
            spread_pct = (spread_eur / mid_world * 100) if mid_world > 0 else 0.0
            volume     = 0.0   # not available in OHLCV — pass 0
            signal_map = self.signal_processor.update(spread_eur, volume, ts)

            z_score = None
            threshold = None
            for _, metrics in (signal_map or {}).items():
                if metrics and metrics.zscore is not None:
                    z_score   = metrics.zscore
                    threshold = metrics.threshold

            # --- phase logic ---
            raw_phase = str(row.get("phase", "")).strip()
            # If phase column is empty (historical Bitstamp data), assume continuous
            phase = raw_phase if raw_phase else PHASE_CONTINUOUS
            is_tradeable = phase == PHASE_CONTINUOUS
            is_auction   = phase in AUCTION_PHASES

            prev_phase = self._last_phase
            post_auction = False
            if phase in AUCTION_PHASES:
                self._armed = True
            if is_tradeable and prev_phase in AUCTION_PHASES:
                post_auction = True
            self._last_phase = phase

            if not is_tradeable:
                continue   # don't simulate fills during halts/auctions

            if z_score is None or threshold is None:
                continue
            if abs(z_score) < threshold:
                continue
            if abs(spread_pct) <= breakeven_pct:
                continue

            # cooldown check
            if self._last_trade_ts is not None:
                elapsed = (ts - self._last_trade_ts).total_seconds()
                if elapsed < TRADE_COOLDOWN_SEC:
                    continue

            # direction
            if spread_eur > 0:
                buy_price, sell_price = world_ask, bsdex_bid
                buy_ex, sell_ex       = "world_lmax", "bsdex"
                buy_fee, sell_fee     = fee_b, fee_a
            else:
                buy_price, sell_price = bsdex_ask, world_bid
                buy_ex, sell_ex       = "bsdex", "world_lmax"
                buy_fee, sell_fee     = fee_a, fee_b

            if buy_price <= 0 or sell_price <= 0:
                continue

            # effective price check
            eff_sell = sell_price * (1 - sell_fee)
            eff_buy  = buy_price  * (1 + buy_fee)
            if eff_sell <= eff_buy:
                continue

            amount = self.capital_per_leg_eur / buy_price
            pnl, fees_paid = self.simulator.simulate_arbitrage_trade(
                symbol=self.market,
                amount=amount,
                buy_exchange=buy_ex,
                buy_price=buy_price,
                sell_exchange=sell_ex,
                sell_price=sell_price,
                buy_fee_rate=buy_fee,
                sell_fee_rate=sell_fee,
            )
            self._last_trade_ts = ts
            self._armed = False
            running_pnl += pnl

            trade_rec = {
                "timestamp": str(ts),
                "market": self.market,
                "preset": self.preset_name,
                "buy_exchange": buy_ex,
                "sell_exchange": sell_ex,
                "buy_price_eur": round(buy_price, 4),
                "sell_price_eur": round(sell_price, 4),
                "amount": round(amount, 8),
                "pnl_eur": round(pnl, 4),
                "fees_eur": round(fees_paid, 4),
                "spread_pct": round(spread_pct, 6),
                "z_score": round(z_score, 4),
                "phase": phase,
                "post_auction_convergence": post_auction,
                "running_pnl_eur": round(running_pnl, 4),
            }
            self.trades.append(trade_rec)
            if post_auction:
                post_auction_trades.append(trade_rec)

            self.equity_curve.append({
                "timestamp": str(ts),
                "pnl": round(running_pnl, 4),
            })

        return self._summarise(post_auction_trades, breakeven_pct)

    # ------------------------------------------------------------------

    def _summarise(self, post_auction_trades: list, breakeven_pct: float) -> dict:
        n = len(self.trades)
        if n == 0:
            return {
                "market": self.market, "preset": self.preset_name,
                "trades": 0, "message": "No trades fired. Check data / thresholds.",
            }
        # simulate_arbitrage_trade() already returns net_pnl (after fees).
        # pnl_eur = net; fees_eur = the fees portion. gross = net + fees.
        net_pnls   = [t["pnl_eur"]  for t in self.trades]
        fees       = [t["fees_eur"] for t in self.trades]
        wins       = sum(1 for p in net_pnls if p > 0)
        net        = sum(net_pnls)           # true net after fees
        total_fees = sum(fees)
        gross      = net + total_fees        # revenue before fees
        win_rate   = wins / n * 100

        # Sharpe (daily, ann.) — P5: aggregate per-trade PnL into calendar days,
        # compute daily return on capital, then annualise with sqrt(365).
        # Guard std == 0 → None (displayed as "n/a" in UI).
        from collections import defaultdict as _dd
        daily_pnl_map: dict = _dd(float)
        for t in self.trades:
            try:
                day = pd.Timestamp(t["timestamp"]).strftime("%Y-%m-%d")
            except Exception:
                day = str(t["timestamp"])[:10]
            daily_pnl_map[day] += t["pnl_eur"]
        capital = self.capital_per_leg_eur or 1.0
        _daily_arr = np.array([v / capital for v in daily_pnl_map.values()])
        if len(_daily_arr) >= 2:
            _mu, _std = float(np.mean(_daily_arr)), float(np.std(_daily_arr, ddof=1))
            sharpe = float(_mu / _std * np.sqrt(365)) if _std > 1e-10 else None
        else:
            sharpe = None

        # Max drawdown (EUR)
        running = np.array(eq)
        peak    = np.maximum.accumulate(running)
        dd      = running - peak
        max_dd  = float(dd.min()) if len(dd) > 0 else 0.0

        return {
            "market":   self.market,
            "preset":   self.preset_name,
            "trades":   n,
            "wins":     wins,
            "win_rate_pct": round(win_rate, 2),
            "gross_pnl_eur": round(gross, 4),
            "total_fees_eur": round(total_fees, 4),
            "net_pnl_eur": round(net, 4),
            "avg_trade_pnl_eur": round(net / n, 4),
            "sharpe_ratio": round(float(sharpe), 4) if sharpe is not None else None,
            "max_drawdown_eur": round(max_dd, 4),
            "breakeven_spread_pct": round(breakeven_pct, 4),
            "post_auction_trades": len(post_auction_trades),
            "post_auction_pnl_eur": round(sum(t["pnl_eur"] for t in post_auction_trades), 4),
        }


# ---------------------------------------------------------------------------
# Comparison runner
# ---------------------------------------------------------------------------

def run_comparison(market: str, presets: List[str]) -> pd.DataFrame:
    rows = []
    for p in presets:
        bt = BSDEXBacktester(market, p)
        summary = bt.run()
        rows.append(summary)
    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------------------

def save_artifacts(results: List[dict], all_backtests: Dict[str, "BSDEXBacktester"], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---- summary TXT --------------------------------------------------------
    lines = [
        "=" * 72,
        "BSDEX vs World Backtest Report",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "=" * 72,
        "",
        "HONESTY NOTES (read before sharing this report):",
        "  • Venue A prices are sourced from Bitstamp EUR order book, NOT real BSDEX.",
        "    BSDEX API requires authentication; this is a proxy with comparable EU",
        "    exchange characteristics.",
        "  • Venue B (World) = Binance USDT price converted to EUR via ECB FX rate.",
        "    This is NOT a live LMAX connection — LMAX fee schedule is applied as",
        "    a modelling assumption only.",
        "  • bsdex_institutional fees are assumed / negotiated rates, NOT confirmed.",
        "  • Phase data is unavailable for historical rows (Bitstamp has no phases).",
        "    Post-auction convergence trades are therefore zero in this run.",
        "",
        "-" * 72,
    ]

    df_all = pd.DataFrame(results)
    cols = ["market", "preset", "trades", "win_rate_pct", "net_pnl_eur",
            "total_fees_eur", "sharpe_ratio", "max_drawdown_eur",
            "breakeven_spread_pct", "post_auction_trades"]
    cols = [c for c in cols if c in df_all.columns]
    lines.append(df_all[cols].to_string(index=False))
    lines += ["", "=" * 72]

    # Post-auction trades section
    for key, bt in all_backtests.items():
        pa = [t for t in bt.trades if t.get("post_auction_convergence")]
        if pa:
            lines.append(f"\nPost-auction convergence trades — {key}:")
            for t in pa[:10]:
                lines.append(f"  {t['timestamp']}  PnL={t['pnl_eur']:.4f} EUR  z={t['z_score']:.3f}")

    txt_path = out_dir / f"bsdex_backtest_{now_tag}.txt"
    with open(txt_path, "w") as f:
        f.write("\n".join(lines))
    print(f"[Artifacts] Summary → {txt_path}")

    # ---- trade logs CSV -----------------------------------------------------
    for key, bt in all_backtests.items():
        if bt.trades:
            tl_path = out_dir / f"bsdex_trades_{key}_{now_tag}.csv"
            pd.DataFrame(bt.trades).to_csv(tl_path, index=False)
            print(f"[Artifacts] Trade log → {tl_path}")

    # ---- equity curve PNG ---------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, axes = plt.subplots(len(all_backtests), 1, figsize=(12, 4 * len(all_backtests)), squeeze=False)
        for idx, (key, bt) in enumerate(all_backtests.items()):
            ax = axes[idx][0]
            if bt.equity_curve:
                eq_df = pd.DataFrame(bt.equity_curve)
                eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])
                ax.plot(eq_df["timestamp"], eq_df["pnl"], lw=1.2, color="black")
                ax.axhline(0, color="gray", lw=0.5, linestyle="--")
                # Mark post-auction trades
                pa_trades = [t for t in bt.trades if t.get("post_auction_convergence")]
                if pa_trades:
                    pa_df = pd.DataFrame(pa_trades)
                    pa_df["timestamp"] = pd.to_datetime(pa_df["timestamp"])
                    ax.scatter(pa_df["timestamp"], pa_df["running_pnl_eur"],
                               marker="^", color="black", s=40, zorder=5,
                               label="Post-auction trade")
                    ax.legend(fontsize=8)
                ax.set_title(f"{key}  |  Net PnL: {bt._summarise([], 0).get('net_pnl_eur', 0):.2f} EUR",
                             fontsize=10)
                ax.set_ylabel("Cumulative PnL (EUR)")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
            else:
                ax.text(0.5, 0.5, "No trades", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(key)

        fig.suptitle("BSDEX vs World — Equity Curves", fontsize=12)
        fig.tight_layout()
        png_path = out_dir / f"bsdex_equity_{now_tag}.png"
        fig.savefig(png_path, dpi=150)
        plt.close(fig)
        print(f"[Artifacts] Equity PNG → {png_path}")
    except ImportError:
        print("[Artifacts] matplotlib not available — skipping PNG.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BSDEX vs World backtester.")
    parser.add_argument("--market",      choices=BSDEX_MARKETS + ["all"], default="all",
                        help="Market to backtest (default: all)")
    parser.add_argument("--fee-preset",  choices=list(BSDEX_FEE_PRESETS), default=None,
                        help="Single fee preset to run (default: all presets)")
    parser.add_argument("--compare",     action="store_true",
                        help="Print side-by-side comparison table")
    parser.add_argument("--out-dir",     default=str(REPORT_DIR),
                        help="Directory for report artifacts")
    args = parser.parse_args()

    markets = BSDEX_MARKETS if args.market == "all" else [args.market]
    presets = [args.fee_preset] if args.fee_preset else list(BSDEX_FEE_PRESETS.keys())
    out_dir = Path(args.out_dir)

    all_results: List[dict] = []
    all_backtests: Dict[str, BSDEXBacktester] = {}

    for market in markets:
        for preset in presets:
            key = f"{market.replace('-','_')}_{preset}"
            try:
                bt = BSDEXBacktester(market, preset)
                summary = bt.run()
                all_results.append(summary)
                all_backtests[key] = bt
            except FileNotFoundError as e:
                print(f"[SKIP] {key}: {e}")
                continue

    if not all_results:
        print("No results — run 'python3 scripts/download_bsdex_data.py' first.")
        return

    if args.compare or len(presets) > 1:
        print("\n" + "=" * 80)
        print("BSDEX vs World — Backtest Comparison")
        print("=" * 80)
        df = pd.DataFrame(all_results)
        cols = ["market", "preset", "trades", "win_rate_pct", "net_pnl_eur",
                "total_fees_eur", "sharpe_ratio", "max_drawdown_eur",
                "breakeven_spread_pct"]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].to_string(index=False))
        print("=" * 80)
    else:
        print(json.dumps(all_results[0], indent=2))

    save_artifacts(all_results, all_backtests, out_dir)


if __name__ == "__main__":
    main()
