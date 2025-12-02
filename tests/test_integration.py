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
    def test_signal_notification_sent(self, mock_post, app, sample_symbol, sample_pattern):
        """Test that notifications are sent for signals"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            # Enable notifications
            Setting.set('notifications_enabled', 'true')
            db.session.commit()

            # Get the pattern
            pattern = Pattern.query.get(sample_pattern)

            # Create a signal
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
                status='pending',
                timeframes_aligned='["1h", "4h", "1d"]'
            )
            db.session.add(signal)
            db.session.commit()

            # Send notification
            from app.services.notifier import notify_signal
            result = notify_signal(signal)

            assert result is True
            assert mock_post.called

    @patch('app.services.notifier.requests.post')
    def test_notification_disabled(self, mock_post, app, sample_symbol, sample_pattern):
        """Test that notifications respect the enabled setting"""
        with app.app_context():
            # Disable notifications
            Setting.set('notifications_enabled', 'false')
            db.session.commit()

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
