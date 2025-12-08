"""
Health Check Service
Provides dependency health checks for monitoring and observability
"""
import time
import requests
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.config import Config


def check_database() -> Dict[str, Any]:
    """
    Check database connectivity and measure latency.

    Returns:
        Dict with status, latency_ms, and optional error
    """
    from app import db

    start = time.time()
    try:
        db.session.execute(db.text('SELECT 1'))
        latency = (time.time() - start) * 1000
        return {
            'status': 'healthy',
            'latency_ms': round(latency, 2)
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'error': str(e)[:200]
        }


def check_cache() -> Dict[str, Any]:
    """
    Check cache connectivity and measure latency.

    Returns:
        Dict with status, type, latency_ms, and optional error
    """
    from flask import current_app
    from app import cache

    start = time.time()
    try:
        cache_type = current_app.config.get('CACHE_TYPE', 'SimpleCache')

        if cache_type == 'RedisCache':
            # Test Redis connection
            cache.set('_health_check', '1', timeout=5)
            if cache.get('_health_check') == '1':
                latency = (time.time() - start) * 1000
                return {
                    'status': 'healthy',
                    'type': 'redis',
                    'latency_ms': round(latency, 2)
                }
            else:
                return {
                    'status': 'unhealthy',
                    'type': 'redis',
                    'error': 'Redis read/write failed'
                }
        else:
            latency = (time.time() - start) * 1000
            return {
                'status': 'healthy',
                'type': 'memory',
                'latency_ms': round(latency, 2)
            }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'type': 'unknown',
            'error': str(e)[:200]
        }


def check_exchange_api(timeout: float = 5.0) -> Dict[str, Any]:
    """
    Check CCXT exchange API connectivity.
    Tests if we can reach the exchange and get basic data.

    Args:
        timeout: Request timeout in seconds

    Returns:
        Dict with status, exchange, latency_ms, and optional error
    """
    start = time.time()
    try:
        import ccxt

        # Use the same exchange as configured
        exchange_id = Config.EXCHANGE or 'binance'
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'timeout': int(timeout * 1000)
        })

        # Simple connectivity test - fetch time from exchange
        exchange.fetch_time()
        latency = (time.time() - start) * 1000

        return {
            'status': 'healthy',
            'exchange': exchange_id,
            'latency_ms': round(latency, 2)
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'exchange': Config.EXCHANGE or 'binance',
            'error': str(e)[:200]
        }


def check_ntfy_service(timeout: float = 5.0) -> Dict[str, Any]:
    """
    Check NTFY notification service connectivity.
    Tests if we can reach the NTFY server.

    Args:
        timeout: Request timeout in seconds

    Returns:
        Dict with status, url, latency_ms, and optional error
    """
    ntfy_url = Config.NTFY_URL or 'https://ntfy.sh'

    start = time.time()
    try:
        # Simple HEAD request to check if NTFY is reachable
        # Using the base URL without a topic
        response = requests.head(ntfy_url, timeout=timeout)
        latency = (time.time() - start) * 1000

        if response.status_code < 500:
            return {
                'status': 'healthy',
                'url': ntfy_url,
                'latency_ms': round(latency, 2)
            }
        else:
            return {
                'status': 'unhealthy',
                'url': ntfy_url,
                'error': f'HTTP {response.status_code}'
            }
    except requests.exceptions.Timeout:
        return {
            'status': 'unhealthy',
            'url': ntfy_url,
            'error': 'Request timeout'
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'status': 'unhealthy',
            'url': ntfy_url,
            'error': f'Connection error: {str(e)[:100]}'
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'url': ntfy_url,
            'error': str(e)[:200]
        }


def get_full_health_status(include_slow_checks: bool = True) -> Dict[str, Any]:
    """
    Get comprehensive health status of all dependencies.

    Args:
        include_slow_checks: Whether to include external API checks (CCXT, NTFY)
                           Set to False for quick liveness checks

    Returns:
        Dict with overall status and individual dependency statuses
    """
    health = {
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version': '2.1.0',
        'dependencies': {}
    }

    # Always check database (critical)
    health['dependencies']['database'] = check_database()
    if health['dependencies']['database']['status'] != 'healthy':
        health['status'] = 'unhealthy'

    # Always check cache (important but not critical)
    health['dependencies']['cache'] = check_cache()
    if health['dependencies']['cache']['status'] != 'healthy':
        if health['status'] == 'healthy':
            health['status'] = 'degraded'

    # Optional slow checks for external services
    if include_slow_checks:
        # Check exchange API
        health['dependencies']['exchange'] = check_exchange_api()
        if health['dependencies']['exchange']['status'] != 'healthy':
            if health['status'] == 'healthy':
                health['status'] = 'degraded'

        # Check NTFY service
        health['dependencies']['ntfy'] = check_ntfy_service()
        if health['dependencies']['ntfy']['status'] != 'healthy':
            if health['status'] == 'healthy':
                health['status'] = 'degraded'

    return health


def get_liveness_status() -> Dict[str, Any]:
    """
    Quick liveness check (is the app running?).
    Only checks database, skips external services.

    Returns:
        Simple health status dict
    """
    return get_full_health_status(include_slow_checks=False)


def get_readiness_status() -> Dict[str, Any]:
    """
    Full readiness check (is the app ready to serve traffic?).
    Includes all dependency checks.

    Returns:
        Comprehensive health status dict
    """
    return get_full_health_status(include_slow_checks=True)
