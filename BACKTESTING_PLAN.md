# Backtesting & Validation Plan — Crypto HFT Tool

> **For:** Cursor + Claude Sonnet 4.6
> **Project:** Cross-exchange statistical arbitrage engine (Binance ↔ Kraken)
> **Goal:** Produce a credible, real-data proof that this engine works, with selectable fee tiers so we can show how the same strategy performs at retail vs institutional (DekaBank-level) fees.

---

## How to use this file

Feed this entire file to Cursor's agent (Sonnet 4.6) and execute the phases **in order**. Each phase has:
- **Goal** — one sentence
- **Files touched** — exact paths
- **What to do** — concrete steps
- **Acceptance** — how we know it's done

Do not skip Phase 0. Everything else depends on it.

---

## Phase 0 — Audit & Remove Fakes (do this first)

**Goal:** Strip every hardcoded / fabricated value that would make the backtest dishonest. If a manager opens the code, nothing should look planted.

### What is currently faked or broken

| # | File | Problem | Why it matters |
|---|------|---------|----------------|
| 1 | `config.py` | `FEES` block has `"taker": 0.00001` for both exchanges with a comment "Temporarily reduced from 0.04% for simulation" | This is ~0.001% fee — almost zero. It inflates PnL by 100x. |
| 2 | `data_provider.py` (`SimulatedSingleExchangeDataProvider`) | Lines that do `current_mid_price *= 1.0002` (secondary) and `*= 0.9998` (primary) | These two lines **fabricate** a persistent 0.04% gap between exchanges. The "arbitrage" the engine finds is the fake gap we injected. |
| 3 | `generate_sample_data.py` | `binance_spread = np.random.normal(0.5, 0.1)` and `kraken_spread = np.random.normal(-0.5, 0.1)` | Injects a 1 USDT spread between exchanges into "sample" data. Same problem as #2 — fabricated arbitrage. |
| 4 | `backtest.py` (`_execute_trade`) | Calls `self.simulator.simulate_trade(symbol=..., buy_exchange=..., buy_price=..., sell_exchange=..., sell_price=..., amount=...)` | The `simulate_trade` method in `simulation.py` does NOT accept those kwargs. It accepts `(symbol, exchange, side, amount, entry_price, fee_rate)`. **The backtester will throw `TypeError` the moment it tries to execute any trade.** |
| 5 | `fee_manager.py` (`get_30d_volume`) | `total_volume = total_volume / 30000` — hardcoded BTC price | Wrong volume calculation. Should use live or per-row BTC price. |
| 6 | `backtest.py` (`_execute_trade`) | Expects `pnl = self.simulator.simulate_trade(...)` as scalar | The correct method (`simulate_arbitrage_trade`) returns a tuple `(pnl, fees)`. Need to unpack. |
| 7 | `backtest.py` (`_calculate_max_drawdown`) | `drawdown = (cumulative - peak) / peak` | Divides by `peak` which can be 0 or negative (early trades). Will throw or produce garbage. |
| 8 | `live_trader.py` (signal_processors init) | Passes `base_windows`, `min_threshold`, `max_threshold`, `vol_window` to `EnhancedSignalProcessor` | None of those kwargs exist on the actual class. Live trader is broken on init. |
| 9 | `main.py` | `Z_SCORE_THRESHOLD = 1.2`, `TRADE_AMOUNT = 0.001`, `EXIT_Z_THRESHOLD = 0.3`, `DEFAULT_ZSCORE_WINDOW = 30`, `TRADE_COOLDOWN_SEC = 30` | All hardcoded in the file body. Move to `config.py`. |
| 10 | `enhanced_signals.py` (`_calculate_adaptive_threshold`) | Hardcoded "trading hours" `if 8 <= hour <= 16: time_factor = 0.9` | Crypto runs 24/7. This rule is borrowed from TradFi and is wrong for crypto. |
| 11 | `enhanced_signals.py` (volatility calc) | `self.volatility = np.std(returns) * np.sqrt(252)` | 252 is the number of stock-market trading days. For crypto minute data, it should be `np.sqrt(365 * 24 * 60)` ≈ 725. Either fix it or remove the annualization. |
| 12 | `enhanced_risk_manager.py` (`_calculate_portfolio_heat`) | `base_portfolio_value = 10000` hardcoded | Move to config; this is the denominator of risk %, can't be a magic number. |

