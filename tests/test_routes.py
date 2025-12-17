"""
Tests for UI Routes
Tests dashboard, stats, logs, patterns, signals, backtest routes
"""
import pytest
from unittest.mock import patch
from app.models import Signal, Log
from app import db
from tests.conftest import login_user


class TestDashboardRoutes:
    """Tests for dashboard routes (requires login)"""

    def test_dashboard_index(self, client, app, sample_user, sample_symbol):
        """Test dashboard index page loads for authenticated user"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/dashboard/')
        assert response.status_code == 200
        assert b'BTC/USDT' in response.data or b'Dashboard' in response.data

    def test_dashboard_redirects_unauthenticated(self, client, app, sample_symbol):
        """Test dashboard redirects unauthenticated users"""
        response = client.get('/dashboard/')
        assert response.status_code == 302  # Redirect to login

    def test_landing_page_public(self, client, app, sample_symbol):
        """Test landing page is public (no login required)"""
        response = client.get('/')
        assert response.status_code == 200  # Landing page is public

    def test_dashboard_with_patterns(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test dashboard shows patterns"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/dashboard/')
        assert response.status_code == 200

    def test_analytics_page(self, client, app, user_lifetime, sample_symbol):
        """Test analytics page loads for authenticated Premium user"""
        login_user(client, 'lifetime@example.com', 'TestPass123')
        response = client.get('/dashboard/analytics')
        assert response.status_code == 200

    def test_analytics_with_data(self, client, app, user_lifetime, sample_symbol, sample_pattern):
        """Test analytics with patterns data"""
        login_user(client, 'lifetime@example.com', 'TestPass123')
        response = client.get('/dashboard/analytics')
        assert response.status_code == 200

    def test_analytics_accessible_to_pro(self, client, app, sample_user):
        """Test analytics is accessible to Pro users"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/dashboard/analytics')
        assert response.status_code == 200  # Pro users have analytics access

    def test_analytics_redirects_free_users(self, client, app):
        """Test analytics redirects free tier users"""
        from app.models import User, Subscription
        from datetime import datetime, timezone

        # Create a free user
        with app.app_context():
            user = User(
                email='free@example.com',
                username='freeuser',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_free123456789'
            )
            user.set_password('FreePass123')
            db.session.add(user)
            db.session.commit()

            # Add free subscription
            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                expires_at=None,  # Free never expires
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

        login_user(client, 'free@example.com', 'FreePass123')
        response = client.get('/dashboard/analytics')
        assert response.status_code == 302  # Redirect to upgrade page


class TestStatsRoutes:
    """Tests for stats routes (requires admin)"""

    def test_stats_index_empty(self, client, app, admin_user):
        """Test stats page with no data"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/stats/')
        assert response.status_code == 200

    def test_stats_index_with_symbol(self, client, app, admin_user, sample_symbol):
        """Test stats page renders (data loaded via AJAX)"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/stats/')
        assert response.status_code == 200
        # Page loads skeleton, data fetched via /stats/api
        assert b'Database Statistics' in response.data

    def test_stats_api(self, client, app, admin_user, sample_symbol):
        """Test stats API returns data"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/stats/api')
        assert response.status_code == 200
        data = response.get_json()
        # API should return stats structure (may be empty if cache not populated)
        assert 'symbols_count' in data or 'error' in data

    def test_stats_with_candles(self, client, app, admin_user, sample_candles_bullish_fvg):
        """Test stats page shows candle counts"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/stats/')
        assert response.status_code == 200

    def test_stats_shows_patterns(self, client, app, admin_user, sample_symbol, sample_pattern):
        """Test stats page shows pattern counts"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/stats/')
        assert response.status_code == 200

    def test_stats_redirects_non_admin(self, client, app, sample_user):
        """Test stats redirects non-admin users"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/stats/')
        assert response.status_code == 302  # Redirect to dashboard


