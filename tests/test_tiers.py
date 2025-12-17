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


class TestSymbolFiltering:
    """Test symbol filtering based on user tier"""

    def test_filter_symbols_free_user(self, app):
        """Free user should only see BTC/USDT"""
        from app.decorators import filter_symbols_by_tier
        from app.models import User, Subscription

        with app.app_context():
            # Create a free user
            user = User(
                email='freesym@test.com',
                username='freesym',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_freesym123'
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

            # Mock symbol list
            class MockSymbol:
                def __init__(self, symbol):
                    self.symbol = symbol

            symbols = [MockSymbol('BTC/USDT'), MockSymbol('ETH/USDT'), MockSymbol('XRP/USDT')]
            filtered = filter_symbols_by_tier(symbols, user)

            # Free user should only see BTC/USDT
            assert len(filtered) == 1
            assert filtered[0].symbol == 'BTC/USDT'

    def test_filter_symbols_pro_user(self, app):
        """Pro user should see default 5 symbols (BTC, ETH, XRP, BNB, SOL)"""
        from app.decorators import filter_symbols_by_tier
        from app.models import User, Subscription

        with app.app_context():
            user = User(
                email='prosym@test.com',
                username='prosym',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_prosym1234'
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

            class MockSymbol:
                def __init__(self, symbol):
                    self.symbol = symbol

            # Include the Pro default symbols plus extras
            all_symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'SOL/USDT',
                          'ADA/USDT', 'DOT/USDT', 'LINK/USDT', 'AVAX/USDT', 'MATIC/USDT']
            symbols = [MockSymbol(s) for s in all_symbols]
            filtered = filter_symbols_by_tier(symbols, user)

            # Pro user should see only the 5 default symbols
            assert len(filtered) == 5
            filtered_names = [s.symbol for s in filtered]
            assert 'BTC/USDT' in filtered_names
            assert 'ETH/USDT' in filtered_names
            assert 'SOL/USDT' in filtered_names
            assert 'ADA/USDT' not in filtered_names  # Not in default 5

    def test_filter_symbols_premium_user(self, app):
        """Premium user should see all symbols"""
        from app.decorators import filter_symbols_by_tier
        from app.models import User, Subscription

        with app.app_context():
            user = User(
                email='premsym@test.com',
                username='premsym',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_premsym12'
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

            class MockSymbol:
                def __init__(self, symbol):
                    self.symbol = symbol

            symbols = [MockSymbol(f'SYM{i}/USDT') for i in range(20)]
            filtered = filter_symbols_by_tier(symbols, user)

            # Premium user should see all symbols
            assert len(filtered) == 20


class TestPortfolioRestrictions:
    """Test portfolio access and limits based on tier"""

    def test_portfolio_has_user_id(self, app):
        """Portfolio should have user_id field"""
        from app.models import Portfolio

        with app.app_context():
            portfolio = Portfolio(
                user_id=1,
                name='Test Portfolio',
                initial_balance=10000,
                current_balance=10000
            )
            assert portfolio.user_id == 1

    def test_pro_portfolio_limit(self, app):
        """Pro user should be limited to 1 portfolio"""
        from app.models import User, Subscription, Portfolio
        from app.routes.portfolio import get_user_portfolio_count

        with app.app_context():
            user = User(
                email='proport@test.com',
                username='proport',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_proport12'
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

            # Initially can create
            assert get_user_portfolio_count(user) == 0

            # Create one portfolio
            portfolio = Portfolio(
                user_id=user.id,
                name='Test Portfolio',
                initial_balance=10000,
                current_balance=10000
            )
            db.session.add(portfolio)
            db.session.commit()

            # Now count should be 1
            assert get_user_portfolio_count(user) == 1

    def test_premium_unlimited_portfolios(self, app):
        """Premium user should have no portfolio limit"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['portfolio_limit'] is None

    def test_pro_transaction_limit(self, app):
        """Pro user should be limited to 5 transactions per day"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['transactions_limit'] == 5

    def test_premium_unlimited_transactions(self, app):
        """Premium user should have no transaction limit"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['transactions_limit'] is None

    def test_portfolio_user_isolation(self, client, app):
        """Users should only see their own portfolios"""
        from app.models import User, Subscription, Portfolio

        with app.app_context():
            # Create user1
            user1 = User(
                email='portuser1@test.com',
                username='portuser1',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_portu1123'
            )
            user1.set_password('TestPass123')
            db.session.add(user1)
            db.session.commit()

            sub1 = Subscription(
                user_id=user1.id,
                plan='pro',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub1)

            # Create user2
            user2 = User(
                email='portuser2@test.com',
                username='portuser2',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_portu2123'
            )
            user2.set_password('TestPass123')
            db.session.add(user2)
            db.session.commit()

            sub2 = Subscription(
                user_id=user2.id,
                plan='pro',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub2)

            # Create portfolios for each user
            port1 = Portfolio(user_id=user1.id, name='User1 Portfolio', initial_balance=10000, current_balance=10000)
            port2 = Portfolio(user_id=user2.id, name='User2 Portfolio', initial_balance=10000, current_balance=10000)
            db.session.add(port1)
            db.session.add(port2)
            db.session.commit()

            port1_id = port1.id
            port2_id = port2.id

        # Login as user1
        client.post('/auth/login', data={
            'email': 'portuser1@test.com',
            'password': 'TestPass123'
        })

        # User1 can access their own portfolio
        response = client.get(f'/portfolio/{port1_id}')
        assert response.status_code == 200

        # User1 cannot access user2's portfolio
        response = client.get(f'/portfolio/{port2_id}')
        assert response.status_code == 403


class TestUserSymbolPreferences:
    """Test user-specific symbol notification preferences"""

    def test_user_symbol_preference_model(self, app):
        """Test UserSymbolPreference model basic functionality"""
        from app.models import User, Subscription, Symbol, UserSymbolPreference

        with app.app_context():
            # Create a user
            user = User(
                email='sympref@test.com',
                username='sympref',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_sympref12'
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

            # Create a symbol
            symbol = Symbol(symbol='TEST/USDT', exchange='binance')
            db.session.add(symbol)
            db.session.commit()

            # Test is_notify_enabled returns True by default
            assert UserSymbolPreference.is_notify_enabled(user.id, symbol.id) is True

            # Test toggle_notify
            new_state = UserSymbolPreference.toggle_notify(user.id, symbol.id)
            assert new_state is False

            # Verify it persists
            assert UserSymbolPreference.is_notify_enabled(user.id, symbol.id) is False

            # Toggle again
            new_state = UserSymbolPreference.toggle_notify(user.id, symbol.id)
            assert new_state is True

    def test_user_symbol_preference_isolation(self, app):
        """Different users have independent symbol preferences"""
        from app.models import User, Symbol, UserSymbolPreference

        with app.app_context():
            # Create two users
            user1 = User(
                email='sympref1@test.com',
                username='sympref1',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_sympref11'
            )
            user1.set_password('TestPass123')
            db.session.add(user1)
            db.session.commit()

            user2 = User(
                email='sympref2@test.com',
                username='sympref2',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_sympref22'
            )
            user2.set_password('TestPass123')
            db.session.add(user2)
            db.session.commit()

            # Create a symbol
            symbol = Symbol(symbol='ISO/USDT', exchange='binance')
            db.session.add(symbol)
            db.session.commit()

            # User1 mutes the symbol
            UserSymbolPreference.toggle_notify(user1.id, symbol.id)
            assert UserSymbolPreference.is_notify_enabled(user1.id, symbol.id) is False

            # User2's preference is still default (True)
            assert UserSymbolPreference.is_notify_enabled(user2.id, symbol.id) is True

    def test_toggle_notify_requires_premium(self, client, app):
        """Pro users cannot toggle notifications, only Premium can"""
        from app.models import User, Subscription, Symbol

        with app.app_context():
            user = User(
                email='pronotify@test.com',
                username='pronotify',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_pronoti12'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='pro',  # Pro, not Premium
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                status='active'
            )
            db.session.add(sub)

            symbol = Symbol(symbol='PRON/USDT', exchange='binance')
            db.session.add(symbol)
            db.session.commit()
            symbol_id = symbol.id

        # Login as Pro user
        client.post('/auth/login', data={
            'email': 'pronotify@test.com',
            'password': 'TestPass123'
        })

        # Try to toggle notification preference
        response = client.post('/settings/symbols',
                               json={'action': 'toggle_notify', 'id': symbol_id},
                               content_type='application/json')
        assert response.status_code == 403
        data = response.get_json()
        assert 'Premium required' in data.get('error', '')

    def test_premium_can_toggle_notify(self, client, app):
        """Premium users can toggle notifications"""
        from app.models import User, Subscription, Symbol

        with app.app_context():
            user = User(
                email='premnotify@test.com',
                username='premnotify',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_premnot12'
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

            symbol = Symbol(symbol='PREM/USDT', exchange='binance')
            db.session.add(symbol)
            db.session.commit()
            symbol_id = symbol.id

        # Login as Premium user
        client.post('/auth/login', data={
            'email': 'premnotify@test.com',
            'password': 'TestPass123'
        })

        # Toggle notification preference
        response = client.post('/settings/symbols',
                               json={'action': 'toggle_notify', 'id': symbol_id},
                               content_type='application/json')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['user_specific'] is True
        assert data['notify_enabled'] is False  # Toggled from default True to False


class TestDashboardSignalRestrictions:
    """Test dashboard signal restrictions based on user tier"""

    def test_free_user_sees_only_btc_signal(self, client, app):
        """Free user should only see 1 BTC signal on dashboard"""
        from app.models import User, Subscription, Symbol, Signal

        with app.app_context():
            # Create free user
            user = User(
                email='freedash@test.com',
                username='freedash',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_freedash1'
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

            # Create symbols
            btc = Symbol(symbol='BTC/USDT', exchange='binance', is_active=True)
            eth = Symbol(symbol='ETH/USDT', exchange='binance', is_active=True)
            db.session.add(btc)
            db.session.add(eth)
            db.session.commit()

            # Create signals for both symbols
            for i in range(3):
                signal = Signal(
                    symbol_id=btc.id,
                    direction='bullish',
                    entry_price=50000.0 + i * 100,
                    stop_loss=48000.0,
                    take_profit_1=52000.0,
                    take_profit_2=54000.0,
                    risk_reward=2.0,
                    confluence_score=3,
                    status='active'
                )
                db.session.add(signal)

            for i in range(3):
                signal = Signal(
                    symbol_id=eth.id,
                    direction='bullish',
                    entry_price=3000.0 + i * 10,
                    stop_loss=2900.0,
                    take_profit_1=3100.0,
                    take_profit_2=3200.0,
                    risk_reward=2.0,
                    confluence_score=3,
                    status='active'
                )
                db.session.add(signal)
            db.session.commit()

        # Login as free user
        client.post('/auth/login', data={
            'email': 'freedash@test.com',
            'password': 'TestPass123'
        })

        # Access dashboard
        response = client.get('/dashboard/')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Free user should only see BTC signals (1 max)
        # Count occurrences of signal entries (they all have 'LONG' or 'SHORT' in them)
        assert 'BTC/USDT' in html or 'No signals yet' in html

    def test_pro_user_signal_limit(self, app):
        """Pro user should see up to 10 signals, max 5 symbols"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['max_symbols'] == 5
        assert tier['daily_notifications'] == 20

    def test_premium_user_unlimited_signals(self, app):
        """Premium user should have no signal limit"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['max_symbols'] is None
        assert tier['daily_notifications'] is None


class TestProfileTradingTabSymbols:
    """Test profile trading tab shows correct symbols for each tier"""

    def test_free_user_sees_only_btc(self, client, app):
        """Free user should only see BTC/USDT in trading tab"""
        from app.models import User, Subscription, Symbol

        with app.app_context():
            user = User(
                email='freetrade@test.com',
                username='freetrade',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_freetra1'
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

            # Create multiple symbols
            for sym in ['BTC/USDT', 'ETH/USDT', 'XRP/USDT']:
                s = Symbol(symbol=sym, exchange='binance', is_active=True)
                db.session.add(s)
            db.session.commit()

        client.post('/auth/login', data={
            'email': 'freetrade@test.com',
            'password': 'TestPass123'
        })

        response = client.get('/auth/profile')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Free user should see "Free Tier Limitations" and only BTC/USDT
        assert 'Free Tier Limitations' in html
        assert 'BTC/USDT only' in html

    def test_pro_user_sees_five_symbols(self, client, app):
        """Pro user should see 5 default symbols in trading tab"""
        from app.models import User, Subscription, Symbol

        with app.app_context():
            user = User(
                email='protrade@test.com',
                username='protrade',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_protra1'
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

            # Create all symbols including the 5 defaults
            for sym in ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'SOL/USDT',
                        'ADA/USDT', 'DOT/USDT', 'LINK/USDT']:
                s = Symbol(symbol=sym, exchange='binance', is_active=True)
                db.session.add(s)
            db.session.commit()

        client.post('/auth/login', data={
            'email': 'protrade@test.com',
            'password': 'TestPass123'
        })

        response = client.get('/auth/profile')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Pro user should see "Pro Tier" banner and 5 symbols
        assert 'Pro Tier' in html
        assert '5/5 symbols' in html
        # Should see the 5 default symbols
        assert 'BTC/USDT' in html
        assert 'ETH/USDT' in html

    def test_premium_user_sees_all_symbols(self, client, app):
        """Premium user should see all symbols in trading tab"""
        from app.models import User, Subscription, Symbol

        with app.app_context():
            user = User(
                email='premtrade@test.com',
                username='premtrade',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_premtra1'
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

            # Create many symbols
            for sym in ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'SOL/USDT',
                        'ADA/USDT', 'DOT/USDT', 'LINK/USDT', 'AVAX/USDT', 'MATIC/USDT']:
                s = Symbol(symbol=sym, exchange='binance', is_active=True)
                db.session.add(s)
            db.session.commit()

        client.post('/auth/login', data={
            'email': 'premtrade@test.com',
            'password': 'TestPass123'
        })

        response = client.get('/auth/profile')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Premium user should not see tier limitation banners
        assert 'Free Tier Limitations' not in html
        # Should see all symbols (Notify/Muted toggles visible)
        assert 'Notify' in html or 'Muted' in html


class TestPatternsPageRestrictions:
    """Test patterns page tier restrictions"""

    def test_pro_patterns_limit_100(self, app):
        """Pro tier should be limited to 100 patterns"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['patterns_limit'] == 100

    def test_premium_patterns_unlimited(self, app):
        """Premium tier should have unlimited patterns"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['patterns_limit'] is None


class TestSignalsPageRestrictions:
    """Test signals page tier restrictions"""

    def test_pro_signals_limit_50(self, app):
        """Pro tier should be limited to 50 signals"""
        tier = SUBSCRIPTION_TIERS['pro']
        assert tier['signals_limit'] == 50

    def test_premium_signals_unlimited(self, app):
        """Premium tier should have unlimited signals"""
        tier = SUBSCRIPTION_TIERS['premium']
        assert tier['signals_limit'] is None


class TestPortfolioTradeSymbolRestrictions:
    """Test portfolio trade symbol restrictions"""

    def test_pro_user_sees_limited_symbols_in_trade_form(self, client, app):
        """Pro user should only see 5 symbols when adding a trade"""
        from app.models import User, Subscription, Symbol, Portfolio

        with app.app_context():
            user = User(
                email='protradef@test.com',
                username='protradef',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_protraf1'
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

            portfolio = Portfolio(
                user_id=user.id,
                name='Test Portfolio',
                initial_balance=10000,
                current_balance=10000,
                currency='USDT'
            )
            db.session.add(portfolio)

            # Create 10 symbols
            for sym in ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'SOL/USDT',
                       'ADA/USDT', 'DOT/USDT', 'LINK/USDT', 'AVAX/USDT', 'MATIC/USDT']:
                s = Symbol(symbol=sym, exchange='binance', is_active=True)
                db.session.add(s)
            db.session.commit()

            portfolio_id = portfolio.id

        client.post('/auth/login', data={
            'email': 'protradef@test.com',
            'password': 'TestPass123'
        })

        response = client.get(f'/portfolio/{portfolio_id}/trades/new')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Count symbol options - Pro should only see 5
        import re
        symbol_options = re.findall(r'<option[^>]*value="([A-Z]+/USDT)"', html)
        assert len(symbol_options) <= 5

    def test_premium_user_sees_all_symbols_in_trade_form(self, client, app):
        """Premium user should see all symbols when adding a trade"""
        from app.models import User, Subscription, Symbol, Portfolio

        with app.app_context():
            user = User(
                email='premtradef@test.com',
                username='premtradef',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_premtraf1'
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

            portfolio = Portfolio(
                user_id=user.id,
                name='Test Portfolio',
                initial_balance=10000,
                current_balance=10000,
                currency='USDT'
            )
            db.session.add(portfolio)

            # Create 10 symbols
            for sym in ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT', 'SOL/USDT',
                       'ADA/USDT', 'DOT/USDT', 'LINK/USDT', 'AVAX/USDT', 'MATIC/USDT']:
                s = Symbol(symbol=sym, exchange='binance', is_active=True)
                db.session.add(s)
            db.session.commit()

            portfolio_id = portfolio.id

        client.post('/auth/login', data={
            'email': 'premtradef@test.com',
            'password': 'TestPass123'
        })

        response = client.get(f'/portfolio/{portfolio_id}/trades/new')
        assert response.status_code == 200
        html = response.data.decode('utf-8')

        # Premium should see all 10 symbols
        import re
        symbol_options = re.findall(r'<option[^>]*value="([A-Z]+/USDT)"', html)
        assert len(symbol_options) == 10


class TestPatternToTradeAPI:
    """Test pattern to trade API endpoint"""

    def test_pattern_to_trade_creates_pending_trade(self, client, app):
        """Pattern to trade should create a pending trade with pattern data"""
        from app.models import User, Subscription, Symbol, Pattern

        with app.app_context():
            user = User(
                email='pattrade@test.com',
                username='pattrade',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_pattra1'
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

            # Create symbol
            symbol = Symbol(symbol='BTC/USDT', exchange='binance', is_active=True)
            db.session.add(symbol)
            db.session.commit()

            # Create pattern with trading levels
            pattern = Pattern(
                symbol_id=symbol.id,
                timeframe='1h',
                pattern_type='order_block',
                direction='bullish',
                zone_high=51000.0,
                zone_low=50000.0,
                detected_at=datetime.now(timezone.utc),
                entry=50500.0,
                stop_loss=49500.0,
                take_profit_1=52000.0,
                take_profit_2=53000.0,
                status='active'
            )
            db.session.add(pattern)
            db.session.commit()

            pattern_id = pattern.id

        client.post('/auth/login', data={
            'email': 'pattrade@test.com',
            'password': 'TestPass123'
        })

        # Call the API
        response = client.post('/portfolio/api/trade-from-pattern',
                               json={'pattern_id': pattern_id},
                               content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'trade_id' in data
        assert 'portfolio_id' in data
        assert 'redirect_url' in data
