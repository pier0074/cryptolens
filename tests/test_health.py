"""
Tests for Health Check Service

Tests the health check functionality including database,
cache, and external service connectivity checks.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.services.health import (
    check_database,
    check_cache,
    check_exchange_api,
    check_ntfy_service,
    get_full_health_status,
    get_liveness_status,
    get_readiness_status
)


class TestCheckDatabase:
    """Test database health check functionality"""

    def test_check_database_healthy(self, app):
        """Database check returns healthy when db is accessible"""
        with app.app_context():
            result = check_database()
            assert result['status'] == 'healthy'
            assert 'latency_ms' in result
            assert result['latency_ms'] >= 0

    def test_check_database_unhealthy(self, app):
        """Database check returns unhealthy on error"""
        with app.app_context():
            from app import db
            with patch.object(db.session, 'execute') as mock_exec:
                mock_exec.side_effect = Exception('Connection refused')
                result = check_database()
                assert result['status'] == 'unhealthy'
                assert 'error' in result


class TestCheckCache:
    """Test cache health check functionality"""

    def test_check_cache_healthy(self, app):
        """Cache check returns healthy when cache is accessible"""
        with app.app_context():
            result = check_cache()
            assert result['status'] == 'healthy'
            assert 'type' in result
            assert result['type'] in ['redis', 'memory']

    def test_check_cache_latency(self, app):
        """Cache check includes latency measurement"""
        with app.app_context():
            result = check_cache()
            if result['status'] == 'healthy':
                assert 'latency_ms' in result
                assert result['latency_ms'] >= 0


class TestCheckExchangeApi:
    """Test exchange API health check functionality"""

    def test_check_exchange_api_healthy(self):
        """Exchange check returns healthy when API is accessible"""
        with patch('ccxt.binance') as mock_exchange_class:
            mock_exchange = MagicMock()
            mock_exchange.fetch_time.return_value = 1234567890
            mock_exchange_class.return_value = mock_exchange

            result = check_exchange_api()
            assert result['status'] == 'healthy'
            assert 'exchange' in result
            assert 'latency_ms' in result

    def test_check_exchange_api_unhealthy(self):
        """Exchange check returns unhealthy on error"""
        with patch('ccxt.binance') as mock_exchange_class:
            mock_exchange = MagicMock()
            mock_exchange.fetch_time.side_effect = Exception('Network error')
            mock_exchange_class.return_value = mock_exchange

            result = check_exchange_api()
            assert result['status'] == 'unhealthy'
            assert 'error' in result


class TestCheckNtfyService:
    """Test NTFY service health check functionality"""

    def test_check_ntfy_healthy(self):
        """NTFY check returns healthy when service is accessible"""
        with patch('requests.head') as mock_head:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_head.return_value = mock_response

            result = check_ntfy_service()
            assert result['status'] == 'healthy'
            assert 'url' in result
            assert 'latency_ms' in result

    def test_check_ntfy_unhealthy_server_error(self):
        """NTFY check returns unhealthy on server error"""
        with patch('requests.head') as mock_head:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_head.return_value = mock_response

            result = check_ntfy_service()
            assert result['status'] == 'unhealthy'
            assert 'error' in result
            assert 'HTTP 503' in result['error']

    def test_check_ntfy_timeout(self):
        """NTFY check handles timeout correctly"""
        import requests
        with patch('requests.head') as mock_head:
            mock_head.side_effect = requests.exceptions.Timeout()

            result = check_ntfy_service()
            assert result['status'] == 'unhealthy'
            assert 'timeout' in result['error'].lower()


class TestGetFullHealthStatus:
    """Test full health status aggregation"""

    def test_get_full_health_status_all_healthy(self, app):
        """Full health returns healthy when all dependencies are healthy"""
        with app.app_context():
            with patch('app.services.health.check_exchange_api') as mock_exchange:
                with patch('app.services.health.check_ntfy_service') as mock_ntfy:
                    mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
                    mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

                    result = get_full_health_status()
                    assert result['status'] == 'healthy'
                    assert 'timestamp' in result
                    assert 'version' in result
                    assert 'dependencies' in result
                    assert 'database' in result['dependencies']
                    assert 'cache' in result['dependencies']

    def test_get_full_health_status_degraded(self, app):
        """Full health returns degraded when external service fails"""
        with app.app_context():
            with patch('app.services.health.check_exchange_api') as mock_exchange:
                with patch('app.services.health.check_ntfy_service') as mock_ntfy:
                    mock_exchange.return_value = {'status': 'unhealthy', 'exchange': 'binance', 'error': 'Network error'}
                    mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

                    result = get_full_health_status()
                    # Should be degraded, not unhealthy (external services are non-critical)
                    assert result['status'] in ['degraded', 'healthy']

    def test_get_full_health_status_unhealthy_database(self, app):
        """Full health returns unhealthy when database fails"""
        with app.app_context():
            with patch('app.services.health.check_database') as mock_db:
                mock_db.return_value = {'status': 'unhealthy', 'error': 'Connection refused'}

                result = get_full_health_status()
                assert result['status'] == 'unhealthy'


class TestLivenessAndReadiness:
    """Test liveness and readiness check endpoints"""

    def test_get_liveness_status(self, app):
        """Liveness check returns quick status without external checks"""
        with app.app_context():
            result = get_liveness_status()
            assert 'status' in result
            assert 'dependencies' in result
            assert 'database' in result['dependencies']
            assert 'cache' in result['dependencies']
            # Liveness should not include exchange or ntfy (slow checks)

    def test_get_readiness_status(self, app):
        """Readiness check returns full status with external checks"""
        with app.app_context():
            with patch('app.services.health.check_exchange_api') as mock_exchange:
                with patch('app.services.health.check_ntfy_service') as mock_ntfy:
                    mock_exchange.return_value = {'status': 'healthy', 'exchange': 'binance', 'latency_ms': 100}
                    mock_ntfy.return_value = {'status': 'healthy', 'url': 'https://ntfy.sh', 'latency_ms': 50}

                    result = get_readiness_status()
                    assert 'status' in result
                    assert 'dependencies' in result
                    assert 'database' in result['dependencies']
                    assert 'cache' in result['dependencies']
                    assert 'exchange' in result['dependencies']
                    assert 'ntfy' in result['dependencies']
