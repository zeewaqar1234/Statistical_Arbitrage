from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, List, Any, Tuple
import time
from datetime import datetime, timezone
import asyncio
from fastapi.responses import JSONResponse
import os
import numpy as np
import pandas as pd

# Centralized logging setup
from src.crypto_hft_tool.utils.logging_config import setup_logging, get_logger

print(">>> RUNNING main.py FROM:", __file__)

# Update imports to use absolute imports
from src.crypto_hft_tool.data_provider import (
    BaseDataProvider,
    SimulatedSingleExchangeDataProvider,
    CCXTSingleExchangeDataProvider,
)
from src.crypto_hft_tool.signals import RollingZScore
from src.crypto_hft_tool.simulation import TradeSimulator
from src.crypto_hft_tool.enhanced_signals import EnhancedSignalProcessor, SignalMetrics
from src.crypto_hft_tool.config import (
    SYMBOLS, TRADE_SETTINGS, ZSCORE_SETTINGS,
    DATA_PROVIDER_MODE, LOG_LEVEL, TARGET_EXCHANGE, ENHANCED_SIGNAL_SETTINGS,
    API_PORT, API_HOST, FEES, MIN_SPREAD_PCT,
    ARBITRAGE_EXCHANGES, STRATEGY_DEFAULTS,
)
from src.crypto_hft_tool.fee_manager import FeeManager
from src.crypto_hft_tool.fee_tiers import list_presets, get_preset
from src.crypto_hft_tool.backtest import Backtester
from src.crypto_hft_tool.bsdex_strategy import bsdex_strategy
from src.crypto_hft_tool.config import BSDEX_MARKETS, BSDEX_FEE_PRESETS, BSDEX_VOLUME_TIERS
import concurrent.futures

# Configure logging once for the entire application
setup_logging(level=LOG_LEVEL)
logger = get_logger(__name__)

app = FastAPI(
    title="Cross-Exchange Statistical Arbitrage System API",
    description="API for cross-exchange statistical arbitrage simulation and market data.",
    version="0.1.0"
)

# --- CORS Middleware Configuration ---
# List of origins that are allowed to make requests to this backend.

# Get CORS origins from environment variable or use defaults
CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'https://*.netlify.app,http://localhost:3000,https://high-frequency-trading-eu.onrender.com,https://curious-cranachan-9e504e.netlify.app')
origins = [origin.strip() for origin in CORS_ORIGINS.split(',')]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)

# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Add error handling middleware
@app.middleware("http")
async def add_error_handling(request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(e)}
        )

# --- Global State Management (Simplified for initial setup) ---
# In a production app, consider more robust state management or dependency injection.

# Data provider is initialised below after all constants are defined (see DATA_PROVIDER_MODE block).

# Store ZScore trackers per symbol
# We need a default window size for RollingZScore if not dynamically configured per symbol via API
DEFAULT_ZSCORE_WINDOW = STRATEGY_DEFAULTS["z_score_window"]
# Update to use all symbols instead of limiting to 3
ACTIVE_SYMBOLS = SYMBOLS  # Track all symbols
zscore_trackers: Dict[str, RollingZScore] = {}
simulator = TradeSimulator()
# risk_manager = RiskManager() # Removed

# Initialize enhanced signal processors
enhanced_signal_processors = {}
for symbol in ACTIVE_SYMBOLS:
    zscore_trackers[symbol] = RollingZScore(windows=[DEFAULT_ZSCORE_WINDOW])
    enhanced_signal_processors[symbol] = EnhancedSignalProcessor(
        symbol=symbol,
        volatility_window=ENHANCED_SIGNAL_SETTINGS['volatility_window'],
        correlation_window=ENHANCED_SIGNAL_SETTINGS['correlation_window'],
        momentum_window=ENHANCED_SIGNAL_SETTINGS['momentum_window'],
        signal_threshold=ENHANCED_SIGNAL_SETTINGS['signal_threshold'],
        vol_impact=ENHANCED_SIGNAL_SETTINGS['vol_impact']
    )

# --- Constants/Configurable Params — sourced from config.py ---
Z_SCORE_THRESHOLD        = STRATEGY_DEFAULTS["z_score_entry_threshold"]
CAPITAL_PER_LEG_USDT     = STRATEGY_DEFAULTS["capital_per_leg_usdt"]
EXIT_Z_THRESHOLD         = STRATEGY_DEFAULTS["z_score_exit_threshold"]
TRADE_COOLDOWN_SEC       = STRATEGY_DEFAULTS["trade_cooldown_sec"]

