import os
from dotenv import load_dotenv
from typing import Dict, List

# Base data folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
data_folder = os.path.join(PROJECT_ROOT, "data")

# Create data directory structure
os.makedirs(os.path.join(data_folder, "raw"), exist_ok=True)
os.makedirs(os.path.join(data_folder, "processed"), exist_ok=True)

# Load .env into os.environ
load_dotenv()

# Trading pairs
SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT'
]

# Data Provider Mode: 'ccxt' uses real live prices via public exchange APIs.
# Switch to 'simulated' if you have no internet access or want a deterministic run.
DATA_PROVIDER_MODE = "ccxt"

# API Configuration
API_HOST = "127.0.0.1"
API_PORT = 8000

# Target Exchange (for single exchange mode)
TARGET_EXCHANGE = "binance"

# Logging Level
LOG_LEVEL = "INFO"

ARBITRAGE_EXCHANGES = {
    "primary": "binance",
    "secondary": "kraken" # Ensure your CCXT or data provider setup supports this
}

# Minimum spread percentage for trading
MIN_SPREAD_PCT = 0.001  # 0.1%

# Enhanced Signal Settings
ENHANCED_SIGNAL_SETTINGS = {
    'volatility_window': 10,        # Reduced from 15 to be more responsive
    'correlation_window': 30,       # Reduced from 50 to be more responsive
    'momentum_window': 5,          # Reduced from 10 to be more responsive
    'signal_threshold': 0.4,       # Reduced from 0.8 to generate more signals
    'vol_impact': 0.05            # Reduced from 0.1 to be less sensitive to volatility
}

# Websocket endpoints
WS_ENDPOINTS = {
    'binance': 'wss://stream.binance.com:9443/ws',
    'kraken': 'wss://ws.kraken.com'
}

# Performance monitoring settings
MONITORING_SETTINGS = {
    'metrics_window': 1000,  # Number of data points to keep
    'update_interval': 5,    # seconds
    'alert_thresholds': {
        'latency': 100,      # ms
        'slippage': 0.001,   # 0.1%
        'fill_ratio': 0.95,
        'price_impact': 0.0005  # 0.05%
    }
}

# Exchange credentials (to be loaded from environment variables)
EXCHANGE_CREDENTIALS = {
    'binance': {
        'apiKey': os.getenv('BINANCE_API_KEY', ''),
        'secret': os.getenv('BINANCE_SECRET', os.getenv('BINANCE_SECRET_KEY', '')),
    },
    'kraken': {
        'apiKey': os.getenv('KRAKEN_API_KEY', ''),
        'secret': os.getenv('KRAKEN_SECRET', os.getenv('KRAKEN_SECRET_KEY', '')),
    },
}

# ----------------------------------------
# Trading fees (in decimal form)
# DEPRECATED: kept for backward compatibility only.
# New code should use fee_tiers.get_fee_rate() — see fee_tiers.py.
# Default fallback values = retail VIP 0 taker, no BNB discount.
FEES = {
    "binance": {"maker": 0.0010, "taker": 0.0010},   # 0.10% / 0.10%
    "kraken":  {"maker": 0.0025, "taker": 0.0040},   # 0.25% / 0.40%
}
# ----------------------------------------
# Risk management parameters

# Maximum notional exposure per symbol (in base-asset units)
# MAX_NOTIONAL_PER_TRADE = {
#     "BTC/USDT": 0.002,
#     "ETH/USDT": 0.03,
# }

# Maximum active notional exposure across all trades
# MAX_TOTAL_NOTIONAL = 0.01  # e.g., 0.01 BTC equivalent

# Stop-loss per trade (in spread units)
# e.g., if we trade expecting spread to decrease, exit if it increases by this amount from entry
# STOP_LOSS_SPREAD_AMOUNT = 5.0 # Example: Exit if spread moves 5.0 USDT against the trade

# Maximum cumulative drawdown before halting new trades
# MAX_DRAWDOWN = -0.005 # Example, adjust as needed

