"""
Tests for Services
Tests scheduler, aggregator, data_fetcher, logger services
"""
import pytest
from unittest.mock import patch, MagicMock
from app.models import Symbol, Candle, Pattern, Log
from app import db


class TestAggregatorService:
    """Tests for aggregator service"""

    def test_aggregate_candles_no_symbol(self, app):
        """Test aggregation with non-existent symbol"""
        with app.app_context():
            from app.services.aggregator import aggregate_candles
            result = aggregate_candles('UNKNOWN/PAIR', '1m', '5m')
            assert result == 0

    def test_aggregate_candles_no_data(self, app, sample_symbol):
        """Test aggregation with no candle data"""
        with app.app_context():
            from app.services.aggregator import aggregate_candles
            result = aggregate_candles('BTC/USDT', '1m', '5m')
            assert result == 0

    def test_aggregate_candles_creates_higher_tf(self, app, sample_symbol):
        """Test aggregation creates higher timeframe candles"""
        with app.app_context():
            # Create 10 1m candles (enough for 2 5m candles)
            base_time = 1700000000000
            for i in range(10):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1m',
                    timestamp=base_time + i * 60000,
                    open=100.0 + i,
                    high=102.0 + i,
                    low=99.0 + i,
                    close=101.0 + i,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            from app.services.aggregator import aggregate_candles
            result = aggregate_candles('BTC/USDT', '1m', '5m')
            assert result >= 1

            # Verify 5m candles were created
            count_5m = Candle.query.filter_by(
                symbol_id=sample_symbol,
                timeframe='5m'
            ).count()
            assert count_5m >= 1

    def test_aggregate_all_timeframes(self, app, sample_symbol):
        """Test aggregation to all timeframes"""
        with app.app_context():
            # Create 100 1m candles
            base_time = 1700000000000
            for i in range(100):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1m',
                    timestamp=base_time + i * 60000,
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            from app.services.aggregator import aggregate_all_timeframes
            result = aggregate_all_timeframes('BTC/USDT')

            assert '5m' in result
            assert '15m' in result
            assert '1h' in result

    def test_aggregate_with_progress_callback(self, app, sample_symbol):
        """Test aggregation with progress callback"""
        with app.app_context():
            # Create some candles
            base_time = 1700000000000
            for i in range(10):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1m',
                    timestamp=base_time + i * 60000,
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            callback_calls = []

            def progress_callback(stage, current, total):
                callback_calls.append((stage, current, total))

            from app.services.aggregator import aggregate_candles
            aggregate_candles('BTC/USDT', '1m', '5m', progress_callback=progress_callback)

            # Callback should have been called
            assert len(callback_calls) > 0

    def test_get_candles_as_dataframe_no_symbol(self, app):
        """Test get_candles_as_dataframe with non-existent symbol"""
        with app.app_context():
            from app.services.aggregator import get_candles_as_dataframe
            df = get_candles_as_dataframe('UNKNOWN/PAIR', '1h')
            assert df.empty

    def test_get_candles_as_dataframe(self, app, sample_candles_bullish_fvg):
        """Test get_candles_as_dataframe returns data"""
        with app.app_context():
            from app.services.aggregator import get_candles_as_dataframe
            df = get_candles_as_dataframe('BTC/USDT', '1h')
            assert not df.empty
            assert 'open' in df.columns
            assert 'high' in df.columns
            assert 'low' in df.columns
            assert 'close' in df.columns
            assert 'volume' in df.columns

    def test_invalid_target_timeframe(self, app, sample_symbol):
        """Test aggregation with invalid target timeframe"""
        with app.app_context():
            # Create some candles
            base_time = 1700000000000
            for i in range(10):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1m',
                    timestamp=base_time + i * 60000,
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            from app.services.aggregator import aggregate_candles
            result = aggregate_candles('BTC/USDT', '1m', 'invalid')
            assert result == 0


class TestSchedulerService:
    """Tests for scheduler service (now cron-based)"""

    def test_get_scheduler_status(self, app):
        """Test scheduler status returns cron info"""
        with app.app_context():
            from app.services.scheduler import get_scheduler_status

            status = get_scheduler_status()
            assert status['mode'] == 'cron'
            assert 'cron_setup' in status
            assert 'operations' in status

    def test_start_scheduler_logs_warning(self, app):
        """Test start_scheduler returns None (cron-based now)"""
        with app.app_context():
            from app.services.scheduler import start_scheduler
            result = start_scheduler(app)
            assert result is None

    def test_stop_scheduler_no_op(self, app):
        """Test stopping scheduler is a no-op (cron-based)"""
        with app.app_context():
            from app.services.scheduler import stop_scheduler
            stop_scheduler()  # Should not raise


