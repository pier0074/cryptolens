"""
Tests for subscription tier restrictions.

Verifies that each tier (free, pro, premium) has correct access to:
- Symbols (BTC/USDT only for free, 5 for pro, unlimited for premium)
- Pattern types (FVG only for free, all 3 for pro/premium)
- Patterns page (none for free, last 100 for pro, full for premium)
- Signals page (none for free, last 50 for pro, full for premium)
- Portfolio (none for free, 1+5tx for pro, unlimited for premium)
- Backtest (none for free/pro, full for premium)
- Analytics (none for free, full for pro/premium)
- Notifications (1/day + 10min delay for free, 20/day for pro, unlimited for premium)
- API Access (none for free/pro, full for premium)
"""
import pytest
from datetime import datetime, timezone, timedelta
from app import db
from app.models import User, Subscription, SUBSCRIPTION_TIERS


class TestTierConfiguration:
    """Test that tier configuration matches spec"""

    def test_free_tier_symbols(self):
        """Free tier should only allow BTC/USDT"""
        tier = SUBSCRIPTION_TIERS['free']
        assert tier['symbols'] == ['BTC/USDT']
        assert tier['max_symbols'] == 1

    def test_pro_tier_symbols(self):
        """Pro tier should allow 5 symbols"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['symbols'] is None  # Any symbol
        assert tier['max_symbols'] == 5

    def test_premium_tier_symbols(self):
        """Premium tier should have unlimited symbols"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['symbols'] is None
        assert tier['max_symbols'] is None

    def test_free_tier_pattern_types(self):
        """Free tier should only see FVG (imbalance)"""
        tier = SUBSCRIPTION_TIERS['free']
        assert tier['pattern_types'] == ['imbalance']

    def test_pro_tier_pattern_types(self):
        """Pro tier should see current 3 pattern types only"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['pattern_types'] == ['imbalance', 'order_block', 'liquidity_sweep']

    def test_premium_tier_pattern_types(self):
        """Premium tier should see all pattern types"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['pattern_types'] is None

    def test_free_tier_page_access(self):
        """Free tier should not have patterns/signals/portfolio/backtest/analytics access"""
        tier = SUBSCRIPTION_TIERS['free']
        assert tier['patterns_page'] is False
        assert tier['signals_page'] is False
        assert tier['portfolio'] is False
        assert tier['backtest'] is False
        assert tier['analytics_page'] is False

    def test_pro_tier_page_access(self):
        """Pro tier should have patterns/signals/portfolio/analytics but not backtest"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['patterns_page'] is True
        assert tier['patterns_limit'] == 100
        assert tier['signals_page'] is True
        assert tier['signals_limit'] == 50
        assert tier['portfolio'] is True
        assert tier['portfolio_limit'] == 1
        assert tier['transactions_limit'] == 5
        assert tier['backtest'] is False
        assert tier['analytics_page'] is True

    def test_premium_tier_page_access(self):
        """Premium tier should have full access to everything"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['patterns_page'] is True
        assert tier['patterns_limit'] is None  # Unlimited
        assert tier['signals_page'] is True
        assert tier['signals_limit'] is None  # Unlimited
        assert tier['portfolio'] is True
        assert tier['portfolio_limit'] is None
        assert tier['transactions_limit'] is None
        assert tier['backtest'] is True
        assert tier['analytics_page'] is True

    def test_notification_limits(self):
        """Test notification limits match spec"""
        assert SUBSCRIPTION_TIERS['free']['daily_notifications'] == 1
        assert SUBSCRIPTION_TIERS['free']['notification_delay_minutes'] == 10
        assert SUBSCRIPTION_TIERS['pro']['daily_notifications'] == 20
        assert SUBSCRIPTION_TIERS['pro']['notification_delay_minutes'] == 0
        assert SUBSCRIPTION_TIERS['premium']['daily_notifications'] is None  # Unlimited
        assert SUBSCRIPTION_TIERS['premium']['notification_delay_minutes'] == 0

    def test_api_access(self):
        """Only premium should have API access"""
        assert SUBSCRIPTION_TIERS['free']['api_access'] is False
        assert SUBSCRIPTION_TIERS['pro']['api_access'] is False
        assert SUBSCRIPTION_TIERS['premium']['api_access'] is True