# Trade Execution Settings
TRADE_SETTINGS = {
    'execution': {
        'min_trade_interval': 1,      # Keep at 1 second
        'max_concurrent_trades': 5,    # Keep at 5
        'order_timeout': 5,           # Keep at 5 seconds
    },
    'position_sizing': {
        'min_size': {
            'BTC/USDT': 0.0001,       # Keep minimum sizes
            'ETH/USDT': 0.001,
            'default': 0.001
        },
        'max_size': {
            'BTC/USDT': 0.005,        # Reduced from 0.01 for smaller positions
            'ETH/USDT': 0.05,         # Reduced from 0.1 for smaller positions
            'default': 0.05
        },
        'size_increment': {
            'BTC/USDT': 0.0001,
            'ETH/USDT': 0.001,
            'default': 0.001
        }
    },
    'thresholds': {
        # Fast noise filter: reject spreads that are clearly too small to ever be
        # profitable (5 bps).  The real profitability check is fee-based (see below).
        'min_spread_ratio': 0.00005,
        'max_spread_ratio': 0.005,
        # Profitability is now checked dynamically:
        #   effective_sell = bid  * (1 - sell_fee_rate)
        #   effective_buy  = ask  * (1 + buy_fee_rate)
        #   execute only when effective_sell > effective_buy  (i.e. profit > 0)
        # The old static 'min_profit_after_fees' dict has been intentionally removed
        # because it was near-zero and made the fee check meaningless.
    }
}

# Z-score Settings
ZSCORE_SETTINGS = {
    'windows': [15, 60, 180, 360],  # Reduced windows for faster response
    'momentum_window': 10,          # Reduced from 20
    'correlation_window': 30,       # Reduced from 50
    'vol_window': 15,              # Reduced from 30
    'vol_impact': 0.15,            # Reduced from 0.3
    'thresholds': {
        'entry': {
            'min': 0.8,            # Reduced from 1.5
            'max': 1.5,            # Reduced from 3.0
            'ultra_short': 0.8,    # Reduced from 1.5
            'short': 1.0,          # Reduced from 2.0
            'medium': 1.2,         # Reduced from 2.5
            'long': 1.5            # Reduced from 3.0
        },
        'exit': {
            'ultra_short': 0.3,    # Reduced from 0.5
            'short': 0.4,          # Reduced from 0.8
            'medium': 0.5,         # Reduced from 1.0
            'long': 0.6            # Reduced from 1.2
        }
    },
    'vol_adjustment': True
}

# Strategy parameters
STRATEGY_DEFAULTS = {
    "z_score_window": 60,
    "z_score_entry_threshold": 1.2,
    "z_score_exit_threshold": 0.3,
    # Capital deployed on each exchange leg (USDT).
    # Trade size (in base asset) = capital_per_leg_usdt / current_ask_price.
    "capital_per_leg_usdt": 1000.0,
    "trade_cooldown_sec": 30,
}

# Portfolio sizing (moved out of enhanced_risk_manager.py)
PORTFOLIO_BASE_VALUE_USD = 10000.0

# =============================================================================
# BSDEX strategy config — ADDITIVE, does not affect Binance/Kraken paths.
# =============================================================================

# BSDEX public API base URLs.
# NOTE: Despite the "api-public" subdomain, BSDEX requires HMAC authentication
# for all endpoints (including WebSocket).  Real BSDEX data requires a BSDEX
# account + API key set via BSDEX_API_KEY / BSDEX_API_SECRET env vars.
# When no BSDEX keys are present the strategy falls back to Bitstamp's
# truly-public EUR order book (a comparable regulated EU exchange).
BSDEX_API_REST = "https://api-public.bsdex.de"
BSDEX_API_WS   = "wss://api-public.bsdex.de/api/v1/ws"
BSDEX_MARKETS  = ["btc-eur", "eth-eur"]
BSDEX_MARKET_MAP = {          # BSDEX market -> Binance world symbol (USDT)
    "btc-eur": "BTC/USDT",
    "eth-eur": "ETH/USDT",
}
BSDEX_BITSTAMP_MAP = {        # BSDEX market -> Bitstamp ticker (EUR fallback)
    "btc-eur": "btceur",
    "eth-eur": "etheur",
}

# EUR/USD FX rate source (Frankfurter wraps the ECB daily reference rate).
FX_RATE_SOURCE   = "https://api.frankfurter.app/latest?from=USD&to=EUR"
FX_REFRESH_SEC   = 60          # Re-fetch FX rate every 60 s

# BSDEX API credentials (optional — enables real BSDEX data instead of Bitstamp proxy).
BSDEX_CREDENTIALS = {
    "apiKey": os.getenv("BSDEX_API_KEY", ""),
    "secret": os.getenv("BSDEX_API_SECRET", ""),
}

