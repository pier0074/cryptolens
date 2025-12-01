"""
Imbalance (Fair Value Gap) Pattern Detector

Detects price imbalances where:
- Bullish: Candle 1 High < Candle 3 Low (gap up)
- Bearish: Candle 1 Low > Candle 3 High (gap down)

These gaps often get "filled" when price returns to them.
"""
from typing import List, Dict, Any
import pandas as pd
from app.services.patterns.base import PatternDetector
from app.models import Symbol, Pattern
from app import db


class ImbalanceDetector(PatternDetector):
    """Detector for Fair Value Gaps (Imbalances)"""

    @property
    def pattern_type(self) -> str:
        return 'imbalance'

    def detect(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Detect imbalances in the given symbol/timeframe

        Returns:
            List of detected imbalance patterns
        """
        df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 3:
            return []

        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return []

        patterns = []

        for i in range(2, len(df)):
            c1 = df.iloc[i - 2]  # First candle
            c2 = df.iloc[i - 1]  # Middle candle (the impulse)
            c3 = df.iloc[i]      # Third candle

            # Bullish Imbalance: Gap between c1 high and c3 low
            if c1['high'] < c3['low']:
                zone_low = c1['high']
                zone_high = c3['low']

                # Check if pattern already exists
                existing = Pattern.query.filter_by(
                    symbol_id=sym.id,
                    timeframe=timeframe,
                    pattern_type='imbalance',
                    detected_at=int(c3['timestamp'])
                ).first()

                if not existing:
                    pattern = Pattern(
                        symbol_id=sym.id,
                        timeframe=timeframe,
                        pattern_type='imbalance',
                        direction='bullish',
                        zone_high=zone_high,
                        zone_low=zone_low,
                        detected_at=int(c3['timestamp']),
                        status='active'
                    )
                    db.session.add(pattern)
                    patterns.append({
                        'type': 'imbalance',
                        'direction': 'bullish',
                        'zone_high': zone_high,
                        'zone_low': zone_low,
                        'detected_at': int(c3['timestamp']),
                        'symbol': symbol,
                        'timeframe': timeframe
                    })

            # Bearish Imbalance: Gap between c1 low and c3 high
            if c1['low'] > c3['high']:
                zone_high = c1['low']
                zone_low = c3['high']

                # Check if pattern already exists
                existing = Pattern.query.filter_by(
                    symbol_id=sym.id,
                    timeframe=timeframe,
                    pattern_type='imbalance',
                    detected_at=int(c3['timestamp'])
                ).first()

                if not existing:
                    pattern = Pattern(
                        symbol_id=sym.id,
                        timeframe=timeframe,
                        pattern_type='imbalance',
                        direction='bearish',
                        zone_high=zone_high,
                        zone_low=zone_low,
                        detected_at=int(c3['timestamp']),
                        status='active'
                    )
                    db.session.add(pattern)
                    patterns.append({
                        'type': 'imbalance',
                        'direction': 'bearish',
                        'zone_high': zone_high,
                        'zone_low': zone_low,
                        'detected_at': int(c3['timestamp']),
                        'symbol': symbol,
                        'timeframe': timeframe
                    })

        db.session.commit()
        return patterns

    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if an imbalance has been filled

        An imbalance is considered:
        - Partially filled: Price has entered the zone
        - Fully filled: Price has crossed through the entire zone
        - Invalidated: Price moved significantly away without filling
        """
        zone_high = pattern['zone_high']
        zone_low = pattern['zone_low']
        direction = pattern['direction']

        if direction == 'bullish':
            # For bullish imbalance, we're waiting for price to come DOWN to fill
            if current_price <= zone_low:
                # Fully filled
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price <= zone_high:
                # Partially filled
                fill_pct = ((zone_high - current_price) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                # Not yet filled
                return {**pattern, 'status': 'active', 'fill_percentage': 0}

        else:  # bearish
            # For bearish imbalance, we're waiting for price to come UP to fill
            if current_price >= zone_high:
                # Fully filled
                return {**pattern, 'status': 'filled', 'fill_percentage': 100}
            elif current_price >= zone_low:
                # Partially filled
                fill_pct = ((current_price - zone_low) / (zone_high - zone_low)) * 100
                return {**pattern, 'status': 'active', 'fill_percentage': min(fill_pct, 100)}
            else:
                # Not yet filled
                return {**pattern, 'status': 'active', 'fill_percentage': 0}

    def update_pattern_status(self, symbol: str, timeframe: str, current_price: float) -> int:
        """
        Update the status of all active patterns for a symbol/timeframe

        Returns:
            Number of patterns updated
        """
        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return 0

        patterns = Pattern.query.filter_by(
            symbol_id=sym.id,
            timeframe=timeframe,
            pattern_type='imbalance',
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