class TestLogsRoutes:
    """Tests for logs routes (requires admin)"""

    def test_logs_index(self, client, app, admin_user):
        """Test logs page loads for admin user"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/logs/')
        assert response.status_code == 200

    def test_logs_redirects_non_admin(self, client, app, sample_user):
        """Test logs redirects non-admin users"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/logs/')
        assert response.status_code == 302  # Redirect to dashboard

    def test_logs_api_no_filter(self, client, app, admin_user):
        """Test logs API without filters"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/logs/api/logs')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data
        assert 'count' in data

    def test_logs_api_with_category_filter(self, client, app, admin_user):
        """Test logs API with category filter"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        with app.app_context():
            log = Log(category='FETCH', level='INFO', message='Test log')
            db.session.add(log)
            db.session.commit()

        response = client.get('/logs/api/logs?category=FETCH')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data

    def test_logs_api_with_level_filter(self, client, app, admin_user):
        """Test logs API with level filter"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        with app.app_context():
            log = Log(category='SCAN', level='ERROR', message='Error log')
            db.session.add(log)
            db.session.commit()

        response = client.get('/logs/api/logs?level=ERROR')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data

    def test_logs_api_with_limit(self, client, app, admin_user):
        """Test logs API with limit"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/logs/api/logs?limit=10')
        assert response.status_code == 200
        data = response.get_json()
        assert data['limit'] == 10

    def test_logs_stats_api(self, client, app, admin_user):
        """Test logs stats API"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/logs/api/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)


class TestPatternsRoutes:
    """Tests for patterns routes (requires Pro+ subscription)"""

    def test_patterns_index(self, client, app, sample_user):
        """Test patterns page loads for authenticated Pro user"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/')
        assert response.status_code == 200

    def test_patterns_index_with_data(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test patterns page with pattern data"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/')
        assert response.status_code == 200

    def test_patterns_filter_by_symbol(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test patterns filtered by symbol"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/?symbol=BTC/USDT')
        assert response.status_code == 200

    def test_patterns_filter_by_timeframe(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test patterns filtered by timeframe"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/?timeframe=1h')
        assert response.status_code == 200

    def test_patterns_filter_by_status(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test patterns filtered by status"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/?status=active')
        assert response.status_code == 200

    def test_patterns_chart_valid_symbol(self, client, app, sample_user, sample_candles_bullish_fvg):
        """Test chart data for valid symbol (requires authentication)"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/chart/BTC-USDT/1h')
        assert response.status_code == 200
        data = response.get_json()
        assert 'candles' in data
        assert 'patterns' in data

    def test_patterns_chart_invalid_symbol(self, client, app, sample_user):
        """Test chart data for invalid symbol (requires authentication)"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/patterns/chart/INVALID-PAIR/1h')
        assert response.status_code == 404

    def test_patterns_chart_unauthenticated(self, client, app, sample_candles_bullish_fvg):
        """Test chart data redirects unauthenticated users"""
        response = client.get('/patterns/chart/BTC-USDT/1h')
        assert response.status_code == 302  # Redirects to login


class TestSignalsRoutes:
    """Tests for signals routes (requires Pro+ subscription)"""

    def test_signals_index(self, client, app, sample_user):
        """Test signals page loads for authenticated Pro user"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/signals/')
        assert response.status_code == 200

    def test_signals_with_data(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test signals page with signal data"""
        login_user(client, 'test@example.com', 'TestPass123')
        with app.app_context():
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

        response = client.get('/signals/')
        assert response.status_code == 200

    def test_signals_filter_by_status(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test signals filtered by status"""
        login_user(client, 'test@example.com', 'TestPass123')
        with app.app_context():
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
                status='notified'
            )
            db.session.add(signal)
            db.session.commit()

        response = client.get('/signals/?status=notified')
        assert response.status_code == 200

    def test_signals_filter_by_direction(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test signals filtered by direction"""
        login_user(client, 'test@example.com', 'TestPass123')
        with app.app_context():
            signal = Signal(
                symbol_id=sample_symbol,
                direction='short',
                entry_price=100.0,
                stop_loss=105.0,
                take_profit_1=90.0,
                take_profit_2=80.0,
                take_profit_3=70.0,
                risk_reward=3.0,
                confluence_score=3,
                pattern_id=sample_pattern,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()

        response = client.get('/signals/?direction=short')
        assert response.status_code == 200

    def test_signal_detail(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test signal detail page"""
        login_user(client, 'test@example.com', 'TestPass123')
        with app.app_context():
            signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=95000.0,
                stop_loss=93000.0,
                take_profit_1=97000.0,
                take_profit_2=99000.0,
                take_profit_3=101000.0,
                risk_reward=3.0,
                confluence_score=3,
                pattern_id=sample_pattern,
                status='pending'
            )
            db.session.add(signal)
            db.session.commit()
            signal_id = signal.id

        response = client.get(f'/signals/{signal_id}')
        assert response.status_code == 200
        assert b'Signal #' in response.data

    def test_signal_detail_not_found(self, client, app, sample_user):
        """Test signal detail for non-existent signal"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/signals/99999')
        assert response.status_code == 404

    def test_signal_update_status(self, client, app, sample_user, sample_symbol, sample_pattern):
        """Test updating signal status"""
        login_user(client, 'test@example.com', 'TestPass123')
        with app.app_context():
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
            signal_id = signal.id

        response = client.post(
            f'/signals/{signal_id}/status',
            json={'status': 'filled'},
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['signal']['status'] == 'filled'


class TestBacktestRoutes:
    """Tests for backtest routes (requires Premium subscription)"""

    def test_backtest_index(self, client, app, user_lifetime):
        """Test backtest page loads for authenticated Premium user"""
        login_user(client, 'lifetime@example.com', 'TestPass123')
        response = client.get('/backtest/')
        assert response.status_code == 200

    def test_backtest_index_with_symbols(self, client, app, user_lifetime, sample_symbol):
        """Test backtest page with symbols"""
        login_user(client, 'lifetime@example.com', 'TestPass123')
        response = client.get('/backtest/')
        assert response.status_code == 200

    def test_backtest_detail_not_found(self, client, app):
        """Test backtest detail for non-existent backtest"""
        response = client.get('/backtest/99999')
        assert response.status_code == 404


class TestSettingsRoutes:
    """Tests for settings routes (requires subscription)"""

    def test_settings_index(self, client, app, sample_user):
        """Test settings page redirects to profile for authenticated user"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/settings/')
        # Settings now redirects to unified profile page
        assert response.status_code == 302
        assert '/profile' in response.headers['Location']

    def test_settings_save(self, client, app, sample_user):
        """Test saving settings"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/settings/save',
            data={'ntfy_topic': 'test-topic', 'ntfy_priority': '3'},
            content_type='application/x-www-form-urlencoded'
        )
        # Should redirect back to settings page
        assert response.status_code in [200, 302]

    def test_settings_add_symbol(self, client, app, sample_user):
        """Test adding a symbol (requires login)"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/settings/symbols',
            json={'action': 'add', 'symbol': 'ETH/USDT'},
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_settings_add_invalid_symbol(self, client, app, sample_user):
        """Test adding invalid symbol format (requires login)"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/settings/symbols',
            json={'action': 'add', 'symbol': 'invalid'},
            content_type='application/json'
        )
        # Returns 400 for invalid symbol format
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False

    def test_settings_toggle_symbol(self, client, app, sample_user, sample_symbol):
        """Test toggling symbol active status (requires login)"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/settings/symbols',
            json={'action': 'toggle', 'id': sample_symbol},
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_settings_test_notification(self, client, app, sample_user):
        """Test test notification endpoint"""
        login_user(client, 'test@example.com', 'TestPass123')
        with patch('app.services.notifier.send_notification') as mock_send:
            mock_send.return_value = True
            response = client.post('/settings/test-notification')
            assert response.status_code == 200
            data = response.get_json()
            assert 'success' in data


class TestPortfolioInputValidation:
    """Tests for portfolio input validation (requires Pro+ subscription)"""

    def test_create_portfolio_valid(self, client, app, sample_user):
        """Test creating portfolio with valid data"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/portfolio/create',
            data={'name': 'Test Portfolio', 'initial_balance': '10000'},
            follow_redirects=False
        )
        # Should redirect on success
        assert response.status_code == 302

    def test_create_portfolio_missing_name(self, client, app, sample_user):
        """Test creating portfolio without name fails validation"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/portfolio/create',
            data={'initial_balance': '10000'},
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Portfolio name is required' in response.data

    def test_create_portfolio_name_too_long(self, client, app, sample_user):
        """Test creating portfolio with name > 100 chars fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        long_name = 'A' * 101
        response = client.post(
            '/portfolio/create',
            data={'name': long_name, 'initial_balance': '10000'},
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be less than 100 characters' in response.data

    def test_create_portfolio_negative_balance(self, client, app, sample_user):
        """Test creating portfolio with negative balance fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/portfolio/create',
            data={'name': 'Test', 'initial_balance': '-100'},
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be at least' in response.data

    def test_create_portfolio_balance_too_high(self, client, app, sample_user):
        """Test creating portfolio with balance > 1 billion fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/portfolio/create',
            data={'name': 'Test', 'initial_balance': '2000000000'},
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be less than' in response.data

    def test_create_portfolio_invalid_balance(self, client, app, sample_user):
        """Test creating portfolio with non-numeric balance fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            '/portfolio/create',
            data={'name': 'Test', 'initial_balance': 'not_a_number'},
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be a valid number' in response.data


class TestTradeInputValidation:
    """Tests for trade input validation (requires Pro+ subscription)"""

    @pytest.fixture
    def sample_portfolio(self, app, sample_user):
        """Create a sample portfolio for testing"""
        from app.models import Portfolio
        with app.app_context():
            portfolio = Portfolio(
                name='Test Portfolio',
                user_id=sample_user,  # Link to the sample_user for ownership validation
                initial_balance=10000,
                current_balance=10000,
                currency='USDT'
            )
            db.session.add(portfolio)
            db.session.commit()
            return portfolio.id

    def test_create_trade_valid(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with valid data"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BTC/USDT',
                'entry_price': '50000',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=False
        )
        # Should redirect on success
        assert response.status_code == 302

    def test_create_trade_missing_symbol(self, client, app, sample_user, sample_portfolio):
        """Test creating trade without symbol fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'entry_price': '50000',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Symbol is required' in response.data

    def test_create_trade_symbol_too_short(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with symbol < 3 chars fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BT',
                'entry_price': '50000',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be at least 3 characters' in response.data

    def test_create_trade_symbol_too_long(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with symbol > 20 chars fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'A' * 21,
                'entry_price': '50000',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'must be less than 20 characters' in response.data

    def test_create_trade_negative_entry_price(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with negative entry_price fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BTC/USDT',
                'entry_price': '-100',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Entry price' in response.data and b'must be at least' in response.data

    def test_create_trade_zero_entry_quantity(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with zero entry_quantity fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BTC/USDT',
                'entry_price': '50000',
                'entry_quantity': '0',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Entry quantity' in response.data and b'must be at least' in response.data

    def test_create_trade_invalid_entry_price(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with non-numeric entry_price fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BTC/USDT',
                'entry_price': 'not_a_number',
                'entry_quantity': '0.1',
                'direction': 'long'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Entry price' in response.data and b'must be a valid number' in response.data

    def test_create_trade_risk_percent_over_100(self, client, app, sample_user, sample_portfolio):
        """Test creating trade with risk_percent > 100 fails"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.post(
            f'/portfolio/{sample_portfolio}/trades/new',
            data={
                'symbol': 'BTC/USDT',
                'entry_price': '50000',
                'entry_quantity': '0.1',
                'direction': 'long',
                'risk_percent': '150'
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Risk percent' in response.data and b'must be less than' in response.data