# ---------------------------------------------------------------------------
# Volume-based fee tiers for the BSDEX vs World tab.
# Source: institutional taker fee comparison table (LMAX Digital vs Bitstamp),
#         verified June 2026.  All values in decimal form (0.0012 = 0.12 %).
#
# Venue A = Bitstamp (EUR order book, BSDEX proxy)
# Venue B = LMAX Digital (institutional world price, fee model only)
#
# The "Retail (< $5M)" row is the standard Bitstamp account tier;
# LMAX Digital is institutional-only, so its entry fee (0.06%) is shown there.
# ---------------------------------------------------------------------------
BSDEX_VOLUME_TIERS: list = [
    {
        "label":           "Retail (< $5M)",
        "min_vol_usd_m":   0,
        "bitstamp_taker":  0.0040,   # 0.40 % — standard Bitstamp account
        "lmax_taker":      0.0006,   # 0.06 % — LMAX entry institutional
        "note":            "Standard retail Bitstamp account; LMAX is institutional-only.",
    },
    {
        "label":           "> $5M",
        "min_vol_usd_m":   5,
        "bitstamp_taker":  0.0012,   # 0.12 %
        "lmax_taker":      0.0006,   # 0.06 %
        "note":            "",
    },
    {
        "label":           "> $20M",
        "min_vol_usd_m":   20,
        "bitstamp_taker":  0.0010,   # 0.10 %
        "lmax_taker":      0.0006,   # 0.06 %
        "note":            "",
    },
    {
        "label":           "> $50M",
        "min_vol_usd_m":   50,
        "bitstamp_taker":  0.0008,   # 0.08 %
        "lmax_taker":      0.0006,   # 0.06 %
        "note":            "",
    },
    {
        "label":           "> $100M",
        "min_vol_usd_m":   100,
        "bitstamp_taker":  0.0006,   # 0.06 %
        "lmax_taker":      0.0004,   # 0.04 %
        "note":            "",
    },
    {
        "label":           "> $200M",
        "min_vol_usd_m":   200,
        "bitstamp_taker":  0.0006,   # 0.06 %
        "lmax_taker":      0.0003,   # 0.03 %
        "note":            "",
    },
    {
        "label":           "> $250M",
        "min_vol_usd_m":   250,
        "bitstamp_taker":  0.0005,   # 0.05 %
        "lmax_taker":      0.0003,   # 0.03 %
        "note":            "",
    },
    {
        "label":           "> $1B (aspirational)",
        "min_vol_usd_m":   1000,
        "bitstamp_taker":  0.0003,   # 0.03 %
        "lmax_taker":      0.0003,   # 0.03 %
        "note":            "Aspirational tier — not representative of typical institutional flow.",
    },
]

# Default startup tier index — "> $20M" (index 2).
# The >$1B tier is selectable but labelled aspirational; headline numbers must
# not assume the most optimistic fee schedule (P7).
BSDEX_DEFAULT_TIER_IDX: int = 2   # "> $20M" as the default starting point

# Legacy fee presets kept for bsdex_backtest.py backward compatibility.
BSDEX_STRATEGY_FEES = {
    "bsdex_retail":        {"maker": 0.0020, "taker": 0.0040},
    "bsdex_institutional": {"maker": 0.0010, "taker": 0.0012},
    "lmax_low":            {"maker": 0.0002, "taker": 0.0003},
    "lmax_high":           {"maker": 0.0002, "taker": 0.0006},
}
BSDEX_FEE_PRESETS = {
    "retail_demo":        {"bsdex": "bsdex_retail",        "world": "lmax_high"},
    "institutional_best": {"bsdex": "bsdex_institutional", "world": "lmax_low"},
    "institutional_mid":  {"bsdex": "bsdex_institutional", "world": "lmax_high"},
}
BSDEX_ACTIVE_FEE_PRESET = "retail_demo"  # legacy — UI now uses volume tiers

# ---------------------------------------------------------------------------
# Backtest execution-cost model (P4).
# Candle closes are mid prices; real fills cross the bid-ask spread.
# These additive bps are applied on top of exchange fees at fill time.
# "upper_bound" scenario zeros these; "realistic" scenario applies them.
# ---------------------------------------------------------------------------
BT_EXEC_COSTS = {
    "half_spread_bps": {
        "venue_a": 5.0,   # Bitstamp — wider spread, lower liquidity
        "venue_b": 1.5,   # Binance/LMAX — tighter institutional spread
    },
    "slippage_bps_per_100k": 2.0,   # linear market-impact per €100k notional
}

# =============================================================================
# Risk Management Settings
RISK_SETTINGS = {
    'max_position_value': {
        'BTC/USDT': 50000,   # Maximum position value in USDT
        'ETH/USDT': 25000,
        'default': 10000
    },
    'max_drawdown': {
        'hourly': 0.02,      # 2% maximum hourly drawdown
        'daily': 0.05,       # 5% maximum daily drawdown
        'total': 0.10        # 10% maximum total drawdown
    },
    'stop_loss': {
        'spread_multiplier': 2.0,  # Stop loss at 2x entry spread
        'max_loss_per_trade': 0.01 # 1% maximum loss per trade
    }
}