### What to do

For each item above, apply the fix listed below. Make changes file by file.

#### Fix 1: `config.py` — restore real fees as the default and define presets

Replace the `FEES` block with:

```python
# DEPRECATED: kept for backward compatibility only.
# New code should use fee_tiers.get_fee_rate() — see fee_tiers.py.
# Default fallback values = retail VIP 0 taker, no BNB discount.
FEES = {
    "binance": {"maker": 0.0010, "taker": 0.0010},   # 0.10% / 0.10%
    "kraken":  {"maker": 0.0025, "taker": 0.0040},   # 0.25% / 0.40%
}
```

Also add at the bottom of `config.py`:

```python
# Strategy parameters (moved out of main.py)
STRATEGY_DEFAULTS = {
    "z_score_window": 60,
    "z_score_entry_threshold": 1.2,
    "z_score_exit_threshold": 0.3,
    "trade_amount": 0.001,
    "trade_cooldown_sec": 30,
}

# Portfolio sizing (moved out of enhanced_risk_manager.py)
PORTFOLIO_BASE_VALUE_USD = 10000.0
```

#### Fix 2: `data_provider.py` — make the offset honest

In `SimulatedSingleExchangeDataProvider.get_market_data_rest`, **remove** the two lines:

```python
if exchange_name == ARBITRAGE_EXCHANGES.get("secondary"):
    current_mid_price *= 1.0002
elif exchange_name == ARBITRAGE_EXCHANGES.get("primary"):
    current_mid_price *= 0.9998
```

Replace with:

```python
# No artificial exchange offset. If both exchanges share the same RNG seed,
# their prices will be identical — which is realistic for highly liquid pairs.
# Real arbitrage opportunities arise from natural microstructure noise,
# not from a planted offset.
```

Do the same for `get_historical_data` in the same file — remove the `1.0002` / `0.9998` block.

#### Fix 3: `generate_sample_data.py` — remove planted spread

Replace:

```python
binance_spread = np.random.normal(0.5, 0.1)
kraken_spread = np.random.normal(-0.5, 0.1)
```

with:

```python
# Both exchanges trade around the same mid-price with independent micro-noise.
# No injected cross-exchange offset — that would fabricate arbitrage.
binance_noise = np.random.normal(0, 0.5)   # USDT
kraken_noise  = np.random.normal(0, 0.5)
```

Then use `binance_noise` and `kraken_noise` instead of the old `_spread` variables when building the row.

Also rename the script's print output to make clear this is **synthetic** data for unit-testing only, not for the backtest report.

#### Fix 4: `backtest.py` — fix the trade-execution crash

In `_execute_trade`, replace **both** calls to `self.simulator.simulate_trade(...)` with `simulate_arbitrage_trade(...)` and unpack the tuple. Also pass the correct fee rates from `FeeManager`.

Example (direction > 0 branch):

```python
buy_fee_rate  = self.fee_manager.get_fees('kraken', is_maker=False)
sell_fee_rate = self.fee_manager.get_fees('binance', is_maker=False)

pnl, fees_paid = self.simulator.simulate_arbitrage_trade(
    symbol=symbol,
    amount=self.trade_amount,
    buy_exchange='kraken',
    buy_price=prices['kraken']['ask'],
    sell_exchange='binance',
    sell_price=prices['binance']['bid'],
    buy_fee_rate=buy_fee_rate,
    sell_fee_rate=sell_fee_rate,
)
self.metrics['fees_paid']['kraken']['taker']  += fees_paid / 2
self.metrics['fees_paid']['binance']['taker'] += fees_paid / 2
```

Do the same for the direction < 0 branch with the exchanges swapped.

Delete the old manual `estimate_fees` lines that double-counted fees.

#### Fix 5: `fee_manager.py` — remove hardcoded BTC price

In `get_30d_volume`, remove `total_volume = total_volume / 30000`. The volume should be stored already in USD (or accept a `current_btc_price` parameter). The simplest fix is to always store volume in USD when `add_volume()` is called (`amount * price`) and stop converting between BTC and USD here.

#### Fix 6: `backtest.py` — fix max drawdown

In `_calculate_max_drawdown`:

```python
def _calculate_max_drawdown(self) -> float:
    if not self.metrics['cumulative_pnls']:
        return 0.0
    cumulative = np.array(self.metrics['cumulative_pnls'])
    peak = np.maximum.accumulate(cumulative)
    # Use absolute drawdown in PnL units (not percentage of peak)
    # because peak can be 0 or negative early in the run.
    drawdown = cumulative - peak
    return float(np.min(drawdown)) if len(drawdown) > 0 else 0.0
```

Add a separate `_calculate_max_drawdown_pct` that only computes percentage when peak > 0.

#### Fix 7: `live_trader.py` — fix EnhancedSignalProcessor kwargs

The current init:

```python
EnhancedSignalProcessor(
    base_windows=...,
    momentum_window=...,
    correlation_window=...,
    vol_window=...,
    min_threshold=...,
    max_threshold=...,
    vol_impact=...,
)
```

doesn't match the actual class signature. Replace with the signature that **does** exist (`enhanced_signals.py`):

```python
EnhancedSignalProcessor(
    symbol=sym,
    volatility_window=ZSCORE_SETTINGS.get('vol_window', 30),
    correlation_window=ZSCORE_SETTINGS.get('correlation_window', 50),
    momentum_window=ZSCORE_SETTINGS.get('momentum_window', 20),
    signal_threshold=ZSCORE_SETTINGS['thresholds']['entry']['min'],
    vol_impact=ZSCORE_SETTINGS.get('vol_impact', 0.3),
)
```

#### Fix 8: `main.py` — move hardcoded params to config

Delete the lines:

```python
Z_SCORE_THRESHOLD = 1.2
TRADE_AMOUNT = 0.001
EXIT_Z_THRESHOLD = 0.3
TRADE_COOLDOWN_SEC = 30
DEFAULT_ZSCORE_WINDOW = 30
```

Replace with:

```python
from .config import STRATEGY_DEFAULTS

Z_SCORE_THRESHOLD   = STRATEGY_DEFAULTS["z_score_entry_threshold"]
TRADE_AMOUNT        = STRATEGY_DEFAULTS["trade_amount"]
EXIT_Z_THRESHOLD    = STRATEGY_DEFAULTS["z_score_exit_threshold"]
TRADE_COOLDOWN_SEC  = STRATEGY_DEFAULTS["trade_cooldown_sec"]
DEFAULT_ZSCORE_WINDOW = STRATEGY_DEFAULTS["z_score_window"]
```

#### Fix 9: `enhanced_signals.py` — fix the wrong-asset assumptions

In `_calculate_adaptive_threshold`, **remove** the hour-of-day block:

```python
hour = datetime.now().hour
time_factor = 1.0
if 8 <= hour <= 16:
    time_factor = 0.9
elif 0 <= hour <= 4:
    time_factor = 1.2
```

Replace with `time_factor = 1.0` (or remove the variable entirely). Crypto trades 24/7; this TradFi pattern is misleading.

In the volatility calc, replace `np.sqrt(252)` with `np.sqrt(365 * 24 * 60)` and add a comment:

```python
# Annualization factor for 1-minute crypto data: 365 days * 24 hours * 60 minutes
self.volatility = np.std(returns) * np.sqrt(365 * 24 * 60)
```

#### Fix 10: `enhanced_risk_manager.py` — config-driven portfolio base

Replace `base_portfolio_value = 10000` with `from .config import PORTFOLIO_BASE_VALUE_USD` and use that.

### Acceptance for Phase 0

- [ ] `python -m src.crypto_hft_tool.backtest` runs without `TypeError`
- [ ] No file contains `1.0002` / `0.9998` exchange-offset multipliers
- [ ] No file contains the planted spread injection from `generate_sample_data.py`
- [ ] Default taker fees in `config.py` reflect realistic retail values (≥ 0.10% Binance, ≥ 0.40% Kraken)
- [ ] `grep -rn "30000" src/` returns no hardcoded BTC prices
- [ ] All strategy params come from `config.py`, none are hardcoded in `main.py`

---

## Phase 1 — Real Historical Data Pipeline

**Goal:** Download genuine 1-minute candle data from Binance and Kraken (no API key needed), align timestamps, write to `data/processed/{SYMBOL}.csv` in the format `backtest.py` expects.

### Files to create

- `scripts/download_real_data.py` (new file at repo root, not inside `src/`)

### What to do

