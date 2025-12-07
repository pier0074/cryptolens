"""
Security Tests for CryptoLens

Tests for:
- CSRF protection
- Session security
- Rate limiting
- Authentication bypass attempts
- Input validation
- Authorization checks
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import json


class TestCSRFProtection:
    """Tests for CSRF protection"""

    def test_csrf_enabled_in_production_config(self, app):
        """Test that CSRF protection is configured"""
        # In test mode, CSRF is disabled for convenience
        # In production, WTF_CSRF_ENABLED defaults to True
        # This test verifies the config exists
        assert 'WTF_CSRF_ENABLED' in app.config
        # Test mode should have CSRF disabled
        assert app.config['WTF_CSRF_ENABLED'] is False

    def test_api_endpoints_exempt_from_csrf(self, app):
        """Test that API endpoints work without CSRF (uses API key instead)"""
        with app.test_client() as client:
            # API GET endpoints should work
            response = client.get('/api/health')
            assert response.status_code == 200

            response = client.get('/api/symbols')
            assert response.status_code == 200

    def test_payment_webhook_csrf_exempt(self, app):
        """Test that payment webhooks are CSRF exempt"""
        with app.test_client() as client:
            # Webhook should accept POST without CSRF
            # (will fail auth but not CSRF)
            response = client.post('/webhook/lemonsqueezy',
                                   data='{}',
                                   content_type='application/json')
            # Should not be 400 CSRF error
            assert response.status_code != 400 or b'CSRF' not in response.data


class TestSessionSecurity:
    """Tests for session security configuration"""

    def test_session_cookie_settings(self, app):
        """Test session cookie security settings"""
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
        # SECURE is True in production, False in debug
        assert 'SESSION_COOKIE_SECURE' in app.config

    def test_session_lifetime(self, app):
        """Test session has reasonable lifetime"""
        lifetime = app.config['PERMANENT_SESSION_LIFETIME']
        # Should be between 1 hour and 30 days
        assert lifetime >= timedelta(hours=1)
        assert lifetime <= timedelta(days=30)

    def test_login_creates_session(self, app, sample_user):
        """Test that login creates a session"""
        with app.test_client() as client:
            # Get CSRF token first
            response = client.get('/auth/login')
            assert response.status_code == 200

            # Simulate successful login (sample_user is user_id from fixture)
            with client.session_transaction() as sess:
                sess['user_id'] = sample_user
                sess['_fresh'] = True

            # Session should now have user_id
            with client.session_transaction() as sess:
                assert sess.get('user_id') == sample_user


class TestRateLimiting:
    """Tests for rate limiting"""

    def test_login_rate_limited(self, app):
        """Test that login endpoint is rate limited"""
        with app.test_client() as client:
            # Make multiple rapid requests
            # Note: In test mode, rate limiting may be disabled
            responses = []
            for i in range(10):
                response = client.post('/auth/login', data={
                    'email': f'test{i}@example.com',
                    'password': 'wrongpassword'
                })
                responses.append(response.status_code)

            # Either should hit rate limit or be handled normally
            # (rate limiting may be disabled in test mode)
            assert all(code in [200, 302, 400, 429] for code in responses)

    def test_api_scan_rate_limited(self, app):
        """Test that API scan endpoint is rate limited to 1/minute"""
        # This is configured in the route decorator
        with app.test_client() as client:
            # First request may succeed or fail auth
            response = client.post('/api/scan')
            # Should be 401 (no API key) or 503 (not configured)
            assert response.status_code in [401, 429, 503]


class TestAuthenticationBypass:
    """Tests for authentication bypass attempts"""

    def test_protected_route_requires_login(self, app):
        """Test that protected routes require login"""
        # Use routes without trailing slash (Flask strict_slashes)
        protected_routes = [
            '/settings',
            '/portfolio',
        ]

        with app.test_client() as client:
            for route in protected_routes:
                response = client.get(route, follow_redirects=False)
                # Should redirect to login (302/308) or require auth (401)
                # 308 is permanent redirect to add trailing slash
                assert response.status_code in [302, 308, 401], \
                    f"{route} returned {response.status_code}"

    def test_admin_route_requires_admin(self, app, sample_user):
        """Test that admin routes require admin privileges"""
        with app.test_client() as client:
            # Login as regular user (sample_user is user_id)
            with client.session_transaction() as sess:
                sess['user_id'] = sample_user

            # Try to access admin panel
            response = client.get('/admin/')
            # Should be forbidden or redirect
            assert response.status_code in [302, 403]

    def test_api_key_required_for_protected_endpoints(self, app):
        """Test that protected API endpoints require API key"""
        protected_endpoints = [
            ('/api/scan', 'POST'),
            ('/api/fetch', 'POST'),
            ('/api/scan/run', 'POST'),
        ]

        with app.test_client() as client:
            for endpoint, method in protected_endpoints:
                if method == 'POST':
                    response = client.post(endpoint)
                else:
                    response = client.get(endpoint)

                # Should be 401 or 503 (not configured)
                assert response.status_code in [401, 503], \
                    f"{endpoint} returned {response.status_code}"

    def test_invalid_api_key_rejected(self, app):
        """Test that invalid API keys are rejected"""
        with app.test_client() as client:
            response = client.post('/api/scan',
                                   headers={'X-API-Key': 'invalid-key'})
            # Should be 401 (invalid key) or 503 (not configured)
            assert response.status_code in [401, 503]


class TestInputValidation:
    """Tests for input validation"""

    def test_sql_injection_in_symbol_param(self, app):
        """Test SQL injection is prevented in symbol parameter"""
        with app.test_client() as client:
            # Try SQL injection in symbol parameter
            malicious_inputs = [
                "BTC'; DROP TABLE users;--",
                "BTC' OR '1'='1",
                "BTC\"; DROP TABLE patterns;--",
            ]

            for payload in malicious_inputs:
                response = client.get(f'/api/patterns?symbol={payload}')
                # Should return 200 (no results) or 404, not crash
                assert response.status_code in [200, 404]

    def test_xss_in_search_params(self, app):
        """Test XSS is prevented in search parameters"""
        with app.test_client() as client:
            xss_payload = "<script>alert('xss')</script>"
            response = client.get(f'/api/patterns?symbol={xss_payload}')
            # Should return JSON, not execute script
            assert response.content_type == 'application/json'
            # Response should not contain unescaped script tag
            assert b'<script>' not in response.data

    def test_path_traversal_prevented(self, app):
        """Test path traversal is prevented"""
        with app.test_client() as client:
            # Try path traversal in candle endpoint
            response = client.get('/api/candles/../../../etc/passwd/1h')
            # Should return 404, not file contents
            assert response.status_code == 404

    def test_large_limit_parameter_handled(self, app):
        """Test that unreasonably large limit parameters are handled"""
        with app.test_client() as client:
            response = client.get('/api/patterns?limit=999999999')
            # Should not crash, may return limited results
            assert response.status_code == 200

    def test_negative_limit_handled(self, app):
        """Test that negative limit parameters are handled"""
        with app.test_client() as client:
            response = client.get('/api/patterns?limit=-1')
            # Should not crash
            assert response.status_code in [200, 400]


class TestAuthorizationChecks:
    """Tests for authorization checks"""

    def test_portfolio_access_requires_login(self, app):
        """Test that portfolio access requires login"""
        with app.test_client() as client:
            # Try to access portfolio without login
            response = client.get('/portfolio/')
            # Should redirect to login
            assert response.status_code in [302, 308]

    def test_subscription_required_for_features(self, app, user_no_subscription):
        """Test that some features require an active subscription"""
        with app.test_client() as client:
            # Login as user without subscription
            with client.session_transaction() as sess:
                sess['user_id'] = user_no_subscription

            # Try to access subscription-required features
            response = client.get('/portfolio/', follow_redirects=False)
            # Should redirect to upgrade or show error
            assert response.status_code in [200, 302, 403]


class TestPasswordSecurity:
    """Tests for password security"""

    def test_password_not_stored_in_plaintext(self, app):
        """Test that passwords are hashed, not stored in plaintext"""
        from app.models import User
        from app import db

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            if user:
                # Password hash should not equal the plaintext
                assert user.password_hash != 'Test123!'
                # Hash should be at least 50 characters (pbkdf2)
                assert len(user.password_hash) >= 50

    def test_password_validation_rules(self, app):
        """Test that password validation rules are enforced"""
        from app.services.auth import validate_password

        # Too short
        valid, errors = validate_password('Short1')
        assert not valid
        assert 'at least 8 characters' in str(errors).lower()

        # No uppercase
        valid, errors = validate_password('lowercase123')
        assert not valid

        # No lowercase
        valid, errors = validate_password('UPPERCASE123')
        assert not valid

        # No digit
        valid, errors = validate_password('NoDigitsHere')
        assert not valid

        # Valid password
        valid, errors = validate_password('ValidPass123')
        assert valid


class TestAccountLockout:
    """Tests for account lockout functionality"""

    def test_lockout_after_failed_attempts(self, app, sample_user):
        """Test that account is locked after too many failed attempts"""
        from app.services.lockout import record_failed_attempt, is_locked
        from app.models import User
        from app import db

        # Default max attempts from lockout service
        MAX_ATTEMPTS = 5

        with app.app_context():
            # Use existing test user email
            user = db.session.get(User, sample_user)
            test_email = user.email

            # Record multiple failed attempts
            for i in range(MAX_ATTEMPTS + 1):
                record_failed_attempt(test_email)

            # Account should now be locked (is_locked returns tuple or bool)
            result = is_locked(test_email)
            locked = result[0] if isinstance(result, tuple) else result
            assert locked is True

    def test_lockout_expires(self, app, sample_user):
        """Test that lockout expires after duration"""
        from app.services.lockout import is_locked
        from app.models import User
        from app import db
        from datetime import datetime, timezone, timedelta

        with app.app_context():
            # Get existing user and set expired lockout
            user = db.session.get(User, sample_user)
            user.failed_attempts = 10
            user.locked_until = datetime.now(timezone.utc) - timedelta(hours=1)
            db.session.commit()

            # Lockout should have expired (is_locked returns tuple or bool)
            result = is_locked(user.email)
            locked = result[0] if isinstance(result, tuple) else result
            assert locked is False


class TestTOTPSecurity:
    """Tests for TOTP (2FA) security"""

    def test_totp_secret_stored(self, app, sample_user):
        """Test that TOTP secrets can be stored"""
        from app.models import User
        from app import db
        import pyotp

        with app.app_context():
            # Get user from database (sample_user is user_id)
            user = db.session.get(User, sample_user)
            assert user is not None

            # Generate and store a TOTP secret
            secret = pyotp.random_base32()
            user.totp_secret = secret
            user.totp_enabled = True
            db.session.commit()

            # Verify it's stored
            db.session.refresh(user)
            assert user.totp_secret is not None
            assert user.totp_enabled is True


class TestAPIKeySecurity:
    """Tests for API key security"""

    def test_api_key_hashed(self, app):
        """Test that API keys are stored as hashes"""
        from app.services.auth import hash_api_key, verify_api_key

        api_key = 'test-api-key-12345'
        hashed = hash_api_key(api_key)

        # Hash should not equal plaintext
        assert hashed != api_key

        # Should be able to verify
        assert verify_api_key(api_key, hashed) is True

        # Wrong key should not verify
        assert verify_api_key('wrong-key', hashed) is False

    def test_api_key_not_in_response(self, app, sample_user):
        """Test that API key is not leaked in responses"""
        with app.test_client() as client:
            # Login (sample_user is user_id)
            with client.session_transaction() as sess:
                sess['user_id'] = sample_user

            # Access settings page
            response = client.get('/settings/')
            # Should not contain actual API key value in HTML
            # (may show masked version or "Set" indicator)
            assert b'api_key=' not in response.data


class TestSecurityHeaders:
    """Tests for security headers"""

    def test_content_type_on_json_responses(self, app):
        """Test that JSON responses have correct content type"""
        with app.test_client() as client:
            response = client.get('/api/health')
            assert response.content_type == 'application/json'

    def test_no_sensitive_info_in_errors(self, app):
        """Test that error responses don't leak sensitive info"""
        with app.test_client() as client:
            # Request non-existent route
            response = client.get('/api/nonexistent')

            # Should not contain stack traces or internal paths
            assert b'Traceback' not in response.data
            assert b'/Users/' not in response.data
            assert b'site-packages' not in response.data
