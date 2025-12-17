"""
Tests for Observability Features
Tests request ID tracing, health checks, and dependency monitoring
"""
from unittest.mock import patch, MagicMock
from app.services.health import (
    check_database, check_cache, check_exchange_api,
    check_ntfy_service, get_full_health_status
)


class TestRequestIdTracing:
    """Tests for request ID middleware"""

    def test_request_id_generated(self, app, client):
        """Test that request ID is generated for requests"""
        response = client.get('/api/health?quick=true')
        assert response.status_code == 200

        # Check X-Request-ID header is present
        assert 'X-Request-ID' in response.headers
        request_id = response.headers['X-Request-ID']
        assert len(request_id) == 8  # Short UUID format

    def test_request_id_preserved_from_header(self, app, client):
        """Test that provided request ID is preserved"""
        custom_id = 'test1234'
        response = client.get('/api/health?quick=true', headers={
            'X-Request-ID': custom_id
        })
        assert response.status_code == 200
        assert response.headers['X-Request-ID'] == custom_id

    def test_request_id_unique_per_request(self, app, client):
        """Test that each request gets unique ID"""
        response1 = client.get('/api/health?quick=true')
        response2 = client.get('/api/health?quick=true')

        id1 = response1.headers['X-Request-ID']
        id2 = response2.headers['X-Request-ID']

        assert id1 != id2


class TestCheckDatabase:
    """Tests for database health check"""

    def test_database_healthy(self, app):
        """Test database health check when connected"""
        with app.app_context():
            result = check_database()

            assert result['status'] == 'healthy'
            assert 'latency_ms' in result
            assert result['latency_ms'] >= 0

    def test_database_unhealthy(self, app):
        """Test database health check when disconnected"""
        with app.app_context():
            from app import db
            with patch.object(db.session, 'execute') as mock_exec:
                mock_exec.side_effect = Exception("Connection refused")

                result = check_database()

                assert result['status'] == 'unhealthy'
                assert 'error' in result


class TestCheckCache:
    """Tests for cache health check"""

    def test_cache_healthy_memory(self, app):
        """Test cache health check with in-memory cache"""
        with app.app_context():
            result = check_cache()

            assert result['status'] == 'healthy'
            assert result['type'] == 'memory'
            assert 'latency_ms' in result


class TestCheckExchangeApi:
    """Tests for exchange API health check"""

    def test_exchange_healthy(self):
        """Test exchange API health check when reachable"""
        import ccxt
        with patch.object(ccxt, 'binance') as mock_exchange_class:
            mock_exchange = MagicMock()
            mock_exchange.fetch_time.return_value = 1234567890
            mock_exchange_class.return_value = mock_exchange

            result = check_exchange_api(timeout=1.0)

            assert result['status'] == 'healthy'
            assert result['exchange'] == 'binance'
            assert 'latency_ms' in result

    def test_exchange_unhealthy(self):
        """Test exchange API health check when unreachable"""
        import ccxt
        with patch.object(ccxt, 'binance') as mock_exchange_class:
            mock_exchange = MagicMock()
            mock_exchange.fetch_time.side_effect = Exception("Network error")
            mock_exchange_class.return_value = mock_exchange

            result = check_exchange_api(timeout=1.0)

            assert result['status'] == 'unhealthy'
            assert 'error' in result


class TestCheckNtfyService:
    """Tests for NTFY service health check"""

    @patch('app.services.health.requests.head')
    def test_ntfy_healthy(self, mock_head):
        """Test NTFY health check when reachable"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_head.return_value = mock_response

        result = check_ntfy_service(timeout=1.0)

        assert result['status'] == 'healthy'
        assert 'latency_ms' in result

    @patch('app.services.health.requests.head')
    def test_ntfy_unhealthy_server_error(self, mock_head):
        """Test NTFY health check with server error"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_head.return_value = mock_response

        result = check_ntfy_service(timeout=1.0)

        assert result['status'] == 'unhealthy'
        assert 'HTTP 500' in result['error']

    @patch('app.services.health.requests.head')
    def test_ntfy_timeout(self, mock_head):
        """Test NTFY health check on timeout"""
        import requests
        mock_head.side_effect = requests.exceptions.Timeout()

        result = check_ntfy_service(timeout=1.0)

        assert result['status'] == 'unhealthy'
        assert 'timeout' in result['error'].lower()

    @patch('app.services.health.requests.head')
    def test_ntfy_connection_error(self, mock_head):
        """Test NTFY health check on connection error"""
        import requests
        mock_head.side_effect = requests.exceptions.ConnectionError("DNS failure")

        result = check_ntfy_service(timeout=1.0)

        assert result['status'] == 'unhealthy'
        assert 'connection' in result['error'].lower()


