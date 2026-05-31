import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from .signals import RollingZScore
from .simulation import TradeSimulator
from .risk_manager import RiskManager
from .fee_manager import FeeManager
from .config import (
    SYMBOLS, data_folder, ZSCORE_SETTINGS, 
    TRADE_SETTINGS, RISK_SETTINGS
)
from .utils.logging_config import get_logger

logger = get_logger(__name__)

class Backtester:
    def __init__(
        self,
        data_dir: str = f"{data_folder}/processed",
        capital_per_leg_usdt: float = 1000.0,
        fee_tier: str = "retail",
        # Legacy alias kept so existing call-sites with trade_amount= still work
        trade_amount: float = None,
    ):
        self.data_dir = Path(data_dir)
        # trade_amount alias: if old kwarg supplied, treat it as capital
        self.capital_per_leg_usdt = capital_per_leg_usdt if trade_amount is None else trade_amount
        self.fee_tier_name = fee_tier

        # Initialize components
        self.simulator = TradeSimulator()
        self.risk_manager = RiskManager()
        self.fee_manager = FeeManager(tier_preset=fee_tier)
        
        # Initialize Z-score trackers for each timeframe
        self.ztrackers = {
            sym: RollingZScore(
                windows=ZSCORE_SETTINGS['windows'],
                vol_adjustment=ZSCORE_SETTINGS['vol_adjustment']
            ) for sym in SYMBOLS
        }
        
        # Performance metrics — all keys initialised here so they are always present
        # even when no trades are executed.
        self.metrics = {
            'total_pnl': 0.0,
            'total_fees': 0.0,
            'win_count': 0,
            'loss_count': 0,
            'win_rate': 0.0,
            'max_drawdown': 0.0,
            'current_drawdown': 0.0,
            'peak_value': 0.0,
            'sharpe_ratio': 0.0,
            'avg_trade_pnl': 0.0,
            'std_trade_pnl': 0.0,
            'trades_per_symbol': {sym: 0 for sym in SYMBOLS},
            'trades_per_timeframe': {str(tf): 0 for tf in ZSCORE_SETTINGS['windows']},
            'pnl_per_timeframe': {str(tf): 0.0 for tf in ZSCORE_SETTINGS['windows']},
            'trade_pnls': [],
            'cumulative_pnls': [],
            'fees_paid': {
                'binance': {'maker': 0.0, 'taker': 0.0},
                'kraken': {'maker': 0.0, 'taker': 0.0}
            },
        }
        
        # Trade tracking
        self.active_trades = {sym: {} for sym in SYMBOLS}
        self.last_trade_time = {sym: None for sym in SYMBOLS}

    def _check_trade_conditions(
        self, 
        symbol: str, 
        z_scores: Dict[str, float],
        spread: float,
        timestamp: datetime,
        prices: Dict[str, Dict[str, float]]
    ) -> Optional[Dict]:
        """
        Check if trade conditions are met across timeframes
        Returns trade parameters if conditions are met, None otherwise
        """
        logger.debug(f"Checking trade conditions for {symbol}")
        logger.debug(f"Current prices: {prices}")
        
        # Check minimum trade interval
        if (self.last_trade_time[symbol] and 
            (timestamp - self.last_trade_time[symbol]).total_seconds() < 
            TRADE_SETTINGS['execution']['min_trade_interval']):
            logger.debug("Trade rejected: Minimum trade interval not met")
            return None

        # Check spread thresholds
        avg_price = (prices['binance']['ask'] + prices['kraken']['bid']) / 2
        spread_ratio = abs(spread) / avg_price
        
        logger.debug(f"Spread ratio: {spread_ratio:.6f}, min: {TRADE_SETTINGS['thresholds']['min_spread_ratio']}, "
                    f"max: {TRADE_SETTINGS['thresholds']['max_spread_ratio']}")
        
        if spread_ratio < TRADE_SETTINGS['thresholds']['min_spread_ratio']:
            logger.debug("Trade rejected: Spread ratio too small")
            return None
        if spread_ratio > TRADE_SETTINGS['thresholds']['max_spread_ratio']:
            logger.debug("Trade rejected: Spread ratio too large")
            return None

        # Map numeric window-size keys ('15', '60', '180', '360') to named threshold keys.
        # The z_scores dict from RollingZScore uses str(window_size) as the key.
        _window_to_threshold_key = {
            str(ZSCORE_SETTINGS['windows'][0]): 'ultra_short',
            str(ZSCORE_SETTINGS['windows'][1]): 'short',
            str(ZSCORE_SETTINGS['windows'][2]): 'medium',
            str(ZSCORE_SETTINGS['windows'][3]): 'long',
        } if len(ZSCORE_SETTINGS['windows']) >= 4 else {}

        # Check z-scores across timeframes
        trade_signals = []
        logger.debug("Z-scores by timeframe:")
        for timeframe, z_score in z_scores.items():
            threshold_key = _window_to_threshold_key.get(timeframe, timeframe)
            threshold = ZSCORE_SETTINGS['thresholds']['entry'].get(
                threshold_key,
                ZSCORE_SETTINGS['thresholds']['entry']['min'],
            )
            logger.debug(f"  {timeframe}: z={z_score:.2f}, threshold={threshold}")
            if abs(z_score) >= threshold:
                trade_signals.append((timeframe, z_score))

        if not trade_signals:
            logger.debug("Trade rejected: No timeframe met z-score threshold")
            return None

        # Use the strongest signal
        timeframe, z_score = max(trade_signals, key=lambda x: abs(x[1]))
        logger.debug(f"Selected signal: {timeframe} with z-score {z_score:.2f}")
        
        # Calculate effective prices including fees
        buy_price_binance = self.fee_manager.calculate_effective_price(
            prices['binance']['ask'], 'binance', True, False)
        sell_price_binance = self.fee_manager.calculate_effective_price(
            prices['binance']['bid'], 'binance', False, False)
        buy_price_kraken = self.fee_manager.calculate_effective_price(
            prices['kraken']['ask'], 'kraken', True, False)
        sell_price_kraken = self.fee_manager.calculate_effective_price(
            prices['kraken']['bid'], 'kraken', False, False)

        logger.debug(f"Effective prices after fees:")
        logger.debug(f"  Binance: buy={buy_price_binance:.2f}, sell={sell_price_binance:.2f}")
        logger.debug(f"  Kraken: buy={buy_price_kraken:.2f}, sell={sell_price_kraken:.2f}")

        # Determine trade direction and fee-adjusted profitability.
        # effective_sell = raw_bid  * (1 - sell_fee)   ← proceeds after paying sell fee
        # effective_buy  = raw_ask  * (1 + buy_fee)    ← cost after paying buy  fee
        # Only execute when effective_sell > effective_buy  (spread covers both fee legs).
        if z_score > 0:  # Sell on Binance, Buy on Kraken
            profit    = sell_price_binance - buy_price_kraken  # already fee-adjusted prices
            direction = 1
            logger.debug(f"Signal direction +1: eff_sell_binance={sell_price_binance:.4f}, "
                         f"eff_buy_kraken={buy_price_kraken:.4f}, net_ppu={profit:.4f}")
        else:  # Sell on Kraken, Buy on Binance
            profit    = sell_price_kraken - buy_price_binance
            direction = -1
            logger.debug(f"Signal direction -1: eff_sell_kraken={sell_price_kraken:.4f}, "
                         f"eff_buy_binance={buy_price_binance:.4f}, net_ppu={profit:.4f}")

        # Gate: if fee-adjusted profit-per-unit ≤ 0, the spread does not cover fees → skip.
        if profit <= 0:
            logger.debug("Trade rejected: spread does not cover fees at current tier")
            return None

        logger.debug("Trade conditions met, returning parameters")
        return {
            'timeframe': timeframe,
            'z_score': z_score,
            'direction': direction,
            'profit': profit
        }

    def _execute_trade(
        self,
        symbol: str,
        trade_params: Dict,
        prices: Dict[str, Dict[str, float]],
        timestamp: datetime
    ) -> float:
        """Execute trade and update metrics"""
        direction = trade_params['direction']
        pnl = 0.0

        if direction > 0:  # Sell on Binance, buy on Kraken
            buy_exchange  = 'kraken'
            sell_exchange = 'binance'
            buy_price     = prices['kraken']['ask']
            sell_price    = prices['binance']['bid']
        else:              # Buy on Binance, sell on Kraken
            buy_exchange  = 'binance'
            sell_exchange = 'kraken'
            buy_price     = prices['binance']['ask']
            sell_price    = prices['kraken']['bid']

        buy_fee_rate  = self.fee_manager.get_fees(buy_exchange,  is_maker=False)
        sell_fee_rate = self.fee_manager.get_fees(sell_exchange, is_maker=False)
        # Trade as much as capital allows on the buy leg
        amount = self.capital_per_leg_usdt / buy_price

        pnl, fees_paid = self.simulator.simulate_arbitrage_trade(
            symbol=symbol,
            amount=amount,
            buy_exchange=buy_exchange,
            buy_price=buy_price,
            sell_exchange=sell_exchange,
            sell_price=sell_price,
            buy_fee_rate=buy_fee_rate,
            sell_fee_rate=sell_fee_rate,
        )
        self.metrics['fees_paid'][buy_exchange]['taker']  += fees_paid / 2
        self.metrics['fees_paid'][sell_exchange]['taker'] += fees_paid / 2

        # Update metrics
        self.metrics['total_pnl'] += pnl
        self.metrics['trades_per_symbol'][symbol] += 1
        self.metrics['trades_per_timeframe'][trade_params['timeframe']] += 1
        self.metrics['pnl_per_timeframe'][trade_params['timeframe']] += pnl
        self.metrics['trade_pnls'].append(pnl)
        self.metrics['cumulative_pnls'].append(self.metrics['total_pnl'])

        if pnl > 0:
            self.metrics['win_count'] += 1
        else:
            self.metrics['loss_count'] += 1

        # Update trade tracking
        self.last_trade_time[symbol] = timestamp
        
        # Update volume history for fee reporting
        avg_price = (prices['binance']['ask'] + prices['kraken']['bid']) / 2
        self.fee_manager.add_volume('binance', amount, avg_price, timestamp)
        self.fee_manager.add_volume('kraken',  amount, avg_price, timestamp)

        return pnl

    def run_backtest(self, symbol: str) -> Dict:
        """Run backtest for a single symbol."""
        # Load data
        df = self.load_data(symbol)
        if df is None:
            return self.metrics

        logger.info(f"Backtesting {symbol} on {len(df)} rows")
        
        for _, row in df.iterrows():
            timestamp = pd.to_datetime(row['timestamp'])
            
            # Current prices
            prices = {
                'binance': {'bid': row['binance_bid'], 'ask': row['binance_ask']},
                'kraken': {'bid': row['kraken_bid'], 'ask': row['kraken_ask']}
            }
            
            # Calculate spread and z-scores
            spread = row['binance_ask'] - row['kraken_bid']
            z_scores = self.ztrackers[symbol].add(spread, timestamp)
            
            # Check for trade opportunities
            if not self.active_trades[symbol]:
                trade_params = self._check_trade_conditions(
                    symbol, z_scores, spread, timestamp, prices
                )
                
                if trade_params and self.risk_manager.can_trade(symbol, self.trade_amount):
                    pnl = self._execute_trade(symbol, trade_params, prices, timestamp)
                    self.risk_manager.register_trade(
                        self.trade_amount, pnl, spread, trade_params['direction']
                    )
                    logger.info(
                        f"Trade executed at {timestamp}: Symbol={symbol}, "
                        f"Timeframe={trade_params['timeframe']}, Z={trade_params['z_score']:.2f}, "
                        f"PnL={pnl:.8f}"
                    )
            
            # Check exit conditions for active trades
            elif self.risk_manager.check_stop_loss(spread):
                logger.info(f"Stop-loss triggered for {symbol} at {timestamp}")
                self.risk_manager.reset_entry_state()

        # Calculate final performance metrics
        self.calculate_performance_metrics()
        return self.metrics

    def calculate_performance_metrics(self):
        """Calculate advanced performance metrics."""
        if not self.metrics['trade_pnls']:
            return
        
        trade_pnls = np.array(self.metrics['trade_pnls'])
        total_trades = len(trade_pnls)
        
        # Calculate metrics
        self.metrics.update({
            'win_rate': (self.metrics['win_count'] / total_trades * 100) if total_trades > 0 else 0,
            'avg_trade_pnl': np.mean(trade_pnls),
            'std_trade_pnl': np.std(trade_pnls),
            'sharpe_ratio': (np.mean(trade_pnls) / np.std(trade_pnls) * np.sqrt(252)) if np.std(trade_pnls) > 0 else 0,
            'max_drawdown': self._calculate_max_drawdown(),
            'total_fees': sum(
                sum(fees.values()) 
                for exchange_fees in self.metrics['fees_paid'].values()
                for fees in [exchange_fees]
            )
        })

    def _calculate_max_drawdown(self) -> float:
        """Return maximum drawdown in absolute PnL units.

        Using absolute units (not percentage of peak) because peak can be 0 or
        negative early in the run, which makes percentage division undefined or
        misleading.
        """
        if not self.metrics['cumulative_pnls']:
            return 0.0
        cumulative = np.array(self.metrics['cumulative_pnls'])
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative - peak
        return float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

    def _calculate_max_drawdown_pct(self) -> float:
        """Return maximum drawdown as a fraction of peak, only when peak > 0."""
        if not self.metrics['cumulative_pnls']:
            return 0.0
        cumulative = np.array(self.metrics['cumulative_pnls'])
        peak = np.maximum.accumulate(cumulative)
        # Only compute percentage where peak is strictly positive to avoid
        # division by zero or a sign-flipped percentage.
        mask = peak > 0
        if not mask.any():
            return 0.0
        drawdown_pct = (cumulative[mask] - peak[mask]) / peak[mask]
        return float(np.min(drawdown_pct))

    def load_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Load historical data for a symbol.

        Preference order:
          1. {SYMBOL}_real_1m.csv  — downloaded via scripts/download_real_data.py
          2. {SYMBOL}.csv          — synthetic fallback (unit-test only)

        The real-data file uses ISO-8601 timestamps written by download_real_data.py;
        the synthetic file uses Unix epoch seconds from generate_sample_data.py.
        """
        try:
            safe = symbol.replace('/', '_')
            real_path      = self.data_dir / f"{safe}_real_1m.csv"
            fallback_path  = self.data_dir / f"{safe}.csv"

            if real_path.exists():
                file_path = real_path
                logger.info(f"Loading real data: {file_path}")
                df = pd.read_csv(file_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            elif fallback_path.exists():
                file_path = fallback_path
                logger.warning(
                    f"Real data not found for {symbol}. "
                    f"Falling back to synthetic data: {file_path}. "
                    f"Run scripts/download_real_data.py for a credible backtest."
                )
                df = pd.read_csv(file_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            else:
                logger.error(
                    f"No data file found for {symbol}. "
                    f"Expected: {real_path} or {fallback_path}"
                )
                return None

            required = ['timestamp', 'binance_bid', 'binance_ask', 'kraken_bid', 'kraken_ask']
            missing = [c for c in required if c not in df.columns]
            if missing:
                logger.error(f"Data file {file_path} missing columns: {missing}")
                return None

            return df
        except Exception as e:
            logger.error(f"Error loading data for {symbol}: {str(e)}")
            return None

    def print_results(self, symbol: Optional[str] = None):
        """Print backtest results for a specific symbol or overall."""
        if symbol:
            print(f"\n=== {symbol} Results ===")
            print(f"Trades: {self.metrics['trades_per_symbol'][symbol]}")
            print("\nTrades by Timeframe:")
            for tf, count in self.metrics['trades_per_timeframe'].items():
                print(f"{tf}: {count} trades, PnL: {self.metrics['pnl_per_timeframe'][tf]:.8f}")
        else:
            print("\n=== Overall Results ===")
            print(f"Total PnL: {self.metrics['total_pnl']:.8f}")
            print(f"Total Fees: {self.metrics['total_fees']:.8f}")
            print(f"Net PnL (after fees): {(self.metrics['total_pnl'] - self.metrics['total_fees']):.8f}")
            print(f"Win Rate: {self.metrics['win_rate']:.2f}%")
            print(f"Sharpe Ratio: {self.metrics['sharpe_ratio']:.2f}")
            print(f"Max Drawdown (USD): {self.metrics['max_drawdown']:.4f}")
            print("\nFees by Exchange:")
            for exchange, fees in self.metrics['fees_paid'].items():
                print(f"{exchange}: Maker={fees['maker']:.8f}, Taker={fees['taker']:.8f}")
            print("\nTrades per Symbol:")
            for sym, count in self.metrics['trades_per_symbol'].items():
                print(f"{sym}: {count}")
            print("\nTrades by Timeframe:")
            for tf, count in self.metrics['trades_per_timeframe'].items():
                pnl = self.metrics['pnl_per_timeframe'][tf]
                print(f"{tf}: {count} trades, PnL: {pnl:.8f}")

    def run_all(self):
        """Run backtest for all configured symbols."""
        for symbol in SYMBOLS:
            logger.info(f"\nBacktesting {symbol}...")
            self.run_backtest(symbol)
            self.print_results(symbol)

        self.print_results()

    def save_artifacts(self, output_dir: str = "reports") -> None:
        """Write durable proof artifacts: trade log CSV, summary TXT, equity curve PNG."""
        import os
        from pathlib import Path as _P

        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        tier = self.fee_tier_name

        # ── 1. Trade log CSV ─────────────────────────────────────────────────
        trades = self.simulator.trades
        csv_path = _P(output_dir) / f"trades_{tier}_{ts}.csv"
        if trades:
            trade_df = pd.DataFrame(trades)
            # Ensure all expected columns exist (some may be missing for single-leg trades)
            for col in ["timestamp", "symbol", "buy_exchange", "buy_price",
                        "sell_exchange", "sell_price", "amount", "pnl", "fees"]:
                if col not in trade_df.columns:
                    trade_df[col] = None
            # Add cumulative PnL column
            trade_df = trade_df.sort_values("timestamp").reset_index(drop=True)
            trade_df["cumulative_pnl"] = trade_df["pnl"].cumsum()
            trade_df.to_csv(csv_path, index=False)
            print(f"Wrote trade log  → {csv_path}")
        else:
            print("No trades executed — trade log CSV skipped.")

        # ── 2. Summary TXT ───────────────────────────────────────────────────
        m = self.metrics
        total_fees = m.get("total_fees", 0.0)
        net_pnl    = m.get("total_pnl", 0.0) - total_fees

        from .fee_tiers import get_preset
        tier_obj = get_preset(tier)

        txt_path = _P(output_dir) / f"summary_{tier}_{ts}.txt"
        with open(txt_path, "w") as f:
            f.write(f"BACKTEST SUMMARY — {tier_obj.name}\n")
            f.write("=" * 60 + "\n\n")
            f.write("Configuration\n")
            f.write(f"  Fee tier          : {tier} ({tier_obj.name})\n")
            f.write(f"  Trade size        : {self.trade_amount} base-asset units\n")
            f.write(f"  Data directory    : {self.data_dir}\n\n")
            f.write("Headline Numbers\n")
            f.write(f"  Total trades      : {sum(m['trades_per_symbol'].values())}\n")
            f.write(f"  Gross PnL         : ${m.get('total_pnl', 0.0):.4f}\n")
            f.write(f"  Total fees paid   : ${total_fees:.4f}\n")
            f.write(f"  Net PnL           : ${net_pnl:.4f}\n")
            f.write(f"  Win rate          : {m.get('win_rate', 0.0):.2f}%\n")
            f.write(f"  Sharpe ratio      : {m.get('sharpe_ratio', 0.0):.3f}\n")
            f.write(f"  Max drawdown (USD): ${m.get('max_drawdown', 0.0):.4f}\n\n")
            f.write("Per-symbol breakdown\n")
            for sym, count in m["trades_per_symbol"].items():
                f.write(f"  {sym}: {count} trades\n")
            f.write("\nPer-timeframe breakdown\n")
            for tf, count in m["trades_per_timeframe"].items():
                pnl_tf = m["pnl_per_timeframe"][tf]
                f.write(f"  window={tf}: {count} trades, PnL=${pnl_tf:.4f}\n")
            if trades:
                f.write("\nTop 5 best trades\n")
                best = sorted(trades, key=lambda t: t.get("pnl", 0), reverse=True)[:5]
                for t in best:
                    f.write(f"  {t.get('timestamp')} {t.get('symbol')} pnl=${t.get('pnl', 0):.6f}\n")
                f.write("\nTop 5 worst trades\n")
                worst = sorted(trades, key=lambda t: t.get("pnl", 0))[:5]
                for t in worst:
                    f.write(f"  {t.get('timestamp')} {t.get('symbol')} pnl=${t.get('pnl', 0):.6f}\n")
        print(f"Wrote summary    → {txt_path}")

        # ── 3. Equity curve PNG ──────────────────────────────────────────────
        png_path = _P(output_dir) / f"equity_{tier}_{ts}.png"
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            cumulative = m.get("cumulative_pnls", [])
            if cumulative:
                fig, ax = plt.subplots(figsize=(12, 5))
                ax.plot(cumulative, linewidth=1)
                ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
                ax.set_title(f"Equity Curve — {tier_obj.name}", fontsize=13)
                ax.set_xlabel("Trade #")
                ax.set_ylabel("Cumulative Gross PnL (USD)")
                fig.tight_layout()
                fig.savefig(png_path, dpi=150)
                plt.close(fig)
                print(f"Wrote equity curve → {png_path}")
            else:
                print("No trades — equity curve PNG skipped.")
        except ImportError:
            print("matplotlib not installed — equity curve PNG skipped.")


if __name__ == "__main__":
    import argparse
    from .fee_tiers import list_presets

    parser = argparse.ArgumentParser(
        description="Run the cross-exchange statistical arbitrage backtester."
    )
    parser.add_argument(
        "--fee-tier", default="retail",
        choices=list_presets(),
        help="Which fee tier preset to apply to all trades.",
    )
    parser.add_argument(
        "--trade-amount", type=float, default=0.001,
        help="Trade size in base currency units (e.g. 0.001 BTC).",
    )
    parser.add_argument(
        "--output-dir", default="reports",
        help="Directory where trade log, summary, and equity curve are written.",
    )
    args = parser.parse_args()

    bt = Backtester(trade_amount=args.trade_amount, fee_tier=args.fee_tier)
    bt.run_all()
    bt.save_artifacts(args.output_dir)