Use the `download_real_data.py` script we already drafted (in the project outputs). It pulls 1-minute OHLCV via `ccxt` from both exchanges, merges on timestamp, reconstructs bid/ask from close ± realistic per-exchange spread, and writes the CSVs.

Update that script with these changes:

1. **Make spread widths configurable per symbol** — add a `SPREAD_BPS_BY_EXCHANGE` dict at the top:
   ```python
   SPREAD_BPS_BY_EXCHANGE = {
       'binance': {'BTC/USDT': 1.0, 'ETH/USDT': 1.5},
       'kraken':  {'BTC/USDT': 4.0, 'ETH/USDT': 6.0},  # Kraken typically wider
   }
   ```

2. **Pull more data** — change `NUM_CANDLES` to 10080 (one full week of 1-minute data).

3. **Honest filename suffix** — save as `{SYMBOL}_real_1m.csv` so we know which file is real data vs simulated. Modify `backtest.py`'s `load_data` to prefer `_real_1m.csv` if present.

4. **Add a metadata file** alongside each CSV (`{SYMBOL}_real_1m.meta.json`) recording:
   - Source: `"binance + kraken via ccxt"`
   - Timeframe, candle count
   - Date range (UTC)
   - Spread reconstruction assumptions (the bps values used)
   - Download timestamp

This metadata file goes into the final report as a transparency artifact.

### Honest caveat to document in the README

This pipeline reconstructs bid/ask from candle close prices. **It is not true L2 orderbook data.** Real bid/ask differs from close-price-plus-spread in three ways:
- Real spread varies with volatility, ours is constant
- Real depth is limited; we assume infinite size at top-of-book
- Real fills include slippage and partial fills

For a true production backtest, paid L2 data (Tardis.dev, Kaiko) would be needed. For a manager demo, candle-derived bid/ask is acceptable **if** the caveat is stated explicitly.

### Acceptance for Phase 1

- [ ] Running `python scripts/download_real_data.py` produces `data/processed/BTC_USDT_real_1m.csv` and `ETH_USDT_real_1m.csv` with at least 7000 rows each
- [ ] Each CSV has columns: `timestamp, binance_bid, binance_ask, kraken_bid, kraken_ask`
- [ ] Metadata `.meta.json` files exist with the recorded source and date range
- [ ] `backtest.py` reads these files by default

---

## Phase 2 — Fee Tier System with DekaBank Profile

**Goal:** Create a clean fee tier abstraction so we can run the same backtest at Retail / VIP 3 / VIP 5 / VIP 9 / Market Maker / DekaBank presets, and show how PnL changes.

### Files to create

- `src/crypto_hft_tool/fee_tiers.py` (new)

### What to put in `fee_tiers.py`

