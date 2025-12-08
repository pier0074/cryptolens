"""
Fair Value Gap (FVG) Pattern Detector

Detects price gaps where:
- Bullish: Candle 1 High < Candle 3 Low (gap up)
- Bearish: Candle 1 Low > Candle 3 High (gap down)

These gaps often get "filled" when price returns to them.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
from app.services.patterns.base import PatternDetector
from app.models import Symbol
from app import db


class FVGDetector(PatternDetector):
    """Detector for Fair Value Gaps (FVG)"""

    @property
    def pattern_type(self) -> str:
        return 'imbalance'  # Keep database value for compatibility

    def detect(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        df: Optional[pd.DataFrame] = None
    ) -> List[Dict[str, Any]]:
        """
        Detect Fair Value Gaps in the given symbol/timeframe

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze
            df: Optional pre-loaded DataFrame (avoids redundant DB queries)

        Returns:
            List of detected FVG patterns
        """
        if df is None:
            df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 3:
            return []

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return []

        patterns = []

        for i in range(2, len(df)):
            c1 = df.iloc[i - 2]  # First candle
            c3 = df.iloc[i]      # Third candle

            # Bullish FVG: Gap between c1 high and c3 low
            if c1['high'] < c3['low']:
                zone_low = c1['high']
                zone_high = c3['low']
                detected_at = int(c3['timestamp'])

                if self._should_save_pattern(sym.id, timeframe, 'bullish', zone_low, zone_high):
                    pattern_dict = self.save_pattern(
                        sym.id, timeframe, 'bullish', zone_low, zone_high, detected_at, symbol, df
                    )
                    if pattern_dict:
                        patterns.append(pattern_dict)

            # Bearish FVG: Gap between c1 low and c3 high
            if c1['low'] > c3['high']:
                zone_high = c1['low']
                zone_low = c3['high']
                detected_at = int(c3['timestamp'])

                if self._should_save_pattern(sym.id, timeframe, 'bearish', zone_low, zone_high):
                    pattern_dict = self.save_pattern(
                        sym.id, timeframe, 'bearish', zone_low, zone_high, detected_at, symbol, df
                    )
                    if pattern_dict:
                        patterns.append(pattern_dict)

        db.session.commit()
        return patterns

    def _should_save_pattern(
        self, symbol_id: int, timeframe: str, direction: str, zone_low: float, zone_high: float
    ) -> bool:
        """Check if pattern should be saved (passes all validation)"""
        if not self.is_zone_tradeable(zone_low, zone_high):
            return False
        if self.has_overlapping_pattern(symbol_id, timeframe, direction, zone_low, zone_high):
            return False
        return True


# Backward compatibility alias
ImbalanceDetector = FVGDetector
