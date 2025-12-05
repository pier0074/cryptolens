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
from typing import List, Dict, Any
import pandas as pd
from app.services.patterns.base import PatternDetector
from app.models import Symbol
from app.config import Config
from app import db


class OrderBlockDetector(PatternDetector):
    """Detector for Order Block patterns"""

    @property
    def pattern_type(self) -> str:
        return 'order_block'

    def detect(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Detect Order Blocks in the given symbol/timeframe

        Returns:
            List of detected order block patterns
        """
        df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 5:
            return []

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return []

        patterns = []

        # Calculate candle body and move strength
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

        db.session.commit()
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
                    symbol_id, timeframe, direction, zone_low, zone_high, detected_at, symbol_name, df
                )
                return pattern_dict

        return None
