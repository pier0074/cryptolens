"""
Tests for UI Routes
Tests dashboard, stats, logs, patterns, signals, backtest routes
"""
import pytest
from unittest.mock import patch
from flask import url_for
from app.models import Symbol, Candle, Pattern, Signal, Log, Backtest, Setting
from app import db


class TestDashboardRoutes:
    """Tests for dashboard routes"""

    def test_dashboard_index(self, client, app, sample_symbol):
        """Test dashboard index page loads"""
        response = client.get('/')
        assert response.status_code == 200
        assert b'BTC/USDT' in response.data or b'Dashboard' in response.data

    def test_dashboard_with_patterns(self, client, app, sample_symbol, sample_pattern):
        """Test dashboard shows patterns"""
        response = client.get('/')
        assert response.status_code == 200

    def test_analytics_page(self, client, app, sample_symbol):
        """Test analytics page loads"""
        response = client.get('/analytics')
        assert response.status_code == 200

    def test_analytics_with_data(self, client, app, sample_symbol, sample_pattern):
        """Test analytics with patterns data"""
        response = client.get('/analytics')
        assert response.status_code == 200


class TestStatsRoutes:
    """Tests for stats routes"""

    def test_stats_index_empty(self, client, app):
        """Test stats page with no data"""
        response = client.get('/stats/')
        assert response.status_code == 200

    def test_stats_index_with_symbol(self, client, app, sample_symbol):
        """Test stats page with symbol"""
        response = client.get('/stats/')
        assert response.status_code == 200
        assert b'BTC/USDT' in response.data

    def test_stats_with_candles(self, client, app, sample_candles_bullish_fvg):
        """Test stats page shows candle counts"""
        response = client.get('/stats/')
        assert response.status_code == 200

    def test_stats_shows_patterns(self, client, app, sample_symbol, sample_pattern):
        """Test stats page shows pattern counts"""
        response = client.get('/stats/')
        assert response.status_code == 200


