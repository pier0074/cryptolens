"""
Order Block Pattern Detector

Order Blocks are the last opposing candle before a strong move.
They represent institutional order flow zones that often get revisited.

Bullish Order Block:
- The last bearish (red) candle before a strong bullish move
- Price often returns to this zone before continuing up

Bearish Order Block:
- The last bullish (green) candle before a strong bearish move
- Price often returns to this zone before continuing down
"""
from typing import List, Dict, Any, Optional
import pandas as pd
from app.services.patterns.base import PatternDetector
from app.models import Symbol
from app.config import Config


class OrderBlockDetector(PatternDetector):
    """Detector for Order Block patterns"""

    def __init__(self):
        super().__init__()

    @property
    def pattern_type(self) -> str:
        return 'order_block'

    def detect(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        df: Optional[pd.DataFrame] = None,
        precomputed: dict = None
    ) -> List[Dict[str, Any]]:
        """
        Detect Order Blocks in the given symbol/timeframe.

        Uses detect_historical() for pattern detection (shared algorithm),
        then filters by DB overlap and saves to database.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze
            df: Optional pre-loaded DataFrame (avoids redundant DB queries)
            precomputed: Optional dict with pre-calculated {'atr', 'swing_high', 'swing_low'}

        Returns:
            List of detected order block patterns
        """
        if df is None:
            df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 5:
            return []

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return []

        # Use shared detection algorithm (skip_overlap=True since we check DB overlap below)
        raw_patterns = self.detect_historical(df, skip_overlap=True)

        # Filter by DB overlap and save valid patterns
        patterns = []
        for raw in raw_patterns:
            zone_low = raw['zone_low']
            zone_high = raw['zone_high']
            direction = raw['direction']
            detected_at = raw['detected_ts']

            # Check DB overlap (production uses persistent pattern storage)
            if self.has_overlapping_pattern(sym.id, timeframe, direction, zone_low, zone_high):
                continue

            pattern_dict = self.save_pattern(
                sym.id, timeframe, direction, zone_low, zone_high, detected_at, symbol, df,
                precomputed=precomputed
            )
            if pattern_dict:
                patterns.append(pattern_dict)

        # Don't commit here - let caller batch commits
        return patterns

    # Note: _find_opposing_candle() removed - detect() now uses detect_historical() + DB overlap check

    def detect_historical(
        self,
        df: pd.DataFrame,
        min_zone_pct: float = None,
        skip_overlap: bool = False,
        verbose: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Detect Order Block patterns in historical data WITHOUT database interaction.
        Uses numpy arrays for fast vectorized detection.

        Args:
            df: DataFrame with OHLCV data (must have: timestamp, open, high, low, close, volume)
            min_zone_pct: Minimum zone size as % of price (None = use Config.MIN_ZONE_PERCENT)
            skip_overlap: If True, skip overlap detection (faster for backtesting)
            verbose: 0=silent, 1=summary only, 2=detailed timing

        Returns:
            List of detected patterns (dicts with zone_high, zone_low, direction, detected_at, etc.)
        """
        import numpy as np
        from datetime import datetime, timezone

        if df.empty or len(df) < 5:
            return []

        t0 = datetime.now(timezone.utc)
        min_zone = min_zone_pct if min_zone_pct is not None else Config.MIN_ZONE_PERCENT
        patterns = []

        # Convert to numpy arrays for fast access (MAJOR speedup vs df.iloc)
        opens = df['open'].values
        closes = df['close'].values
        timestamps = df['timestamp'].values if 'timestamp' in df.columns else None

        t1 = datetime.now(timezone.utc)
        n = len(df)

        # Precompute body metrics as numpy arrays
        body = closes - opens
        body_size = np.abs(body)
        is_bullish = body > 0
        is_bearish = body < 0

        # Calculate rolling average body size (vectorized with pandas - 100x faster than loop)
        avg_body = pd.Series(body_size).rolling(20).mean().values

        t2 = datetime.now(timezone.utc)

        # For overlap tracking - use numpy arrays for fast vectorized checking
        seen_bullish_lows = []
        seen_bullish_highs = []
        seen_bearish_lows = []
        seen_bearish_highs = []
        overlap_threshold = Config.DEFAULT_OVERLAP_THRESHOLD

        for i in range(3, n):
            current_body_size = body_size[i]
            avg = avg_body[i]

            if np.isnan(avg) or avg == 0:
                continue

            # Check for strong move (body larger than threshold * average)
            if current_body_size <= (avg * Config.ORDER_BLOCK_STRENGTH_MULTIPLIER):
                continue

            detected_ts = int(timestamps[i]) if timestamps is not None else None

            # Bullish OB: Last bearish candle before strong bullish move
            if is_bullish[i]:
                pattern = self._find_historical_opposing_candle_fast(
                    opens, closes, is_bearish,
                    i, 'bullish', min_zone, seen_bullish_lows, seen_bullish_highs,
                    skip_overlap, overlap_threshold
                )
                if pattern:
                    pattern['detected_ts'] = detected_ts
                    patterns.append(pattern)

            # Bearish OB: Last bullish candle before strong bearish move
            elif is_bearish[i]:
                pattern = self._find_historical_opposing_candle_fast(
                    opens, closes, is_bullish,
                    i, 'bearish', min_zone, seen_bearish_lows, seen_bearish_highs,
                    skip_overlap, overlap_threshold
                )
                if pattern:
                    pattern['detected_ts'] = detected_ts
                    patterns.append(pattern)

        t3 = datetime.now(timezone.utc)
        total_ms = (t3 - t0).total_seconds() * 1000

        # Debug output based on verbose level
        if verbose >= 2 and total_ms > 500:  # Detailed timing only if slow
            arr_ms = (t1 - t0).total_seconds() * 1000
            precomp_ms = (t2 - t1).total_seconds() * 1000
            loop_ms = (t3 - t2).total_seconds() * 1000
            print(f"      [OB] {n:,} candles: arr={arr_ms:.0f}ms, precomp={precomp_ms:.0f}ms, "
                  f"loop={loop_ms:.0f}ms, total={total_ms:.0f}ms, patterns={len(patterns)}", flush=True)
        elif verbose >= 1 and len(patterns) > 0:
            print(f"      [OB] Found {len(patterns)} patterns in {n:,} candles", flush=True)

        return patterns

    def _find_historical_opposing_candle_fast(
        self,
        opens: 'np.ndarray',
        closes: 'np.ndarray',
        is_opposing: 'np.ndarray',
        current_idx: int,
        direction: str,
        min_zone_pct: float,
        seen_lows: list,
        seen_highs: list,
        skip_overlap: bool,
        overlap_threshold: float
    ) -> Optional[Dict[str, Any]]:
        """Find the last opposing candle for historical detection (no DB access, numpy-optimized)"""
        import numpy as np

        # Look for the last opposing candle in the previous 3 candles
        for j in range(current_idx - 1, max(current_idx - 4, 0), -1):
            if is_opposing[j]:
                zone_high = float(max(opens[j], closes[j]))
                zone_low = float(min(opens[j], closes[j]))

                # Check minimum zone size
                if zone_low <= 0:
                    continue
                zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                if zone_size_pct < min_zone_pct:
                    continue

                # Fast vectorized overlap check
                if not skip_overlap and seen_lows:
                    s_lows = np.array(seen_lows)
                    s_highs = np.array(seen_highs)
                    overlap_lows = np.maximum(s_lows, zone_low)
                    overlap_highs = np.minimum(s_highs, zone_high)
                    overlap_sizes = np.maximum(0, overlap_highs - overlap_lows)
                    seen_sizes = s_highs - s_lows
                    zone_size = zone_high - zone_low
                    smaller_sizes = np.minimum(seen_sizes, zone_size)
                    with np.errstate(divide='ignore', invalid='ignore'):
                        overlap_pcts = np.where(smaller_sizes > 0, overlap_sizes / smaller_sizes, 0)
                    if np.any(overlap_pcts >= overlap_threshold):
                        continue
                    seen_lows.append(zone_low)
                    seen_highs.append(zone_high)
                elif not skip_overlap:
                    seen_lows.append(zone_low)
                    seen_highs.append(zone_high)

                return {
                    'pattern_type': self.pattern_type,
                    'direction': direction,
                    'zone_high': zone_high,
                    'zone_low': zone_low,
                    'detected_at': current_idx
                }

        return None
