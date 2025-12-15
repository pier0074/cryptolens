"""
Comprehensive tests for the API Key system.

Tests:
- ApiKey model (creation, validation, expiry, scopes)
- IpRule model (whitelist/blacklist matching)
- Rate limiting
- API authentication with new keys
- Standardized API responses
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import (
    User, Symbol, ApiKey, IpRule, ApiKeyUsage, ApiResponse,
    API_KEY_STATUS, API_KEY_SCOPES
)


@pytest.fixture
def app():
    """Create test app with MySQL test database."""
    app = create_app('testing')
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def test_user(app):
    """Create a test user."""
    import secrets
    with app.app_context():
        user = User(
            email='testuser@example.com',
            username='testuser',
            is_active=True,
            is_verified=True,
            ntfy_topic=f'test_{secrets.token_hex(8)}'  # Required field
        )
        user.set_password('testpass123')
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def test_symbol(app):
    """Create a test symbol."""
    with app.app_context():
        symbol = Symbol(symbol='TEST/USDT', is_active=True)
        db.session.add(symbol)
        db.session.commit()
        return symbol.id


# =============================================================================
# API KEY MODEL TESTS
# =============================================================================

class TestApiKeyModel:
    """Test ApiKey model functionality."""

    def test_create_api_key(self, app):
        """Test creating a new API key."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Test Key',
                description='A test API key'
            )

            assert api_key.id is not None
            assert api_key.name == 'Test Key'
            assert api_key.description == 'A test API key'
            assert api_key.status == 'active'
            assert api_key.key_prefix == raw_key[:8]
            assert len(raw_key) == 43  # URL-safe base64 of 32 bytes

    def test_create_api_key_with_user(self, app, test_user):
        """Test creating API key associated with a user."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='User Key',
                user_id=test_user
            )

            assert api_key.user_id == test_user
            user = User.query.get(test_user)
            assert api_key in user.api_keys.all()

    def test_create_api_key_with_expiry(self, app):
        """Test creating API key with expiration."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Expiring Key',
                expires_in_days=30
            )

            assert api_key.expires_at is not None
            assert api_key.days_until_expiry <= 30
            assert api_key.is_expired is False
            assert api_key.is_valid is True

    def test_create_api_key_with_custom_rate_limits(self, app):
        """Test creating API key with custom rate limits."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Limited Key',
                rate_limit_per_minute=10,
                rate_limit_per_hour=100,
                rate_limit_per_day=500
            )

            assert api_key.rate_limit_per_minute == 10
            assert api_key.rate_limit_per_hour == 100
            assert api_key.rate_limit_per_day == 500

    def test_create_api_key_with_scopes(self, app):
        """Test creating API key with specific scopes."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Scoped Key',
                scopes=['read:symbols', 'read:candles']
            )

            assert api_key.scope_list == ['read:symbols', 'read:candles']
            assert api_key.has_scope('read:symbols') is True
            assert api_key.has_scope('read:candles') is True
            assert api_key.has_scope('write:scan') is False

    def test_api_key_all_scope(self, app):
        """Test API key with 'all' scope has all permissions."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Full Access Key',
                scopes=['all']
            )

            assert api_key.has_scope('read:symbols') is True
            assert api_key.has_scope('read:candles') is True
            assert api_key.has_scope('write:scan') is True
            assert api_key.has_scope('admin:scheduler') is True
            assert api_key.has_scope('any_random_scope') is True

    def test_find_by_key(self, app):
        """Test finding API key by raw key."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Find Test Key')

            found = ApiKey.find_by_key(raw_key)
            assert found is not None
            assert found.id == api_key.id

    def test_find_by_invalid_key(self, app):
        """Test finding with invalid key returns None."""
        with app.app_context():
            ApiKey.create(name='Test Key')

            assert ApiKey.find_by_key('invalid_key') is None
            assert ApiKey.find_by_key('') is None
            assert ApiKey.find_by_key(None) is None

    def test_api_key_hash_verification(self, app):
        """Test that key hash is verified correctly."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Hash Test Key')

            # Correct key should work
            assert ApiKey.find_by_key(raw_key) is not None

            # Key with same prefix but different hash should fail
            wrong_key = raw_key[:8] + 'x' * 35
            assert ApiKey.find_by_key(wrong_key) is None


class TestApiKeyValidity:
    """Test API key validity checks."""

    def test_valid_active_key(self, app):
        """Test that active key without expiry is valid."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Active Key')

            assert api_key.is_valid is True
            assert api_key.is_expired is False

    def test_inactive_key_not_valid(self, app):
        """Test that inactive key is not valid."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Inactive Key')
            api_key.status = 'inactive'
            db.session.commit()

            assert api_key.is_valid is False

    def test_revoked_key_not_valid(self, app):
        """Test that revoked key is not valid."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Revoked Key')
            api_key.revoke(reason='Test revocation')

            assert api_key.status == 'revoked'
            assert api_key.is_valid is False

    def test_expired_key_not_valid(self, app):
        """Test that expired key is not valid."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Expired Key', expires_in_days=1)
            # Manually set expiry in the past
            api_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.session.commit()

            assert api_key.is_expired is True
            assert api_key.is_valid is False


class TestApiKeyUsageTracking:
    """Test API key usage tracking."""

    def test_record_usage(self, app):
        """Test recording API key usage."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Usage Test Key')

            api_key.record_usage(
                ip_address='192.168.1.1',
                endpoint='/api/symbols',
                method='GET',
                response_code=200
            )

            assert api_key.total_requests == 1
            assert api_key.last_used_at is not None

            usage = api_key.usage_logs.first()
            assert usage.ip_address == '192.168.1.1'
            assert usage.endpoint == '/api/symbols'

    def test_get_usage_count(self, app):
        """Test getting usage count for time periods."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Count Test Key')

            # Record some usage
            for i in range(5):
                api_key.record_usage(ip_address='192.168.1.1')

            assert api_key.get_usage_count(minutes=1) == 5
            assert api_key.get_usage_count(hours=1) == 5

    def test_cleanup_old_usage(self, app):
        """Test cleanup of old usage entries."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Cleanup Test Key')

            # Create old usage entry
            old_usage = ApiKeyUsage(
                api_key_id=api_key.id,
                timestamp=datetime.now(timezone.utc) - timedelta(days=10),
                ip_address='192.168.1.1'
            )
            db.session.add(old_usage)
            db.session.commit()

            # Create new usage
            api_key.record_usage(ip_address='192.168.1.2')

            assert api_key.usage_logs.count() == 2

            # Cleanup entries older than 7 days
            deleted = ApiKeyUsage.cleanup_old_entries(days=7)
            assert deleted == 1
            assert api_key.usage_logs.count() == 1