# --- Live-adjustable strategy config (updated via POST /api/v1/config) ---
_live_fee_tier:             str   = "retail"
_live_capital_per_leg_usdt: float = CAPITAL_PER_LEG_USDT
_live_fee_manager:          FeeManager = FeeManager(tier_preset="retail")

# --- Data provider: CCXT = real live prices, simulated = random walk ---
if DATA_PROVIDER_MODE == "ccxt":
    data_provider: BaseDataProvider = CCXTSingleExchangeDataProvider(SYMBOLS)
    logger.info("Data provider: CCXT (real Binance + Kraken prices via public API).")
else:
    data_provider: BaseDataProvider = SimulatedSingleExchangeDataProvider(SYMBOLS)
    logger.info("Data provider: Simulated (random walk, no real prices).")
last_trade_time = {sym: 0 for sym in ACTIVE_SYMBOLS}  # Only initialize for active symbols

# --- Pydantic Models for API Request/Response ---
class BookLevel(BaseModel):
    bid: float
    ask: float

class PositionMetrics(BaseModel):
    symbol: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    duration: float
    risk_score: float

class PortfolioMetrics(BaseModel):
    volatility: Dict[str, float]
    correlations: Dict[str, Dict[str, float]]
    var: Dict[str, float]
    portfolio_var: float
    sharpe_ratios: Dict[str, float]
    max_drawdowns: Dict[str, float]

class MarketDataResponse(BaseModel):
    timestamp: str
    symbol: str
    bid_price: float
    ask_price: float
    mid_price: float
    total_volume: float
    binance_price: Optional[float] = None
    kraken_price: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    signal: str = "HOLD"
    trade_executed: bool = False
    reason: str = "Initial state"
    raw_zscore: Optional[float] = None
    volume_weighted_zscore: Optional[float] = None
    momentum_score: Optional[float] = None
    correlation_filter: Optional[float] = None
    volatility: Optional[float] = None
    adaptive_threshold: Optional[float] = None
    signal_strength: Optional[float] = None

class MarketDataAllResponse(BaseModel):
    data: Dict[str, MarketDataResponse]
    portfolio_pnl: float = 0.0

class SimulationStatusResponse(BaseModel):
    total_pnl:            float
    total_trades:         int
    win_rate:             float
    avg_pnl_per_trade:    float
    total_fees_paid:      float
    sharpe_ratio:         Optional[float] = None
    max_drawdown:         Optional[float] = None
    z_score_threshold:    float
    capital_per_leg_usdt: float
    exit_z_threshold:     float
    fee_tier:             str = "retail"


