"""
Tests for Signal Generation
"""
from unittest.mock import patch, MagicMock
from app.models import Pattern, Setting, Candle
from app.services.signals import (
    calculate_atr,
    generate_signal_from_pattern,
    check_confluence,
    generate_confluence_signal
)
from app import db


class TestATRCalculation:
    """Tests for Average True Range calculation"""

    def test_atr_with_sufficient_data(self, app, sample_symbol):
        """Test ATR calculation with enough candles"""
        with app.app_context():
            # Create 20 candles with known values
            base_time = 1700000000000
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0 + i,
                    high=102.0 + i,  # High-Low range of 4
                    low=98.0 + i,
                    close=101.0 + i,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            atr = calculate_atr('BTC/USDT', '1h', period=14)

            # ATR should be positive and around 4 (high-low range)
            assert atr > 0
            assert 3.0 <= atr <= 5.0

    def test_atr_with_empty_data(self, app, sample_symbol):
        """Test ATR calculation with no candles"""
        with app.app_context():
            atr = calculate_atr('BTC/USDT', '1h', period=14)
            assert atr == 0.0

    def test_atr_with_insufficient_data(self, app, sample_symbol):
        """Test ATR calculation with less than period candles"""
        with app.app_context():
            # Only add 5 candles, but need 14+1
            base_time = 1700000000000
            for i in range(5):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            atr = calculate_atr('BTC/USDT', '1h', period=14)
            assert atr == 0.0

    def test_atr_unknown_symbol(self, app):
        """Test ATR calculation with non-existent symbol"""
        with app.app_context():
            atr = calculate_atr('UNKNOWN/PAIR', '1h', period=14)
            assert atr == 0.0


