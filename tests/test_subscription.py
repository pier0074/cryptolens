"""
Tests for Subscription Management
Tests subscription creation, expiry, grace periods, and status transitions.
"""
import pytest
from datetime import datetime, timezone, timedelta
from app import db
from app.models import User, Subscription, SUBSCRIPTION_PLANS
from app.services.subscription import (
    create_subscription, extend_subscription, cancel_subscription,
    suspend_subscription, reactivate_subscription, check_subscription_status,
    expire_subscriptions, get_expiring_soon, get_subscription_stats,
    SubscriptionError
)


class TestSubscriptionCreation:
    """Tests for subscription creation"""

    def test_create_free_subscription(self, app, user_no_subscription):
        """Test creating a free trial subscription"""
        with app.app_context():
            sub = create_subscription(user_no_subscription, 'free')

            assert sub is not None
            assert sub.plan == 'free'
            assert sub.status == 'active'
            assert sub.days_remaining >= 6  # 6-7 days depending on time of creation
            assert sub.is_valid is True

    def test_create_pro_subscription(self, app, user_no_subscription):
        """Test creating a pro subscription"""
        with app.app_context():
            sub = create_subscription(user_no_subscription, 'pro')

            assert sub is not None
            assert sub.plan == 'pro'
            assert sub.status == 'active'
            assert sub.days_remaining >= 29  # 29-30 days depending on time of creation
            assert sub.plan_name == 'Pro'
            assert sub.tier == 'pro'

    def test_create_yearly_subscription(self, app, user_no_subscription):
        """Test creating a yearly subscription"""
        with app.app_context():
            sub = create_subscription(user_no_subscription, 'yearly')

            assert sub is not None
            assert sub.plan == 'yearly'
            assert sub.days_remaining >= 364  # 364-365 days depending on time of creation

    def test_create_lifetime_subscription(self, app, user_no_subscription):
        """Test creating a lifetime subscription"""
        with app.app_context():
            sub = create_subscription(user_no_subscription, 'lifetime')

            assert sub is not None
            assert sub.plan == 'lifetime'
            assert sub.expires_at is None
            assert sub.is_lifetime is True
            assert sub.is_valid is True

    def test_create_subscription_invalid_plan(self, app, user_no_subscription):
        """Test creating subscription with invalid plan fails"""
        with app.app_context():
            with pytest.raises(SubscriptionError) as exc_info:
                create_subscription(user_no_subscription, 'invalid_plan')
            assert 'Invalid plan' in str(exc_info.value)

    def test_create_subscription_user_already_has_one(self, app, sample_user):
        """Test creating subscription when user already has one fails"""
        with app.app_context():
            with pytest.raises(SubscriptionError) as exc_info:
                create_subscription(sample_user, 'monthly')
            assert 'already has a subscription' in str(exc_info.value)


class TestSubscriptionProperties:
    """Tests for subscription property calculations"""

    def test_is_expired_active_subscription(self, app, sample_user):
        """Test is_expired returns False for active subscription"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            sub = user.subscription
            assert sub.is_expired is False

    def test_is_expired_expired_subscription(self, app, user_expired_subscription):
        """Test is_expired returns True for expired subscription"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)
            sub = user.subscription
            assert sub.is_expired is True

    def test_days_remaining_positive(self, app, sample_user):
        """Test days_remaining for active subscription"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            sub = user.subscription
            assert sub.days_remaining > 0
            assert sub.days_remaining <= 30

    def test_days_remaining_expired(self, app, user_expired_subscription):
        """Test days_remaining for expired subscription"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)
            sub = user.subscription
            assert sub.days_remaining <= 0

    def test_days_remaining_lifetime(self, app, user_lifetime):
        """Test days_remaining for lifetime subscription"""
        with app.app_context():
            user = db.session.get(User, user_lifetime)
            sub = user.subscription
            assert sub.days_remaining is None or sub.days_remaining > 36500

    def test_is_in_grace_period(self, app, user_grace_period):
        """Test grace period detection"""
        with app.app_context():
            user = db.session.get(User, user_grace_period)
            sub = user.subscription
            assert sub.is_expired is True
            assert sub.is_in_grace_period is True
            assert sub.is_valid is True

    def test_not_in_grace_period(self, app, user_expired_subscription):
        """Test expired past grace period"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)
            sub = user.subscription
            assert sub.is_expired is True
            assert sub.is_in_grace_period is False
            assert sub.is_valid is False


class TestSubscriptionExtension:
    """Tests for subscription extension"""

    def test_extend_active_subscription(self, app, sample_user):
        """Test extending an active subscription"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            original_expiry = user.subscription.expires_at

            sub = extend_subscription(sample_user, 'monthly')
            db.session.refresh(user.subscription)

            assert sub is not None
            assert user.subscription.expires_at > original_expiry

    def test_extend_creates_if_none(self, app, user_no_subscription):
        """Test extending creates subscription if none exists"""
        with app.app_context():
            sub = extend_subscription(user_no_subscription, 'monthly')
            assert sub is not None
            assert sub.plan == 'monthly'
            assert sub.status == 'active'


class TestSubscriptionCancellation:
    """Tests for subscription cancellation"""

    def test_cancel_active_subscription(self, app, sample_user):
        """Test cancelling an active subscription"""
        with app.app_context():
            sub = cancel_subscription(sample_user)
            assert sub.status == 'cancelled'

    def test_cancel_no_subscription(self, app, user_no_subscription):
        """Test cancelling when no subscription exists"""
        with app.app_context():
            with pytest.raises(SubscriptionError) as exc_info:
                cancel_subscription(user_no_subscription)
            assert 'No subscription found' in str(exc_info.value)


