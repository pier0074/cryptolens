"""
Liquidity Sweep Pattern Detector

Liquidity Sweeps occur when price takes out a previous high/low (where stop losses are placed)
and then reverses. This is often a sign of institutional manipulation.

Bullish Liquidity Sweep (Sweep Low):
- Price takes out a previous swing low (hunts stop losses)
- Then reverses and closes back above the low
- Signal to go long

Bearish Liquidity Sweep (Sweep High):
- Price takes out a previous swing high (hunts stop losses)
- Then reverses and closes back below the high
- Signal to go short
"""
from typing import List, Dict, Any
import pandas as pd
import numpy as np
from app.services.patterns.base import PatternDetector
from app.models import Symbol, Pattern
from app import db


class LiquiditySweepDetector(PatternDetector):
    """Detector for Liquidity Sweep patterns"""

    @property
    def pattern_type(self) -> str:
        return 'liquidity_sweep'

    def find_swing_points(self, df: pd.DataFrame, lookback: int = 5) -> tuple:
        """Find swing highs and swing lows"""
        swing_highs = []
        swing_lows = []

        for i in range(lookback, len(df) - lookback):
            # Check for swing high
            is_swing_high = True
            for j in range(1, lookback + 1):
                if df.iloc[i]['high'] <= df.iloc[i - j]['high'] or \
                   df.iloc[i]['high'] <= df.iloc[i + j]['high']:
                    is_swing_high = False
                    break

            if is_swing_high:
                swing_highs.append({
                    'index': i,
                    'price': df.iloc[i]['high'],
                    'timestamp': df.iloc[i]['timestamp']
                })

            # Check for swing low
            is_swing_low = True
            for j in range(1, lookback + 1):
                if df.iloc[i]['low'] >= df.iloc[i - j]['low'] or \
                   df.iloc[i]['low'] >= df.iloc[i + j]['low']:
                    is_swing_low = False
                    break

            if is_swing_low:
                swing_lows.append({
                    'index': i,
                    'price': df.iloc[i]['low'],
                    'timestamp': df.iloc[i]['timestamp']
                })

        return swing_highs, swing_lows

    def detect(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Detect Liquidity Sweeps in the given symbol/timeframe

        Returns:
            List of detected liquidity sweep patterns
        """
        df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 20:
            return []

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return []

        patterns = []

        # Find swing points
        swing_highs, swing_lows = self.find_swing_points(df, lookback=3)

        # Look for liquidity sweeps in recent candles
        for i in range(len(df) - 10, len(df)):
            if i < 0:
                continue

            current = df.iloc[i]

            # Check for bullish sweep (sweep of lows)
            for swing_low in swing_lows:
                # Skip if swing is too recent or after current candle
                if swing_low['index'] >= i - 3 or swing_low['index'] < i - 50:
                    continue

                # Check if current candle swept the low and reversed
                if current['low'] < swing_low['price'] and current['close'] > swing_low['price']:
                    # This is a bullish liquidity sweep
                    zone_low = current['low']
                    zone_high = swing_low['price']

                    # Skip zones that are too small to trade
                    if not self.is_zone_tradeable(zone_low, zone_high):
                        continue

                    # Skip if overlapping pattern already exists (70% threshold)
                    if self.has_overlapping_pattern(sym.id, timeframe, 'bullish', zone_low, zone_high):
                        continue

                    pattern_dict = self.save_pattern(
                        sym.id, timeframe, 'bullish', zone_low, zone_high,
                        int(current['timestamp']), symbol, df
                    )
                    if pattern_dict:
                        pattern_dict['swept_level'] = swing_low['price']
                        patterns.append(pattern_dict)
                    break  # Only one sweep per candle

            # Check for bearish sweep (sweep of highs)
            for swing_high in swing_highs:
                # Skip if swing is too recent or after current candle
                if swing_high['index'] >= i - 3 or swing_high['index'] < i - 50:
                    continue

                # Check if current candle swept the high and reversed
                if current['high'] > swing_high['price'] and current['close'] < swing_high['price']:
                    # This is a bearish liquidity sweep
                    zone_high = current['high']
                    zone_low = swing_high['price']

                    # Skip zones that are too small to trade
                    if not self.is_zone_tradeable(zone_low, zone_high):
                        continue

                    # Skip if overlapping pattern already exists (70% threshold)
                    if self.has_overlapping_pattern(sym.id, timeframe, 'bearish', zone_low, zone_high):
                        continue

                    pattern_dict = self.save_pattern(
                        sym.id, timeframe, 'bearish', zone_low, zone_high,
                        int(current['timestamp']), symbol, df
                    )
                    if pattern_dict:
                        pattern_dict['swept_level'] = swing_high['price']
                        patterns.append(pattern_dict)
                    break  # Only one sweep per candle

        db.session.commit()
        return patterns

    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if a liquidity sweep setup is still valid

        A sweep is invalidated if price moves significantly against the expected direction
        """
        zone_high = pattern['zone_high']
        zone_low = pattern['zone_low']
        direction = pattern['direction']

        zone_size = zone_high - zone_low

        if direction == 'bullish':
            # Bullish sweep invalidated if price drops below the sweep low
            if current_price < zone_low - zone_size:
                return {**pattern, 'status': 'invalidated', 'fill_percentage': 0}
            # Filled if price has moved up significantly
            elif current_price > zone_high + (zone_size * 2):
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 50}
        else:
            # Bearish sweep invalidated if price rises above the sweep high
            if current_price > zone_high + zone_size:
                return {**pattern, 'status': 'invalidated', 'fill_percentage': 0}
            # Filled if price has moved down significantly
            elif current_price < zone_low - (zone_size * 2):
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            else:
                return {**pattern, 'status': 'active', 'fill_percentage': 50}

    def update_pattern_status(self, symbol: str, timeframe: str, current_price: float) -> int:
        """
        Update the status of all active liquidity sweep patterns

        Returns:
            Number of patterns updated
        """
        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return 0

        patterns = Pattern.query.filter_by(
            symbol_id=sym.id,
            timeframe=timeframe,
            pattern_type='liquidity_sweep',
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
