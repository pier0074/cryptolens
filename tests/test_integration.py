"""
Integration Tests for CryptoLens
Tests the full pipeline: data -> patterns -> signals -> notifications
"""
import pytest
from unittest.mock import patch, MagicMock
from app.models import Symbol, Candle, Pattern, Signal, Setting
from app.services.patterns import scan_all_patterns
from app.services.signals import (
    generate_signal_from_pattern,
    check_confluence,
    generate_confluence_signal
)
from app import db


class TestPatternDetectionPipeline:
    """Tests for the full pattern detection pipeline"""

    def test_scan_all_patterns_with_data(self, app, sample_candles_bullish_fvg):
        """Test that scan_all_patterns detects patterns"""
        with app.app_context():
            result = scan_all_patterns()

            assert 'patterns_found' in result
            assert 'by_symbol' in result
            assert result['patterns_found'] >= 1

    def test_scan_all_patterns_empty_db(self, app):
        """Test scan with no symbols"""
        with app.app_context():
            result = scan_all_patterns()

            assert result['patterns_found'] == 0

    def test_pattern_to_signal_pipeline(self, app, sample_symbol):
        """Test full flow: candles -> pattern -> signal"""
        with app.app_context():
            base_time = 1700000000000

            # Create candles for ATR (need 15+)
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0,
                    volume=1000
                )
                db.session.add(candle)

            # Create a pattern
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=base_time,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            # Generate signal from pattern
            signal = generate_signal_from_pattern(pattern)

            assert signal is not None
            assert signal.direction == 'long'
            assert signal.entry_price == 105.0
            assert signal.stop_loss < 100.0
            assert signal.take_profit_1 > 105.0


class TestConfluencePipeline:
    """Tests for multi-timeframe confluence detection"""

    def test_full_confluence_flow(self, app, sample_symbol):
        """Test confluence detection across multiple timeframes"""
        with app.app_context():
            base_time = 1700000000000

            # Add candles for ATR calculation
            for i in range(20):
                for tf in ['1h', '4h', '1d']:
                    candle = Candle(
                        symbol_id=sample_symbol,
                        timeframe=tf,
                        timestamp=base_time + i * 3600000,
                        open=100.0, high=102.0, low=98.0, close=101.0,
                        volume=1000
                    )
                    db.session.add(candle)

            # Create bullish patterns in 3 timeframes
            for tf in ['1h', '4h', '1d']:
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time,
                    status='active'
                )
                db.session.add(pattern)

            db.session.commit()

            # Check confluence
            confluence = check_confluence('BTC/USDT')

            assert confluence['score'] == 3
            assert confluence['dominant'] == 'bullish'
            assert '1h' in confluence['aligned_timeframes']
            assert '4h' in confluence['aligned_timeframes']
            assert '1d' in confluence['aligned_timeframes']