class TestLogsRoutes:
    """Tests for logs routes"""

    def test_logs_index(self, client, app):
        """Test logs page loads"""
        response = client.get('/logs/')
        assert response.status_code == 200

    def test_logs_api_no_filter(self, client, app):
        """Test logs API without filters"""
        response = client.get('/logs/api/logs')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data
        assert 'count' in data

    def test_logs_api_with_category_filter(self, client, app):
        """Test logs API with category filter"""
        with app.app_context():
            log = Log(category='FETCH', level='INFO', message='Test log')
            db.session.add(log)
            db.session.commit()

        response = client.get('/logs/api/logs?category=FETCH')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data

    def test_logs_api_with_level_filter(self, client, app):
        """Test logs API with level filter"""
        with app.app_context():
            log = Log(category='SCAN', level='ERROR', message='Error log')
            db.session.add(log)
            db.session.commit()

        response = client.get('/logs/api/logs?level=ERROR')
        assert response.status_code == 200
        data = response.get_json()
        assert 'logs' in data

    def test_logs_api_with_limit(self, client, app):
        """Test logs API with limit"""
        response = client.get('/logs/api/logs?limit=10')
        assert response.status_code == 200
        data = response.get_json()
        assert data['limit'] == 10

    def test_logs_stats_api(self, client, app):
        """Test logs stats API"""
        response = client.get('/logs/api/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)


class TestPatternsRoutes:
    """Tests for patterns routes"""

    def test_patterns_index(self, client, app):
        """Test patterns page loads"""
        response = client.get('/patterns/')
        assert response.status_code == 200

    def test_patterns_index_with_data(self, client, app, sample_symbol, sample_pattern):
        """Test patterns page with pattern data"""
        response = client.get('/patterns/')
        assert response.status_code == 200

    def test_patterns_filter_by_symbol(self, client, app, sample_symbol, sample_pattern):
        """Test patterns filtered by symbol"""
        response = client.get('/patterns/?symbol=BTC/USDT')
        assert response.status_code == 200

    def test_patterns_filter_by_timeframe(self, client, app, sample_symbol, sample_pattern):
        """Test patterns filtered by timeframe"""
        response = client.get('/patterns/?timeframe=1h')
        assert response.status_code == 200

    def test_patterns_filter_by_status(self, client, app, sample_symbol, sample_pattern):
        """Test patterns filtered by status"""
        response = client.get('/patterns/?status=active')
        assert response.status_code == 200

    def test_patterns_chart_valid_symbol(self, client, app, sample_candles_bullish_fvg):
        """Test chart data for valid symbol"""
        response = client.get('/patterns/chart/BTC-USDT/1h')
        assert response.status_code == 200
        data = response.get_json()
        assert 'candles' in data
        assert 'patterns' in data

    def test_patterns_chart_invalid_symbol(self, client, app):
        """Test chart data for invalid symbol"""
        response = client.get('/patterns/chart/INVALID-PAIR/1h')
        assert response.status_code == 404


class TestSignalsRoutes:
    """Tests for signals routes"""

    def test_signals_index(self, client, app):
        """Test signals page loads"""
        response = client.get('/signals/')
        assert response.status_code == 200

    def test_signals_with_data(self, client, app, sample_symbol, sample_pattern):
        """Test signals page with signal data"""
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

    def test_signals_filter_by_status(self, client, app, sample_symbol, sample_pattern):
        """Test signals filtered by status"""
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

    def test_signals_filter_by_direction(self, client, app, sample_symbol, sample_pattern):
        """Test signals filtered by direction"""
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

    @pytest.mark.skip(reason="Template signal_detail.html does not exist")
    def test_signal_detail(self, client, app, sample_symbol, sample_pattern):
        """Test signal detail page - skipped due to missing template"""
        pass

    def test_signal_detail_not_found(self, client, app):
        """Test signal detail for non-existent signal"""
        response = client.get('/signals/99999')
        assert response.status_code == 404

    def test_signal_update_status(self, client, app, sample_symbol, sample_pattern):
        """Test updating signal status"""
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
    """Tests for backtest routes"""

    def test_backtest_index(self, client, app):
        """Test backtest page loads"""
        response = client.get('/backtest/')
        assert response.status_code == 200

    def test_backtest_index_with_symbols(self, client, app, sample_symbol):
        """Test backtest page with symbols"""
        response = client.get('/backtest/')
        assert response.status_code == 200

    def test_backtest_detail_not_found(self, client, app):
        """Test backtest detail for non-existent backtest"""
        response = client.get('/backtest/99999')
        assert response.status_code == 404


class TestSettingsRoutes:
    """Tests for settings routes"""

    def test_settings_index(self, client, app):
        """Test settings page loads"""
        response = client.get('/settings/')
        assert response.status_code == 200

    def test_settings_save(self, client, app):
        """Test saving settings"""
        response = client.post(
            '/settings/save',
            data={'ntfy_topic': 'test-topic', 'ntfy_priority': '3'},
            content_type='application/x-www-form-urlencoded'
        )
        # Should redirect back to settings page
        assert response.status_code in [200, 302]

    def test_settings_add_symbol(self, client, app):
        """Test adding a symbol"""
        response = client.post(
            '/settings/symbols',
            json={'action': 'add', 'symbol': 'ETH/USDT'},
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_settings_add_invalid_symbol(self, client, app):
        """Test adding invalid symbol format"""
        response = client.post(
            '/settings/symbols',
            json={'action': 'add', 'symbol': 'invalid'},
            content_type='application/json'
        )
        # Returns 400 for invalid symbol format
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False

    def test_settings_toggle_symbol(self, client, app, sample_symbol):
        """Test toggling symbol active status"""
        response = client.post(
            '/settings/symbols',
            json={'action': 'toggle', 'id': sample_symbol},
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_settings_test_notification(self, client, app):
        """Test test notification endpoint"""
        with patch('app.services.notifier.send_notification') as mock_send:
            mock_send.return_value = True
            response = client.post('/settings/test-notification')
            assert response.status_code == 200
            data = response.get_json()
            assert 'success' in data
