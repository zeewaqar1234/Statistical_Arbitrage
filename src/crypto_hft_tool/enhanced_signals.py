import numpy as np
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass, field

from .signals import RollingZScore
from .utils.logging_config import get_logger

logger = get_logger(__name__)

@dataclass
class SignalMetrics:
    """Holds signal metrics for a given timeframe"""
    zscore: float
    volume_weighted_zscore: float
    momentum_score: float
    correlation_filter: float
    volatility: float
    threshold: float
    signal_strength: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

class EnhancedSignalProcessor:
    """
    Enhanced signal processor that combines multiple indicators
    for more robust trading signals.
    """
    def __init__(
        self,
        symbol: str,
        volatility_window: int = 100,
        correlation_window: int = 50,
        momentum_window: int = 20,
        signal_threshold: float = 1.0,
        vol_impact: float = 0.5
    ):
        self.symbol = symbol
        self.volatility_window = volatility_window
        self.correlation_window = correlation_window
        self.momentum_window = momentum_window
        self.base_signal_threshold = signal_threshold
        self.vol_impact = vol_impact
        
        # Historical data storage
        self.spreads = []
        self.volumes = []
        self.timestamps = []
        self.zscores = []
        self.thresholds = []
        
        # Market state tracking
        self.volatility = 0.0
        self.momentum = 0.0
        self.last_signal = "HOLD"
        self.signal_duration = 0
        
    def _calculate_adaptive_threshold(self, current_volatility: float, current_volume: float) -> float:
        """Calculate adaptive threshold based on market conditions"""
        try:
            # Base threshold adjustment based on volatility
            vol_adjustment = 1.0 + (current_volatility * self.vol_impact)
            
            # Volume impact - lower threshold during high volume periods
            avg_volume = np.mean(self.volumes[-20:]) if len(self.volumes) >= 20 else current_volume
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            vol_factor = 1.0 / (1.0 + np.log1p(volume_ratio))
            
            # Crypto trades 24/7 — a TradFi hour-of-day adjustment is not applicable here.
            time_factor = 1.0

            # Momentum adjustment
            momentum_impact = abs(self.momentum) * 0.1
            
            # Combine all factors
            adaptive_threshold = (
                self.base_signal_threshold *
                vol_adjustment *
                vol_factor *
                time_factor *
                (1.0 + momentum_impact)
            )
            
            # Clamp to a range that keeps the threshold meaningful vs typical |z-scores|
            return float(np.clip(adaptive_threshold, 0.3, 2.0))
            
        except Exception as e:
            logger.error(f"Error calculating adaptive threshold: {e}")
            return self.base_signal_threshold
            
    def update(self, spread: float, volume: float, timestamp: datetime) -> Dict[int, SignalMetrics]:
        try:
            # Store historical data
            self.spreads.append(spread)
            self.volumes.append(volume)
            self.timestamps.append(timestamp)
            
            # Keep only required history
            max_window = max(self.volatility_window, self.correlation_window, self.momentum_window)
            if len(self.spreads) > max_window:
                self.spreads = self.spreads[-max_window:]
                self.volumes = self.volumes[-max_window:]
                self.timestamps = self.timestamps[-max_window:]
            
            # Return default values if not enough data
            if len(self.spreads) < 2:
                return {
                    self.volatility_window: SignalMetrics(
                        zscore=0.0,
                        volume_weighted_zscore=0.0,
                        momentum_score=0.0,
                        correlation_filter=0.0,
                        volatility=0.0,
                        threshold=self.base_signal_threshold,
                        signal_strength=0.0
                    )
                }
                
            # Compute spread-change volatility (dimensionless).
            # We use absolute changes normalised by spread std, NOT percentage returns,
            # because the spread is a difference of prices and can pass through zero —
            # division by a near-zero spread would make returns explode, saturating the
            # adaptive threshold at its 2.0 ceiling.
            spread_arr = np.array(self.spreads)
            changes    = np.diff(spread_arr)           # absolute tick-to-tick changes
            spread_std = np.std(spread_arr)
            self.volatility = float(np.std(changes) / spread_std) if spread_std > 1e-10 else 0.0

            # Calculate momentum from absolute spread changes (same basis as volatility)
            if len(changes) >= self.momentum_window:
                recent_changes = changes[-self.momentum_window:]
                self.momentum  = float(np.sum(recent_changes))
            
            # Calculate volume-weighted z-score
            mean_spread = np.mean(self.spreads)
            std_spread = np.std(self.spreads)
            if std_spread > 0:
                raw_zscore = (spread - mean_spread) / std_spread
                volume_weight = volume / np.mean(self.volumes)
                volume_weighted_zscore = raw_zscore * volume_weight
            else:
                raw_zscore = 0.0
                volume_weighted_zscore = 0.0
            
            # Calculate adaptive threshold
            threshold = self._calculate_adaptive_threshold(self.volatility, volume)
            
            # Calculate signal strength
            signal_strength = abs(volume_weighted_zscore)
            
            # Store for historical reference
            self.zscores.append(raw_zscore)
            self.thresholds.append(threshold)
            
            return {
                self.volatility_window: SignalMetrics(
                    zscore=raw_zscore,
                    volume_weighted_zscore=volume_weighted_zscore,
                    momentum_score=self.momentum,
                    correlation_filter=0.0,  # Not implemented in this version
                    volatility=self.volatility,
                    threshold=threshold,
                    signal_strength=signal_strength
                )
            }
            
        except Exception as e:
            logger.error(f"Error updating signal processor: {e}")
            return {} 