def _compute_performance_metrics(trades: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """Sharpe ratio and max drawdown from simulated trade PnLs."""
    if len(trades) < 2:
        return None, None
    pnls = np.array([float(t.get('pnl', 0)) for t in trades], dtype=float)
    std = float(np.std(pnls))
    if std <= 0:
        sharpe = None
    else:
        sharpe = float(np.mean(pnls) / std * np.sqrt(252))
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    denom = np.where(peak != 0, np.abs(peak), 1.0)
    drawdowns = (cumulative - peak) / denom
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    return sharpe, max_dd

class RecentTradesResponse(BaseModel):
    trades: List[Dict[str, Any]]

class LeaderboardEntry(BaseModel):
    symbol: str
    total_pnl: float
    trade_count: int

class LeaderboardResponse(BaseModel):
    leaderboard: List[LeaderboardEntry]

class TradeDetail(BaseModel):
    timestamp: str
    symbol: str
    buy_exchange: str
    buy_price: float
    sell_exchange: str
    sell_price: float
    amount: float
    pnl: float

class StrategyConfigResponse(BaseModel):
    fee_tier:             str
    fee_tier_label:       str
    capital_per_leg_usdt: float
    binance_taker_pct:    float
    kraken_taker_pct:     float
    combined_fee_pct:     float   # combined cost per round-trip (buy leg + sell leg)
    break_even_spread_pct: float  # minimum spread% required to trade profitably
    available_tiers:      List[str]

class StrategyConfigRequest(BaseModel):
    fee_tier:             Optional[str]   = None
    capital_per_leg_usdt: Optional[float] = None

# --- Background Trading Loop ---
async def trading_loop():
    logger.info("Background trading loop started.")
    while True:
        try:
            for symbol in ACTIVE_SYMBOLS:
                primary_ex = ARBITRAGE_EXCHANGES["primary"]
                secondary_ex = ARBITRAGE_EXCHANGES["secondary"]
                data_primary = await data_provider.get_market_data_rest(symbol, primary_ex)
                data_secondary = await data_provider.get_market_data_rest(symbol, secondary_ex)
                if not data_primary or not data_secondary:
                    continue
                bid_primary = float(data_primary['bid'])
                ask_primary = float(data_primary['ask'])
                bid_secondary = float(data_secondary['bid'])
                ask_secondary = float(data_secondary['ask'])
                vol_primary = float(data_primary.get('baseVolume', 0) or data_primary.get('volume', 0))
                vol_secondary = float(data_secondary.get('baseVolume', 0) or data_secondary.get('volume', 0))
                avg_volume = (vol_primary + vol_secondary) / 2
                api_timestamp_str = data_primary['timestamp']
                if 'Z' in api_timestamp_str:
                    timestamp_dt = datetime.fromisoformat(api_timestamp_str.replace('Z', '+00:00'))
                else:
                    try:
                        timestamp_dt = datetime.fromisoformat(api_timestamp_str)
                    except ValueError:
                        try:
                            timestamp_dt = datetime.fromtimestamp(float(api_timestamp_str)/1000)
                        except ValueError:
                            timestamp_dt = datetime.utcnow()
                # Calculate spread for signal processing
                current_market_spread_for_signal = bid_primary - ask_secondary
                signal_metrics = enhanced_signal_processors[symbol].update(
                    spread=current_market_spread_for_signal,
                    volume=avg_volume,
                    timestamp=timestamp_dt
                )
                best_metrics = None
                if signal_metrics:
                    best_metrics = max(signal_metrics.values(), key=lambda x: x.signal_strength)
                # Check cooldown
                now = time.time()
                if now - last_trade_time[symbol] < TRADE_COOLDOWN_SEC:
                    continue
                # Determine trading signal and simulate trade
                if best_metrics and best_metrics.signal_strength >= best_metrics.threshold:
                    # Determine which direction the signal suggests
                    if best_metrics.zscore > 0:
                        buy_ex,  raw_buy_price  = secondary_ex, float(ask_secondary)
                        sell_ex, raw_sell_price = primary_ex,   float(bid_primary)
                    else:
                        buy_ex,  raw_buy_price  = primary_ex,   float(ask_primary)
                        sell_ex, raw_sell_price = secondary_ex, float(bid_secondary)

                    buy_fee  = _live_fee_manager.get_fees(buy_ex,  is_maker=False)
                    sell_fee = _live_fee_manager.get_fees(sell_ex, is_maker=False)

                    # Fee-adjusted prices — only proceed when the spread covers both legs
                    eff_buy  = raw_buy_price  * (1.0 + buy_fee)
                    eff_sell = raw_sell_price * (1.0 - sell_fee)
                    net_profit_per_unit = eff_sell - eff_buy   # positive ⟺ profitable after fees

                    if net_profit_per_unit > 0:
                        # Size the trade from USDT capital, not a fixed BTC amount
                        amount = _live_capital_per_leg_usdt / raw_buy_price
                        simulator.simulate_arbitrage_trade(
                            symbol=symbol,
                            amount=amount,
                            buy_exchange=buy_ex,
                            buy_price=raw_buy_price,
                            sell_exchange=sell_ex,
                            sell_price=raw_sell_price,
                            buy_fee_rate=buy_fee,
                            sell_fee_rate=sell_fee,
                        )
                        last_trade_time[symbol] = now
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
        await asyncio.sleep(1)  # Check every second

# --- API Endpoints ---
@app.on_event("startup")
async def startup_event():
    """Initialize application state on startup."""
    logger.info("FastAPI application startup complete.")
    
    # Initialize ZScore trackers for all symbols
    for symbol in ACTIVE_SYMBOLS:
        zscore_trackers[symbol] = RollingZScore(windows=[DEFAULT_ZSCORE_WINDOW])
        enhanced_signal_processors[symbol] = EnhancedSignalProcessor(
            symbol=symbol,
            volatility_window=ENHANCED_SIGNAL_SETTINGS['volatility_window'],
            correlation_window=ENHANCED_SIGNAL_SETTINGS['correlation_window'],
            momentum_window=ENHANCED_SIGNAL_SETTINGS['momentum_window'],
            signal_threshold=ENHANCED_SIGNAL_SETTINGS['signal_threshold'],
            vol_impact=ENHANCED_SIGNAL_SETTINGS['vol_impact']
        )
    
    # Initialize simulator parameters
    simulator.update_settings(
        z_score_threshold=Z_SCORE_THRESHOLD,
        trade_amount=0.001,           # simulator default; actual sizing is capital-based at runtime
        exit_z_threshold=EXIT_Z_THRESHOLD
    )
    
    # data_provider / historical preloading were used by the old Live Monitor loop.
    # That loop is disabled, so we skip these to avoid unnecessary network calls.
    # await data_provider.start_data_generation()  ← not needed
    
    # The Binance/Kraken trading_loop is no longer used — the Live Monitor tab
    # has been removed. Keeping it running wastes REST calls and pollutes logs.
    # asyncio.create_task(trading_loop())  ← intentionally disabled

    # Start BSDEX strategy loop — own isolated task, does not touch global state
    asyncio.create_task(bsdex_strategy.run())
    logger.info("All components initialized successfully.")

@app.get("/")
async def read_root():
    return {"message": "Welcome to Cross-Exchange Statistical Arbitrage System API"}

@app.get("/api/v1/market_data/all", response_model=MarketDataAllResponse)
async def get_all_market_data():
    try:
        data = {}
        for symbol in SYMBOLS:
            market_data = await data_provider.get_market_data_rest(symbol, TARGET_EXCHANGE)
            if market_data:
                data[symbol] = MarketDataResponse(
                    timestamp=market_data['timestamp'],
                    symbol=market_data['symbol'],
                    bid_price=market_data['bid'],
                    ask_price=market_data['ask'],
                    mid_price=market_data['mid_price'],
                    total_volume=market_data['baseVolume']
                )
        return MarketDataAllResponse(data=data)
    except Exception as e:
        logger.error(f"Error getting market data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/market_data/{symbol:path}", response_model=MarketDataResponse)
async def get_market_data(
    symbol: str = Path(..., description="The symbol to get market data for, e.g., BTC/USDT")
):
    try:
        primary_ex = ARBITRAGE_EXCHANGES["primary"]
        secondary_ex = ARBITRAGE_EXCHANGES["secondary"]
        data_primary = await data_provider.get_market_data_rest(symbol, primary_ex)
        data_secondary = await data_provider.get_market_data_rest(symbol, secondary_ex)
        if not data_primary or not data_secondary:
            raise HTTPException(status_code=404, detail=f"No data available for {symbol}")

        binance_mid = (float(data_primary['bid']) + float(data_primary['ask'])) / 2
        kraken_mid = (float(data_secondary['bid']) + float(data_secondary['ask'])) / 2
        spread_abs = binance_mid - kraken_mid
        spread_pct = (spread_abs / kraken_mid) * 100 if kraken_mid else 0.0

        # Calculate spread for signal processing (arb spread)
        current_market_spread = float(data_primary['bid']) - float(data_secondary['ask'])
        avg_volume = (
            float(data_primary.get('baseVolume', 0) or data_primary.get('volume', 0))
            + float(data_secondary.get('baseVolume', 0) or data_secondary.get('volume', 0))
        ) / 2
        
        # Get timestamp
        api_timestamp_str = data_primary['timestamp']
        if 'Z' in api_timestamp_str:
            timestamp_dt = datetime.fromisoformat(api_timestamp_str.replace('Z', '+00:00'))
        else:
            try:
                timestamp_dt = datetime.fromisoformat(api_timestamp_str)
            except ValueError:
                try:
                    timestamp_dt = datetime.fromtimestamp(float(api_timestamp_str)/1000)
                except ValueError:
                    timestamp_dt = datetime.utcnow()

        # Update signal processor
        signal_metrics = enhanced_signal_processors[symbol].update(
            spread=current_market_spread,
            volume=avg_volume,
            timestamp=timestamp_dt
        )

        # Get the best metrics (or default if none available)
        best_metrics = None
        if signal_metrics:
            best_metrics = max(signal_metrics.values(), key=lambda x: x.signal_strength)
        else:
            # Create default metrics if none available
            best_metrics = SignalMetrics(
                zscore=0.0,
                volume_weighted_zscore=0.0,
                momentum_score=0.0,
                correlation_filter=0.0,
                volatility=0.0,
                threshold=ENHANCED_SIGNAL_SETTINGS['signal_threshold'],
                signal_strength=0.0
            )

        zscore = best_metrics.zscore
        threshold = best_metrics.threshold
        signal = "HOLD"
        if best_metrics.signal_strength >= threshold:
            signal = "SELL" if zscore > 0 else "BUY"

        return MarketDataResponse(
            timestamp=timestamp_dt.isoformat(),
            symbol=symbol,
            bid_price=float(data_primary['bid']),
            ask_price=float(data_primary['ask']),
            mid_price=binance_mid,
            total_volume=avg_volume,
            binance_price=binance_mid,
            kraken_price=kraken_mid,
            spread=spread_abs,
            spread_pct=spread_pct,
            signal=signal,
            trade_executed=False,
            reason="Initial state",
            raw_zscore=zscore,
            volume_weighted_zscore=best_metrics.volume_weighted_zscore,
            momentum_score=best_metrics.momentum_score,
            correlation_filter=best_metrics.correlation_filter,
            volatility=best_metrics.volatility,
            adaptive_threshold=threshold,
            signal_strength=best_metrics.signal_strength
        )
    except Exception as e:
        logger.error(f"Error getting market data for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/simulation/status", response_model=SimulationStatusResponse)
async def get_simulation_status():
    """
    Get the current status of the trade simulation (e.g., PnL, total trades).
    """
    total_trades = len(simulator.trades)
    winning_trades = sum(1 for trade in simulator.trades if trade.get('pnl', 0) > 0)
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0
    avg_pnl_per_trade = simulator.total_pnl / total_trades if total_trades > 0 else 0.0
    sharpe_ratio, max_drawdown = _compute_performance_metrics(simulator.trades)

    return SimulationStatusResponse(
        total_pnl=simulator.total_pnl,
        total_trades=total_trades,
        win_rate=win_rate,
        avg_pnl_per_trade=avg_pnl_per_trade,
        total_fees_paid=simulator.total_fees_paid,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        z_score_threshold=Z_SCORE_THRESHOLD,
        capital_per_leg_usdt=_live_capital_per_leg_usdt,
        exit_z_threshold=EXIT_Z_THRESHOLD,
        fee_tier=_live_fee_tier,
    )

@app.get("/api/v1/simulation/trades", response_model=RecentTradesResponse)
async def get_recent_trades(limit: int = 10):
    """
    Get a list of the most recent simulated trades.
    """
    recent_trades = []
    for trade_dict in reversed(simulator.trades[-limit:]):
        trade_timestamp = trade_dict.get('timestamp')
        timestamp_str = "Invalid Timestamp" # Default / error value

        try:
            if isinstance(trade_timestamp, pd.Timestamp):
                # Ensure timezone is UTC before formatting
                if trade_timestamp.tzinfo is None:
                    ts_obj = trade_timestamp.tz_localize('UTC')
                else:
                    ts_obj = trade_timestamp.tz_convert('UTC')
                # Format to ISO string with Z for UTC, milliseconds precision
                timestamp_str = ts_obj.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            elif isinstance(trade_timestamp, (int, float)):
                # Convert from Unix timestamp, assuming UTC
                ts_obj = pd.Timestamp.fromtimestamp(trade_timestamp, tz='UTC')
                timestamp_str = ts_obj.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            elif isinstance(trade_timestamp, str):
                 # Attempt to parse string, assuming UTC if no tzinfo
                ts_obj = pd.Timestamp(trade_timestamp)
                if ts_obj.tzinfo is None:
                    ts_obj = ts_obj.tz_localize('UTC')
                else:
                    ts_obj = ts_obj.tz_convert('UTC')
                timestamp_str = ts_obj.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        except Exception as e:
            logger.error(f"Error formatting timestamp '{trade_timestamp}': {e}")
            # timestamp_str remains "Invalid Timestamp"

        amount = float(trade_dict.get('amount', 0.0))
        buy_price = float(trade_dict.get('buy_price', 0.0))
        sell_price = float(trade_dict.get('sell_price', 0.0))
        fees = float(trade_dict.get('fees', 0.0))
        gross_pnl = amount * (sell_price - buy_price)

        recent_trades.append({
            "timestamp": timestamp_str,
            "symbol": trade_dict.get('symbol', 'N/A'),
            "buy_exchange": trade_dict.get('buy_exchange', 'N/A'),
            "buy_price": buy_price,
            "sell_exchange": trade_dict.get('sell_exchange', 'N/A'),
            "sell_price": sell_price,
            "amount": amount,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "pnl": float(trade_dict.get('pnl', 0.0)),
        })
    return RecentTradesResponse(trades=recent_trades)

def _make_config_response() -> StrategyConfigResponse:
    tier = get_preset(_live_fee_tier)
    bn_taker  = round(tier.binance_taker * 100, 4)
    kr_taker  = round(tier.kraken_taker  * 100, 4)
    combined  = round((tier.binance_taker + tier.kraken_taker) * 100, 4)
    return StrategyConfigResponse(
        fee_tier=_live_fee_tier,
        fee_tier_label=tier.name,
        capital_per_leg_usdt=_live_capital_per_leg_usdt,
        binance_taker_pct=bn_taker,
        kraken_taker_pct=kr_taker,
        combined_fee_pct=combined,
        break_even_spread_pct=combined,   # spread must exceed this for profit > 0
        available_tiers=list_presets(),
    )


@app.get("/api/v1/config", response_model=StrategyConfigResponse)
async def get_strategy_config():
    """Return the currently active strategy configuration."""
    return _make_config_response()


@app.post("/api/v1/config", response_model=StrategyConfigResponse)
async def update_strategy_config(req: StrategyConfigRequest):
    """Update fee tier and/or capital per leg. Changes take effect on the next trade signal."""
    global _live_fee_tier, _live_capital_per_leg_usdt, _live_fee_manager

    if req.fee_tier is not None:
        available = list_presets()
        if req.fee_tier not in available:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown fee tier '{req.fee_tier}'. Available: {available}",
            )
        _live_fee_tier    = req.fee_tier
        _live_fee_manager = FeeManager(tier_preset=req.fee_tier)
        logger.info(f"Fee tier updated to: {req.fee_tier}")

    if req.capital_per_leg_usdt is not None:
        if req.capital_per_leg_usdt <= 0:
            raise HTTPException(status_code=422, detail="capital_per_leg_usdt must be > 0")
        _live_capital_per_leg_usdt = req.capital_per_leg_usdt
        logger.info(f"Capital per leg updated to: {req.capital_per_leg_usdt} USDT")

    return _make_config_response()