class TestNotificationPipeline:
    """Tests for notification sending"""

    @patch('app.services.notifier.requests.post')
    def test_long_signal_notification_btc_fvg(self, mock_post, app, sample_symbol, sample_pattern):
        """Test LONG notification for BTC with FVG pattern"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            Setting.set('notifications_enabled', 'true')
            db.session.commit()

            # Create LONG signal with FVG pattern
            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=97500.0,
                stop_loss=95000.0,
                take_profit_1=100000.0,
                take_profit_2=105000.0,
                take_profit_3=110000.0,
                risk_reward=4.0,
                confluence_score=4,
                pattern_id=sample_pattern,
                status='pending',
                timeframes_aligned='["15m", "1h", "4h", "1d"]'
            )
            db.session.add(signal)
            db.session.commit()

            from app.services.notifier import notify_signal
            result = notify_signal(signal)

            assert result is True
            assert mock_post.called
            # Check tags contain direction, symbol, pattern
            call_args = mock_post.call_args
            request_json = call_args[1]['json']
            assert 'long' in request_json['tags']
            assert 'BTC' in request_json['tags']
            assert 'FVG' in request_json['tags']
            assert '🟢' in request_json['title']

    @patch('app.services.notifier.requests.post')
    def test_notification_test_mode(self, mock_post, app, sample_symbol, sample_pattern):
        """Test that test_mode adds 'Test' to tags and title"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            Setting.set('notifications_enabled', 'true')
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=97500.0,
                stop_loss=95000.0,
                take_profit_1=100000.0,
                take_profit_2=105000.0,
                take_profit_3=110000.0,
                risk_reward=4.0,
                confluence_score=4,
                pattern_id=sample_pattern,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()

            from app.services.notifier import notify_signal
            result = notify_signal(signal, test_mode=True)

            assert result is True
            call_args = mock_post.call_args
            request_json = call_args[1]['json']
            # Test mode should add 'test' to tags and '[TEST]' to title
            assert 'test' in request_json['tags']
            assert '[TEST]' in request_json['title']

    @patch('app.services.notifier.requests.post')
    def test_short_signal_notification_eth_order_block(self, mock_post, app):
        """Test SHORT notification for ETH with Order Block pattern"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            # Create ETH symbol
            eth_symbol = Symbol(symbol='ETH/USDT', exchange='binance', is_active=True)
            db.session.add(eth_symbol)
            db.session.commit()

            # Create Order Block pattern
            pattern = Pattern(
                symbol_id=eth_symbol.id,
                timeframe='4h',
                pattern_type='order_block',
                direction='bearish',
                zone_high=2100.0,
                zone_low=2050.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            # Create SHORT signal
            signal = Signal(
                symbol_id=eth_symbol.id,
                direction='short',
                entry_price=2050.0,
                stop_loss=2100.0,
                take_profit_1=2000.0,
                take_profit_2=1950.0,
                take_profit_3=1900.0,
                risk_reward=3.0,
                confluence_score=2,
                pattern_id=pattern.id,
                status='pending',
                timeframes_aligned='["4h", "1d"]'
            )
            db.session.add(signal)
            db.session.commit()

            from app.services.notifier import notify_signal
            result = notify_signal(signal)

            assert result is True
            call_args = mock_post.call_args
            request_json = call_args[1]['json']
            assert 'short' in request_json['tags']
            assert 'ETH' in request_json['tags']
            assert 'OB' in request_json['tags']
            assert '🔴' in request_json['title']

    @patch('app.services.notifier.requests.post')
    def test_long_signal_notification_sol_liquidity_sweep(self, mock_post, app):
        """Test LONG notification for SOL with Liquidity Sweep pattern"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            # Create SOL symbol
            sol_symbol = Symbol(symbol='SOL/USDT', exchange='binance', is_active=True)
            db.session.add(sol_symbol)
            db.session.commit()

            # Create Liquidity Sweep pattern
            pattern = Pattern(
                symbol_id=sol_symbol.id,
                timeframe='1h',
                pattern_type='liquidity_sweep',
                direction='bullish',
                zone_high=180.0,
                zone_low=175.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            # Create LONG signal with high confluence
            signal = Signal(
                symbol_id=sol_symbol.id,
                direction='long',
                entry_price=180.0,
                stop_loss=172.0,
                take_profit_1=188.0,
                take_profit_2=196.0,
                take_profit_3=204.0,
                risk_reward=2.5,
                confluence_score=5,
                pattern_id=pattern.id,
                status='pending',
                timeframes_aligned='["5m", "15m", "1h", "4h", "1d"]'
            )
            db.session.add(signal)
            db.session.commit()

            from app.services.notifier import notify_signal
            result = notify_signal(signal)

            assert result is True
            call_args = mock_post.call_args
            request_json = call_args[1]['json']
            assert 'long' in request_json['tags']
            assert 'SOL' in request_json['tags']
            assert 'LS' in request_json['tags']
            assert '🟢' in request_json['title']
            assert 'SOL/USDT' in request_json['title']

    @patch('app.services.notifier.requests.post')
    def test_notification_disabled(self, mock_post, app):
        """Test that notifications respect the enabled setting"""
        with app.app_context():
            Setting.set('notifications_enabled', 'false')

            # Create XRP symbol
            xrp_symbol = Symbol(symbol='XRP/USDT', exchange='binance', is_active=True)
            db.session.add(xrp_symbol)
            db.session.commit()

            pattern = Pattern(
                symbol_id=xrp_symbol.id,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bearish',
                zone_high=0.65,
                zone_low=0.62,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = Signal(
                symbol_id=xrp_symbol.id,
                direction='short',
                entry_price=0.62,
                stop_loss=0.65,
                take_profit_1=0.59,
                take_profit_2=0.56,
                take_profit_3=0.53,
                risk_reward=3.0,
                confluence_score=1,
                pattern_id=pattern.id,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()

            from app.services.notifier import notify_signal
            result = notify_signal(signal)

            assert result is False
            assert not mock_post.called


class TestDatabaseIntegrity:
    """Tests for database relationships and integrity"""

    def test_pattern_symbol_relationship(self, app, sample_symbol):
        """Test pattern-symbol relationship"""
        with app.app_context():
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            # Verify relationship
            loaded_pattern = Pattern.query.first()
            assert loaded_pattern.symbol is not None
            assert loaded_pattern.symbol.symbol == 'BTC/USDT'

    def test_signal_pattern_relationship(self, app, sample_symbol, sample_pattern):
        """Test signal-pattern relationship"""
        with app.app_context():
            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=103.5,
                stop_loss=100.0,
                take_profit_1=107.0,
                take_profit_2=110.5,
                take_profit_3=114.0,
                risk_reward=3.0,
                confluence_score=3,
                pattern_id=sample_pattern,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()

            # Verify relationship
            loaded_signal = Signal.query.first()
            assert loaded_signal.pattern is not None
            assert loaded_signal.pattern.pattern_type == 'imbalance'

    def test_cascade_candle_queries(self, app, sample_symbol):
        """Test that candle queries work correctly with symbol"""
        with app.app_context():
            # Add candles for multiple timeframes
            base_time = 1700000000000
            for tf in ['1h', '4h']:
                for i in range(5):
                    candle = Candle(
                        symbol_id=sample_symbol,
                        timeframe=tf,
                        timestamp=base_time + i * 3600000,
                        open=100.0, high=102.0, low=98.0, close=101.0,
                        volume=1000
                    )
                    db.session.add(candle)
            db.session.commit()

            # Query by timeframe
            hourly = Candle.query.filter_by(
                symbol_id=sample_symbol,
                timeframe='1h'
            ).all()
            four_hourly = Candle.query.filter_by(
                symbol_id=sample_symbol,
                timeframe='4h'
            ).all()

            assert len(hourly) == 5
            assert len(four_hourly) == 5


class TestSettingsIntegration:
    """Tests for settings integration"""

    def test_settings_affect_signal_generation(self, app, sample_symbol):
        """Test that settings affect signal parameters"""
        with app.app_context():
            # Set custom R:R
            Setting.set('default_rr', '4.0')
            db.session.commit()

            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=110.0,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = generate_signal_from_pattern(pattern)

            assert signal.risk_reward == 4.0

    def test_min_confluence_setting(self, app, sample_symbol):
        """Test that min_confluence setting affects signal generation"""
        with app.app_context():
            # Require 4 timeframes
            Setting.set('min_confluence', '4')
            Setting.set('require_htf', 'false')
            db.session.commit()

            # Create only 3 patterns
            for tf in ['1h', '4h', '1d']:
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=1700000000000,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            # Should not generate signal (only 3 aligned, need 4)
            signal = generate_confluence_signal('BTC/USDT')
            assert signal is None