class TestSubscriptionSuspension:
    """Tests for subscription suspension"""

    def test_suspend_active_subscription(self, app, sample_user):
        """Test suspending an active subscription"""
        with app.app_context():
            sub = suspend_subscription(sample_user)
            assert sub.status == 'suspended'
            assert sub.is_valid is False

    def test_reactivate_suspended_subscription(self, app, sample_user):
        """Test reactivating a suspended subscription"""
        with app.app_context():
            suspend_subscription(sample_user)
            sub = reactivate_subscription(sample_user)
            assert sub.status == 'active'


class TestSubscriptionExpiry:
    """Tests for subscription expiry processing"""

    def test_expire_subscriptions_marks_expired(self, app):
        """Test that expire_subscriptions marks old subscriptions as expired"""
        with app.app_context():
            user = User(
                email='testexpire@example.com',
                username='testexpire',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_testexpire12345'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='monthly',
                starts_at=datetime.now(timezone.utc) - timedelta(days=40),
                expires_at=datetime.now(timezone.utc) - timedelta(days=10),
                status='active',
                grace_period_days=3
            )
            db.session.add(sub)
            db.session.commit()

            count = expire_subscriptions()
            db.session.refresh(sub)

            assert count >= 1
            assert sub.status == 'expired'

    def test_expire_subscriptions_respects_grace(self, app, user_grace_period):
        """Test that subscriptions in grace period are not expired"""
        with app.app_context():
            user = db.session.get(User, user_grace_period)
            original_status = user.subscription.status

            count = expire_subscriptions()
            db.session.refresh(user.subscription)

            # Should not be expired since in grace period
            assert user.subscription.status == original_status


class TestExpiringSubscriptions:
    """Tests for finding subscriptions expiring soon"""

    def test_get_expiring_soon(self, app, user_expiring_soon):
        """Test finding subscriptions expiring within X days"""
        with app.app_context():
            expiring = get_expiring_soon(days=7)
            user_ids = [sub.user_id for sub in expiring]
            assert user_expiring_soon in user_ids

    def test_expiring_soon_excludes_distant(self, app, sample_user):
        """Test that subscriptions far from expiry are excluded"""
        with app.app_context():
            expiring = get_expiring_soon(days=3)
            user_ids = [sub.user_id for sub in expiring]
            # sample_user has 30 days, should not be in 3-day list
            assert sample_user not in user_ids


class TestSubscriptionStats:
    """Tests for subscription statistics"""

    def test_get_subscription_stats_counts(self, app, sample_user, user_expired_subscription):
        """Test subscription statistics counting"""
        with app.app_context():
            stats = get_subscription_stats()

            assert 'total' in stats
            assert 'active' in stats
            assert 'expired' in stats
            assert stats['total'] >= 2


class TestSubscriptionStatusDisplay:
    """Tests for status display properties"""

    def test_status_display_active(self, app, sample_user):
        """Test status display for active subscription"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            assert 'Active' in user.subscription.status_display

    def test_status_display_expired(self, app, user_expired_subscription):
        """Test status display for expired subscription"""
        with app.app_context():
            user = db.session.get(User, user_expired_subscription)
            assert 'Expired' in user.subscription.status_display

    def test_status_display_grace_period(self, app, user_grace_period):
        """Test status display for grace period"""
        with app.app_context():
            user = db.session.get(User, user_grace_period)
            display = user.subscription.status_display
            assert display is not None


class TestSubscriptionPlans:
    """Tests for subscription plan configurations"""

    def test_all_plans_exist(self, app):
        """Test that all expected plans are configured"""
        assert 'free' in SUBSCRIPTION_PLANS
        assert 'monthly' in SUBSCRIPTION_PLANS
        assert 'yearly' in SUBSCRIPTION_PLANS
        assert 'lifetime' in SUBSCRIPTION_PLANS

    def test_plan_properties(self, app):
        """Test plan configurations have required properties"""
        for plan_key, plan in SUBSCRIPTION_PLANS.items():
            assert 'name' in plan
            assert 'price' in plan
            if plan_key != 'lifetime':
                assert 'days' in plan


class TestCheckSubscriptionStatus:
    """Tests for subscription status checking"""

    def test_check_status_active(self, app, sample_user):
        """Test checking status of active subscription"""
        with app.app_context():
            status = check_subscription_status(sample_user)
            assert status['status'] == 'active'
            assert status['has_access'] is True

    def test_check_status_no_subscription(self, app, user_no_subscription):
        """Test checking status with no subscription"""
        with app.app_context():
            status = check_subscription_status(user_no_subscription)
            assert status['status'] == 'none'
            assert status['has_access'] is False

    def test_check_status_expired(self, app, user_expired_subscription):
        """Test checking status of expired subscription"""
        with app.app_context():
            status = check_subscription_status(user_expired_subscription)
            assert status['status'] == 'expired'
            assert status['has_access'] is False

    def test_check_status_grace(self, app, user_grace_period):
        """Test checking status during grace period"""
        with app.app_context():
            status = check_subscription_status(user_grace_period)
            # In grace period, status is still 'active' but is_in_grace_period is True
            assert status['is_in_grace_period'] is True
            assert status['has_access'] is True
