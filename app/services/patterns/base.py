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

    def __init__(self):
        # Cache for existing patterns to avoid N+1 queries
        self._existing_patterns_cache = {}

    def _get_cached_patterns(self, symbol_id: int, timeframe: str, direction: str) -> list:
        """
        Get cached active patterns for overlap checking.
        Call prefetch_existing_patterns() before detection to populate cache.
        """
        key = (symbol_id, timeframe, self.pattern_type, direction)
        return self._existing_patterns_cache.get(key, [])

    def prefetch_existing_patterns(self, symbol_id: int, timeframe: str):
        """
        Prefetch all active patterns for a symbol/timeframe to avoid N+1 queries.
        Call this once before running detection loop.
        """
        from app.models import Pattern

        patterns = Pattern.query.filter_by(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            status='active'
        ).all()

        # Cache by direction
        for pattern in patterns:
            key = (symbol_id, timeframe, self.pattern_type, pattern.direction)
            if key not in self._existing_patterns_cache:
                self._existing_patterns_cache[key] = []
            self._existing_patterns_cache[key].append({
                'zone_low': pattern.zone_low,
                'zone_high': pattern.zone_high
            })

    def clear_pattern_cache(self):
        """Clear the pattern cache after detection completes."""
        self._existing_patterns_cache = {}

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

        Uses cache if prefetch_existing_patterns() was called, otherwise queries DB.

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
        if threshold is None:
            threshold = self.get_overlap_threshold(timeframe)

        # Try to use cache first (populated by prefetch_existing_patterns)
        cache_key = (symbol_id, timeframe, self.pattern_type, direction)
        if cache_key in self._existing_patterns_cache:
            existing_patterns = self._existing_patterns_cache[cache_key]
            for existing in existing_patterns:
                overlap = self._calculate_zone_overlap(
                    existing['zone_low'], existing['zone_high'],
                    zone_low, zone_high
                )
                if overlap >= threshold:
                    return True
            return False

        # Fallback to DB query if cache not populated
        from app.models import Pattern

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
        symbol_name: str,
        df: pd.DataFrame = None
    ) -> Optional[Dict[str, Any]]:
        """
        Common pattern saving logic. Checks for duplicates and saves to DB.
        Also pre-computes and stores trading levels.

        Args:
            symbol_id: Symbol ID
            timeframe: Timeframe
            direction: Pattern direction
            zone_low: Zone low price
            zone_high: Zone high price
            detected_at: Detection timestamp
            symbol_name: Symbol name for return dict
            df: DataFrame with candle data for ATR/swing calculations

        Returns:
            Pattern dict if saved, None if already exists
        """
        from app.models import Pattern
        from app import db
        from app.services.trading import calculate_trading_levels, calculate_atr, find_swing_high, find_swing_low

        # Check if exact pattern already exists
        existing = Pattern.query.filter_by(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            detected_at=detected_at
        ).first()

        if existing:
            return None

        # Compute trading levels
        atr = 0.0
        swing_high = None
        swing_low = None
        if df is not None and not df.empty:
            atr = calculate_atr(df)
            swing_high = find_swing_high(df, len(df) - 1)
            swing_low = find_swing_low(df, len(df) - 1)

        levels = calculate_trading_levels(
            pattern_type=self.pattern_type,
            zone_low=zone_low,
            zone_high=zone_high,
            direction=direction,
            atr=atr,
            swing_high=swing_high,
            swing_low=swing_low
        )

        pattern = Pattern(
            symbol_id=symbol_id,
            timeframe=timeframe,
            pattern_type=self.pattern_type,
            direction=direction,
            zone_high=zone_high,
            zone_low=zone_low,
            detected_at=detected_at,
            status='active',
            # Pre-computed trading levels
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            take_profit_1=levels.take_profit_1,
            take_profit_2=levels.take_profit_2,
            take_profit_3=levels.take_profit_3,
            risk=levels.risk,
            risk_reward_1=round(levels.risk_reward_1, 2),
            risk_reward_2=round(levels.risk_reward_2, 2),
            risk_reward_3=round(levels.risk_reward_3, 2),
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
    def detect(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        df: Optional[pd.DataFrame] = None
    ) -> List[Dict[str, Any]]:
        """
        Detect patterns in the given symbol/timeframe

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze
            df: Optional pre-loaded DataFrame (avoids redundant DB queries)

        Returns:
            List of detected patterns
        """
        pass

    def get_candles_df(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Get candles as DataFrame"""
        from app.services.aggregator import get_candles_as_dataframe
        return get_candles_as_dataframe(symbol, timeframe, limit)