@app.get("/api/v1/simulation/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard():
    """
    Return leaderboard of all symbols by total PnL and trade count.
    """
    # Aggregate trades by symbol
    symbol_stats = {sym: {"total_pnl": 0.0, "trade_count": 0} for sym in SYMBOLS}
    for trade in simulator.trades:
        sym = trade.get("symbol", None)
        if sym in symbol_stats:
            symbol_stats[sym]["total_pnl"] += trade.get("pnl", 0.0)
            symbol_stats[sym]["trade_count"] += 1
    leaderboard = [
        LeaderboardEntry(symbol=sym, total_pnl=stats["total_pnl"], trade_count=stats["trade_count"])
        for sym, stats in symbol_stats.items()
    ]
    leaderboard.sort(key=lambda x: x.total_pnl, reverse=True)
    return LeaderboardResponse(leaderboard=leaderboard)

class BacktestRequest(BaseModel):
    fee_tier:     str   = "retail"
    trade_amount: float = 0.001
    symbols: List[str]  = ["BTC/USDT", "ETH/USDT"]


def _run_backtest_sync(req: BacktestRequest) -> Dict[str, Any]:
    """Runs the backtester synchronously (called via thread-pool to avoid blocking)."""
    bt = Backtester(trade_amount=req.trade_amount, fee_tier=req.fee_tier)

    symbol_results = {}
    all_trades: List[Dict] = []
    data_sources: Dict[str, str] = {}

    for sym in req.symbols:
        # Peek at the data to detect source, then let run_backtest load it internally
        df_peek = bt.load_data(sym)
        if df_peek is None or df_peek.empty:
            symbol_results[sym] = {"trades": 0, "pnl": 0.0, "data_source": "none"}
            continue
        real_cols = {"binance_bid", "kraken_bid"}
        data_sources[sym] = "real" if real_cols.issubset(df_peek.columns) else "synthetic"
        trades_before = len(bt.simulator.trades)
        bt.run_backtest(sym)
        trades_this_sym = len(bt.simulator.trades) - trades_before
        sym_pnl = sum(
            float(t.get("pnl", 0))
            for t in bt.simulator.trades[trades_before:]
        )
        symbol_results[sym] = {
            "trades":      trades_this_sym,
            "pnl":         round(sym_pnl, 8),
            "data_source": data_sources.get(sym, "synthetic"),
        }

    if bt.metrics.get("trade_pnls"):
        bt.calculate_performance_metrics()

    # Build equity curve from cumulative PnLs
    equity_curve = []
    running = 0.0
    for i, p in enumerate(bt.metrics.get("trade_pnls", [])):
        running += p
        equity_curve.append({"trade": i + 1, "cumulative_pnl": round(running, 8)})

    # Build trade log from simulator
    trade_log = []
    for t in bt.simulator.trades[-50:]:
        ts = t.get("timestamp")
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        trade_log.append({
            "timestamp":    ts_str,
            "symbol":       t.get("symbol", ""),
            "buy_exchange": t.get("buy_exchange", ""),
            "sell_exchange":t.get("sell_exchange", ""),
            "buy_price":    round(float(t.get("buy_price",  0)), 4),
            "sell_price":   round(float(t.get("sell_price", 0)), 4),
            "amount":       float(t.get("amount", 0)),
            "gross_pnl":    round(float(t.get("amount", 0)) * (float(t.get("sell_price", 0)) - float(t.get("buy_price", 0))), 8),
            "fees":         round(float(t.get("fees", 0)), 8),
            "net_pnl":      round(float(t.get("pnl",  0)), 8),
        })

    gross = bt.metrics["total_pnl"]
    fees  = bt.metrics["total_fees"]
    return {
        "fee_tier":      req.fee_tier,
        "trade_amount":  req.trade_amount,
        "symbols":       symbol_results,
        "data_sources":  data_sources,
        "summary": {
            "total_trades":  len(bt.simulator.trades),
            "gross_pnl":     round(gross, 8),
            "total_fees":    round(fees,  8),
            "net_pnl":       round(gross - fees, 8),
            "win_rate":      round(bt.metrics.get("win_rate", 0.0), 4),
            "sharpe_ratio":  round(bt.metrics.get("sharpe_ratio", 0.0), 4),
            "max_drawdown":  round(bt.metrics.get("max_drawdown", 0.0), 8),
        },
        "equity_curve": equity_curve,
        "trades":        trade_log,
    }


@app.post("/api/v1/backtest/run")
async def run_backtest_endpoint(req: BacktestRequest):
    """Run the offline backtester and return results as JSON."""
    available_tiers = list_presets()
    if req.fee_tier not in available_tiers:
        raise HTTPException(status_code=422, detail=f"Unknown fee tier '{req.fee_tier}'. Available: {available_tiers}")
    if req.trade_amount <= 0:
        raise HTTPException(status_code=422, detail="trade_amount must be > 0")

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _run_backtest_sync, req)
    return result


