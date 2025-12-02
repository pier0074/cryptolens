"""
Base Pattern Detector
Abstract base class for all pattern detectors
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd

# Minimum zone size as percentage of price
# Zones smaller than this are filtered out (too small to trade profitably after fees)
MIN_ZONE_PERCENT = 0.15  # 0.15% minimum zone size

# Timeframe-based overlap thresholds for deduplication
# Higher timeframes = stricter thresholds (fewer patterns but higher quality)
# Lower timeframes = looser thresholds (more patterns for scalping)
OVERLAP_THRESHOLDS = {
    '1m': 0.50,   # 50% - Allow more patterns for scalping
    '5m': 0.55,   # 55%
    '15m': 0.60,  # 60%
    '30m': 0.65,  # 65%
    '1h': 0.70,   # 70% - Standard threshold
    '2h': 0.75,   # 75%
    '4h': 0.80,   # 80% - Stricter for swing trading
    '1d': 0.85,   # 85% - Very strict for position trading
}
DEFAULT_OVERLAP_THRESHOLD = 0.70


class PatternDetector(ABC):
    """Abstract base class for pattern detection"""

    def is_zone_tradeable(self, zone_low: float, zone_high: float) -> bool:
        """
        Check if a zone is large enough to be tradeable.
        Very small zones (< 0.15%) aren't worth trading after fees.
        """
        if zone_low <= 0:
            return False
        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
        return zone_size_pct >= MIN_ZONE_PERCENT

    def get_overlap_threshold(self, timeframe: str) -> float:
        """
        Get the overlap threshold for a specific timeframe.
        Higher timeframes use stricter thresholds.
        """
        return OVERLAP_THRESHOLDS.get(timeframe, DEFAULT_OVERLAP_THRESHOLD)

    def has_overlapping_pattern(
        self, symbol_id: int, timeframe: str, direction: str,
        zone_low: float, zone_high: float, threshold: float = None
    ) -> bool:
        """
        Check if there's already an active pattern with overlapping zone.
        This prevents duplicate patterns with nearly identical zones.

        Args:
            symbol_id: Symbol ID
            timeframe: Timeframe
            direction: Pattern direction (bullish/bearish)
            zone_low: New pattern's zone low
            zone_high: New pattern's zone high
            threshold: Override threshold (if None, uses timeframe-based threshold)

        Returns:
            True if overlapping pattern exists, False otherwise
        """
        from app.models import Pattern

        # Use timeframe-based threshold if not specified
        if threshold is None:
            threshold = self.get_overlap_threshold(timeframe)

        existing_patterns = Pattern.query.filter_by(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            direction=direction,
            status='active'
        ).all()

        for existing in existing_patterns:
            overlap = self._calculate_zone_overlap(
                existing.zone_low, existing.zone_high,
                zone_low, zone_high
            )
            if overlap >= threshold:
                return True

        return False

    def _calculate_zone_overlap(
        self, zone1_low: float, zone1_high: float,
        zone2_low: float, zone2_high: float
    ) -> float:
        """
        Calculate the overlap percentage between two zones.
        Returns value between 0 (no overlap) and 1 (complete overlap).
        """
        overlap_low = max(zone1_low, zone2_low)
        overlap_high = min(zone1_high, zone2_high)

        if overlap_high <= overlap_low:
            return 0.0

        overlap_size = overlap_high - overlap_low
        zone1_size = zone1_high - zone1_low
        zone2_size = zone2_high - zone2_low

        if zone1_size == 0 or zone2_size == 0:
            return 0.0

        smaller_zone = min(zone1_size, zone2_size)
        return overlap_size / smaller_zone

    @property
    @abstractmethod
    def pattern_type(self) -> str:
        """Return the pattern type name"""
        pass

    @abstractmethod
    def detect(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Detect patterns in the given symbol/timeframe

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze

        Returns:
            List of detected patterns
        """
        pass

    @abstractmethod
    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if a pattern has been filled

        Args:
            pattern: The pattern to check
            current_price: Current market price

        Returns:
            Updated pattern with fill status
        """
        pass

    def get_candles_df(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Get candles as DataFrame"""
        from app.services.aggregator import get_candles_as_dataframe
        return get_candles_as_dataframe(symbol, timeframe, limit)
