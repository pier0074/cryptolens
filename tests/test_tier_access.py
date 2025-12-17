"""
Tests for Tier-Based Feature Access
Tests that Free, Pro, and Premium users have correct feature access
"""
import pytest
from app import db
from app.models import User, Subscription
from app.models.base import SUBSCRIPTION_TIERS


class TestTierFeatureLimits:
    """Tests for tier feature limit values"""

    def test_free_tier_limits(self):
        """Test Free tier has correct limits"""
        free = SUBSCRIPTION_TIERS['free']
        assert free['symbols'] == ['BTC/USDT']
        assert free['max_symbols'] == 1
        assert free['pattern_types'] == ['imbalance']
        assert free['daily_notifications'] == 1
        assert free['notification_delay_minutes'] == 10
        assert free['patterns_page'] is False
        assert free['signals_page'] is False
        assert free['portfolio'] is False
        assert free['backtest'] is False
        assert free['api_access'] is False

    def test_pro_tier_limits(self):
        """Test Pro tier has correct limits"""
        pro = SUBSCRIPTION_TIERS['pro']
        assert pro['max_symbols'] == 5
        # Pro has access to all pattern types (list of all)
        assert 'imbalance' in pro['pattern_types']
        assert 'order_block' in pro['pattern_types']
        assert 'liquidity_sweep' in pro['pattern_types']
        assert pro['daily_notifications'] == 20
        assert pro['notification_delay_minutes'] == 0
        assert pro['patterns_page'] is True
        assert pro['patterns_limit'] == 100
        assert pro['signals_page'] is True
        assert pro['signals_limit'] == 50
        assert pro['portfolio'] is True
        assert pro['backtest'] is False
        assert pro['api_access'] is False

    def test_premium_tier_limits(self):
        """Test Premium tier has correct limits"""
        premium = SUBSCRIPTION_TIERS['premium']
        assert premium['max_symbols'] is None  # Unlimited
        assert premium['pattern_types'] is None  # All patterns
        assert premium['daily_notifications'] is None  # Unlimited
        assert premium['patterns_page'] is True
        assert premium['patterns_limit'] is None  # Unlimited
        assert premium['signals_page'] is True
        assert premium['signals_limit'] is None  # Unlimited
        assert premium['backtest'] is True
        assert premium['api_access'] is True


