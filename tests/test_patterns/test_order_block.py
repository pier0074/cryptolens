"""
Tests for Order Block Pattern Detection
"""
from app.models import Candle
from app.services.patterns.order_block import OrderBlockDetector
from app import db


class TestOrderBlockDetector:
    """Tests for Order Block detection"""

    def test_detect_bullish_order_block(self, app, sample_symbol):
        """Test detection of bullish order block (bearish candle before strong bullish move)"""
        with app.app_context():
            base_time = 1700000000000

            # Create candles: need 20+ for rolling average, then pattern
            # First 20 candles: normal sized bodies (~1.0)
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0 + i * 0.1,
                    high=101.0 + i * 0.1,
                    low=99.0 + i * 0.1,
                    close=100.5 + i * 0.1,  # Small bullish body
                    volume=1000
                )
                db.session.add(candle)

            # Candle 20: Bearish candle (the order block)
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 20 * 3600000,
                open=103.0,
                high=103.5,
                low=102.0,
                close=102.5,  # Bearish: close < open
                volume=1000
            )
            db.session.add(candle)

            # Candle 21: Strong bullish move (1.5x average body)
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 21 * 3600000,
                open=102.5,
                high=106.0,
                low=102.0,
                close=105.5,  # Strong bullish: body = 3.0 (vs avg ~0.5)
                volume=2000
            )
            db.session.add(candle)

            # Candle 22: Continuation
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 22 * 3600000,
                open=105.5,
                high=107.0,
                low=105.0,
                close=106.5,
                volume=1500
            )
            db.session.add(candle)

            db.session.commit()

            detector = OrderBlockDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            bullish = [p for p in patterns if p['direction'] == 'bullish']
            assert len(bullish) >= 1
            assert bullish[0]['type'] == 'order_block'
            assert bullish[0]['zone_low'] < bullish[0]['zone_high']

    def test_detect_bearish_order_block(self, app, sample_symbol):
        """Test detection of bearish order block (bullish candle before strong bearish move)"""
        with app.app_context():
            base_time = 1700000000000

            # First 20 candles: normal sized bodies
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0 - i * 0.1,
                    high=101.0 - i * 0.1,
                    low=99.0 - i * 0.1,
                    close=99.5 - i * 0.1,  # Small bearish body
                    volume=1000
                )
                db.session.add(candle)

            # Candle 20: Bullish candle (the order block)
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 20 * 3600000,
                open=98.0,
                high=99.0,
                low=97.5,
                close=98.5,  # Bullish: close > open
                volume=1000
            )
            db.session.add(candle)

            # Candle 21: Strong bearish move
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 21 * 3600000,
                open=98.5,
                high=99.0,
                low=94.0,
                close=94.5,  # Strong bearish: body = 4.0
                volume=2000
            )
            db.session.add(candle)

            # Candle 22: Continuation
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=base_time + 22 * 3600000,
                open=94.5,
                high=95.0,
                low=93.0,
                close=93.5,
                volume=1500
            )
            db.session.add(candle)

            db.session.commit()

            detector = OrderBlockDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            bearish = [p for p in patterns if p['direction'] == 'bearish']
            assert len(bearish) >= 1
            assert bearish[0]['type'] == 'order_block'

    def test_no_order_block_weak_move(self, app, sample_symbol):
        """Test that weak moves don't create order blocks"""
        with app.app_context():
            base_time = 1700000000000

            # Create 25 candles with consistent small bodies
            for i in range(25):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0,
                    high=100.5,
                    low=99.5,
                    close=100.2,  # Very small body
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = OrderBlockDetector()
            patterns = detector.detect('BTC/USDT', '1h')

            # No strong moves = no order blocks
            assert len(patterns) == 0

    def test_order_block_insufficient_candles(self, app, sample_symbol):
        """Test with less than 5 candles"""
        with app.app_context():
            for i in range(3):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            detector = OrderBlockDetector()
            patterns = detector.detect('BTC/USDT', '1h')
            assert patterns == []

    def test_order_block_unknown_symbol(self, app):
        """Test with non-existent symbol"""
        with app.app_context():
            detector = OrderBlockDetector()
            patterns = detector.detect('UNKNOWN/PAIR', '1h')
            assert patterns == []


class TestOrderBlockFillDetection:
    """Tests for order block fill checking"""

    def test_bullish_ob_not_filled(self, app):
        """Test bullish OB not filled when price above zone"""
        with app.app_context():
            detector = OrderBlockDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            result = detector.check_fill(pattern, 105.0)
            assert result['status'] == 'active'
            assert result['fill_percentage'] == 0

    def test_bullish_ob_partially_filled(self, app):
        """Test bullish OB partially filled when price in zone"""
        with app.app_context():
            detector = OrderBlockDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            result = detector.check_fill(pattern, 99.0)  # Middle of zone
            assert result['status'] == 'active'
            assert 40 <= result['fill_percentage'] <= 60

    def test_bullish_ob_fully_filled(self, app):
        """Test bullish OB fully filled when price below zone"""
        with app.app_context():
            detector = OrderBlockDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bullish'
            }
            result = detector.check_fill(pattern, 97.0)
            assert result['status'] == 'filled'
            assert result['fill_percentage'] == 100

    def test_bearish_ob_fully_filled(self, app):
        """Test bearish OB fully filled when price above zone"""
        with app.app_context():
            detector = OrderBlockDetector()
            pattern = {
                'zone_high': 100.0,
                'zone_low': 98.0,
                'direction': 'bearish'
            }
            result = detector.check_fill(pattern, 101.0)
            assert result['status'] == 'filled'
            assert result['fill_percentage'] == 100