class TestApiKeyRateLimiting:
    """Test API key rate limiting."""

    def test_rate_limit_per_minute(self, app):
        """Test per-minute rate limiting."""
        with app.app_context():
            api_key, _ = ApiKey.create(
                name='Rate Limited Key',
                rate_limit_per_minute=3
            )

            # First 3 requests should be allowed
            for i in range(3):
                api_key.record_usage()

            is_limited, reason = api_key.is_rate_limited()
            assert is_limited is True
            # Check for rate limit message format: "3/minute"
            assert 'minute' in reason.lower()

    def test_not_rate_limited_under_limit(self, app):
        """Test not rate limited when under limit."""
        with app.app_context():
            api_key, _ = ApiKey.create(
                name='Under Limit Key',
                rate_limit_per_minute=100
            )

            api_key.record_usage()

            is_limited, reason = api_key.is_rate_limited()
            assert is_limited is False
            assert reason == ''


# =============================================================================
# IP RULE TESTS
# =============================================================================

class TestIpRules:
    """Test IP whitelist/blacklist rules."""

    def test_exact_ip_match(self, app):
        """Test exact IP matching."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='IP Test Key')

            rule = IpRule(
                api_key_id=api_key.id,
                rule_type='whitelist',
                ip_pattern='192.168.1.100'
            )
            db.session.add(rule)
            db.session.commit()

            assert rule.matches_ip('192.168.1.100') is True
            assert rule.matches_ip('192.168.1.101') is False

    def test_cidr_match(self, app):
        """Test CIDR notation matching."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='CIDR Test Key')

            rule = IpRule(
                api_key_id=api_key.id,
                rule_type='whitelist',
                ip_pattern='192.168.1.0/24'
            )
            db.session.add(rule)
            db.session.commit()

            assert rule.matches_ip('192.168.1.1') is True
            assert rule.matches_ip('192.168.1.255') is True
            assert rule.matches_ip('192.168.2.1') is False

    def test_wildcard_match(self, app):
        """Test wildcard pattern matching."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Wildcard Test Key')

            rule = IpRule(
                api_key_id=api_key.id,
                rule_type='whitelist',
                ip_pattern='10.0.*.*'
            )
            db.session.add(rule)
            db.session.commit()

            assert rule.matches_ip('10.0.0.1') is True
            assert rule.matches_ip('10.0.255.255') is True
            assert rule.matches_ip('10.1.0.1') is False

    def test_blacklist_blocks_ip(self, app):
        """Test that blacklisted IPs are blocked."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Blacklist Test Key')

            rule = IpRule(
                api_key_id=api_key.id,
                rule_type='blacklist',
                ip_pattern='192.168.1.100'
            )
            db.session.add(rule)
            db.session.commit()

            allowed, reason = api_key.check_ip_allowed('192.168.1.100')
            assert allowed is False
            assert 'blacklisted' in reason.lower()

            allowed, reason = api_key.check_ip_allowed('192.168.1.101')
            assert allowed is True

    def test_whitelist_only_allows_listed(self, app):
        """Test that whitelist only allows listed IPs."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='Whitelist Test Key')

            rule = IpRule(
                api_key_id=api_key.id,
                rule_type='whitelist',
                ip_pattern='192.168.1.0/24'
            )
            db.session.add(rule)
            db.session.commit()

            allowed, _ = api_key.check_ip_allowed('192.168.1.50')
            assert allowed is True

            allowed, reason = api_key.check_ip_allowed('10.0.0.1')
            assert allowed is False
            assert 'not in whitelist' in reason.lower()

    def test_no_rules_allows_all(self, app):
        """Test that no IP rules allows all IPs."""
        with app.app_context():
            api_key, _ = ApiKey.create(name='No Rules Key')

            allowed, _ = api_key.check_ip_allowed('192.168.1.1')
            assert allowed is True

            allowed, _ = api_key.check_ip_allowed('10.0.0.1')
            assert allowed is True


# =============================================================================
# API RESPONSE FORMAT TESTS
# =============================================================================

class TestApiResponse:
    """Test standardized API response format."""

    def test_success_response(self, app):
        """Test success response format."""
        with app.app_context():
            response, status = ApiResponse.success({'key': 'value'})

            assert status == 200
            data = response.get_json()
            assert data['success'] is True
            assert data['data'] == {'key': 'value'}
            assert data['error'] is None
            assert 'timestamp' in data['meta']
            assert 'request_id' in data['meta']

    def test_success_with_meta(self, app):
        """Test success response with additional meta."""
        with app.app_context():
            response, status = ApiResponse.success(
                {'items': []},
                meta={'count': 0, 'page': 1}
            )

            data = response.get_json()
            assert data['meta']['count'] == 0
            assert data['meta']['page'] == 1

    def test_error_response(self, app):
        """Test error response format."""
        with app.app_context():
            response, status = ApiResponse.error(
                'NOT_FOUND',
                'Resource not found',
                404
            )

            assert status == 404
            data = response.get_json()
            assert data['success'] is False
            assert data['data'] is None
            assert data['error']['code'] == 'NOT_FOUND'
            assert data['error']['message'] == 'Resource not found'

    def test_paginated_response(self, app):
        """Test paginated response format."""
        with app.app_context():
            items = [{'id': 1}, {'id': 2}]
            response, status = ApiResponse.paginated(
                items,
                total=100,
                page=1,
                per_page=10
            )

            data = response.get_json()
            assert data['success'] is True
            assert len(data['data']) == 2
            assert data['meta']['pagination']['total'] == 100
            assert data['meta']['pagination']['page'] == 1
            assert data['meta']['pagination']['per_page'] == 10
            assert data['meta']['pagination']['total_pages'] == 10
            assert data['meta']['pagination']['has_next'] is True
            assert data['meta']['pagination']['has_prev'] is False

    def test_unauthorized_response(self, app):
        """Test unauthorized response helper."""
        with app.app_context():
            response, status = ApiResponse.unauthorized()

            assert status == 401
            data = response.get_json()
            assert data['error']['code'] == 'UNAUTHORIZED'

    def test_forbidden_response(self, app):
        """Test forbidden response helper."""
        with app.app_context():
            response, status = ApiResponse.forbidden()

            assert status == 403
            data = response.get_json()
            assert data['error']['code'] == 'FORBIDDEN'

    def test_rate_limited_response(self, app):
        """Test rate limited response helper."""
        with app.app_context():
            response, status = ApiResponse.rate_limited()

            assert status == 429
            data = response.get_json()
            assert data['error']['code'] == 'RATE_LIMITED'


# =============================================================================
# API AUTHENTICATION TESTS
# =============================================================================

class TestApiAuthentication:
    """Test API authentication with new key system."""

    def test_unauthenticated_request_rejected(self, app, client, test_symbol):
        """Test that unauthenticated requests are rejected."""
        with app.app_context():
            # Create an API key so the system knows it's configured
            api_key, raw_key = ApiKey.create(name='Test Key')

        # Request without providing the API key should be rejected
        response = client.get('/api/symbols')
        # Should get 401 (unauthorized) since API key is configured but not provided
        assert response.status_code == 401
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['code'] == 'UNAUTHORIZED'

    def test_valid_api_key_accepted(self, app, client, test_symbol):
        """Test that valid API key is accepted."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Valid Key')

        response = client.get(
            '/api/symbols',
            headers={'X-API-Key': raw_key}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_api_key_via_query_param(self, app, client, test_symbol):
        """Test API key via query parameter."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Query Param Key')

        response = client.get(f'/api/symbols?api_key={raw_key}')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_invalid_api_key_rejected(self, app, client, test_symbol):
        """Test that invalid API key is rejected."""
        with app.app_context():
            ApiKey.create(name='Existing Key')

        response = client.get(
            '/api/symbols',
            headers={'X-API-Key': 'invalid_key_here'}
        )
        assert response.status_code == 401
        data = response.get_json()
        assert data['error']['code'] == 'UNAUTHORIZED'

    def test_expired_api_key_rejected(self, app, client, test_symbol):
        """Test that expired API key is rejected."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(
                name='Expired Key',
                expires_in_days=1
            )
            api_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.session.commit()

        response = client.get(
            '/api/symbols',
            headers={'X-API-Key': raw_key}
        )
        assert response.status_code == 401
        data = response.get_json()
        assert 'expired' in data['error']['message'].lower()

    def test_revoked_api_key_rejected(self, app, client, test_symbol):
        """Test that revoked API key is rejected."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Revoked Key')
            api_key.revoke('Testing revocation')

        response = client.get(
            '/api/symbols',
            headers={'X-API-Key': raw_key}
        )
        assert response.status_code == 401
        data = response.get_json()
        assert 'revoked' in data['error']['message'].lower()

    def test_scope_restriction(self, app, client, test_symbol):
        """Test that API key scope restrictions are enforced."""
        with app.app_context():
            # Create key with only read:symbols scope
            api_key, raw_key = ApiKey.create(
                name='Limited Scope Key',
                scopes=['read:symbols']
            )

        # Should work - has read:symbols scope
        response = client.get(
            '/api/symbols',
            headers={'X-API-Key': raw_key}
        )
        assert response.status_code == 200

        # Should fail - doesn't have read:candles scope
        response = client.get(
            '/api/candles/TEST-USDT/5m',  # 5m is a valid timeframe
            headers={'X-API-Key': raw_key}
        )
        assert response.status_code == 403
        data = response.get_json()
        assert 'scope' in data['error']['message'].lower()


# =============================================================================
# API ENDPOINT RESPONSE FORMAT TESTS
# =============================================================================

class TestApiEndpointResponses:
    """Test that all API endpoints return consistent response format."""

    def test_symbols_endpoint_format(self, app, client, test_symbol):
        """Test /api/symbols response format."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Test Key')

        response = client.get('/api/symbols', headers={'X-API-Key': raw_key})
        data = response.get_json()

        assert 'success' in data
        assert 'data' in data
        assert 'error' in data
        assert 'meta' in data
        assert isinstance(data['data'], list)
        assert 'count' in data['meta']

    def test_candles_endpoint_format(self, app, client, test_symbol):
        """Test /api/candles response format."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Test Key')

        response = client.get(
            '/api/candles/TEST-USDT/5m',  # 5m is a valid timeframe
            headers={'X-API-Key': raw_key}
        )
        data = response.get_json()

        assert data['success'] is True
        assert isinstance(data['data'], list)
        assert 'symbol' in data['meta']
        assert 'timeframe' in data['meta']

    def test_candles_not_found_format(self, app, client):
        """Test candles endpoint with invalid symbol."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Test Key')

        response = client.get(
            '/api/candles/INVALID-SYMBOL/1m',
            headers={'X-API-Key': raw_key}
        )

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert data['error']['code'] == 'NOT_FOUND'

    def test_health_endpoint_format(self, app, client):
        """Test /api/health response format (no auth required)."""
        response = client.get('/api/health')
        data = response.get_json()

        assert 'success' in data
        assert 'data' in data
        assert 'status' in data['data']

    def test_patterns_endpoint_format(self, app, client, test_symbol):
        """Test /api/patterns response format."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Test Key')

        response = client.get('/api/patterns', headers={'X-API-Key': raw_key})
        data = response.get_json()

        assert data['success'] is True
        assert isinstance(data['data'], list)
        assert 'filters' in data['meta']

    def test_signals_endpoint_format(self, app, client, test_symbol):
        """Test /api/signals response format."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Test Key')

        response = client.get('/api/signals', headers={'X-API-Key': raw_key})
        data = response.get_json()

        assert data['success'] is True
        assert isinstance(data['data'], list)
        assert 'filters' in data['meta']