class TestLoggerService:
    """Tests for logger service"""

    def test_log_fetch(self, app):
        """Test fetch logging"""
        with app.app_context():
            from app.services.logger import log_fetch
            log_fetch("Test fetch message", symbol="BTC/USDT")

            log = Log.query.filter_by(category='fetch').first()
            assert log is not None
            assert "Test fetch" in log.message

    def test_log_aggregate(self, app):
        """Test aggregate logging"""
        with app.app_context():
            from app.services.logger import log_aggregate
            log_aggregate("Test aggregate message", symbol="BTC/USDT")

            log = Log.query.filter_by(category='aggregate').first()
            assert log is not None

    def test_log_scan(self, app):
        """Test scan logging"""
        with app.app_context():
            from app.services.logger import log_scan
            log_scan("Test scan message")

            log = Log.query.filter_by(category='scan').first()
            assert log is not None

    def test_log_signal(self, app):
        """Test signal logging"""
        with app.app_context():
            from app.services.logger import log_signal
            log_signal("Test signal message", symbol="BTC/USDT")

            log = Log.query.filter_by(category='signal').first()
            assert log is not None

    def test_log_notify(self, app):
        """Test notify logging"""
        with app.app_context():
            from app.services.logger import log_notify
            log_notify("Test notify message", symbol="BTC/USDT")

            log = Log.query.filter_by(category='notify').first()
            assert log is not None

    def test_log_error(self, app):
        """Test error logging"""
        with app.app_context():
            from app.services.logger import log_error
            log_error("Test error message")

            log = Log.query.filter_by(level='ERROR').first()
            assert log is not None

    def test_log_system(self, app):
        """Test system logging"""
        with app.app_context():
            from app.services.logger import log_system
            log_system("Test system message")

            log = Log.query.filter_by(category='system').first()
            assert log is not None

    def test_get_recent_logs(self, app):
        """Test getting recent logs"""
        with app.app_context():
            from app.services.logger import log_fetch, get_recent_logs
            log_fetch("Log 1")
            log_fetch("Log 2")
            log_fetch("Log 3")

            logs = get_recent_logs(limit=10)
            assert len(logs) >= 3

    def test_get_recent_logs_with_category(self, app):
        """Test getting logs filtered by category"""
        with app.app_context():
            from app.services.logger import log_fetch, log_scan, get_recent_logs
            log_fetch("Fetch log")
            log_scan("Scan log")

            logs = get_recent_logs(limit=10, category='fetch')
            for log in logs:
                assert log['category'] == 'fetch'

    def test_get_log_stats(self, app):
        """Test getting log statistics"""
        with app.app_context():
            from app.services.logger import log_fetch, log_error, get_log_stats
            log_fetch("Fetch log")
            log_error("Error log")

            stats = get_log_stats()
            assert 'total' in stats
            assert 'by_category' in stats
            assert 'errors_today' in stats