# =============================================================================
# BSDEX vs World routes — new namespace, existing routes untouched
# =============================================================================

class BSDEXFeePresetRequest(BaseModel):
    preset: str


class BSDEXConfigRequest(BaseModel):
    """Full BSDEX tab configuration payload — all fields optional for partial updates."""
    venue_a_taker: Optional[float] = None   # Bitstamp taker fee (decimal; 0.0012 = 0.12%)
    venue_b_taker: Optional[float] = None   # LMAX taker fee (decimal)
    tier_label:    Optional[str]   = None   # display label e.g. "> $5M"
    tier_idx:      Optional[int]   = None   # index into BSDEX_VOLUME_TIERS
    fee_mode:      Optional[str]   = None   # "auto" | "manual"
    capital_eur:   Optional[float] = None   # capital per leg in EUR


@app.get("/api/v1/bsdex/status")
async def bsdex_status():
    """PnL, total trades, win rate, total fees, FX rate, active preset."""
    return bsdex_strategy.get_status()


@app.get("/api/v1/bsdex/trades")
async def bsdex_trades(limit: int = 50):
    """Recent simulated BSDEX trades (includes phase, post_auction_convergence, fx_rate)."""
    return bsdex_strategy.get_recent_trades(limit=min(limit, 500))


@app.get("/api/v1/bsdex/market/{market}")
async def bsdex_market(market: str = Path(..., description="e.g. btc-eur")):
    """Latest spread, z-score, threshold, signal state, phase, bid/ask for a market."""
    if market not in BSDEX_MARKETS:
        raise HTTPException(status_code=404, detail=f"Unknown market '{market}'. Available: {BSDEX_MARKETS}")
    data = bsdex_strategy.get_latest_market(market)
    if data is None:
        return {"market": market, "status": "no_data_yet", "venue_a": bsdex_strategy.venue_a_label}
    return {"market": market, **data}


