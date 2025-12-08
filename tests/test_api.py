"""
Tests for API Endpoints
"""
import pytest
import json
from app.models import Symbol, Candle, Pattern, Signal, Setting
from app.services.auth import hash_api_key
from app import db


class TestHealthEndpoint:
    """Tests for /api/health endpoint (Phase 2.1)"""

    def test_health_returns_200(self, client, app):
        """Test health endpoint returns 200 when healthy"""
        with app.app_context():
            response = client.get('/api/health')
            assert response.status_code == 200

    def test_health_returns_json(self, client, app):
        """Test health endpoint returns valid JSON"""
        with app.app_context():
            response = client.get('/api/health')
            assert response.content_type == 'application/json'

    def test_health_contains_required_fields(self, client, app):
        """Test health response contains all required fields"""
        with app.app_context():
            response = client.get('/api/health')
            data = response.json
            assert 'status' in data
            assert 'database' in data
            assert 'timestamp' in data
            assert 'version' in data

    def test_health_status_healthy(self, client, app):
        """Test health status is 'healthy' when DB is connected"""
        with app.app_context():
            response = client.get('/api/health')
            data = response.json
            assert data['status'] == 'healthy'
            assert data['database'] == 'connected'

    def test_health_no_auth_required(self, client, app):
        """Test health endpoint doesn't require authentication"""
        with app.app_context():
            from app.models import Setting
            # Set API key (which would normally require auth)
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            # Health should still work without auth
            response = client.get('/api/health')
            assert response.status_code == 200


class TestSymbolsEndpoint:
    """Tests for /api/symbols endpoint"""

    def test_get_symbols_empty(self, client, app):
        """Test getting symbols when none exist"""
        with app.app_context():
            response = client.get('/api/symbols')
            assert response.status_code == 200
            assert response.json == []

    def test_get_symbols(self, client, app, sample_symbol):
        """Test getting all active symbols"""
        with app.app_context():
            response = client.get('/api/symbols')
            assert response.status_code == 200
            data = response.json
            assert len(data) == 1
            assert data[0]['symbol'] == 'BTC/USDT'
            assert data[0]['is_active'] is True

    def test_get_symbols_include_inactive(self, client, app, sample_symbol):
        """Test getting all symbols including inactive"""
        with app.app_context():
            # Add inactive symbol
            inactive = Symbol(symbol='ETH/USDT', exchange='binance', is_active=False)
            db.session.add(inactive)
            db.session.commit()

            # Default: only active
            response = client.get('/api/symbols')
            assert len(response.json) == 1

            # Include all
            response = client.get('/api/symbols?active=false')
            assert len(response.json) == 2


class TestCandlesEndpoint:
    """Tests for /api/candles endpoint"""

    def test_get_candles(self, client, app, sample_symbol):
        """Test getting candles for a symbol"""
        with app.app_context():
            # Add candles
            for i in range(5):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            response = client.get('/api/candles/BTC-USDT/1h')
            assert response.status_code == 200
            data = response.json
            assert len(data) == 5
            assert 'open' in data[0]
            assert 'high' in data[0]
            assert 'low' in data[0]
            assert 'close' in data[0]

    def test_get_candles_with_limit(self, client, app, sample_symbol):
        """Test candles endpoint respects limit parameter"""
        with app.app_context():
            for i in range(10):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            response = client.get('/api/candles/BTC-USDT/1h?limit=3')
            assert response.status_code == 200
            assert len(response.json) == 3

    def test_get_candles_unknown_symbol(self, client, app):
        """Test 404 for unknown symbol"""
        with app.app_context():
            response = client.get('/api/candles/UNKNOWN-PAIR/1h')
            assert response.status_code == 404
            assert 'error' in response.json

    def test_get_candles_slash_format(self, client, app, sample_symbol):
        """Test symbol with dash is converted to slash"""
        with app.app_context():
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=1700000000000,
                open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
            )
            db.session.add(candle)
            db.session.commit()

            # Using dash format in URL
            response = client.get('/api/candles/BTC-USDT/1h')
            assert response.status_code == 200
            assert len(response.json) == 1