class TestGetFullHealthStatus:
    """Tests for full health status aggregation"""

    @patch('app.services.health.check_ntfy_service')
    @patch('app.services.health.check_exchange_api')
    @patch('app.services.health.check_cache')
    @patch('app.services.health.check_database')
    def test_all_healthy(self, mock_db, mock_cache, mock_exchange, mock_ntfy):
        """Test overall status when all dependencies healthy"""
        mock_db.return_value = {'status': 'healthy', 'latency_ms': 1}
        mock_cache.return_value = {'status': 'healthy', 'type': 'memory', 'latency_ms': 1}
        mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
        mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

        result = get_full_health_status()

        assert result['status'] == 'healthy'
        assert 'dependencies' in result
        assert result['dependencies']['database']['status'] == 'healthy'
        assert result['dependencies']['cache']['status'] == 'healthy'
        assert result['dependencies']['exchange']['status'] == 'healthy'
        assert result['dependencies']['ntfy']['status'] == 'healthy'

    @patch('app.services.health.check_ntfy_service')
    @patch('app.services.health.check_exchange_api')
    @patch('app.services.health.check_cache')
    @patch('app.services.health.check_database')
    def test_database_unhealthy(self, mock_db, mock_cache, mock_exchange, mock_ntfy):
        """Test overall status unhealthy when database down"""
        mock_db.return_value = {'status': 'unhealthy', 'error': 'Connection refused'}
        mock_cache.return_value = {'status': 'healthy', 'type': 'memory', 'latency_ms': 1}
        mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
        mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

        result = get_full_health_status()

        assert result['status'] == 'unhealthy'

    @patch('app.services.health.check_ntfy_service')
    @patch('app.services.health.check_exchange_api')
    @patch('app.services.health.check_cache')
    @patch('app.services.health.check_database')
    def test_external_service_unhealthy_is_degraded(self, mock_db, mock_cache, mock_exchange, mock_ntfy):
        """Test overall status degraded when external service down"""
        mock_db.return_value = {'status': 'healthy', 'latency_ms': 1}
        mock_cache.return_value = {'status': 'healthy', 'type': 'memory', 'latency_ms': 1}
        mock_exchange.return_value = {'status': 'unhealthy', 'error': 'Network error'}
        mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

        result = get_full_health_status()

        assert result['status'] == 'degraded'

    @patch('app.services.health.check_cache')
    @patch('app.services.health.check_database')
    def test_quick_check_skips_external(self, mock_db, mock_cache):
        """Test quick check doesn't call external services"""
        mock_db.return_value = {'status': 'healthy', 'latency_ms': 1}
        mock_cache.return_value = {'status': 'healthy', 'type': 'memory', 'latency_ms': 1}

        result = get_full_health_status(include_slow_checks=False)

        assert 'exchange' not in result['dependencies']
        assert 'ntfy' not in result['dependencies']


class TestLivenessReadinessEndpoints:
    """Tests for Kubernetes probe endpoints"""

    def test_liveness_endpoint(self, app, client):
        """Test /api/health/live endpoint"""
        response = client.get('/api/health/live')

        assert response.status_code == 200
        data = response.get_json()
        assert 'status' in data
        assert 'dependencies' in data
        assert 'database' in data['dependencies']
        # Liveness shouldn't include slow checks
        assert 'exchange' not in data['dependencies']

    def test_readiness_endpoint(self, app, client):
        """Test /api/health/ready endpoint"""
        with patch('app.services.health.check_exchange_api') as mock_exchange, \
             patch('app.services.health.check_ntfy_service') as mock_ntfy:

            mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
            mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

            response = client.get('/api/health/ready')

            assert response.status_code == 200
            data = response.get_json()
            assert 'exchange' in data['dependencies']
            assert 'ntfy' in data['dependencies']

    def test_health_quick_mode(self, app, client):
        """Test /api/health?quick=true skips slow checks"""
        response = client.get('/api/health?quick=true')

        assert response.status_code == 200
        data = response.get_json()
        assert 'exchange' not in data['dependencies']
        assert 'ntfy' not in data['dependencies']

    def test_health_full_mode(self, app, client):
        """Test /api/health includes all checks by default"""
        with patch('app.services.health.check_exchange_api') as mock_exchange, \
             patch('app.services.health.check_ntfy_service') as mock_ntfy:

            mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
            mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

            response = client.get('/api/health')

            assert response.status_code == 200
            data = response.get_json()
            assert 'exchange' in data['dependencies']
            assert 'ntfy' in data['dependencies']


class TestHealthResponseFormat:
    """Tests for health response format"""

    def test_health_response_structure(self, app, client):
        """Test health response has correct structure"""
        response = client.get('/api/health?quick=true')
        data = response.get_json()

        # Required fields
        assert 'status' in data
        assert 'timestamp' in data
        assert 'version' in data
        assert 'dependencies' in data

        # Status must be valid value
        assert data['status'] in ['healthy', 'degraded', 'unhealthy']

        # Timestamp should be ISO format
        from datetime import datetime
        datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))

    def test_unhealthy_returns_503(self, app, client):
        """Test that unhealthy status returns 503"""
        with patch('app.services.health.check_database') as mock_db:
            mock_db.return_value = {'status': 'unhealthy', 'error': 'Connection refused'}

            response = client.get('/api/health?quick=true')

            assert response.status_code == 503
            data = response.get_json()
            assert data['status'] == 'unhealthy'


class TestLoggerRequestId:
    """Tests for request ID in logging"""

    def test_get_request_id_in_context(self, app, client):
        """Test get_request_id returns ID in request context"""

        with client.session_transaction():
            # Make a request to set up context
            response = client.get('/api/health?quick=true')
            request_id = response.headers.get('X-Request-ID')
            assert request_id is not None

    def test_get_request_id_outside_context(self):
        """Test get_request_id returns None outside request context"""
        from app.services.logger import get_request_id

        result = get_request_id()
        assert result is None