@app.get("/api/v1/bsdex/spread_series/{market}")
async def bsdex_spread_series(
    market: str = Path(..., description="e.g. btc-eur"),
    n: int = 200,
):
    """Recent spread/z-score time series for the chart (up to 500 points)."""
    if market not in BSDEX_MARKETS:
        raise HTTPException(status_code=404, detail=f"Unknown market '{market}'. Available: {BSDEX_MARKETS}")
    return bsdex_strategy.get_spread_series(market, n=min(n, 500))


@app.get("/api/v1/bsdex/volume_tiers")
async def bsdex_list_volume_tiers():
    """All volume-based fee tiers (Bitstamp + LMAX taker fees) for the UI dropdown."""
    active_idx = bsdex_strategy._tier_idx
    result = []
    for idx, tier in enumerate(BSDEX_VOLUME_TIERS):
        result.append({
            **tier,
            "idx":              idx,
            "bitstamp_taker_pct": round(tier["bitstamp_taker"] * 100, 4),
            "lmax_taker_pct":     round(tier["lmax_taker"] * 100, 4),
            "breakeven_pct":      round((tier["bitstamp_taker"] + tier["lmax_taker"]) * 100, 4),
            "active":             idx == active_idx,
        })
    return result


@app.post("/api/v1/bsdex/config")
async def bsdex_set_config(req: BSDEXConfigRequest):
    """
    Update BSDEX tab config: fees (from volume tier or manual) and/or capital.
    Partial updates are supported — only the provided fields are applied.
    """
    changed = {}

    # Apply fee update if provided
    if req.venue_a_taker is not None or req.venue_b_taker is not None:
        new_a   = req.venue_a_taker   if req.venue_a_taker   is not None else bsdex_strategy._venue_a_taker
        new_b   = req.venue_b_taker   if req.venue_b_taker   is not None else bsdex_strategy._venue_b_taker
        label   = req.tier_label      if req.tier_label       is not None else bsdex_strategy._tier_label
        idx     = req.tier_idx        if req.tier_idx         is not None else bsdex_strategy._tier_idx
        mode    = req.fee_mode        if req.fee_mode         is not None else bsdex_strategy._fee_mode
        bsdex_strategy.set_fees(new_a, new_b, tier_label=label, tier_idx=idx, mode=mode)
        changed["fees"] = {
            "venue_a_taker_pct": round(new_a * 100, 4),
            "venue_b_taker_pct": round(new_b * 100, 4),
            "breakeven_pct":     round((new_a + new_b) * 100, 4),
            "tier_label": label, "mode": mode,
        }

    # Apply capital update if provided
    if req.capital_eur is not None:
        bsdex_strategy.set_capital(req.capital_eur)
        changed["capital_eur"] = req.capital_eur

    if not changed:
        return {"success": False, "detail": "No fields provided."}

    return {"success": True, "applied": changed, "status": bsdex_strategy.get_status()}