class TestSignalGeneration:
    """Tests for signal generation from patterns"""

    def test_generate_long_signal(self, app, sample_symbol):
        """Test generating a long signal from bullish pattern"""
        with app.app_context():
            # Add candles for ATR calculation
            base_time = 1700000000000
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)

            # Create bullish pattern
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

            signal = generate_signal_from_pattern(pattern)

            assert signal is not None
            assert signal.direction == 'long'
            assert signal.entry_price == 105.0  # Top of zone
            assert signal.stop_loss < 100.0  # Below zone with buffer
            assert signal.take_profit_1 > signal.entry_price
            assert signal.take_profit_2 > signal.take_profit_1
            assert signal.take_profit_3 > signal.take_profit_2
            assert signal.status == 'pending'

    def test_generate_short_signal(self, app, sample_symbol):
        """Test generating a short signal from bearish pattern"""
        with app.app_context():
            # Add candles for ATR calculation
            base_time = 1700000000000
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)

            # Create bearish pattern
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bearish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=base_time,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = generate_signal_from_pattern(pattern)

            assert signal is not None
            assert signal.direction == 'short'
            assert signal.entry_price == 100.0  # Bottom of zone
            assert signal.stop_loss > 105.0  # Above zone with buffer
            assert signal.take_profit_1 < signal.entry_price
            assert signal.take_profit_2 < signal.take_profit_1
            assert signal.take_profit_3 < signal.take_profit_2

    def test_minimum_risk_enforcement_long(self, app, sample_symbol):
        """Test that minimum risk percentage is enforced for long signals"""
        with app.app_context():
            # Create pattern with very small zone (< 0.5% risk)
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=100.1,  # Only 0.1% above low
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = generate_signal_from_pattern(pattern)

            assert signal is not None
            # Risk should be at least 0.5% of entry
            risk = signal.entry_price - signal.stop_loss
            min_risk = signal.entry_price * 0.005  # 0.5%
            assert risk >= min_risk * 0.99  # Allow small float error

    def test_minimum_risk_enforcement_short(self, app, sample_symbol):
        """Test that minimum risk percentage is enforced for short signals"""
        with app.app_context():
            # Create pattern with very small zone
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bearish',
                zone_high=100.1,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = generate_signal_from_pattern(pattern)

            assert signal is not None
            # Risk should be at least 0.5% of entry
            risk = signal.stop_loss - signal.entry_price
            min_risk = signal.entry_price * 0.005  # 0.5%
            assert risk >= min_risk * 0.99

    def test_signal_risk_reward_ratio(self, app, sample_symbol):
        """Test that take profits follow risk:reward ratio"""
        with app.app_context():
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

            risk = signal.entry_price - signal.stop_loss
            tp1_reward = signal.take_profit_1 - signal.entry_price
            tp2_reward = signal.take_profit_2 - signal.entry_price
            tp3_reward = signal.take_profit_3 - signal.entry_price

            # TP1 = 1:1, TP2 = 1:2, TP3 = 1:RR (default 3)
            assert abs(tp1_reward - risk) < 0.01  # 1:1
            assert abs(tp2_reward - risk * 2) < 0.01  # 1:2
            assert abs(tp3_reward - risk * 3) < 0.01  # 1:3

    def test_invalid_pattern_symbol(self, app, sample_symbol):
        """Test signal generation with invalid symbol reference"""
        with app.app_context():
            pattern = Pattern(
                symbol_id=99999,  # Non-existent symbol
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            # Don't add to session - just test the function

            signal = generate_signal_from_pattern(pattern)
            assert signal is None


class TestConfluence:
    """Tests for confluence checking"""

    def test_confluence_single_direction(self, app, sample_symbol):
        """Test confluence with all bullish patterns"""
        with app.app_context():
            base_time = 1700000000000

            # Create bullish patterns in multiple timeframes
            for i, tf in enumerate(['1h', '4h', '1d']):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            confluence = check_confluence('BTC/USDT')

            assert confluence['dominant'] == 'bullish'
            assert confluence['score'] == 3
            assert len(confluence['bullish']) == 3
            assert len(confluence['bearish']) == 0
            assert '1h' in confluence['aligned_timeframes']
            assert '4h' in confluence['aligned_timeframes']
            assert '1d' in confluence['aligned_timeframes']

    def test_confluence_mixed_directions(self, app, sample_symbol):
        """Test confluence with mixed bullish/bearish patterns"""
        with app.app_context():
            base_time = 1700000000000

            # Create patterns with different directions
            # Note: 1m removed from TIMEFRAMES (too noisy), using valid timeframes only
            patterns_data = [
                ('5m', 'bullish'),
                ('30m', 'bullish'),
                ('15m', 'bearish'),
                ('1h', 'bullish'),
                ('4h', 'bullish'),
            ]

            for i, (tf, direction) in enumerate(patterns_data):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction=direction,
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            confluence = check_confluence('BTC/USDT')

            assert confluence['dominant'] == 'bullish'
            assert confluence['score'] == 4  # 4 bullish vs 1 bearish
            assert len(confluence['bullish']) == 4
            assert len(confluence['bearish']) == 1

    def test_confluence_neutral(self, app, sample_symbol):
        """Test confluence with equal bullish/bearish patterns"""
        with app.app_context():
            base_time = 1700000000000

            patterns_data = [
                ('1h', 'bullish'),
                ('4h', 'bearish'),
            ]

            for i, (tf, direction) in enumerate(patterns_data):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction=direction,
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            confluence = check_confluence('BTC/USDT')

            assert confluence['dominant'] == 'neutral'
            assert confluence['score'] == 0
            assert confluence['aligned_timeframes'] == []

    def test_confluence_no_patterns(self, app, sample_symbol):
        """Test confluence with no active patterns"""
        with app.app_context():
            confluence = check_confluence('BTC/USDT')

            assert confluence['dominant'] == 'neutral'
            assert confluence['score'] == 0
            assert confluence['bullish'] == []
            assert confluence['bearish'] == []

    def test_confluence_unknown_symbol(self, app):
        """Test confluence with non-existent symbol"""
        with app.app_context():
            confluence = check_confluence('UNKNOWN/PAIR')

            assert confluence['score'] == 0
            assert confluence['bullish'] == []
            assert confluence['bearish'] == []


class TestConfluenceSignal:
    """Tests for confluence-based signal generation"""

    @patch('app.services.notifier.requests.post')
    def test_signal_generated_with_sufficient_confluence(self, mock_post, app, sample_symbol):
        """Test signal is generated when confluence threshold is met"""
        mock_post.return_value = MagicMock(status_code=200)
        with app.app_context():
            # Set minimum confluence to 3
            Setting.set('min_confluence', '3')
            Setting.set('require_htf', 'false')  # Don't require HTF for this test

            base_time = 1700000000000

            # Add candles for ATR
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)

            # Create 3 bullish patterns
            for i, tf in enumerate(['1h', '4h', '1d']):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            signal = generate_confluence_signal('BTC/USDT')

            assert signal is not None
            assert signal.confluence_score == 3
            assert signal.direction == 'long'

    def test_no_signal_below_threshold(self, app, sample_symbol):
        """Test no signal generated when below confluence threshold"""
        with app.app_context():
            Setting.set('min_confluence', '3')

            base_time = 1700000000000

            # Only 2 bullish patterns (below threshold of 3)
            for i, tf in enumerate(['1h', '4h']):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            signal = generate_confluence_signal('BTC/USDT')
            assert signal is None

    @patch('app.services.notifier.requests.post')
    def test_signal_cooldown(self, mock_post, app, sample_symbol):
        """Test signal cooldown prevents duplicate signals"""
        mock_post.return_value = MagicMock(status_code=200)
        with app.app_context():
            Setting.set('min_confluence', '3')
            Setting.set('signal_cooldown_hours', '4')
            Setting.set('require_htf', 'false')

            base_time = 1700000000000

            # Add candles for ATR
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_time + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)

            # Create 3 bullish patterns
            for i, tf in enumerate(['1h', '4h', '1d']):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            # First signal should be generated
            signal1 = generate_confluence_signal('BTC/USDT')
            assert signal1 is not None

            # Second signal should be blocked by cooldown
            signal2 = generate_confluence_signal('BTC/USDT')
            assert signal2 is None

    def test_htf_requirement(self, app, sample_symbol):
        """Test that HTF requirement filters signals without 4h/1d patterns"""
        with app.app_context():
            Setting.set('min_confluence', '3')
            Setting.set('require_htf', 'true')

            base_time = 1700000000000

            # Add candles
            for i in range(20):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1m',
                    timestamp=base_time + i * 60000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)

            # Only lower timeframe patterns (no 4h or 1d)
            for i, tf in enumerate(['1m', '5m', '15m']):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            signal = generate_confluence_signal('BTC/USDT')

            # Should be None because no HTF (4h/1d) in aligned timeframes
            assert signal is None

    @patch('app.services.notifier.requests.post')
    def test_signal_uses_highest_tf_pattern(self, mock_post, app, sample_symbol):
        """Test that signal uses the highest timeframe pattern"""
        mock_post.return_value = MagicMock(status_code=200)
        with app.app_context():
            Setting.set('min_confluence', '3')
            Setting.set('require_htf', 'false')

            base_time = 1700000000000

            # Add candles for multiple timeframes
            for i in range(20):
                for tf in ['1h', '4h', '1d']:
                    candle = Candle(
                        symbol_id=sample_symbol,
                        timeframe=tf,
                        timestamp=base_time + i * 3600000,
                        open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                    )
                    db.session.add(candle)

            # Create patterns with different zone values per timeframe
            patterns_data = [
                ('1h', 105.0, 100.0),
                ('4h', 110.0, 105.0),
                ('1d', 120.0, 115.0),  # Highest TF should be used
            ]

            for i, (tf, zone_high, zone_low) in enumerate(patterns_data):
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=zone_high,
                    zone_low=zone_low,
                    detected_at=base_time + i,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            signal = generate_confluence_signal('BTC/USDT')

            assert signal is not None
            # Entry should be from 1d pattern (zone_high=120.0)
            assert signal.entry_price == 120.0