```python
"""
Fee tier presets for Binance and Kraken spot trading.

Sources (verify before any external report):
- Binance VIP schedule: https://www.binance.com/en/fee/schedule
- Kraken Pro fee schedule: https://www.kraken.com/features/fee-schedule

Fees here are decimals (0.001 = 0.10%).
"""
from dataclasses import dataclass
from typing import Dict, Literal

ExchangeName = Literal["binance", "kraken"]
FeeType = Literal["maker", "taker"]


@dataclass(frozen=True)
class TierFees:
    name: str
    binance_maker: float
    binance_taker: float
    kraken_maker: float
    kraken_taker: float
    monthly_volume_usd: float    # Approx volume needed to reach this tier
    note: str = ""

    def get(self, exchange: ExchangeName, side: FeeType) -> float:
        return getattr(self, f"{exchange}_{side}")


# ── Preset tiers ────────────────────────────────────────────────────────────
# Numbers below are the publicly published retail schedules.
# Confirm the live schedule on each exchange before publishing any results.

PRESETS: Dict[str, TierFees] = {
    "retail": TierFees(
        name="Retail (VIP 0 / Kraken Tier 0)",
        binance_maker=0.0010, binance_taker=0.0010,
        kraken_maker=0.0025,  kraken_taker=0.0040,
        monthly_volume_usd=0,
        note="Default published fees, no discounts.",
    ),

    "retail_bnb": TierFees(
        name="Retail + BNB discount (25% off Binance)",
        binance_maker=0.00075, binance_taker=0.00075,
        kraken_maker=0.0025,   kraken_taker=0.0040,
        monthly_volume_usd=0,
        note="Holding BNB enables 25% Binance fee discount. No Kraken equivalent.",
    ),

    "vip3": TierFees(
        name="Binance VIP 3 / Kraken Pro Tier 3",
        binance_maker=0.00042, binance_taker=0.00060,
        kraken_maker=0.0012,   kraken_taker=0.0024,
        monthly_volume_usd=20_000_000,
        note="~$20M/month volume. Realistic for a serious prop shop.",
    ),

    "vip5": TierFees(
        name="Binance VIP 5 / Kraken Pro Tier 5",
        binance_maker=0.00036, binance_taker=0.00048,
        kraken_maker=0.0004,   kraken_taker=0.0020,
        monthly_volume_usd=150_000_000,
        note="~$150M/month. Mid-size institutional.",
    ),

    "vip9": TierFees(
        name="Binance VIP 9 / Kraken Pro Tier 10",
        binance_maker=0.00012, binance_taker=0.00024,
        kraken_maker=0.0000,   kraken_taker=0.0010,
        monthly_volume_usd=5_000_000_000,
        note="Top published tier. Effectively maker-rebate territory.",
    ),

    "market_maker": TierFees(
        name="Registered Market Maker (negative maker fees)",
        binance_maker=-0.00005, binance_taker=0.00020,
        kraken_maker=-0.0001,   kraken_taker=0.0010,
        monthly_volume_usd=100_000_000,
        note="Exchanges pay you to provide liquidity. Requires application + obligations.",
    ),

    "dekabank_proxy": TierFees(
        name="DekaBank-scale proxy (assumed institutional tier)",
        binance_maker=0.00030, binance_taker=0.00040,
        kraken_maker=0.0002,   kraken_taker=0.0014,
        monthly_volume_usd=100_000_000,
        note=(
            "DekaBank does not trade on Binance/Kraken directly — it routes through "
            "Boerse Stuttgart Digital. This preset is a *proxy* approximating the "
            "fees a Deka-scale player would face if running this strategy on a "
            "regulated venue with negotiated institutional rates. Treat as illustrative."
        ),
    ),
}


def get_preset(name: str) -> TierFees:
    if name not in PRESETS:
        raise KeyError(
            f"Unknown fee tier preset '{name}'. "
            f"Available: {list(PRESETS.keys())}"
        )
    return PRESETS[name]


def list_presets() -> list[str]:
    return list(PRESETS.keys())
```

### Wire it into `FeeManager`

Modify `fee_manager.py`:

1. Add a new constructor parameter:
   ```python
   def __init__(self, tier_preset: str = "retail"):
       from .fee_tiers import get_preset
       self.tier = get_preset(tier_preset)
       # ... keep existing volume tracking for completeness, but ...
   ```

2. Replace `get_fees()` body with:
   ```python
   def get_fees(self, exchange: str, is_maker: bool = False) -> float:
       side = "maker" if is_maker else "taker"
       return self.tier.get(exchange, side)
   ```

3. Keep the volume-tracking method (`add_volume`) as-is — it's useful for the report ("over the backtest period the strategy traded $X, which corresponds to tier Y").

### Wire it into `Backtester`

Modify `backtest.py`'s `__init__`:

```python
def __init__(self, data_dir=..., trade_amount=0.001, fee_tier="retail"):
    ...
    self.fee_manager = FeeManager(tier_preset=fee_tier)
    self.fee_tier_name = fee_tier
```

### CLI for the backtester

Modify the `if __name__ == "__main__":` block in `backtest.py`:

```python
if __name__ == "__main__":
    import argparse
    from .fee_tiers import list_presets

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fee-tier", default="retail",
        choices=list_presets(),
        help="Which fee tier to apply to all trades."
    )
    parser.add_argument(
        "--trade-amount", type=float, default=0.001,
        help="Trade size in base currency units (e.g. 0.001 BTC)."
    )
    parser.add_argument(
        "--output-dir", default="reports",
        help="Where to write the trade log and summary."
    )
    args = parser.parse_args()

    bt = Backtester(trade_amount=args.trade_amount, fee_tier=args.fee_tier)
    bt.run_all()
    bt.save_artifacts(args.output_dir)   # see Phase 3
```

### Acceptance for Phase 2

