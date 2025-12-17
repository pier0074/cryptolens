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
from app.config import Config


class FVGDetector(PatternDetector):
    """Detector for Fair Value Gaps (FVG)"""

    def __init__(self):
        super().__init__()

    @property
    def pattern_type(self) -> str:
        return 'imbalance'  # Keep database value for compatibility

    def detect(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        df: Optional[pd.DataFrame] = None,
        precomputed: dict = None
    ) -> List[Dict[str, Any]]:
        """
        Detect Fair Value Gaps in the given symbol/timeframe

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze
            df: Optional pre-loaded DataFrame (avoids redundant DB queries)
            precomputed: Optional dict with pre-calculated {'atr', 'swing_high', 'swing_low'}

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
                        sym.id, timeframe, 'bullish', zone_low, zone_high, detected_at, symbol, df,
                        precomputed=precomputed
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
                        sym.id, timeframe, 'bearish', zone_low, zone_high, detected_at, symbol, df,
                        precomputed=precomputed
                    )
                    if pattern_dict:
                        patterns.append(pattern_dict)

        # Don't commit here - let caller batch commits
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

    def detect_historical(
        self,
        df: pd.DataFrame,
        min_zone_pct: float = None,
        skip_overlap: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Detect FVG patterns in historical data WITHOUT database interaction.
        Uses numpy arrays for fast vectorized detection.

        Args:
            df: DataFrame with OHLCV data (must have: timestamp, open, high, low, close, volume)
            min_zone_pct: Minimum zone size as % of price (None = use Config.MIN_ZONE_PERCENT)
            skip_overlap: If True, skip overlap detection (faster for backtesting)

        Returns:
            List of detected patterns (dicts with zone_high, zone_low, direction, detected_at, etc.)
        """
        from app.config import Config
        import numpy as np
        from datetime import datetime, timezone

        if df.empty or len(df) < 3:
            return []

        t0 = datetime.now(timezone.utc)
        min_zone = min_zone_pct if min_zone_pct is not None else Config.MIN_ZONE_PERCENT

        # Convert to numpy arrays for fast access (MAJOR speedup vs df.iloc)
        highs = df['high'].values
        lows = df['low'].values
        timestamps = df['timestamp'].values if 'timestamp' in df.columns else None

        t1 = datetime.now(timezone.utc)
        n = len(df)
        patterns = []

        # For overlap tracking - use numpy arrays for fast vectorized checking
        seen_bullish_lows = []
        seen_bullish_highs = []
        seen_bearish_lows = []
        seen_bearish_highs = []
        overlap_threshold = Config.DEFAULT_OVERLAP_THRESHOLD

        for i in range(2, n):
            c1_high = highs[i - 2]
            c1_low = lows[i - 2]
            c3_high = highs[i]
            c3_low = lows[i]

            # Bullish FVG: Gap between c1 high and c3 low
            if c1_high < c3_low:
                zone_low = float(c1_high)
                zone_high = float(c3_low)

                # Check minimum zone size
                if zone_low > 0:
                    zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                    if zone_size_pct >= min_zone:
                        # Fast vectorized overlap check
                        is_valid = True
                        if not skip_overlap and seen_bullish_lows:
                            seen_lows = np.array(seen_bullish_lows)
                            seen_highs = np.array(seen_bullish_highs)
                            overlap_lows = np.maximum(seen_lows, zone_low)
                            overlap_highs = np.minimum(seen_highs, zone_high)
                            overlap_sizes = np.maximum(0, overlap_highs - overlap_lows)
                            seen_sizes = seen_highs - seen_lows
                            zone_size = zone_high - zone_low
                            smaller_sizes = np.minimum(seen_sizes, zone_size)
                            with np.errstate(divide='ignore', invalid='ignore'):
                                overlap_pcts = np.where(smaller_sizes > 0, overlap_sizes / smaller_sizes, 0)
                            if np.any(overlap_pcts >= overlap_threshold):
                                is_valid = False
                            else:
                                seen_bullish_lows.append(zone_low)
                                seen_bullish_highs.append(zone_high)
                        elif not skip_overlap:
                            seen_bullish_lows.append(zone_low)
                            seen_bullish_highs.append(zone_high)

                        if is_valid:
                            patterns.append({
                                'pattern_type': self.pattern_type,
                                'direction': 'bullish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': i,
                                'detected_ts': int(timestamps[i]) if timestamps is not None else None
                            })

            # Bearish FVG: Gap between c1 low and c3 high
            if c1_low > c3_high:
                zone_high = float(c1_low)
                zone_low = float(c3_high)

                # Check minimum zone size
                if zone_low > 0:
                    zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                    if zone_size_pct >= min_zone:
                        # Fast vectorized overlap check
                        is_valid = True
                        if not skip_overlap and seen_bearish_lows:
                            seen_lows = np.array(seen_bearish_lows)
                            seen_highs = np.array(seen_bearish_highs)
                            overlap_lows = np.maximum(seen_lows, zone_low)
                            overlap_highs = np.minimum(seen_highs, zone_high)
                            overlap_sizes = np.maximum(0, overlap_highs - overlap_lows)
                            seen_sizes = seen_highs - seen_lows
                            zone_size = zone_high - zone_low
                            smaller_sizes = np.minimum(seen_sizes, zone_size)
                            with np.errstate(divide='ignore', invalid='ignore'):
                                overlap_pcts = np.where(smaller_sizes > 0, overlap_sizes / smaller_sizes, 0)
                            if np.any(overlap_pcts >= overlap_threshold):
                                is_valid = False
                            else:
                                seen_bearish_lows.append(zone_low)
                                seen_bearish_highs.append(zone_high)
                        elif not skip_overlap:
                            seen_bearish_lows.append(zone_low)
                            seen_bearish_highs.append(zone_high)

                        if is_valid:
                            patterns.append({
                                'pattern_type': self.pattern_type,
                                'direction': 'bearish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': i,
                                'detected_ts': int(timestamps[i]) if timestamps is not None else None
                            })

        t2 = datetime.now(timezone.utc)
        arr_ms = (t1 - t0).total_seconds() * 1000
        loop_ms = (t2 - t1).total_seconds() * 1000
        total_ms = (t2 - t0).total_seconds() * 1000
        if total_ms > 500:  # Log if >500ms
            print(f"      [FVG] {n:,} candles: arr={arr_ms:.0f}ms, loop={loop_ms:.0f}ms, "
                  f"total={total_ms:.0f}ms, patterns={len(patterns)}", flush=True)

        return patterns

    def _is_valid_historical_pattern(
        self,
        zone_low: float,
        zone_high: float,
        direction: str,
        min_zone_pct: float,
        seen_zones: list,
        skip_overlap: bool
    ) -> bool:
        """Check if pattern is valid for historical detection (no DB access)"""
        # Check minimum zone size
        if zone_low <= 0:
            return False
        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
        if zone_size_pct < min_zone_pct:
            return False

        # Check overlap with already-detected patterns (same direction only)
        if not skip_overlap:
            for seen_dir, seen_low, seen_high in seen_zones:
                if seen_dir != direction:
                    continue
                overlap = self._calculate_zone_overlap(seen_low, seen_high, zone_low, zone_high)
                if overlap >= Config.DEFAULT_OVERLAP_THRESHOLD:
                    return False

        return True


# Backward compatibility alias
ImbalanceDetector = FVGDetector
