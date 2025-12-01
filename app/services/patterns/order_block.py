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
from app.models import Symbol, Pattern
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
        df['range'] = df['high'] - df['low']
        df['is_bullish'] = df['body'] > 0
        df['is_bearish'] = df['body'] < 0

        # Calculate average body size for comparison
        avg_body = df['body_size'].rolling(20).mean()

        for i in range(3, len(df) - 1):
            # Look for strong moves (2x average body size)
            current_body = df.iloc[i]['body_size']

            if pd.isna(avg_body.iloc[i]) or avg_body.iloc[i] == 0:
                continue

            is_strong_move = current_body > (avg_body.iloc[i] * 1.5)

            if not is_strong_move:
                continue

            # Bullish Order Block: Last bearish candle before strong bullish move
            if df.iloc[i]['is_bullish']:
                # Look for the last bearish candle in the previous 3 candles
                for j in range(i - 1, max(i - 4, 0), -1):
                    if df.iloc[j]['is_bearish']:
                        zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                        zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])

                        # Check if pattern already exists
                        existing = Pattern.query.filter_by(
                            symbol_id=sym.id,
                            timeframe=timeframe,
                            pattern_type='order_block',
                            detected_at=int(df.iloc[i]['timestamp'])
                        ).first()

                        if not existing:
                            pattern = Pattern(
                                symbol_id=sym.id,
                                timeframe=timeframe,
                                pattern_type='order_block',
                                direction='bullish',
                                zone_high=zone_high,
                                zone_low=zone_low,
                                detected_at=int(df.iloc[i]['timestamp']),
                                status='active'
                            )
                            db.session.add(pattern)
                            patterns.append({
                                'type': 'order_block',
                                'direction': 'bullish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': int(df.iloc[i]['timestamp']),
                                'symbol': symbol,
                                'timeframe': timeframe
                            })
                        break

            # Bearish Order Block: Last bullish candle before strong bearish move
            elif df.iloc[i]['is_bearish']:
                # Look for the last bullish candle in the previous 3 candles
                for j in range(i - 1, max(i - 4, 0), -1):
                    if df.iloc[j]['is_bullish']:
                        zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                        zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])

                        # Check if pattern already exists
                        existing = Pattern.query.filter_by(
                            symbol_id=sym.id,
                            timeframe=timeframe,
                            pattern_type='order_block',
                            detected_at=int(df.iloc[i]['timestamp'])
                        ).first()

                        if not existing:
                            pattern = Pattern(
                                symbol_id=sym.id,
                                timeframe=timeframe,
                                pattern_type='order_block',
                                direction='bearish',
                                zone_high=zone_high,
                                zone_low=zone_low,
                                detected_at=int(df.iloc[i]['timestamp']),
                                status='active'
                            )
                            db.session.add(pattern)
                            patterns.append({
                                'type': 'order_block',
                                'direction': 'bearish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': int(df.iloc[i]['timestamp']),
                                'symbol': symbol,
                                'timeframe': timeframe
                            })
                        break

        db.session.commit()
        return patterns

    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if an order block has been filled (mitigated)

        An order block is considered:
        - Partially filled: Price has entered the zone
        - Fully filled: Price has wicked through 50%+ of the zone
        """
        zone_high = pattern['zone_high']
        zone_low = pattern['zone_low']
        direction = pattern['direction']

        if direction == 'bullish':
            # For bullish OB, we wait for price to come DOWN to the zone
            if current_price <= zone_low:
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price <= zone_high:
                fill_pct = ((zone_high - current_price) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 0}
        else:
            # For bearish OB, we wait for price to come UP to the zone
            if current_price >= zone_high:
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price >= zone_low:
                fill_pct = ((current_price - zone_low) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 0}