# =============================================================================
# EDGE CASES AND SECURITY TESTS
# =============================================================================

class TestSecurityEdgeCases:
    """Test security edge cases."""

    def test_timing_safe_key_comparison(self, app):
        """Test that key comparison is timing-safe."""
        with app.app_context():
            api_key, raw_key = ApiKey.create(name='Timing Test Key')

            # Both should use timing-safe comparison
            import time
            times = []

            for _ in range(10):
                start = time.perf_counter()
                ApiKey.find_by_key(raw_key)
                times.append(time.perf_counter() - start)

            wrong_key = raw_key[:8] + 'x' * 35
            wrong_times = []

            for _ in range(10):
                start = time.perf_counter()
                ApiKey.find_by_key(wrong_key)
                wrong_times.append(time.perf_counter() - start)

            # Times should be roughly similar (timing-safe)
            # This is a weak test but better than nothing
            avg_valid = sum(times) / len(times)
            avg_invalid = sum(wrong_times) / len(wrong_times)

            # Should not differ by more than 10x
            assert avg_valid < avg_invalid * 10
            assert avg_invalid < avg_valid * 10

    def test_key_prefix_uniqueness(self, app):
        """Test that key prefixes are unique."""
        with app.app_context():
            key1, _ = ApiKey.create(name='Key 1')
            key2, _ = ApiKey.create(name='Key 2')

            assert key1.key_prefix != key2.key_prefix

    def test_concurrent_key_creation(self, app):
        """Test creating multiple keys doesn't cause conflicts."""
        with app.app_context():
            keys = []
            for i in range(10):
                api_key, raw_key = ApiKey.create(name=f'Concurrent Key {i}')
                keys.append((api_key.key_prefix, raw_key))

            # All prefixes should be unique
            prefixes = [k[0] for k in keys]
            assert len(set(prefixes)) == 10
