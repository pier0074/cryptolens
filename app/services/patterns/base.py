"""
Base Pattern Detector
Abstract base class for all pattern detectors
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import pandas as pd
from app.config import Config


class PatternDetector(ABC):
    """Abstract base class for pattern detection"""

    def is_zone_tradeable(self, zone_low: float, zone_high: float) -> bool:
        """
        Check if a zone is large enough to be tradeable.
        Very small zones aren't worth trading after fees.
        """
        if zone_low <= 0:
            return False
        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
        return zone_size_pct >= Config.MIN_ZONE_PERCENT

    def get_overlap_threshold(self, timeframe: str) -> float:
        """
        Get the overlap threshold for a specific timeframe.
        Higher timeframes use stricter thresholds.
        """
        return Config.OVERLAP_THRESHOLDS.get(timeframe, Config.DEFAULT_OVERLAP_THRESHOLD)

    def has_overlapping_pattern(
        self,
        symbol_id: int,
        timeframe: str,
        direction: str,
        zone_low: float,
        zone_high: float,
        threshold: Optional[float] = None
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
        self,
        zone1_low: float,
        zone1_high: float,
        zone2_low: float,
        zone2_high: float
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

    def save_pattern(
        self,
        symbol_id: int,
        timeframe: str,
        direction: str,
        zone_low: float,
        zone_high: float,
        detected_at: int,
        symbol_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Common pattern saving logic. Checks for duplicates and saves to DB.

        Returns:
            Pattern dict if saved, None if already exists
        """
        from app.models import Pattern
        from app import db

        # Check if exact pattern already exists
        existing = Pattern.query.filter_by(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            detected_at=detected_at
        ).first()

        if existing:
            return None

        pattern = Pattern(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            direction=direction,
            zone_high=zone_high,
            zone_low=zone_low,
            detected_at=detected_at,
            status='active'
        )
        db.session.add(pattern)

        return {
            'type': self.pattern_type,
            'direction': direction,
            'zone_high': zone_high,
            'zone_low': zone_low,
            'detected_at': detected_at,
            'symbol': symbol_name,
            'timeframe': timeframe
        }

    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if a pattern zone has been filled.

        Args:
            pattern: Pattern dict with zone_high, zone_low, direction
            current_price: Current market price

        Returns:
            Updated pattern with status and fill_percentage
        """
        zone_high = pattern['zone_high']
        zone_low = pattern['zone_low']
        direction = pattern['direction']

        if direction == 'bullish':
            # For bullish patterns, we wait for price to come DOWN to fill the zone
            if current_price <= zone_low:
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price <= zone_high:
                fill_pct = ((zone_high - current_price) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 0}
        else:  # bearish
            # For bearish patterns, we wait for price to come UP to fill the zone
            if current_price >= zone_high:
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price >= zone_low:
                fill_pct = ((current_price - zone_low) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 0}

    def update_pattern_status(self, symbol: str, timeframe: str, current_price: float) -> int:
        """
        Update the status of all active patterns for a symbol/timeframe.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Timeframe (e.g., '1h')
            current_price: Current market price

        Returns:
            Number of patterns updated
        """
        from app.models import Symbol, Pattern
        from app import db

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return 0

        patterns = Pattern.query.filter_by(
            symbol_id=sym.id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            status='active'
        ).all()

        updated = 0
        for pattern in patterns:
            pattern_dict = pattern.to_dict()
            pattern_dict['direction'] = pattern.direction

            result = self.check_fill(pattern_dict, current_price)

            if result['status'] != pattern.status:
                pattern.status = result['status']
                if result['status'] == 'filled':
                    pattern.filled_at = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
                updated += 1

            pattern.fill_percentage = result.get('fill_percentage', 0)

        db.session.commit()
        return updated

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

    def get_candles_df(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Get candles as DataFrame"""
        from app.services.aggregator import get_candles_as_dataframe
        return get_candles_as_dataframe(symbol, timeframe, limit)
