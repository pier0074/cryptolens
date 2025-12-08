"""
Tests for Fair Value Gap (FVG) Pattern Detection
"""
import pytest
from app.models import Pattern, Symbol, Candle
from app.services.patterns.fair_value_gap import FVGDetector, ImbalanceDetector
from app.config import Config
from app import db


class TestFVGDetector:
    """Tests for Fair Value Gap (FVG) detection"""

    def test_detect_bullish_fvg(self, app, sample_candles_bullish_fvg):
        """Test detection of bullish Fair Value Gap"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            assert len(patterns) >= 1
            bullish = [p for p in patterns if p['direction'] == 'bullish']
            assert len(bullish) >= 1

            pattern = bullish[0]
            assert pattern['type'] == 'imbalance'
            assert pattern['direction'] == 'bullish'
            assert pattern['zone_low'] < pattern['zone_high']
            assert pattern['symbol'] == 'BTC/USDT'
            assert pattern['timeframe'] == '1h'

    def test_detect_bearish_fvg(self, app, sample_candles_bearish_fvg):
        """Test detection of bearish Fair Value Gap"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            assert len(patterns) >= 1
            bearish = [p for p in patterns if p['direction'] == 'bearish']
            assert len(bearish) >= 1

            pattern = bearish[0]
            assert pattern['type'] == 'imbalance'
            assert pattern['direction'] == 'bearish'
            assert pattern['zone_low'] < pattern['zone_high']

    def test_no_fvg_overlapping_wicks(self, app, sample_candles_no_fvg):
        """Test that overlapping wicks don't create FVG"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            # Should not detect any imbalances when wicks overlap
            assert len(patterns) == 0

    def test_small_fvg_filtered(self, app, sample_candles_small_fvg):
        """Test that FVGs smaller than minimum size are filtered out"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            # Small FVGs should be filtered out
            assert len(patterns) == 0

    def test_pattern_saved_to_database(self, app, sample_candles_bullish_fvg):
        """Test that detected patterns are saved to database"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            # Check patterns in database
            db_patterns = Pattern.query.filter_by(
                pattern_type='imbalance',
                status='active'
            ).all()

            assert len(db_patterns) >= 1
            assert db_patterns[0].direction in ['bullish', 'bearish']

    def test_no_duplicate_patterns(self, app, sample_candles_bullish_fvg):
        """Test that running detection twice doesn't create duplicates"""
        with app.app_context():
            detector = FVGDetector()

            # Run detection twice
            patterns1 = detector.detect('BTC/USDT', '1h')
            patterns2 = detector.detect('BTC/USDT', '1h')

            # Second run should return empty (patterns already exist)
            assert len(patterns2) == 0

            # Database should have same count as first run
            db_patterns = Pattern.query.filter_by(pattern_type='imbalance').all()
            assert len(db_patterns) == len(patterns1)

    def test_empty_candles(self, app, sample_symbol):
        """Test detection with no candles"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            assert patterns == []

    def test_insufficient_candles(self, app, sample_symbol):
        """Test detection with less than 3 candles"""
        with app.app_context():
            # Add only 2 candles
            for i in range(2):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 60000,
                    open=100.0, high=101.0, low=99.0, close=100.5, volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            assert patterns == []

    def test_unknown_symbol(self, app):
        """Test detection with non-existent symbol"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('UNKNOWN/PAIR', '1h')

            assert patterns == []


class TestFillDetection:
    """Tests for pattern fill detection"""

    def test_bullish_fvg_not_filled(self, app, sample_candles_bullish_fvg):
        """Test bullish FVG not filled when price above zone"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            pattern = [p for p in patterns if p['direction'] == 'bullish'][0]

            # Price above zone
            result = detector.check_fill(pattern, pattern['zone_high'] + 5)

            assert result['status'] == 'active'
            assert result['fill_percentage'] == 0

    def test_bullish_fvg_partially_filled(self, app, sample_candles_bullish_fvg):
        """Test bullish FVG partially filled when price in zone"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            pattern = [p for p in patterns if p['direction'] == 'bullish'][0]

            # Price in middle of zone
            mid_price = (pattern['zone_high'] + pattern['zone_low']) / 2
            result = detector.check_fill(pattern, mid_price)

            assert result['status'] == 'active'
            assert 40 <= result['fill_percentage'] <= 60  # Around 50%

    def test_bullish_fvg_fully_filled(self, app, sample_candles_bullish_fvg):
        """Test bullish FVG fully filled when price below zone"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            pattern = [p for p in patterns if p['direction'] == 'bullish'][0]

            # Price below zone
            result = detector.check_fill(pattern, pattern['zone_low'] - 1)

            assert result['status'] == 'filled'
            assert result['fill_percentage'] == 100

    def test_bearish_fvg_fully_filled(self, app, sample_candles_bearish_fvg):
        """Test bearish FVG fully filled when price above zone"""
        with app.app_context():
            detector = FVGDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            pattern = [p for p in patterns if p['direction'] == 'bearish'][0]

            # Price above zone
            result = detector.check_fill(pattern, pattern['zone_high'] + 1)

            assert result['status'] == 'filled'
            assert result['fill_percentage'] == 100


class TestZoneSize:
    """Tests for zone size filtering"""

    def test_is_zone_tradeable_valid(self, app):
        """Test zone size validation for valid zones"""
        with app.app_context():
            detector = FVGDetector()

            # 1% zone should be tradeable
            assert detector.is_zone_tradeable(100.0, 101.0) is True

            # 0.5% zone should be tradeable
            assert detector.is_zone_tradeable(100.0, 100.5) is True

            # 0.15% zone should be tradeable (at threshold)
            assert detector.is_zone_tradeable(100.0, 100.15) is True

    def test_is_zone_tradeable_too_small(self, app):
        """Test zone size validation for zones too small"""
        with app.app_context():
            detector = FVGDetector()

            # 0.1% zone should NOT be tradeable
            assert detector.is_zone_tradeable(100.0, 100.1) is False

            # 0.05% zone should NOT be tradeable
            assert detector.is_zone_tradeable(100.0, 100.05) is False

    def test_is_zone_tradeable_zero_low(self, app):
        """Test zone size validation with zero low price"""
        with app.app_context():
            detector = FVGDetector()

            # Zero or negative low should not be tradeable
            assert detector.is_zone_tradeable(0, 100.0) is False
            assert detector.is_zone_tradeable(-1, 100.0) is False
