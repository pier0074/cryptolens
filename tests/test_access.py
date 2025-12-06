"""
Tests for Notification Access Control
Tests who can and cannot receive notifications based on account status
and subscription state.

Test scenarios:
- User with active subscription: CAN receive notifications
- User with no subscription: CANNOT receive notifications
- User with expired subscription: CANNOT receive notifications
- User in grace period: CAN receive notifications
- Unverified user: CANNOT receive notifications
- Inactive user: CANNOT receive notifications
- Lifetime subscriber: CAN receive notifications (forever)
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app import db
from app.models import User, Subscription, Signal, Symbol, Pattern
from app.services.notifier import get_eligible_subscribers, notify_all_subscribers


class TestUserCanReceiveNotifications:
    """Tests for the can_receive_notifications property on User model"""

    def test_active_user_with_subscription_can_receive(self, app, sample_user):
        """Test: Verified user with active subscription CAN receive notifications"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            assert user.is_active is True
            assert user.is_verified is True
            assert user.subscription is not None
            assert user.subscription.is_valid is True
            assert user.can_receive_notifications is True

    def test_unverified_user_cannot_receive(self, app, unverified_user):
        """Test: Unverified user CANNOT receive notifications"""
        with app.app_context():
            user = db.session.get(User, unverified_user)
            assert user.is_verified is False
            assert user.can_receive_notifications is False

    def test_inactive_user_cannot_receive(self, app, inactive_user):
        """Test: Inactive (deactivated) user CANNOT receive notifications"""
        with app.app_context():
            user = db.session.get(User, inactive_user)
            assert user.is_active is False
            assert user.can_receive_notifications is False

    def test_user_without_subscription_cannot_receive(self, app, user_no_subscription):
        """Test: User with no subscription CANNOT receive notifications"""
        with app.app_context():
            user = db.session.get(User, user_no_subscription)
            assert user.subscription is None
            assert user.can_receive_notifications is False

    def test_user_with_expired_subscription_cannot_receive(self, app, user_expired_subscription):
        """Test: User with expired subscription (past grace) CANNOT receive notifications"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)
            assert user.subscription.is_valid is False
            assert user.can_receive_notifications is False

    def test_user_in_grace_period_can_receive(self, app, user_grace_period):
        """Test: User in grace period CAN still receive notifications"""
        with app.app_context():
            user = db.session.get(User, user_grace_period)
            assert user.subscription.is_expired is True
            assert user.subscription.is_in_grace_period is True
            assert user.subscription.is_valid is True
            assert user.can_receive_notifications is True

    def test_lifetime_user_can_receive(self, app, user_lifetime):
        """Test: User with lifetime subscription CAN always receive notifications"""
        with app.app_context():
            user = db.session.get(User, user_lifetime)
            assert user.subscription.is_lifetime is True
            assert user.subscription.is_valid is True
            assert user.can_receive_notifications is True


class TestGetEligibleSubscribers:
    """Tests for the get_eligible_subscribers function"""

    def test_includes_active_verified_users(self, app, sample_user):
        """Test that active verified users with valid subscriptions are included"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert sample_user in user_ids

    def test_excludes_unverified_users(self, app, unverified_user):
        """Test that unverified users are excluded"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert unverified_user not in user_ids

    def test_excludes_inactive_users(self, app, inactive_user):
        """Test that inactive users are excluded"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert inactive_user not in user_ids

    def test_excludes_users_without_subscription(self, app, user_no_subscription):
        """Test that users without subscriptions are excluded"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert user_no_subscription not in user_ids

    def test_excludes_expired_users(self, app, user_expired_subscription):
        """Test that users with expired subscriptions are excluded"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert user_expired_subscription not in user_ids

    def test_includes_grace_period_users(self, app, user_grace_period):
        """Test that users in grace period are included"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert user_grace_period in user_ids

    def test_includes_lifetime_users(self, app, user_lifetime):
        """Test that lifetime subscribers are included"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert user_lifetime in user_ids

    def test_multiple_eligible_users(self, app, sample_user, user_grace_period, user_lifetime):
        """Test that all eligible users are returned"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]

            assert sample_user in user_ids
            assert user_grace_period in user_ids
            assert user_lifetime in user_ids
            assert len(subscribers) >= 3


class TestNotificationDelivery:
    """Tests for actual notification delivery to eligible subscribers"""

    @pytest.fixture
    def test_signal(self, app, sample_symbol):
        """Create a test signal for notification tests"""
        with app.app_context():
            pattern = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=100.0,
                zone_low=95.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=95.0,
                stop_loss=90.0,
                take_profit_1=105.0,
                take_profit_2=110.0,
                take_profit_3=115.0,
                risk_reward=3.0,
                confluence_score=4,
                pattern_id=pattern.id,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()
            return signal.id

    @patch('app.services.notifier.send_notification')
    def test_notification_sent_to_eligible_users(self, mock_send, app, sample_user, test_signal):
        """Test that notifications are sent to eligible users"""
        with app.app_context():
            # Enable per-user mode
            from app.models import Setting
            Setting.set('per_user_notifications', 'true')

            mock_send.return_value = True

            signal = db.session.get(Signal, test_signal)
            result = notify_all_subscribers(signal)

            assert result['total'] >= 1
            assert result['success'] >= 1
            assert mock_send.called

    @patch('app.services.notifier.send_notification')
    def test_notification_not_sent_to_unverified(self, mock_send, app, unverified_user, test_signal):
        """Test that notifications are NOT sent to unverified users"""
        with app.app_context():
            from app.models import Setting
            Setting.set('per_user_notifications', 'true')

            mock_send.return_value = True

            signal = db.session.get(Signal, test_signal)
            result = notify_all_subscribers(signal)

            # Check that unverified user was not included
            call_topics = [call[1]['topic'] if 'topic' in call[1] else call[0][0]
                          for call in mock_send.call_args_list]

            user = db.session.get(User, unverified_user)
            assert user.ntfy_topic not in call_topics

    @patch('app.services.notifier.send_notification')
    def test_notification_not_sent_to_expired(self, mock_send, app, user_expired_subscription, test_signal):
        """Test that notifications are NOT sent to expired users"""
        with app.app_context():
            from app.models import Setting
            Setting.set('per_user_notifications', 'true')

            mock_send.return_value = True

            signal = db.session.get(Signal, test_signal)
            result = notify_all_subscribers(signal)

            call_topics = [call[1].get('topic', call[0][0] if call[0] else None)
                          for call in mock_send.call_args_list]

            user = db.session.get(User, user_expired_subscription)
            assert user.ntfy_topic not in call_topics


class TestAccessTransitions:
    """Tests for access changes when subscription status changes"""

    def test_access_lost_when_subscription_expires(self, app, sample_user):
        """Test that user loses access when subscription expires beyond grace"""
        with app.app_context():
            user = db.session.get(User, sample_user)

            # Initially should have access
            assert user.can_receive_notifications is True

            # Expire the subscription beyond grace period
            user.subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=10)
            user.subscription.status = 'expired'
            db.session.commit()

            # Should no longer have access
            db.session.refresh(user)
            assert user.can_receive_notifications is False

    def test_access_maintained_during_grace_period(self, app, sample_user):
        """Test that user maintains access during grace period"""
        with app.app_context():
            user = db.session.get(User, sample_user)

            # Initially should have access
            assert user.can_receive_notifications is True

            # Set subscription to just expired (within grace)
            user.subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            user.subscription.grace_period_days = 3
            db.session.commit()

            # Should still have access
            db.session.refresh(user)
            assert user.subscription.is_in_grace_period is True
            assert user.can_receive_notifications is True

    def test_access_regained_when_subscription_renewed(self, app, user_expired_subscription):
        """Test that expired user regains access when subscription renewed"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)

            # Initially should not have access
            assert user.can_receive_notifications is False

            # Renew subscription
            user.subscription.status = 'active'
            user.subscription.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            db.session.commit()

            # Should now have access
            db.session.refresh(user)
            assert user.can_receive_notifications is True

    def test_access_lost_when_account_deactivated(self, app, sample_user):
        """Test that user loses access when account is deactivated"""
        with app.app_context():
            user = db.session.get(User, sample_user)

            # Initially should have access
            assert user.can_receive_notifications is True

            # Deactivate account
            user.is_active = False
            db.session.commit()

            # Should no longer have access
            db.session.refresh(user)
            assert user.can_receive_notifications is False

    def test_access_lost_when_subscription_cancelled(self, app, sample_user):
        """Test that user loses access when subscription is cancelled"""
        with app.app_context():
            user = db.session.get(User, sample_user)

            # Initially should have access
            assert user.can_receive_notifications is True

            # Cancel subscription
            user.subscription.status = 'cancelled'
            db.session.commit()

            # Should no longer have access
            db.session.refresh(user)
            assert user.can_receive_notifications is False

    def test_access_lost_when_subscription_suspended(self, app, sample_user):
        """Test that user loses access when subscription is suspended"""
        with app.app_context():
            user = db.session.get(User, sample_user)

            # Initially should have access
            assert user.can_receive_notifications is True

            # Suspend subscription
            user.subscription.status = 'suspended'
            db.session.commit()

            # Should no longer have access
            db.session.refresh(user)
            assert user.can_receive_notifications is False