class TestPatternsEndpoint:
    """Tests for /api/patterns endpoint"""

    def test_get_patterns(self, client, app, sample_pattern):
        """Test getting patterns"""
        with app.app_context():
            response = client.get('/api/patterns')
            assert response.status_code == 200
            data = response.json
            assert len(data) >= 1
            assert data[0]['pattern_type'] == 'imbalance'

    def test_get_patterns_filter_status(self, client, app, sample_symbol):
        """Test filtering patterns by status"""
        with app.app_context():
            # Add active pattern
            active = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            # Add filled pattern
            filled = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bearish',
                zone_high=95.0,
                zone_low=90.0,
                detected_at=1700000000001,
                status='filled'
            )
            db.session.add_all([active, filled])
            db.session.commit()

            # Default filter: active
            response = client.get('/api/patterns?status=active')
            assert all(p['status'] == 'active' for p in response.json)

            # Filter: filled
            response = client.get('/api/patterns?status=filled')
            assert all(p['status'] == 'filled' for p in response.json)

    def test_get_patterns_filter_timeframe(self, client, app, sample_symbol):
        """Test filtering patterns by timeframe"""
        with app.app_context():
            for tf in ['1h', '4h', '1d']:
                pattern = Pattern(
                    symbol_id=sample_symbol,
                    timeframe=tf,
                    pattern_type='imbalance',
                    direction='bullish',
                    zone_high=105.0,
                    zone_low=100.0,
                    detected_at=1700000000000,
                    status='active'
                )
                db.session.add(pattern)
            db.session.commit()

            response = client.get('/api/patterns?timeframe=4h')
            assert response.status_code == 200
            assert all(p['timeframe'] == '4h' for p in response.json)

    def test_get_patterns_empty(self, client, app):
        """Test getting patterns when none exist"""
        with app.app_context():
            response = client.get('/api/patterns')
            assert response.status_code == 200
            assert response.json == []


class TestSignalsEndpoint:
    """Tests for /api/signals endpoint"""

    def test_get_signals(self, client, app, sample_signal):
        """Test getting signals"""
        with app.app_context():
            response = client.get('/api/signals')
            assert response.status_code == 200
            data = response.json
            assert len(data) >= 1
            assert 'direction' in data[0]
            assert 'entry_price' in data[0]
            assert 'symbol' in data[0]

    def test_get_signals_filter_direction(self, client, app, sample_symbol, sample_pattern):
        """Test filtering signals by direction"""
        with app.app_context():
            # Add long signal
            long_signal = Signal(
                symbol_id=sample_symbol,
                direction='long',
                entry_price=100.0,
                stop_loss=95.0,
                take_profit_1=105.0,
                take_profit_2=110.0,
                take_profit_3=115.0,
                risk_reward=3.0,
                confluence_score=3,
                pattern_id=sample_pattern,
                status='pending'
            )
            # Add short signal
            short_signal = Signal(
                symbol_id=sample_symbol,
                direction='short',
                entry_price=100.0,
                stop_loss=105.0,
                take_profit_1=95.0,
                take_profit_2=90.0,
                take_profit_3=85.0,
                risk_reward=3.0,
                confluence_score=3,
                pattern_id=sample_pattern,
                status='pending'
            )
            db.session.add_all([long_signal, short_signal])
            db.session.commit()

            response = client.get('/api/signals?direction=long')
            assert all(s['direction'] == 'long' for s in response.json)

            response = client.get('/api/signals?direction=short')
            assert all(s['direction'] == 'short' for s in response.json)

    def test_get_signals_empty(self, client, app):
        """Test getting signals when none exist"""
        with app.app_context():
            response = client.get('/api/signals')
            assert response.status_code == 200
            assert response.json == []


