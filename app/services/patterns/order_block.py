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
from app import db


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
        Detect Order Blocks in the given symbol/timeframe

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

        # Store precomputed for use in _find_opposing_candle
        self._precomputed = precomputed

        patterns = []

        # Calculate candle body and move strength
        df = df.copy()  # Avoid modifying original
        df['body'] = df['close'] - df['open']
        df['body_size'] = abs(df['body'])
        df['is_bullish'] = df['body'] > 0
        df['is_bearish'] = df['body'] < 0

        # Calculate average body size for comparison
        avg_body = df['body_size'].rolling(20).mean()

        for i in range(3, len(df) - 1):
            current_body = df.iloc[i]['body_size']

            if pd.isna(avg_body.iloc[i]) or avg_body.iloc[i] == 0:
                continue

            # Check for strong move (body larger than threshold * average)
            is_strong_move = current_body > (avg_body.iloc[i] * Config.ORDER_BLOCK_STRENGTH_MULTIPLIER)
            if not is_strong_move:
                continue

            detected_at = int(df.iloc[i]['timestamp'])

            # Bullish Order Block: Last bearish candle before strong bullish move
            if df.iloc[i]['is_bullish']:
                pattern = self._find_opposing_candle(
                    df, i, 'bearish', sym.id, timeframe, symbol, detected_at
                )
                if pattern:
                    patterns.append(pattern)

            # Bearish Order Block: Last bullish candle before strong bearish move
            elif df.iloc[i]['is_bearish']:
                pattern = self._find_opposing_candle(
                    df, i, 'bullish', sym.id, timeframe, symbol, detected_at
                )
                if pattern:
                    patterns.append(pattern)

        # Don't commit here - let caller batch commits
        self._precomputed = None
        return patterns

    def _find_opposing_candle(
        self,
        df: pd.DataFrame,
        current_idx: int,
        candle_type: str,
        symbol_id: int,
        timeframe: str,
        symbol_name: str,
        detected_at: int
    ) -> Dict[str, Any]:
        """Find the last opposing candle and create order block pattern"""
        is_opposing = 'is_bearish' if candle_type == 'bearish' else 'is_bullish'
        direction = 'bullish' if candle_type == 'bearish' else 'bearish'

        # Look for the last opposing candle in the previous 3 candles
        for j in range(current_idx - 1, max(current_idx - 4, 0), -1):
            if df.iloc[j][is_opposing]:
                zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])

                # Check if pattern should be saved
                if not self.is_zone_tradeable(zone_low, zone_high):
                    continue
                if self.has_overlapping_pattern(symbol_id, timeframe, direction, zone_low, zone_high):
                    continue

                pattern_dict = self.save_pattern(
                    symbol_id, timeframe, direction, zone_low, zone_high, detected_at, symbol_name, df,
                    precomputed=self._precomputed
                )
                return pattern_dict

        return None

    def detect_historical(
        self,
        df: pd.DataFrame,
        min_zone_pct: float = None,
        skip_overlap: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Detect Order Block patterns in historical data WITHOUT database interaction.
        Used for backtesting to match production detection exactly.

        Args:
            df: DataFrame with OHLCV data (must have: timestamp, open, high, low, close, volume)
            min_zone_pct: Minimum zone size as % of price (None = use Config.MIN_ZONE_PERCENT)
            skip_overlap: If True, skip overlap detection (faster for backtesting)

        Returns:
            List of detected patterns (dicts with zone_high, zone_low, direction, detected_at, etc.)
        """
        if df.empty or len(df) < 5:
            return []

        min_zone = min_zone_pct if min_zone_pct is not None else Config.MIN_ZONE_PERCENT
        patterns = []
        seen_zones = []  # For local overlap tracking

        # Calculate candle body and move strength
        df = df.copy()
        df['body'] = df['close'] - df['open']
        df['body_size'] = abs(df['body'])
        df['is_bullish'] = df['body'] > 0
        df['is_bearish'] = df['body'] < 0

        # Calculate average body size for comparison
        avg_body = df['body_size'].rolling(20).mean()

        for i in range(3, len(df)):
            current_body = df.iloc[i]['body_size']

            if pd.isna(avg_body.iloc[i]) or avg_body.iloc[i] == 0:
                continue

            # Check for strong move (body larger than threshold * average)
            is_strong_move = current_body > (avg_body.iloc[i] * Config.ORDER_BLOCK_STRENGTH_MULTIPLIER)
            if not is_strong_move:
                continue

            # Bullish OB: Last bearish candle before strong bullish move
            if df.iloc[i]['is_bullish']:
                pattern = self._find_historical_opposing_candle(
                    df, i, 'bearish', 'bullish', min_zone, seen_zones, skip_overlap
                )
                if pattern:
                    patterns.append(pattern)
                    if not skip_overlap:
                        seen_zones.append((pattern['direction'], pattern['zone_low'], pattern['zone_high']))

            # Bearish OB: Last bullish candle before strong bearish move
            elif df.iloc[i]['is_bearish']:
                pattern = self._find_historical_opposing_candle(
                    df, i, 'bullish', 'bearish', min_zone, seen_zones, skip_overlap
                )
                if pattern:
                    patterns.append(pattern)
                    if not skip_overlap:
                        seen_zones.append((pattern['direction'], pattern['zone_low'], pattern['zone_high']))

        return patterns

    def _find_historical_opposing_candle(
        self,
        df: pd.DataFrame,
        current_idx: int,
        candle_type: str,
        direction: str,
        min_zone_pct: float,
        seen_zones: list,
        skip_overlap: bool
    ) -> Optional[Dict[str, Any]]:
        """Find the last opposing candle for historical detection (no DB access)"""
        is_opposing = 'is_bearish' if candle_type == 'bearish' else 'is_bullish'

        # Look for the last opposing candle in the previous 3 candles
        for j in range(current_idx - 1, max(current_idx - 4, 0), -1):
            if df.iloc[j][is_opposing]:
                zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])

                # Check minimum zone size
                if zone_low <= 0:
                    continue
                zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                if zone_size_pct < min_zone_pct:
                    continue

                # Check overlap with already-detected patterns
                if not skip_overlap:
                    has_overlap = False
                    for seen_dir, seen_low, seen_high in seen_zones:
                        if seen_dir != direction:
                            continue
                        overlap = self._calculate_zone_overlap(seen_low, seen_high, zone_low, zone_high)
                        if overlap >= 0.7:
                            has_overlap = True
                            break
                    if has_overlap:
                        continue

                return {
                    'pattern_type': self.pattern_type,
                    'direction': direction,
                    'zone_high': float(zone_high),
                    'zone_low': float(zone_low),
                    'detected_at': current_idx,
                    'detected_ts': int(df.iloc[current_idx]['timestamp']) if 'timestamp' in df.columns else None
                }

        return None
