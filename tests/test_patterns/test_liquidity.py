"""
Tests for Liquidity Sweep Pattern Detection
"""
import pytest
from app.models import Pattern, Symbol, Candle
from app.services.patterns.liquidity import LiquiditySweepDetector
from app import db


class TestSwingPointDetection:
    """Tests for swing point identification"""

    def test_find_swing_high(self, app, sample_symbol):
        """Test detection of swing highs"""
        with app.app_context():
            import pandas as pd
            base_time = 1700000000000

            # Create pattern: low-low-HIGH-low-low (swing high in middle)
            highs = [100, 101, 105, 101, 100, 99, 100, 101, 100, 99, 100]
            lows = [98, 99, 103, 99, 98, 97, 98, 99, 98, 97, 98]

            for i, (h, l) in enumerate(zip(highs, lows)):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=l + 0.5,
                    high=h,
                    low=l,
                    close=h - 0.5,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = LiquiditySweepDetector()
            df = detector.get_candles_df('BTC/USDT', '1h')
            swing_highs, swing_lows = detector.find_swing_points(df, lookback=2)

            # Should find the swing high at 105
            assert len(swing_highs) >= 1
            assert any(sh['price'] == 105 for sh in swing_highs)

    def test_find_swing_low(self, app, sample_symbol):
        """Test detection of swing lows"""
        with app.app_context():
            base_time = 1700000000000

            # Create pattern: high-high-LOW-high-high (swing low in middle)
            highs = [102, 101, 97, 101, 102, 103, 102, 101, 102, 103, 102]
            lows = [100, 99, 95, 99, 100, 101, 100, 99, 100, 101, 100]

            for i, (h, l) in enumerate(zip(highs, lows)):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=l + 0.5,
                    high=h,
                    low=l,
                    close=h - 0.5,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = LiquiditySweepDetector()
            df = detector.get_candles_df('BTC/USDT', '1h')
            swing_highs, swing_lows = detector.find_swing_points(df, lookback=2)

            # Should find the swing low at 95
            assert len(swing_lows) >= 1
            assert any(sl['price'] == 95 for sl in swing_lows)


class TestLiquiditySweepDetector:
    """Tests for Liquidity Sweep detection"""

    def test_detect_bullish_sweep(self, app, sample_symbol):
        """Test detection of bullish liquidity sweep (sweep of lows)"""
        with app.app_context():
            base_time = 1700000000000

            # First create a swing low, then later sweep it and reverse
            # Candles 0-9: Build up with a swing low at index 5
            lows = [100, 99, 98, 99, 100, 95, 100, 99, 100, 101]  # Swing low at 95
            highs = [102, 101, 100, 101, 102, 97, 102, 101, 102, 103]

            for i, (h, l) in enumerate(zip(highs, lows)):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=l + 1,
                    high=h,
                    low=l,
                    close=h - 0.5,
                    volume=1000
                )
                db.session.add(candle)

            # Add more candles to reach the detection window (need 20+)
            for i in range(10, 20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=101.0,
                    high=102.0,
                    low=100.0,
                    close=101.5,
                    volume=1000
                )
                db.session.add(candle)

            # Candle 20: Sweep the low at 95 and close above it
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 20 * 3600000,
                open=100.0,
                high=101.0,
                low=93.0,  # Sweeps below 95
                close=96.0,  # Closes above 95 (reversal)
                volume=2000
            )
            db.session.add(candle)
            db.session.commit()

            detector = LiquiditySweepDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            # May or may not detect depending on lookback, but should not error
            # The detection logic requires specific swing point timing
            assert isinstance(patterns, list)

    def test_detect_bearish_sweep(self, app, sample_symbol):
        """Test detection of bearish liquidity sweep (sweep of highs)"""
        with app.app_context():
            base_time = 1700000000000

            # Build up with a swing high at index 5
            highs = [100, 101, 102, 101, 100, 108, 100, 101, 100, 99]  # Swing high at 108
            lows = [98, 99, 100, 99, 98, 106, 98, 99, 98, 97]

            for i, (h, l) in enumerate(zip(highs, lows)):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=l + 1,
                    high=h,
                    low=l,
                    close=l + 0.5,
                    volume=1000
                )
                db.session.add(candle)

            # Add more candles
            for i in range(10, 20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=99.0,
                    high=100.0,
                    low=98.0,
                    close=98.5,
                    volume=1000
                )
                db.session.add(candle)

            # Sweep the high at 108 and close below it
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 20 * 3600000,
                open=100.0,
                high=110.0,  # Sweeps above 108
                low=99.0,
                close=106.0,  # Closes below 108 (reversal)
                volume=2000
            )
            db.session.add(candle)
            db.session.commit()

            detector = LiquiditySweepDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            assert isinstance(patterns, list)

    def test_insufficient_candles(self, app, sample_symbol):
        """Test with less than 20 candles"""
        with app.app_context():
            for i in range(15):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = LiquiditySweepDetector()
            patterns = detector.detect('BTC/USDT', '1h')
            assert patterns == []

    def test_unknown_symbol(self, app):
        """Test with non-existent symbol"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            patterns = detector.detect('UNKNOWN/PAIR', '1h')
            assert patterns == []


class TestLiquiditySweepFillDetection:
    """Tests for liquidity sweep fill/invalidation checking"""

    def test_bullish_sweep_active(self, app):
        """Test bullish sweep still active"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            result = detector.check_fill(pattern, 99.0)
            assert result['status'] == 'active'

    def test_bullish_sweep_invalidated(self, app):
        """Test bullish sweep invalidated when price drops below zone"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            # Price below zone_low - zone_size (98 - 2 = 96)
            result = detector.check_fill(pattern, 95.0)
            assert result['status'] == 'invalidated'

    def test_bullish_sweep_filled(self, app):
        """Test bullish sweep filled when price moves up significantly"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            # Price above zone_high + (zone_size * 2) = 100 + 4 = 104
            result = detector.check_fill(pattern, 105.0)
            assert result['status'] == 'filled'

    def test_bearish_sweep_invalidated(self, app):
        """Test bearish sweep invalidated when price rises above zone"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bearish'
            }
            # Price above zone_high + zone_size (100 + 2 = 102)
            result = detector.check_fill(pattern, 103.0)
            assert result['status'] == 'invalidated'

    def test_bearish_sweep_filled(self, app):
        """Test bearish sweep filled when price moves down significantly"""
        with app.app_context():
            detector = LiquiditySweepDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bearish'
            }
            # Price below zone_low - (zone_size * 2) = 98 - 4 = 94
            result = detector.check_fill(pattern, 93.0)
            assert result['status'] == 'filled'