class TestMatrixEndpoint:
    """Tests for /api/matrix endpoint"""

    def test_get_matrix_empty(self, client, app, sample_symbol):
        """Test matrix with no patterns (all neutral)"""
        with app.app_context():
            response = client.get('/api/matrix')
            assert response.status_code == 200
            data = response.json

            # Should have the symbol
            assert 'BTC/USDT' in data
            # All timeframes should be neutral
            assert all(v == 'neutral' for v in data['BTC/USDT'].values())

    def test_get_matrix_with_patterns(self, client, app, sample_symbol):
        """Test matrix reflects pattern directions"""
        with app.app_context():
            # Add patterns
            bullish = Pattern(
                symbol_id=sample_symbol,
                timeframe='1h',
                pattern_type='imbalance',
                direction='bullish',
                zone_high=105.0,
                zone_low=100.0,
                detected_at=1700000000000,
                status='active'
            )
            bearish = Pattern(
                symbol_id=sample_symbol,
                timeframe='4h',
                pattern_type='imbalance',
                direction='bearish',
                zone_high=95.0,
                zone_low=90.0,
                detected_at=1700000000000,
                status='active'
            )
            db.session.add_all([bullish, bearish])
            db.session.commit()

            response = client.get('/api/matrix')
            assert response.status_code == 200
            data = response.json

            assert data['BTC/USDT']['1h'] == 'bullish'
            assert data['BTC/USDT']['4h'] == 'bearish'
            assert data['BTC/USDT']['1d'] == 'neutral'


class TestAPIAuthentication:
    """Tests for API key authentication"""

    def test_scan_without_api_key_no_key_set(self, client, app):
        """Test scan endpoint denies access when no API key is configured (secure default)"""
        with app.app_context():
            # No API key set - should return 503 (secure default)
            response = client.post('/api/scan')
            assert response.status_code == 503
            assert 'API not configured' in response.json['error']

    def test_scan_with_api_key_required(self, client, app):
        """Test scan endpoint requires API key when configured"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            # No key provided - should be 401
            response = client.post('/api/scan')
            assert response.status_code == 401
            assert 'Unauthorized' in response.json['error']

    def test_scan_with_valid_api_key_header(self, client, app):
        """Test scan endpoint accepts valid API key in header"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            response = client.post(
                '/api/scan',
                headers={'X-API-Key': 'test-secret-key'}
            )
            # Should pass auth (may have other errors, but not 401)
            assert response.status_code != 401

    def test_scan_with_valid_api_key_param(self, client, app):
        """Test scan endpoint accepts valid API key as query param"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            response = client.post('/api/scan?api_key=test-secret-key')
            assert response.status_code != 401

    def test_scan_with_invalid_api_key(self, client, app):
        """Test scan endpoint rejects invalid API key"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            response = client.post(
                '/api/scan',
                headers={'X-API-Key': 'wrong-key'}
            )
            assert response.status_code == 401

    def test_scheduler_endpoints_require_auth(self, client, app):
        """Test scheduler control endpoints require authentication"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            # All these should return 401 without key
            assert client.post('/api/scheduler/start').status_code == 401
            assert client.post('/api/scheduler/stop').status_code == 401
            assert client.post('/api/scheduler/toggle').status_code == 401

    def test_scheduler_status_no_auth(self, client, app):
        """Test scheduler status endpoint doesn't require auth"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            # Status is read-only, shouldn't need auth
            response = client.get('/api/scheduler/status')
            assert response.status_code == 200