# Legacy preset endpoint — kept for backward compat; redirects to new fee logic
@app.post("/api/v1/bsdex/fee_preset")
async def bsdex_set_fee_preset(req: BSDEXFeePresetRequest):
    ok = bsdex_strategy.set_fee_preset(req.preset)
    return {"success": ok, "active_tier": bsdex_strategy._tier_label}


# Legacy phase endpoint — Bitstamp has no phases; returns a stable no-op response
@app.get("/api/v1/bsdex/phase/{market}")
async def bsdex_phase(market: str = Path(..., description="e.g. btc-eur")):
    return {"market": market, "name": "continuous-trading",
            "note": "Bitstamp proxy has no auction phases."}


# Legacy preset list — redirects callers to volume_tiers
@app.get("/api/v1/bsdex/fee_presets")
async def bsdex_list_fee_presets():
    return {"deprecated": True,
            "message": "Use GET /api/v1/bsdex/volume_tiers instead.",
            "redirect": "/api/v1/bsdex/volume_tiers"}


# ---------------------------------------------------------------------------
# BSDEX Historical Backtest
# ---------------------------------------------------------------------------

class BSDEXBacktestRequest(BaseModel):
    symbol:         str   = "btc-eur"    # "btc-eur" | "eth-eur"
    start_dt:       str                  # ISO-8601, e.g. "2026-05-01T00:00:00Z"
    end_dt:         str                  # ISO-8601
    venue_a_taker:  float = 0.0012       # Bitstamp taker (decimal)
    venue_b_taker:  float = 0.0006       # LMAX/Binance taker (decimal)
    capital_eur:    float = 1000.0       # EUR per leg per trade
    tier_label:     str   = "custom"