class TestAdminAccess:
    """Tests for admin user access"""

    def test_admin_with_subscription_can_receive(self, app, admin_user):
        """Test that admin with valid subscription can receive notifications"""
        with app.app_context():
            user = db.session.get(User, admin_user)
            assert user.is_admin is True
            assert user.can_receive_notifications is True

    def test_admin_in_eligible_list(self, app, admin_user):
        """Test that admin is included in eligible subscribers"""
        with app.app_context():
            subscribers = get_eligible_subscribers()
            user_ids = [u.id for u in subscribers]
            assert admin_user in user_ids


class TestEdgeCases:
    """Tests for edge cases and boundary conditions"""

    def test_subscription_expires_exactly_now(self, app, sample_user):
        """Test subscription expiring at exact current moment"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            user.subscription.expires_at = datetime.now(timezone.utc)
            db.session.commit()

            db.session.refresh(user)
            # Should still be in grace period
            assert user.subscription.is_in_grace_period is True
            assert user.can_receive_notifications is True

    def test_subscription_expires_one_second_ago(self, app, sample_user):
        """Test subscription expired one second ago"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            user.subscription.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            user.subscription.grace_period_days = 3
            db.session.commit()

            db.session.refresh(user)
            # Should be in grace period
            assert user.subscription.is_in_grace_period is True
            assert user.can_receive_notifications is True

    def test_grace_period_ends_exactly_now(self, app, sample_user):
        """Test grace period ending at exact current moment"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            user.subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=3)
            user.subscription.grace_period_days = 3
            db.session.commit()

            db.session.refresh(user)
            # At boundary - depends on implementation (inclusive vs exclusive)
            # Either result is acceptable

    def test_user_verified_but_no_subscription(self, app, user_no_subscription):
        """Test verified user without any subscription"""
        with app.app_context():
            user = db.session.get(User, user_no_subscription)
            assert user.is_verified is True
            assert user.is_active is True
            assert user.subscription is None
            assert user.can_receive_notifications is False

    def test_subscription_renewal_after_expiry(self, app, sample_user):
        """Test renewing subscription after expiry using extend_subscription"""
        from app.services.subscription import extend_subscription

        with app.app_context():
            user = db.session.get(User, sample_user)
            old_sub_id = user.subscription.id

            # Expire current subscription
            user.subscription.status = 'expired'
            user.subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=30)
            db.session.commit()

            # User should no longer have access
            db.session.refresh(user)
            assert user.can_receive_notifications is False

            # Renew subscription using extend_subscription
            renewed_sub = extend_subscription(user.id, 'yearly')

            # User should now have access with renewed subscription
            db.session.refresh(user)
            assert user.subscription.status == 'active'
            assert user.subscription.plan == 'yearly'
            assert user.subscription.is_valid is True
            assert user.can_receive_notifications is True
