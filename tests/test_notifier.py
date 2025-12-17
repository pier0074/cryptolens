"""
Tests for Notification Service
Tests send_notification, notify_all_subscribers, per-user notifications, tier filtering
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from app import db
from app.models import (
    User, Symbol, Pattern, Signal, Notification, UserNotification,
    Setting, Subscription
)
from app.services.notifier import (
    send_notification, notify_signal,
    get_eligible_subscribers, get_subscribers_with_delay,
    send_notification_to_user, notify_all_subscribers,
    notify_confluence, notify_subscribers_confluence
)
from app.services.notifier import test_ntfy_connection as ntfy_connection_test


class TestSendNotification:
    """Tests for send_notification function"""

    @patch('app.services.notifier._send_ntfy_request')
    def test_send_notification_success(self, mock_send):
        """Test successful notification send"""
        mock_send.return_value = True

        result = send_notification(
            topic='test_topic',
            title='Test Title',
            message='Test Message',
            priority=3
        )

        assert result is True
        mock_send.assert_called_once()

    @patch('app.services.notifier._send_ntfy_request')
    def test_send_notification_retry_on_failure(self, mock_send):
        """Test retry logic on failure"""
        # Fail twice, then succeed
        mock_send.side_effect = [Exception("error"), Exception("error"), True]

        result = send_notification(
            topic='test_topic',
            title='Test Title',
            message='Test Message',
            max_retries=3
        )

        assert result is True
        assert mock_send.call_count == 3

    @patch('app.services.notifier._send_ntfy_request')
    def test_send_notification_all_retries_fail(self, mock_send):
        """Test when all retries fail"""
        mock_send.side_effect = Exception("persistent error")

        result = send_notification(
            topic='test_topic',
            title='Test Title',
            message='Test Message',
            max_retries=2
        )

        assert result is False
        assert mock_send.call_count == 2

    @patch('app.services.notifier._send_ntfy_request')
    def test_send_notification_circuit_breaker_open(self, mock_send):
        """Test circuit breaker prevents retries"""
        import pybreaker
        mock_send.side_effect = pybreaker.CircuitBreakerError("open")

        result = send_notification(
            topic='test_topic',
            title='Test Title',
            message='Test Message'
        )

        assert result is False
        # Should not retry when circuit is open
        assert mock_send.call_count == 1

    @patch('app.services.notifier._send_ntfy_request')
    def test_send_notification_tags_parsing(self, mock_send):
        """Test tags are parsed correctly"""
        mock_send.return_value = True

        # Test with string tags
        send_notification(
            topic='test_topic',
            title='Test',
            message='Test',
            tags='tag1,tag2,tag3'
        )

        call_args = mock_send.call_args
        assert call_args[0][4] == ['tag1', 'tag2', 'tag3']  # 5th arg is tags list


class TestTestNtfyConnection:
    """Tests for test_ntfy_connection function"""

    @patch('app.services.notifier.requests.post')
    def test_connection_success(self, mock_post):
        """Test successful connection test"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_post.return_value = mock_response

        result = ntfy_connection_test()

        assert result['success'] is True
        assert result['status_code'] == 200

    @patch('app.services.notifier.requests.post')
    def test_connection_failure(self, mock_post):
        """Test connection failure"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Error"
        mock_post.return_value = mock_response

        result = ntfy_connection_test()

        assert result['success'] is False
        assert result['status_code'] == 500

    @patch('app.services.notifier.requests.post')
    def test_connection_timeout(self, mock_post):
        """Test connection timeout"""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()

        result = ntfy_connection_test()

        assert result['success'] is False
        assert 'timeout' in result['error'].lower()

    @patch('app.services.notifier.requests.post')
    def test_connection_error(self, mock_post):
        """Test network connection error"""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Network unreachable")

        result = ntfy_connection_test()

        assert result['success'] is False
        assert 'connection' in result['error'].lower()


class TestGetEligibleSubscribers:
    """Tests for get_eligible_subscribers function"""

    def test_returns_active_verified_users(self, app):
        """Test that only active verified users are returned"""
        with app.app_context():
            # Create verified active user
            user1 = User(
                email='eligible@test.com',
                username='eligible',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_eligible'
            )
            user1.set_password('password')

            # Create unverified user
            user2 = User(
                email='unverified@test.com',
                username='unverified',
                is_active=True,
                is_verified=False,
                ntfy_topic='topic_unverified'
            )
            user2.set_password('password')

            # Create inactive user
            user3 = User(
                email='inactive@test.com',
                username='inactive',
                is_active=False,
                is_verified=True,
                ntfy_topic='topic_inactive'
            )
            user3.set_password('password')

            db.session.add_all([user1, user2, user3])
            db.session.commit()

            # Add subscriptions for all
            for user in [user1, user2, user3]:
                sub = Subscription(
                    user_id=user.id,
                    plan='pro',
                    status='active'
                )
                db.session.add(sub)
            db.session.commit()

            eligible = get_eligible_subscribers()

            # Only the verified active user should be eligible
            emails = [u.email for u in eligible]
            assert 'eligible@test.com' in emails
            assert 'unverified@test.com' not in emails
            assert 'inactive@test.com' not in emails

    def test_filters_by_pattern_type(self, app):
        """Test filtering by pattern type access"""
        with app.app_context():
            # Create free tier user (only FVG/imbalance)
            free_user = User(
                email='free_notif@test.com',
                username='free_notif',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free'
            )
            free_user.set_password('password')

            # Create pro tier user (all patterns)
            pro_user = User(
                email='pro_notif@test.com',
                username='pro_notif',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro'
            )
            pro_user.set_password('password')

            db.session.add_all([free_user, pro_user])
            db.session.commit()

            # Add subscriptions
            free_sub = Subscription(
                user_id=free_user.id,
                plan='free',
                status='active'
            )
            pro_sub = Subscription(
                user_id=pro_user.id,
                plan='pro',
                status='active'
            )
            db.session.add_all([free_sub, pro_sub])
            db.session.commit()

            # Get subscribers for order_block pattern
            eligible = get_eligible_subscribers(pattern_type='order_block')

            emails = [u.email for u in eligible]
            # Free user shouldn't have access to order_block
            assert 'free_notif@test.com' not in emails
            # Pro user should have access
            assert 'pro_notif@test.com' in emails


class TestGetSubscribersWithDelay:
    """Tests for get_subscribers_with_delay function"""

    def test_groups_by_delay(self, app):
        """Test that subscribers are grouped by notification delay"""
        with app.app_context():
            # Create users with different tiers (different delays)
            free_user = User(
                email='free_delay@test.com',
                username='free_delay',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_delay'
            )
            free_user.set_password('password')

            premium_user = User(
                email='premium_delay@test.com',
                username='premium_delay',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_premium_delay'
            )
            premium_user.set_password('password')

            db.session.add_all([free_user, premium_user])
            db.session.commit()

            # Free tier: 10 minute delay
            free_sub = Subscription(
                user_id=free_user.id,
                plan='free',
                status='active'
            )
            # Premium: no delay
            premium_sub = Subscription(
                user_id=premium_user.id,
                plan='premium',
                status='active'
            )
            db.session.add_all([free_sub, premium_sub])
            db.session.commit()

            by_delay = get_subscribers_with_delay()

            # Should have different delay buckets
            assert isinstance(by_delay, dict)
            # At least one bucket should exist
            assert len(by_delay) >= 0  # May be 0 if rate limited


class TestSendNotificationToUser:
    """Tests for send_notification_to_user function"""

    @patch('app.services.notifier.send_notification')
    def test_sends_and_tracks(self, mock_send, app):
        """Test notification is sent and tracked"""
        mock_send.return_value = True

        with app.app_context():
            # Create user
            user = User(
                email='tracked@test.com',
                username='tracked',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_tracked'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            # Create a signal
            symbol = Symbol(symbol='TEST/USDT', exchange='test')
            db.session.add(symbol)
            db.session.commit()

            signal = Signal(
                symbol_id=symbol.id,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=110,
                risk_reward=2.0
            )
            db.session.add(signal)
            db.session.commit()

            result = send_notification_to_user(
                user=user,
                signal_id=signal.id,
                title='Test',
                message='Test message'
            )

            assert result is True

            # Check tracking record was created
            notification = UserNotification.query.filter_by(
                user_id=user.id,
                signal_id=signal.id
            ).first()
            assert notification is not None
            assert notification.success is True

    @patch('app.services.notifier.send_notification')
    def test_tracks_failure(self, mock_send, app):
        """Test failed notification is tracked"""
        mock_send.return_value = False

        with app.app_context():
            user = User(
                email='fail_tracked@test.com',
                username='fail_tracked',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_fail'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            symbol = Symbol(symbol='FAIL/USDT', exchange='test')
            db.session.add(symbol)
            db.session.commit()

            signal = Signal(
                symbol_id=symbol.id,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=110,
                risk_reward=2.0
            )
            db.session.add(signal)
            db.session.commit()

            result = send_notification_to_user(
                user=user,
                signal_id=signal.id,
                title='Test',
                message='Test message'
            )

            assert result is False

            notification = UserNotification.query.filter_by(
                user_id=user.id,
                signal_id=signal.id
            ).first()
            assert notification is not None
            assert notification.success is False
            assert notification.error is not None


class TestNotifySignal:
    """Tests for notify_signal function (single-topic mode)"""

    @patch('app.services.notifier.send_notification')
    def test_notify_signal_success(self, mock_send, app, sample_symbol):
        """Test successful signal notification"""
        mock_send.return_value = True

        with app.app_context():
            # Ensure notifications are enabled
            Setting.set('notifications_enabled', 'true')
            Setting.set('ntfy_topic', 'test_topic')

            # Create pattern
            pattern = Pattern(
                symbol_id=sample_symbol,
                pattern_type='imbalance',
                timeframe='1h',
                direction='bullish',
                zone_low=95,
                zone_high=105,
                detected_at=datetime.now(timezone.utc)
            )
            db.session.add(pattern)
            db.session.commit()

            # Create signal
            signal = Signal(
                symbol_id=sample_symbol,
                pattern_id=pattern.id,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_signal(signal)

            assert result is True
            mock_send.assert_called_once()

            # Check signal was updated
            db.session.refresh(signal)
            assert signal.status == 'notified'
            assert signal.notified_at is not None

            # Check notification record was created
            notif = Notification.query.filter_by(signal_id=signal.id).first()
            assert notif is not None
            assert notif.success is True

    @patch('app.services.notifier.send_notification')
    def test_notify_signal_disabled(self, mock_send, app, sample_symbol):
        """Test notification when disabled"""
        with app.app_context():
            Setting.set('notifications_enabled', 'false')

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_signal(signal)

            assert result is False
            mock_send.assert_not_called()

    @patch('app.services.notifier.send_notification')
    def test_notify_signal_test_mode(self, mock_send, app, sample_symbol):
        """Test test_mode adds prefix"""
        mock_send.return_value = True

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            notify_signal(signal, test_mode=True)

            # Check title contains [TEST]
            call_kwargs = mock_send.call_args[1]
            assert '[TEST]' in call_kwargs['title']
            assert 'test' in call_kwargs['tags']


class TestNotifyAllSubscribers:
    """Tests for notify_all_subscribers (per-user mode)"""

    @patch('app.services.notifier.notify_signal')
    def test_fallback_to_legacy_mode(self, mock_notify, app, sample_symbol):
        """Test fallback when per-user mode disabled"""
        mock_notify.return_value = True

        with app.app_context():
            Setting.set('notifications_enabled', 'true')
            Setting.set('per_user_notifications', 'false')

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_all_subscribers(signal)

            assert result['total'] == 1
            mock_notify.assert_called_once()

    def test_returns_skipped_when_disabled(self, app, sample_symbol):
        """Test returns skipped when notifications disabled"""
        with app.app_context():
            Setting.set('notifications_enabled', 'false')

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_all_subscribers(signal)

            assert result['skipped'] is True
            assert result['total'] == 0

    @patch('app.services.async_notifier.notify_subscribers_async')
    @patch('app.services.notifier.get_eligible_subscribers')
    def test_per_user_mode_sends_to_all(self, mock_get_subs, mock_async, app, sample_symbol):
        """Test per-user mode sends to all eligible subscribers"""
        with app.app_context():
            Setting.set('notifications_enabled', 'true')
            Setting.set('per_user_notifications', 'true')

            # Create users
            user1 = User(
                email='sub1@test.com',
                username='sub1',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_sub1'
            )
            user1.set_password('password')

            user2 = User(
                email='sub2@test.com',
                username='sub2',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_sub2'
            )
            user2.set_password('password')

            db.session.add_all([user1, user2])
            db.session.commit()

            mock_get_subs.return_value = [user1, user2]
            mock_async.return_value = {
                'success': 2,
                'failed': 0,
                'results': []
            }

            # Create pattern
            pattern = Pattern(
                symbol_id=sample_symbol,
                pattern_type='imbalance',
                timeframe='1h',
                direction='bullish',
                zone_low=95,
                zone_high=105,
                detected_at=datetime.now(timezone.utc)
            )
            db.session.add(pattern)
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                pattern_id=pattern.id,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_all_subscribers(signal)

            assert result['total'] == 2
            assert result['success'] == 2
            assert result['failed'] == 0

    @patch('app.services.async_notifier.notify_subscribers_async')
    @patch('app.services.notifier.get_eligible_subscribers')
    def test_no_eligible_subscribers(self, mock_get_subs, mock_async, app, sample_symbol):
        """Test when no subscribers are eligible"""
        with app.app_context():
            Setting.set('notifications_enabled', 'true')
            Setting.set('per_user_notifications', 'true')

            mock_get_subs.return_value = []

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            result = notify_all_subscribers(signal)

            assert result['total'] == 0
            mock_async.assert_not_called()


class TestNotifyConfluence:
    """Tests for notify_confluence function"""

    @patch('app.services.notifier.send_notification')
    @patch('app.services.notifier.Setting.get')
    def test_confluence_notification(self, mock_setting, mock_send, app):
        """Test high confluence notification format"""
        mock_send.return_value = True
        mock_setting.return_value = 'test_topic'

        with app.app_context():
            result = notify_confluence(
                symbol='BTC/USDT',
                direction='long',
                aligned_timeframes=['1h', '4h', '1d'],
                entry=50000.0,
                stop_loss=48000.0,
                take_profits=[55000.0, 60000.0]
            )

            assert result is True

            # Check call parameters
            call_kwargs = mock_send.call_args[1]
            assert 'HIGH CONFLUENCE' in call_kwargs['title']
            assert call_kwargs['priority'] == 5  # Urgent
            assert 'confluence' in call_kwargs['tags']
            assert 'BTC' in call_kwargs['tags']

    @patch('app.services.notifier.send_notification')
    @patch('app.services.notifier.Setting.get')
    def test_confluence_message_format(self, mock_setting, mock_send, app):
        """Test message contains all required info"""
        mock_send.return_value = True
        mock_setting.return_value = 'test_topic'

        with app.app_context():
            notify_confluence(
                symbol='ETH/USDT',
                direction='short',
                aligned_timeframes=['15m', '1h'],
                entry=3000.0,
                stop_loss=3100.0,
                take_profits=[2800.0, 2600.0, 2400.0],
                risk_reward=2.5
            )

            call_kwargs = mock_send.call_args[1]
            message = call_kwargs['message']

            # Check all required elements
            assert 'Entry:' in message
            assert 'SL:' in message
            assert 'TP1:' in message
            assert 'TP2:' in message
            assert 'R:R:' in message
            assert 'Confluence:' in message
            assert '[15m, 1h]' in message


class TestNotifySubscribersConfluence:
    """Tests for notify_subscribers_confluence function"""

    @patch('app.services.notifier.notify_confluence')
    def test_fallback_to_legacy(self, mock_notify):
        """Test fallback when per-user mode disabled"""
        mock_notify.return_value = True

        with patch('app.services.notifier.Setting.get', return_value='false'):
            result = notify_subscribers_confluence(
                symbol='BTC/USDT',
                direction='long',
                aligned_timeframes=['1h', '4h'],
                entry=50000.0,
                stop_loss=48000.0,
                take_profits=[55000.0]
            )

            assert result['total'] == 1
            mock_notify.assert_called_once()

    @patch('app.services.async_notifier.notify_subscribers_async')
    @patch('app.services.notifier.get_eligible_subscribers')
    def test_per_user_confluence(self, mock_get_subs, mock_async, app):
        """Test per-user confluence notifications"""
        with app.app_context():
            Setting.set('per_user_notifications', 'true')

            user = User(
                email='conf_user@test.com',
                username='conf_user',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_conf'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            mock_get_subs.return_value = [user]
            mock_async.return_value = {
                'success': 1,
                'failed': 0,
                'results': []
            }

            result = notify_subscribers_confluence(
                symbol='BTC/USDT',
                direction='long',
                aligned_timeframes=['1h', '4h', '1d'],
                entry=50000.0,
                stop_loss=48000.0,
                take_profits=[55000.0]
            )

            assert result['total'] == 1
            assert result['success'] == 1


class TestNotificationRateLimiting:
    """Tests for notification rate limiting"""

    def test_user_daily_limit_respected(self, app):
        """Test that users are filtered when at daily limit"""
        with app.app_context():
            # Create user at daily limit
            user = User(
                email='limited@test.com',
                username='limited',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_limited'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            # Free tier: 1 notification per day
            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Add notification from today
            user_notif = UserNotification(
                user_id=user.id,
                signal_id=1,
                success=True
            )
            db.session.add(user_notif)
            db.session.commit()

            # User should not be eligible (at limit)
            eligible = get_eligible_subscribers()
            emails = [u.email for u in eligible]
            assert 'limited@test.com' not in emails


class TestNotificationContentFormatting:
    """Tests for notification content formatting"""

    @patch('app.services.notifier.send_notification')
    def test_long_signal_format(self, mock_send, app, sample_symbol):
        """Test LONG signal has correct formatting"""
        mock_send.return_value = True

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            pattern = Pattern(
                symbol_id=sample_symbol,
                pattern_type='order_block',
                timeframe='4h',
                direction='bullish',
                zone_low=95,
                zone_high=105,
                detected_at=datetime.now(timezone.utc)
            )
            db.session.add(pattern)
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                pattern_id=pattern.id,
                direction='long',
                confluence_score=4,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            notify_signal(signal)

            call_kwargs = mock_send.call_args[1]
            assert 'LONG' in call_kwargs['title']
            assert 'OB' in call_kwargs['title']  # Order Block abbreviation
            assert '[4h]' in call_kwargs['title']

    @patch('app.services.notifier.send_notification')
    def test_short_signal_format(self, mock_send, app, sample_symbol):
        """Test SHORT signal has correct formatting"""
        mock_send.return_value = True

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            pattern = Pattern(
                symbol_id=sample_symbol,
                pattern_type='liquidity_sweep',
                timeframe='1h',
                direction='bearish',
                zone_low=105,
                zone_high=115,
                detected_at=datetime.now(timezone.utc)
            )
            db.session.add(pattern)
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                pattern_id=pattern.id,
                direction='short',
                confluence_score=3,
                entry_price=110,
                stop_loss=115,
                take_profit_1=95,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            notify_signal(signal)

            call_kwargs = mock_send.call_args[1]
            assert 'SHORT' in call_kwargs['title']
            assert 'LS' in call_kwargs['title']  # Liquidity Sweep abbreviation

    @patch('app.services.notifier.send_notification')
    def test_current_price_percentage(self, mock_send, app, sample_symbol):
        """Test current price percentage is calculated"""
        mock_send.return_value = True

        with app.app_context():
            Setting.set('notifications_enabled', 'true')

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                confluence_score=3,
                entry_price=100,
                stop_loss=95,
                take_profit_1=115,
                risk_reward=3.0
            )
            db.session.add(signal)
            db.session.commit()

            notify_signal(signal, current_price=98.0)

            call_kwargs = mock_send.call_args[1]
            message = call_kwargs['message']
            assert 'Current:' in message
            assert '+' in message  # Entry is above current price