@app.post("/api/v1/bsdex/historical_backtest")
async def bsdex_historical_backtest(req: BSDEXBacktestRequest):
    """
    Fetch real 1-minute OHLCV from Bitstamp (EUR) + Binance (USDT→EUR),
    run the spread/z-score arbitrage strategy, and return:
      summary, equity_curve, spread_series, trades
    
    Max range: 7 days.  All prices in EUR.  No synthetic data.
    """
    from src.crypto_hft_tool.bsdex_historical_bt import run_historical_backtest

    if req.symbol not in ("btc-eur", "eth-eur", "btc-eur-kraken"):
        raise HTTPException(status_code=422, detail="symbol must be 'btc-eur', 'eth-eur', or 'btc-eur-kraken'")

    try:
        start_dt = datetime.fromisoformat(req.start_dt.replace("Z", "+00:00"))
        end_dt   = datetime.fromisoformat(req.end_dt.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {e}")

    try:
        result = await run_historical_backtest(
            symbol=req.symbol,
            start_dt=start_dt,
            end_dt=end_dt,
            venue_a_taker=req.venue_a_taker,
            venue_b_taker=req.venue_b_taker,
            capital_eur=req.capital_eur,
            tier_label=req.tier_label,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BT] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {e}")

    return result


# To run the server (save this as main.py in src/crypto_hft_tool/):
# Ensure your terminal is in the root of your project (crypto_hft_tool folder, not src)
# Then run: uvicorn src.crypto_hft_tool.main:app --reload --port 8000