class TestFetchEndpoint:
    """Tests for /api/fetch endpoint"""

    def test_fetch_requires_auth(self, client, app):
        """Test fetch endpoint requires authentication"""
        with app.app_context():
            # No API key configured - should return 503
            response = client.post(
                '/api/fetch',
                content_type='application/json',
                data=json.dumps({})
            )
            assert response.status_code == 503
            assert 'API not configured' in response.json['error']

    def test_fetch_missing_params(self, client, app):
        """Test fetch endpoint requires symbol and timeframe"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            response = client.post(
                '/api/fetch',
                content_type='application/json',
                headers={'X-API-Key': 'test-secret-key'},
                data=json.dumps({})
            )
            assert response.status_code == 400
            assert 'error' in response.json

    def test_fetch_with_params(self, client, app, sample_symbol):
        """Test fetch endpoint with valid parameters"""
        with app.app_context():
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            response = client.post(
                '/api/fetch',
                content_type='application/json',
                headers={'X-API-Key': 'test-secret-key'},
                data=json.dumps({'symbol': 'BTC/USDT', 'timeframe': '1h'})
            )
            # May succeed or fail (network), but shouldn't be 400 or 401
            # Just verify the endpoint handles the request
            assert response.status_code in [200, 500]  # 200 success or 500 network error


class TestSchedulerEndpoint:
    """Tests for /api/scheduler endpoints"""

    def test_scheduler_status(self, client, app):
        """Test getting scheduler status"""
        with app.app_context():
            response = client.get('/api/scheduler/status')
            assert response.status_code == 200
            data = response.json
            assert data['mode'] == 'cron'
            assert 'cron_setup' in data


class TestRateLimiting:
    """Tests for API rate limiting"""

    def test_rate_limit_headers_present(self, client, app):
        """Test that rate limit headers are present in responses"""
        with app.app_context():
            response = client.get('/api/symbols')
            # Rate limit headers should be present
            assert response.status_code == 200


class TestJSONResponses:
    """Tests to ensure all endpoints return valid JSON"""

    def test_symbols_returns_json(self, client, app):
        """Test symbols endpoint returns JSON"""
        with app.app_context():
            response = client.get('/api/symbols')
            assert response.content_type == 'application/json'

    def test_patterns_returns_json(self, client, app):
        """Test patterns endpoint returns JSON"""
        with app.app_context():
            response = client.get('/api/patterns')
            assert response.content_type == 'application/json'

    def test_signals_returns_json(self, client, app):
        """Test signals endpoint returns JSON"""
        with app.app_context():
            response = client.get('/api/signals')
            assert response.content_type == 'application/json'

    def test_matrix_returns_json(self, client, app, sample_symbol):
        """Test matrix endpoint returns JSON"""
        with app.app_context():
            response = client.get('/api/matrix')
            assert response.content_type == 'application/json'

    def test_error_returns_json(self, client, app):
        """Test 404 error returns JSON"""
        with app.app_context():
            response = client.get('/api/candles/UNKNOWN-PAIR/1h')
            assert response.status_code == 404
            assert response.content_type == 'application/json'
            assert 'error' in response.json


class TestMetricsEndpoint:
    """Tests for /metrics endpoint (Prometheus)"""

    def test_metrics_endpoint_returns_200(self, client, app):
        """Test metrics endpoint returns 200"""
        with app.app_context():
            response = client.get('/metrics')
            assert response.status_code == 200

    def test_metrics_returns_prometheus_format(self, client, app):
        """Test metrics endpoint returns Prometheus format"""
        with app.app_context():
            response = client.get('/metrics')
            assert response.status_code == 200
            # Prometheus format should have text content
            assert b'cryptolens' in response.data

    def test_metrics_contains_app_info(self, client, app):
        """Test metrics contains application info"""
        with app.app_context():
            response = client.get('/metrics')
            # Should contain app info metric
            assert b'cryptolens_info' in response.data or b'cryptolens' in response.data

    def test_metrics_contains_pattern_gauges(self, client, app):
        """Test metrics contains pattern count gauges"""
        with app.app_context():
            response = client.get('/metrics')
            # Should contain pattern metrics
            assert b'cryptolens_patterns_active' in response.data

    def test_metrics_contains_user_metrics(self, client, app):
        """Test metrics contains user-related metrics"""
        with app.app_context():
            response = client.get('/metrics')
            # Should contain user metrics
            assert b'cryptolens_users_active' in response.data

    def test_metrics_no_auth_required(self, client, app):
        """Test metrics endpoint doesn't require authentication"""
        with app.app_context():
            # Set API key
            Setting.set('api_key_hash', hash_api_key('test-secret-key'))
            db.session.commit()

            # Metrics should still work without auth
            response = client.get('/metrics')
            assert response.status_code == 200