class TestUserTierMethods:
    """Test User model tier-related methods"""

    @pytest.fixture
    def free_user(self, app):
        """Create a free tier user"""
        with app.app_context():
            user = User(
                email='freeuser@test.com',
                username='freeuser',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_free12345678'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                expires_at=None,
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    @pytest.fixture
    def pro_user(self, app):
        """Create a pro tier user"""
        with app.app_context():
            user = User(
                email='prouser@test.com',
                username='prouser',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_pro123456789'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    @pytest.fixture
    def premium_user(self, app):
        """Create a premium tier user"""
        with app.app_context():
            user = User(
                email='premiumuser@test.com',
                username='premiumuser',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_prem1234567'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    def test_free_user_tier(self, app, free_user):
        """Free user should have free tier"""
        with app.app_context():
            user = db.session.get(User, free_user)
            assert user.subscription_tier == 'free'

    def test_pro_user_tier(self, app, pro_user):
        """Pro user should have pro tier"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            assert user.subscription_tier == 'pro'

    def test_premium_user_tier(self, app, premium_user):
        """Premium user should have premium tier"""
        with app.app_context():
            user = db.session.get(User, premium_user)
            assert user.subscription_tier == 'premium'

    def test_free_user_feature_access(self, app, free_user):
        """Free user should not access premium features"""
        with app.app_context():
            user = db.session.get(User, free_user)
            assert user.can_access_feature('patterns_page') is False
            assert user.can_access_feature('signals_page') is False
            assert user.can_access_feature('portfolio') is False
            assert user.can_access_feature('backtest') is False
            assert user.can_access_feature('analytics_page') is False
            assert user.can_access_feature('api_access') is False

    def test_pro_user_feature_access(self, app, pro_user):
        """Pro user should access pro features but not backtest/api"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            assert user.can_access_feature('patterns_page') is True
            assert user.can_access_feature('signals_page') is True
            assert user.can_access_feature('portfolio') is True
            assert user.can_access_feature('backtest') is False
            assert user.can_access_feature('analytics_page') is True
            assert user.can_access_feature('api_access') is False

    def test_premium_user_feature_access(self, app, premium_user):
        """Premium user should access all features"""
        with app.app_context():
            user = db.session.get(User, premium_user)
            assert user.can_access_feature('patterns_page') is True
            assert user.can_access_feature('signals_page') is True
            assert user.can_access_feature('portfolio') is True
            assert user.can_access_feature('backtest') is True
            assert user.can_access_feature('analytics_page') is True
            assert user.can_access_feature('api_access') is True

    def test_free_user_pattern_types(self, app, free_user):
        """Free user should only see FVG patterns"""
        with app.app_context():
            user = db.session.get(User, free_user)
            allowed = user.get_allowed_pattern_types()
            assert allowed == ['imbalance']

    def test_pro_user_pattern_types(self, app, pro_user):
        """Pro user should see current 3 pattern types only"""
        with app.app_context():
            user = db.session.get(User, pro_user)
            allowed = user.get_allowed_pattern_types()
            assert allowed == ['imbalance', 'order_block', 'liquidity_sweep']

    def test_notification_delay(self, app, free_user, pro_user):
        """Free user should have 10 min delay, pro no delay"""
        with app.app_context():
            free = db.session.get(User, free_user)
            pro = db.session.get(User, pro_user)
            assert free.get_notification_delay_seconds() == 600  # 10 min
            assert pro.get_notification_delay_seconds() == 0


class TestViewAsAdmin:
    """Test that View As functionality works for admins"""

    def test_view_as_sets_session(self, client, app, admin_user):
        """Admin can set view_as tier in session"""
        from tests.test_routes import login_user

        login_user(client, 'admin@example.com', 'AdminPass123')

        # Set view as free
        response = client.post('/admin/set-view-as', data={'tier': 'free'})
        assert response.status_code == 302

        with client.session_transaction() as sess:
            assert sess.get('view_as') == 'free'

    def test_view_as_admin_resets(self, client, app, admin_user):
        """Setting tier to admin removes view_as from session"""
        from tests.test_routes import login_user

        login_user(client, 'admin@example.com', 'AdminPass123')

        # Set view as free first
        client.post('/admin/set-view-as', data={'tier': 'free'})

        # Reset to admin
        client.post('/admin/set-view-as', data={'tier': 'admin'})

        with client.session_transaction() as sess:
            assert 'view_as' not in sess


class TestAPIAccess:
    """Test API access restrictions for protected endpoints.

    Note: Read-only endpoints (GET /patterns, /signals, etc.) are public for UI use.
    Protected write endpoints (POST /scan, /fetch, etc.) require Premium tier or API key.
    """

    def test_protected_api_requires_auth(self, client, app):
        """Protected API endpoints require authentication"""
        response = client.post('/api/scan')
        assert response.status_code in [401, 503]  # Unauthorized or not configured

    def test_protected_api_rejects_free_user(self, client, app):
        """Free users cannot access protected API endpoints"""
        from app.models import User, Subscription

        with app.app_context():
            user = User(
                email='freeapi@test.com',
                username='freeapi',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_freeapi1234'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                expires_at=None,
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

        # Login as free user
        client.post('/auth/login', data={
            'email': 'freeapi@test.com',
            'password': 'TestPass123'
        })

        response = client.post('/api/scan')
        assert response.status_code == 403  # Forbidden - no API access

    def test_protected_api_allows_premium_user(self, client, app):
        """Premium users can access protected API endpoints"""
        from app.models import User, Subscription

        with app.app_context():
            user = User(
                email='premiumapi@test.com',
                username='premiumapi',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_premapi123'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='premium',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

        # Login as premium user
        client.post('/auth/login', data={
            'email': 'premiumapi@test.com',
            'password': 'TestPass123'
        })

        # POST /api/scan is rate limited (1/min), should return 200 on success
        response = client.post('/api/scan')
        assert response.status_code == 200

    def test_public_api_accessible_to_all(self, client, app):
        """Public API endpoints (GET) are accessible without auth for UI"""
        response = client.get('/api/patterns')
        assert response.status_code == 200

        response = client.get('/api/health')
        assert response.status_code == 200