- [ ] Running `python -m src.crypto_hft_tool.backtest --fee-tier retail` and `--fee-tier vip5` and `--fee-tier dekabank_proxy` all complete cleanly
- [ ] PnL differs measurably between presets (this is the proof that fees matter)
- [ ] `python -m src.crypto_hft_tool.backtest --fee-tier list_me` errors with a helpful message listing presets

---

## Phase 3 — Proof Artifacts

**Goal:** Every backtest run writes durable artifacts a manager can open and verify: trade log, summary, equity curve, fee-tier comparison.

### What to add

In `backtest.py`, add a new method `save_artifacts(self, output_dir: str)`:

1. **Trade log CSV** (`{output_dir}/trades_{tier}_{timestamp}.csv`)
   Columns: `timestamp, symbol, buy_exchange, buy_price, sell_exchange, sell_price, amount, gross_pnl, fees, net_pnl, cumulative_pnl, z_score, timeframe`
   Pull from `self.simulator.trades`.

2. **Summary report** (`{output_dir}/summary_{tier}_{timestamp}.txt`)
   Plain text. Include:
   - Backtest configuration (data source, date range, fee tier, trade size, parameters)
   - Headline numbers (total PnL, total fees, net PnL, win rate, Sharpe, max drawdown, trades count)
   - Per-symbol breakdown
   - Per-timeframe breakdown
   - Top 5 best / worst trades

3. **Equity curve** (`{output_dir}/equity_{tier}_{timestamp}.png`)
   Use matplotlib (already a transitive dep via numpy). Plot cumulative PnL over time. Save as PNG. If matplotlib not installed, skip silently with a warning.

### New script: `scripts/compare_fee_tiers.py`

This is the key demo artifact for managers. Runs the backtest at every preset and produces a side-by-side comparison:

```python
"""
Run the backtester at every fee tier preset and produce a comparison table.

Usage:
    python scripts/compare_fee_tiers.py

Output:
    reports/fee_tier_comparison_{timestamp}.csv
    reports/fee_tier_comparison_{timestamp}.txt
"""
from datetime import datetime
import csv
import os
from src.crypto_hft_tool.backtest import Backtester
from src.crypto_hft_tool.fee_tiers import list_presets, get_preset


def main():
    out_dir = "reports"
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    rows = []
    for tier_name in list_presets():
        print(f"\n{'='*70}\nRunning backtest with tier: {tier_name}\n{'='*70}")
        bt = Backtester(trade_amount=0.001, fee_tier=tier_name)
        bt.run_all()

        m = bt.metrics
        tier = get_preset(tier_name)
        rows.append({
            "tier": tier_name,
            "tier_label": tier.name,
            "monthly_volume_required_usd": tier.monthly_volume_usd,
            "total_trades": sum(m['trades_per_symbol'].values()),
            "total_pnl_usd": round(m.get('total_pnl', 0), 4),
            "total_fees_usd": round(m.get('total_fees', 0), 4),
            "net_pnl_usd": round(m.get('total_pnl', 0) - m.get('total_fees', 0), 4),
            "win_rate_pct": round(m.get('win_rate', 0), 2),
            "sharpe_ratio": round(m.get('sharpe_ratio', 0), 3),
            "max_drawdown_usd": round(m.get('max_drawdown', 0), 4),
        })

    csv_path = f"{out_dir}/fee_tier_comparison_{ts}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {csv_path}")

    # Plain text table for managers
    txt_path = f"{out_dir}/fee_tier_comparison_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write("FEE TIER COMPARISON — same strategy, same data, different fee tiers\n")
        f.write("=" * 70 + "\n\n")
        for r in rows:
            f.write(f"{r['tier_label']}\n")
            f.write(f"  Required 30d volume: ${r['monthly_volume_required_usd']:,.0f}\n")
            f.write(f"  Trades:              {r['total_trades']}\n")
            f.write(f"  Gross PnL:           ${r['total_pnl_usd']:,.4f}\n")
            f.write(f"  Fees paid:           ${r['total_fees_usd']:,.4f}\n")
            f.write(f"  Net PnL:             ${r['net_pnl_usd']:,.4f}\n")
            f.write(f"  Win rate:            {r['win_rate_pct']:.2f}%\n")
            f.write(f"  Sharpe:              {r['sharpe_ratio']:.3f}\n\n")
    print(f"Wrote {txt_path}")


if __name__ == "__main__":
    main()
```

