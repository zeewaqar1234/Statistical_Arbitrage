from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from .fee_tiers import get_preset, TierFees
from .utils.logging_config import get_logger

logger = get_logger(__name__)

@dataclass
class VolumeTier:
    maker_fee: float
    taker_fee: float
    min_volume: float
    currency: str  # 'USD'

class FeeManager:
    """
    Manages exchange fees and volume tracking.

    Fee rates are now driven by a named tier preset from fee_tiers.py.
    Pass tier_preset="retail" (default), "vip3", "vip5", "vip9",
    "market_maker", "dekabank_proxy", or "zero_fee".
    """
    def __init__(self, tier_preset: str = "retail"):
        from .fee_tiers import get_preset
        self.tier: TierFees = get_preset(tier_preset)
        self.tier_preset_name = tier_preset

        # Track 30-day rolling volume (used for reporting, not for fee lookup)
        self.volume_history: Dict[str, list] = {
            'binance': [],
            'kraken': []
        }
        
    def add_volume(self, exchange: str, amount: float, price: float, timestamp: Optional[datetime] = None):
        """
        Record trading volume for fee tier calculation
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
            
        volume_usd = amount * price
        self.volume_history[exchange].append((timestamp, volume_usd))
        
        # Clean up old volume data (older than 30 days)
        cutoff = timestamp - timedelta(days=30)
        self.volume_history[exchange] = [
            (ts, vol) for ts, vol in self.volume_history[exchange]
            if ts > cutoff
        ]
        
    def get_30d_volume(self, exchange: str) -> float:
        """Return 30-day rolling trading volume in USD.

        Volume is stored in USD at the time each trade is recorded via
        add_volume(amount, price), so no currency conversion is needed here.
        The old in_btc parameter and the hardcoded BTC price of 30000 have
        been removed to avoid stale conversion errors.
        """
        return sum(vol for _, vol in self.volume_history[exchange])
        
    def get_fees(self, exchange: str, is_maker: bool = False) -> float:
        """Return fee rate for the active tier preset."""
        side = "maker" if is_maker else "taker"
        return self.tier.get(exchange, side)  # type: ignore[arg-type]
        
    def estimate_fees(self, exchange: str, amount: float, price: float, is_maker: bool = False) -> float:
        """
        Estimate fees for a potential trade
        """
        fee_rate = self.get_fees(exchange, is_maker)
        trade_value = amount * price
        return trade_value * fee_rate
        
    def calculate_effective_price(self, price: float, exchange: str, is_buy: bool, is_maker: bool = False) -> float:
        """
        Calculate effective price after fees
        """
        fee_rate = self.get_fees(exchange, is_maker)
        logger.debug(f"Fee rate for {exchange} ({'maker' if is_maker else 'taker'}): {fee_rate:.6f}")
        
        if is_buy:
            effective_price = price * (1 + fee_rate)  # Higher effective price when buying
            logger.debug(f"Buy price adjustment: {price:.2f} -> {effective_price:.2f}")
        else:
            effective_price = price * (1 - fee_rate)  # Lower effective price when selling
            logger.debug(f"Sell price adjustment: {price:.2f} -> {effective_price:.2f}")
            
        return effective_price 