class TestNotifierService:
    """Tests for notifier service"""

    @patch('app.services.notifier.requests.post')
    def test_send_notification_success(self, mock_post, app):
        """Test sending notification successfully"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            from app.services.notifier import send_notification
            result = send_notification(
                topic='test-topic',
                title='Test Title',
                message='Test Message',
                priority=3
            )
            assert result is True
            mock_post.assert_called_once()

    @patch('app.services.notifier.requests.post')
    def test_send_notification_failure(self, mock_post, app):
        """Test sending notification with failure"""
        mock_post.return_value = MagicMock(status_code=500)

        with app.app_context():
            from app.services.notifier import send_notification
            result = send_notification(
                topic='test-topic',
                title='Test Title',
                message='Test Message',
                priority=3,
                max_retries=1
            )
            assert result is False

    @patch('app.services.notifier.requests.post')
    def test_send_notification_timeout(self, mock_post, app):
        """Test sending notification with timeout"""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()

        with app.app_context():
            from app.services.notifier import send_notification
            result = send_notification(
                topic='test-topic',
                title='Test Title',
                message='Test Message',
                priority=3,
                max_retries=1
            )
            assert result is False

    @patch('app.services.notifier.requests.post')
    def test_notify_signal_disabled(self, mock_post, app, sample_symbol, sample_pattern):
        """Test notify_signal when notifications disabled"""
        with app.app_context():
            from app.models import Setting, Signal
            Setting.set('notifications_enabled', 'false')
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=100.0,
                stop_loss=95.0,
                take_profit_1=110.0,
                take_profit_2=120.0,
                take_profit_3=130.0,
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
            mock_post.assert_not_called()

    @patch('app.services.notifier.requests.post')
    def test_notify_confluence(self, mock_post, app):
        """Test notify_confluence function"""
        mock_post.return_value = MagicMock(status_code=200)

        with app.app_context():
            from app.services.notifier import notify_confluence
            result = notify_confluence(
                symbol='BTC/USDT',
                direction='long',
                aligned_timeframes=['1h', '4h', '1d'],
                entry=95000.0,
                stop_loss=92000.0,
                take_profits=[98000.0, 101000.0, 104000.0],
                risk_reward=3.0
            )
            assert result is True


class TestEncryptionService:
    """Tests for encryption service"""

    def test_encrypt_and_decrypt_roundtrip(self, app):
        """Test that encryption and decryption work correctly"""
        with app.app_context():
            from app.services.encryption import encrypt_value, decrypt_value
            original = "JBSWY3DPEHPK3PXP"  # Sample TOTP secret

            encrypted = encrypt_value(original)
            assert encrypted != original
            assert encrypted.startswith('gAAAAA')  # Fernet prefix

            decrypted = decrypt_value(encrypted)
            assert decrypted == original

    def test_encrypt_empty_string(self, app):
        """Test encrypting empty string returns empty"""
        with app.app_context():
            from app.services.encryption import encrypt_value, decrypt_value
            assert encrypt_value('') == ''
            assert decrypt_value('') == ''

    def test_encrypt_different_values_produce_different_ciphertexts(self, app):
        """Test that different values produce different ciphertexts"""
        with app.app_context():
            from app.services.encryption import encrypt_value
            encrypted1 = encrypt_value("secret1")
            encrypted2 = encrypt_value("secret2")
            assert encrypted1 != encrypted2

    def test_generate_encryption_key(self, app):
        """Test generating a new encryption key"""
        with app.app_context():
            from app.services.encryption import generate_encryption_key
            key = generate_encryption_key()
            assert len(key) == 44  # Base64-encoded 32-byte key
            assert key.endswith('=')


class TestTOTPEncryption:
    """Tests for TOTP secret encryption in User model"""

    def test_generate_totp_secret_encrypts(self, app, sample_user):
        """Test that generated TOTP secrets are encrypted"""
        with app.app_context():
            from app.models import User
            user = db.session.get(User, sample_user)

            plaintext_secret = user.generate_totp_secret()
            db.session.commit()

            # The stored value should be encrypted (Fernet prefix)
            assert user.totp_secret.startswith('gAAAAA')
            # The returned value should be plaintext
            assert not plaintext_secret.startswith('gAAAAA')

    def test_verify_totp_with_encrypted_secret(self, app, sample_user):
        """Test TOTP verification works with encrypted secrets"""
        with app.app_context():
            import pyotp
            from app.models import User
            user = db.session.get(User, sample_user)

            plaintext_secret = user.generate_totp_secret()
            db.session.commit()

            # Generate a valid token
            totp = pyotp.TOTP(plaintext_secret)
            valid_token = totp.now()

            # Verification should work
            assert user.verify_totp(valid_token) is True
            assert user.verify_totp('000000') is False

    def test_get_totp_uri_with_encrypted_secret(self, app, sample_user):
        """Test TOTP URI generation works with encrypted secrets"""
        with app.app_context():
            from urllib.parse import quote
            from app.models import User
            user = db.session.get(User, sample_user)

            user.generate_totp_secret()
            db.session.commit()

            uri = user.get_totp_uri()
            assert uri is not None
            assert 'otpauth://totp/' in uri
            # Email is URL-encoded in the URI
            assert quote(user.email, safe='') in uri

    def test_decrypt_legacy_unencrypted_secret(self, app, sample_user):
        """Test that legacy unencrypted secrets still work"""
        with app.app_context():
            import pyotp
            from app.models import User
            user = db.session.get(User, sample_user)

            # Simulate a legacy unencrypted secret
            legacy_secret = pyotp.random_base32()
            user.totp_secret = legacy_secret  # Store directly without encryption
            db.session.commit()

            # Verification should still work (fallback to plaintext)
            totp = pyotp.TOTP(legacy_secret)
            valid_token = totp.now()
            assert user.verify_totp(valid_token) is True