class TestUserTierAccess:
    """Tests for user tier access methods"""

    @pytest.fixture
    def free_user(self, app):
        """Create a free tier user"""
        with app.app_context():
            user = User(
                email='free_tier@test.com',
                username='free_tier',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            yield user.id

    @pytest.fixture
    def pro_user(self, app):
        """Create a pro tier user"""
        with app.app_context():
            user = User(
                email='pro_tier@test.com',
                username='pro_tier',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            yield user.id

    @pytest.fixture
    def premium_user(self, app):
        """Create a premium tier user"""
        with app.app_context():
            user = User(
                email='premium_tier@test.com',
                username='premium_tier',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_premium'
            )
            user.set_password('password')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            yield user.id

    def test_free_user_allowed_symbols(self, app, free_user):
        """Test free user can only access BTC/USDT"""
        with app.app_context():
            user = db.session.get(User, free_user)
            # Free tier limit is stored in tier_features
            symbols = user.tier_features.get('symbols')
            assert symbols == ['BTC/USDT']

    def test_free_user_allowed_patterns(self, app, free_user):
        """Test free user can only access imbalance pattern"""
        with app.app_context():
            user = db.session.get(User, free_user)
            patterns = user.get_allowed_pattern_types()
            assert patterns == ['imbalance']

    def test_pro_user_allowed_symbols(self, app, pro_user):
        """Test pro user can access up to 5 symbols"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            limit = user.get_feature_limit('max_symbols')
            assert limit == 5

    def test_pro_user_allowed_patterns(self, app, pro_user):
        """Test pro user can access all pattern types"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            patterns = user.get_allowed_pattern_types()
            # Pro has access to all three pattern types
            assert 'imbalance' in patterns
            assert 'order_block' in patterns
            assert 'liquidity_sweep' in patterns

    def test_premium_user_unlimited_symbols(self, app, premium_user):
        """Test premium user has unlimited symbols"""
        with app.app_context():
            user = db.session.get(User, premium_user)
            limit = user.get_feature_limit('max_symbols')
            assert limit is None  # Unlimited

    def test_premium_user_can_backtest(self, app, premium_user):
        """Test premium user can access backtest"""
        with app.app_context():
            user = db.session.get(User, premium_user)
            assert user.can_access_feature('backtest') is True

    def test_free_user_cannot_backtest(self, app, free_user):
        """Test free user cannot access backtest"""
        with app.app_context():
            user = db.session.get(User, free_user)
            assert user.can_access_feature('backtest') is False

    def test_pro_user_cannot_backtest(self, app, pro_user):
        """Test pro user cannot access backtest"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            assert user.can_access_feature('backtest') is False


class TestDashboardTierAccess:
    """Tests for dashboard tier features (via User model methods)"""

    def test_free_user_dashboard_symbols_limited(self, app):
        """Test free user is limited to BTC/USDT via tier_features"""
        with app.app_context():
            user = User(
                email='free_dash@test.com',
                username='free_dash',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_dash'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Check tier features
            symbols = user.tier_features.get('symbols')
            assert symbols == ['BTC/USDT']
            assert user.tier_features.get('dashboard') == 'limited'

    def test_pro_user_dashboard_symbols_limited(self, app):
        """Test pro user has max 5 symbols"""
        with app.app_context():
            user = User(
                email='pro_dash@test.com',
                username='pro_dash',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_dash'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Check tier features
            assert user.get_feature_limit('max_symbols') == 5
            assert user.tier_features.get('dashboard') == 'full'


class TestPatternsPageTierAccess:
    """Tests for patterns page feature access by tier"""

    def test_free_user_patterns_feature_disabled(self, app):
        """Test free user cannot access patterns feature"""
        with app.app_context():
            user = User(
                email='free_pat@test.com',
                username='free_pat',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_pat'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Free tier doesn't have patterns_page access
            assert user.can_access_feature('patterns_page') is False
            assert user.get_feature_limit('patterns_limit') == 0

    def test_pro_user_patterns_limited(self, app):
        """Test pro user has limited patterns access (100)"""
        with app.app_context():
            user = User(
                email='pro_pat@test.com',
                username='pro_pat',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_pat'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('patterns_page') is True
            assert user.get_feature_limit('patterns_limit') == 100

    def test_premium_user_patterns_unlimited(self, app):
        """Test premium user has unlimited patterns access"""
        with app.app_context():
            user = User(
                email='prem_pat@test.com',
                username='prem_pat',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_prem_pat'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('patterns_page') is True
            assert user.get_feature_limit('patterns_limit') is None  # Unlimited


class TestSignalsPageTierAccess:
    """Tests for signals page feature access by tier"""

    def test_free_user_signals_feature_disabled(self, app):
        """Test free user cannot access signals feature"""
        with app.app_context():
            user = User(
                email='free_sig@test.com',
                username='free_sig',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_sig'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Free tier doesn't have signals_page access
            assert user.can_access_feature('signals_page') is False
            assert user.get_feature_limit('signals_limit') == 0

    def test_pro_user_signals_limited(self, app):
        """Test pro user has limited signals access (50)"""
        with app.app_context():
            user = User(
                email='pro_sig@test.com',
                username='pro_sig',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_sig'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('signals_page') is True
            assert user.get_feature_limit('signals_limit') == 50


class TestBacktestTierAccess:
    """Tests for backtest feature access by tier"""

    def test_free_user_backtest_feature_disabled(self, app):
        """Test free user cannot access backtest feature"""
        with app.app_context():
            user = User(
                email='free_bt@test.com',
                username='free_bt',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_bt'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('backtest') is False

    def test_pro_user_backtest_feature_disabled(self, app):
        """Test pro user cannot access backtest feature"""
        with app.app_context():
            user = User(
                email='pro_bt@test.com',
                username='pro_bt',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_bt'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('backtest') is False

    def test_premium_user_backtest_feature_enabled(self, app):
        """Test premium user can access backtest feature"""
        with app.app_context():
            user = User(
                email='prem_bt@test.com',
                username='prem_bt',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_prem_bt'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('backtest') is True


class TestPortfolioTierAccess:
    """Tests for portfolio feature access by tier"""

    def test_free_user_portfolio_feature_disabled(self, app):
        """Test free user cannot access portfolio feature"""
        with app.app_context():
            user = User(
                email='free_pf@test.com',
                username='free_pf',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_pf'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('portfolio') is False
            assert user.get_feature_limit('portfolio_limit') == 0

    def test_pro_user_portfolio_limited(self, app):
        """Test pro user has limited portfolio access (1 portfolio)"""
        with app.app_context():
            user = User(
                email='pro_pf@test.com',
                username='pro_pf',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_pf'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('portfolio') is True
            assert user.get_feature_limit('portfolio_limit') == 1
            assert user.get_feature_limit('transactions_limit') == 5  # 5 tx/day


class TestAPIAccessTierAccess:
    """Tests for API access by tier"""

    def test_free_user_no_api_access(self, app):
        """Test free user doesn't have API access feature"""
        with app.app_context():
            user = User(
                email='free_api@test.com',
                username='free_api',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_api'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('api_access') is False

    def test_pro_user_no_api_access(self, app):
        """Test pro user doesn't have API access feature"""
        with app.app_context():
            user = User(
                email='pro_api@test.com',
                username='pro_api',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_api'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('api_access') is False

    def test_premium_user_has_api_access(self, app):
        """Test premium user has API access feature"""
        with app.app_context():
            user = User(
                email='prem_api@test.com',
                username='prem_api',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_prem_api'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            assert user.can_access_feature('api_access') is True


class TestAdminBypassTierRestrictions:
    """Tests that admin users bypass tier restrictions"""

    def test_admin_bypasses_all_restrictions(self, app):
        """Test admin has access to all features"""
        with app.app_context():
            admin = User(
                email='admin_test@test.com',
                username='admin_test',
                is_active=True,
                is_verified=True,
                is_admin=True,
                ntfy_topic='topic_admin'
            )
            admin.set_password('Test123!')
            db.session.add(admin)
            db.session.commit()

            # Admin with free subscription still has full access
            sub = Subscription(
                user_id=admin.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            # Admin should have access to all features
            assert admin.can_access_feature('backtest') is True
            assert admin.can_access_feature('api_access') is True
            assert admin.can_access_feature('patterns_page') is True
            assert admin.can_access_feature('signals_page') is True
            assert admin.can_access_feature('portfolio') is True


class TestNotificationTierLimits:
    """Tests for notification limits by tier"""

    def test_free_user_notification_delay(self, app):
        """Test free user has 10 minute notification delay"""
        with app.app_context():
            user = User(
                email='free_notif_delay@test.com',
                username='free_notif_delay',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_notif'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            delay = user.get_notification_delay_seconds()
            assert delay == 600  # 10 minutes

    def test_pro_user_no_notification_delay(self, app):
        """Test pro user has no notification delay"""
        with app.app_context():
            user = User(
                email='pro_notif_delay@test.com',
                username='pro_notif_delay',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_notif'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            delay = user.get_notification_delay_seconds()
            assert delay == 0

    def test_free_user_daily_notification_limit(self, app):
        """Test free user has 1 notification per day limit"""
        with app.app_context():
            user = User(
                email='free_notif_limit@test.com',
                username='free_notif_limit',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_free_limit'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            limit = user.get_feature_limit('daily_notifications')
            assert limit == 1

    def test_pro_user_daily_notification_limit(self, app):
        """Test pro user has 20 notifications per day limit"""
        with app.app_context():
            user = User(
                email='pro_notif_limit@test.com',
                username='pro_notif_limit',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_pro_limit'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            limit = user.get_feature_limit('daily_notifications')
            assert limit == 20

    def test_premium_user_unlimited_notifications(self, app):
        """Test premium user has unlimited notifications"""
        with app.app_context():
            user = User(
                email='prem_notif_limit@test.com',
                username='prem_notif_limit',
                is_active=True,
                is_verified=True,
                ntfy_topic='topic_prem_limit'
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            limit = user.get_feature_limit('daily_notifications')
            assert limit is None  # Unlimited
