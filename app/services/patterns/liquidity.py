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
from typing import List, Dict, Any, Optional
import pandas as pd
from app.services.patterns.base import PatternDetector
from app.models import Symbol, Pattern
from app import db


class LiquiditySweepDetector(PatternDetector):
    """Detector for Liquidity Sweep patterns"""

    def __init__(self):
        super().__init__()

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

    def find_swing_points_fast(self, highs: 'np.ndarray', lows: 'np.ndarray',
                                timestamps: 'np.ndarray', lookback: int = 5) -> tuple:
        """Find swing highs and swing lows using pandas rolling (vectorized, fast)"""
        import numpy as np

        n = len(highs)
        if n < 2 * lookback + 1:
            return [], []

        window_size = 2 * lookback + 1

        # Use pandas rolling for vectorized max/min
        high_series = pd.Series(highs)
        low_series = pd.Series(lows)

        rolling_max = high_series.rolling(window_size, center=True).max().values
        rolling_min = low_series.rolling(window_size, center=True).min().values

        # Swing high: equals rolling max (close enough for backtesting)
        is_swing_high = (highs == rolling_max)
        is_swing_low = (lows == rolling_min)

        # Filter to valid range
        valid_range = np.zeros(n, dtype=bool)
        valid_range[lookback:n - lookback] = True
        is_swing_high = is_swing_high & valid_range
        is_swing_low = is_swing_low & valid_range

        # Get indices
        swing_high_indices = np.where(is_swing_high)[0]
        swing_low_indices = np.where(is_swing_low)[0]

        # Convert to list of dicts
        swing_highs = [
            {'index': int(i), 'price': float(highs[i]),
             'timestamp': int(timestamps[i]) if timestamps is not None else None}
            for i in swing_high_indices
        ]

        swing_lows = [
            {'index': int(i), 'price': float(lows[i]),
             'timestamp': int(timestamps[i]) if timestamps is not None else None}
            for i in swing_low_indices
        ]

        return swing_highs, swing_lows

    def detect(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        df: Optional[pd.DataFrame] = None,
        precomputed: dict = None
    ) -> List[Dict[str, Any]]:
        """
        Detect Liquidity Sweeps in the given symbol/timeframe.

        Uses detect_historical() for pattern detection (shared algorithm),
        then filters by DB overlap and saves to database.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze
            df: Optional pre-loaded DataFrame (avoids redundant DB queries)
            precomputed: Optional dict with pre-calculated {'atr', 'swing_high', 'swing_low'}

        Returns:
            List of detected liquidity sweep patterns
        """
        if df is None:
            df = self.get_candles_df(symbol, timeframe, limit)

        if df.empty or len(df) < 20:
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
            swept_level = raw.get('swept_level')

            # Check DB overlap (production uses persistent pattern storage)
            if self.has_overlapping_pattern(sym.id, timeframe, direction, zone_low, zone_high):
                continue

            pattern_dict = self.save_pattern(
                sym.id, timeframe, direction, zone_low, zone_high, detected_at, symbol, df,
                precomputed=precomputed
            )
            if pattern_dict:
                if swept_level:
                    pattern_dict['swept_level'] = swept_level
                patterns.append(pattern_dict)

        # Don't commit here - let caller batch commits
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

    def update_pattern_status(self, symbol: str, timeframe: str, current_price: float, commit: bool = True) -> int:
        """
        Update the status of all active liquidity sweep patterns

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            current_price: Current market price
            commit: Whether to commit immediately (False for batching)

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

        if commit:
            db.session.commit()
        return updated

    def detect_historical(
        self,
        df: pd.DataFrame,
        min_zone_pct: float = None,
        skip_overlap: bool = False,
        verbose: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Detect Liquidity Sweep patterns in historical data WITHOUT database interaction.
        Uses numpy arrays for fast vectorized detection.

        Args:
            df: DataFrame with OHLCV data (must have: timestamp, open, high, low, close, volume)
            min_zone_pct: Minimum zone size as % of price (None = use Config.MIN_ZONE_PERCENT)
            skip_overlap: If True, skip overlap detection (faster for backtesting)
            verbose: 0=silent, 1=summary only, 2=detailed timing

        Returns:
            List of detected patterns (dicts with zone_high, zone_low, direction, detected_at, etc.)
        """
        from app.config import Config
        import numpy as np
        from datetime import datetime, timezone

        if df.empty or len(df) < 20:
            return []

        t0 = datetime.now(timezone.utc)
        min_zone = min_zone_pct if min_zone_pct is not None else Config.MIN_ZONE_PERCENT
        patterns = []

        # Convert to numpy arrays for fast access (MAJOR speedup vs df.iloc)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        timestamps = df['timestamp'].values if 'timestamp' in df.columns else None

        t1 = datetime.now(timezone.utc)
        n = len(df)

        # Find swing points using numpy arrays (fast)
        swing_highs, swing_lows = self.find_swing_points_fast(highs, lows, timestamps, lookback=3)

        t2 = datetime.now(timezone.utc)

        # Pre-allocate numpy arrays for overlap tracking (avoids O(n²) list-to-array conversions)
        # Initial capacity of 64, doubles when full (amortized O(1) append)
        initial_capacity = 64
        seen_bullish_lows = np.empty(initial_capacity, dtype=np.float64)
        seen_bullish_highs = np.empty(initial_capacity, dtype=np.float64)
        seen_bearish_lows = np.empty(initial_capacity, dtype=np.float64)
        seen_bearish_highs = np.empty(initial_capacity, dtype=np.float64)
        n_bullish = 0
        n_bearish = 0
        overlap_threshold = Config.DEFAULT_OVERLAP_THRESHOLD

        # Pre-extract swing indices for fast lookup
        # Swing points are already sorted by index from find_swing_points_fast
        swing_low_indices = np.array([s['index'] for s in swing_lows], dtype=np.int64)
        swing_low_prices = np.array([s['price'] for s in swing_lows])
        swing_high_indices = np.array([s['index'] for s in swing_highs], dtype=np.int64)
        swing_high_prices = np.array([s['price'] for s in swing_highs])

        n_swing_lows = len(swing_low_indices)
        n_swing_highs = len(swing_high_indices)

        # Scan through all candles (not just recent 10 like production)
        for i in range(10, n):
            current_low = lows[i]
            current_high = highs[i]
            current_close = closes[i]
            current_ts = int(timestamps[i]) if timestamps is not None else None

            # Valid swing range: index in [i-50, i-4] (i.e., >= i-50 and < i-3)
            min_idx = i - 50
            max_idx = i - 3

            # Check for bullish sweep (sweep of lows) - use binary search for O(log s)
            if n_swing_lows > 0:
                # Binary search to find range of valid swing lows
                left = np.searchsorted(swing_low_indices, min_idx, side='left')
                right = np.searchsorted(swing_low_indices, max_idx, side='left')

                # Check if current candle swept any of these lows and reversed
                for j in range(left, right):
                    swing_price = swing_low_prices[j]
                    if current_low < swing_price and current_close > swing_price:
                        zone_low = float(current_low)
                        zone_high = float(swing_price)

                        # Must have positive zone
                        if zone_high <= zone_low or zone_low <= 0:
                            continue

                        # Check minimum zone size
                        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                        if zone_size_pct < min_zone:
                            continue

                        # Fast vectorized overlap check using pre-allocated arrays
                        is_valid = True
                        if not skip_overlap and n_bullish > 0:
                            # Use sliced view instead of creating new array
                            s_lows = seen_bullish_lows[:n_bullish]
                            s_highs = seen_bullish_highs[:n_bullish]
                            overlap_lows = np.maximum(s_lows, zone_low)
                            overlap_highs = np.minimum(s_highs, zone_high)
                            overlap_sizes = np.maximum(0, overlap_highs - overlap_lows)
                            seen_sizes = s_highs - s_lows
                            zone_size = zone_high - zone_low
                            smaller_sizes = np.minimum(seen_sizes, zone_size)
                            with np.errstate(divide='ignore', invalid='ignore'):
                                overlap_pcts = np.where(smaller_sizes > 0, overlap_sizes / smaller_sizes, 0)
                            if np.any(overlap_pcts >= overlap_threshold):
                                is_valid = False
                            else:
                                # Grow array if needed (double capacity)
                                if n_bullish >= len(seen_bullish_lows):
                                    seen_bullish_lows = np.concatenate([seen_bullish_lows, np.empty(len(seen_bullish_lows), dtype=np.float64)])
                                    seen_bullish_highs = np.concatenate([seen_bullish_highs, np.empty(len(seen_bullish_highs), dtype=np.float64)])
                                seen_bullish_lows[n_bullish] = zone_low
                                seen_bullish_highs[n_bullish] = zone_high
                                n_bullish += 1
                        elif not skip_overlap:
                            # Grow array if needed
                            if n_bullish >= len(seen_bullish_lows):
                                seen_bullish_lows = np.concatenate([seen_bullish_lows, np.empty(len(seen_bullish_lows), dtype=np.float64)])
                                seen_bullish_highs = np.concatenate([seen_bullish_highs, np.empty(len(seen_bullish_highs), dtype=np.float64)])
                            seen_bullish_lows[n_bullish] = zone_low
                            seen_bullish_highs[n_bullish] = zone_high
                            n_bullish += 1

                        if is_valid:
                            patterns.append({
                                'pattern_type': self.pattern_type,
                                'direction': 'bullish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': i,
                                'detected_ts': current_ts,
                                'swept_level': float(swing_price)
                            })
                        break  # Only one sweep per candle

            # Check for bearish sweep (sweep of highs) - use binary search for O(log s)
            if n_swing_highs > 0:
                # Binary search to find range of valid swing highs
                left = np.searchsorted(swing_high_indices, min_idx, side='left')
                right = np.searchsorted(swing_high_indices, max_idx, side='left')

                for j in range(left, right):
                    swing_price = swing_high_prices[j]
                    if current_high > swing_price and current_close < swing_price:
                        zone_high = float(current_high)
                        zone_low = float(swing_price)

                        # Must have positive zone
                        if zone_high <= zone_low or zone_low <= 0:
                            continue

                        # Check minimum zone size
                        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
                        if zone_size_pct < min_zone:
                            continue

                        # Fast vectorized overlap check using pre-allocated arrays
                        is_valid = True
                        if not skip_overlap and n_bearish > 0:
                            # Use sliced view instead of creating new array
                            s_lows = seen_bearish_lows[:n_bearish]
                            s_highs = seen_bearish_highs[:n_bearish]
                            overlap_lows = np.maximum(s_lows, zone_low)
                            overlap_highs = np.minimum(s_highs, zone_high)
                            overlap_sizes = np.maximum(0, overlap_highs - overlap_lows)
                            seen_sizes = s_highs - s_lows
                            zone_size = zone_high - zone_low
                            smaller_sizes = np.minimum(seen_sizes, zone_size)
                            with np.errstate(divide='ignore', invalid='ignore'):
                                overlap_pcts = np.where(smaller_sizes > 0, overlap_sizes / smaller_sizes, 0)
                            if np.any(overlap_pcts >= overlap_threshold):
                                is_valid = False
                            else:
                                # Grow array if needed
                                if n_bearish >= len(seen_bearish_lows):
                                    seen_bearish_lows = np.concatenate([seen_bearish_lows, np.empty(len(seen_bearish_lows), dtype=np.float64)])
                                    seen_bearish_highs = np.concatenate([seen_bearish_highs, np.empty(len(seen_bearish_highs), dtype=np.float64)])
                                seen_bearish_lows[n_bearish] = zone_low
                                seen_bearish_highs[n_bearish] = zone_high
                                n_bearish += 1
                        elif not skip_overlap:
                            # Grow array if needed
                            if n_bearish >= len(seen_bearish_lows):
                                seen_bearish_lows = np.concatenate([seen_bearish_lows, np.empty(len(seen_bearish_lows), dtype=np.float64)])
                                seen_bearish_highs = np.concatenate([seen_bearish_highs, np.empty(len(seen_bearish_highs), dtype=np.float64)])
                            seen_bearish_lows[n_bearish] = zone_low
                            seen_bearish_highs[n_bearish] = zone_high
                            n_bearish += 1

                        if is_valid:
                            patterns.append({
                                'pattern_type': self.pattern_type,
                                'direction': 'bearish',
                                'zone_high': zone_high,
                                'zone_low': zone_low,
                                'detected_at': i,
                                'detected_ts': current_ts,
                                'swept_level': float(swing_price)
                            })
                        break  # Only one sweep per candle

        t3 = datetime.now(timezone.utc)
        total_ms = (t3 - t0).total_seconds() * 1000

        # Debug output based on verbose level
        if verbose >= 2 and total_ms > 500:  # Detailed timing only if slow
            arr_ms = (t1 - t0).total_seconds() * 1000
            swing_ms = (t2 - t1).total_seconds() * 1000
            loop_ms = (t3 - t2).total_seconds() * 1000
            print(f"      [LS] {n:,} candles: arr={arr_ms:.0f}ms, swing={swing_ms:.0f}ms, "
                  f"loop={loop_ms:.0f}ms, total={total_ms:.0f}ms, swings=({len(swing_highs)}H,{len(swing_lows)}L), "
                  f"patterns={len(patterns)}", flush=True)
        elif verbose >= 1 and len(patterns) > 0:
            print(f"      [LS] Found {len(patterns)} patterns in {n:,} candles", flush=True)

        return patterns

    def _is_valid_historical_sweep(
        self,
        zone_low: float,
        zone_high: float,
        direction: str,
        min_zone_pct: float,
        seen_zones: list,
        skip_overlap: bool
    ) -> bool:
        """Check if sweep pattern is valid for historical detection (no DB access)"""
        # Must have positive zone
        if zone_high <= zone_low or zone_low <= 0:
            return False

        # Check minimum zone size
        zone_size_pct = ((zone_high - zone_low) / zone_low) * 100
        if zone_size_pct < min_zone_pct:
            return False

        # Check overlap with already-detected patterns
        if not skip_overlap:
            for seen_dir, seen_low, seen_high in seen_zones:
                if seen_dir != direction:
                    continue
                overlap = self._calculate_zone_overlap(seen_low, seen_high, zone_low, zone_high)
                if overlap >= 0.7:
                    return False

        return True