This script **is the proof artifact** — it shows the same strategy goes from unprofitable at retail fees to potentially profitable at institutional fees. That's a sophisticated story to tell a manager.

### Acceptance for Phase 3

- [ ] `python -m src.crypto_hft_tool.backtest --fee-tier retail --output-dir reports` writes 3 files (trade log, summary, equity curve)
- [ ] `python scripts/compare_fee_tiers.py` writes a CSV and TXT comparing all presets
- [ ] The comparison table shows monotonically improving Net PnL as the tier improves

---

## Phase 4 — Final Report (manager-ready)

**Goal:** A single PDF or markdown document that summarizes the whole thing in language a non-coder can read.

### File to create

`reports/REPORT_TEMPLATE.md` — fill in after Phase 3.

Structure (1-2 pages max):

1. **What this is** — 3 sentences. Cross-exchange arbitrage engine, statistical signal, fee-tier aware.
2. **How we tested** — Real Binance + Kraken 1-minute candle data, N days, M trades simulated.
3. **Headline result** — A single table from the fee-tier comparison.
4. **What this proves** — The strategy logic is functional and the fee tier is the dominant driver of profitability.
5. **What this does not prove** — Honest caveats (no L2 depth, no slippage, no latency, candle-reconstructed bid/ask, etc.). This honesty section is what makes the rest credible.
6. **What would be needed for a real Deka deployment** — Regulated venue (Boerse Stuttgart Digital), L2 data, compliance review, institutional fee schedule, paper-trading on testnet first.

---

## Phase 5 — Optional: Live Testnet (for after Phase 0–4)

**Goal:** Show that the engine can actually place orders against a live exchange API (using fake money on testnet).

### Why this is a separate phase

Testnet does **not** prove the strategy is profitable. Testnet liquidity and prices are artificial. Testnet proves only that **your order-routing code works end to end** — the API calls succeed, orders fill, balances update.

This is worth doing because it's the difference between "I have a backtester" and "I have a working trading engine," but the proof-of-strategy lives in Phase 3, not here.

### What to do

1. Create a free account at `https://testnet.binance.vision/` (GitHub login).
2. Generate API keys from the testnet dashboard (separate from real Binance).
3. Add to `.env`:
   ```
   BINANCE_TESTNET_API_KEY=...
   BINANCE_TESTNET_SECRET=...
   ```
4. In `data_provider.py` (CCXT path) and `live_trader.py`, add a `testnet: bool` flag. When `True`, set `client.set_sandbox_mode(True)` on the Binance client.
5. Kraken does not have a public spot testnet — for paper-trading Kraken, use the `paper_trader.py` script (real prices, simulated execution) we already wrote.

### Acceptance for Phase 5

- [ ] `python -m src.crypto_hft_tool.run_live --testnet` connects to Binance testnet
- [ ] At least one round-trip arbitrage order pair fills successfully on testnet
- [ ] Trade logs match what the backtester predicted for the same prices

---

## Execution checklist (do these in order)

1. [ ] Phase 0 — audit and remove every fake / hardcoded value
2. [ ] Phase 1 — download real historical data
3. [ ] Phase 2 — fee tier system with DekaBank proxy preset
4. [ ] Phase 3 — proof artifacts (trade log, summary, equity curve, comparison table)
5. [ ] Phase 4 — write the final report
6. [ ] Phase 5 — (optional) testnet integration

After Phase 3 you have everything needed to show managers.

---

## Things to NOT do

- Do not re-introduce simulated arbitrage offsets ("just for visualization")
- Do not use the 0.00001 fee values anywhere — if you need a "no fees" scenario, add `"zero_fee"` as an explicit preset in `fee_tiers.py` so it's labeled in any output
- Do not paper-over the bid/ask-from-close approximation — name it explicitly in the report
- Do not present results without specifying the fee tier used
- Do not skip the "What this does not prove" section in the final report

---

## Notes for the Cursor agent

- Make changes file by file, not all at once.
- Run the backtester after each phase to confirm nothing else broke.
- If a fix in Phase 0 reveals more fakes than listed in the table, **add them to the audit and fix them too**. The list above is minimum, not maximum.
- When in doubt about a fee tier number, leave a `# TODO: verify against live schedule` comment rather than guessing.
- Keep commit messages tight: `phase-0: remove planted exchange offset in data_provider`, `phase-2: add fee_tiers module`, etc.
