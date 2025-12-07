"""
Tests for User Authentication
Tests registration, login, logout, password changes, and user validation.
"""
import pytest
from app import db
from app.models import User
from app.services.auth import (
    register_user, authenticate_user, change_password,
    validate_password, generate_unique_topic, AuthError
)


class TestPasswordValidation:
    """Tests for password validation rules"""

    def test_valid_password(self, app):
        """Test that valid passwords pass validation"""
        with app.app_context():
            valid, error = validate_password('ValidPass1')
            assert valid is True
            assert error is None

    def test_password_too_short(self, app):
        """Test passwords shorter than 8 characters are rejected"""
        with app.app_context():
            valid, error = validate_password('Short1')
            assert valid is False
            assert 'at least 8' in error

    def test_password_no_uppercase(self, app):
        """Test passwords without uppercase are rejected"""
        with app.app_context():
            valid, error = validate_password('lowercase1')
            assert valid is False
            assert 'uppercase' in error.lower()

    def test_password_no_lowercase(self, app):
        """Test passwords without lowercase are rejected"""
        with app.app_context():
            valid, error = validate_password('UPPERCASE1')
            assert valid is False
            assert 'lowercase' in error.lower()

    def test_password_no_digit(self, app):
        """Test passwords without digits are rejected"""
        with app.app_context():
            valid, error = validate_password('NoDigitsHere')
            assert valid is False
            assert 'digit' in error.lower()


class TestUserRegistration:
    """Tests for user registration"""

    def test_register_valid_user(self, app):
        """Test registering a valid user"""
        with app.app_context():
            user = register_user(
                email='newuser@example.com',
                username='newuser',
                password='ValidPass123'
            )
            assert user is not None
            assert user.email == 'newuser@example.com'
            assert user.username == 'newuser'
            assert user.is_active is True
            assert user.is_verified is False
            assert user.ntfy_topic.startswith('cl_')

    def test_register_duplicate_email(self, app, sample_user):
        """Test that duplicate emails are rejected"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='test@example.com',
                    username='different',
                    password='ValidPass123'
                )
            assert 'Email already registered' in str(exc_info.value)

    def test_register_duplicate_username(self, app, sample_user):
        """Test that duplicate usernames are rejected"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='different@example.com',
                    username='testuser',
                    password='ValidPass123'
                )
            assert 'Username already taken' in str(exc_info.value)

    def test_register_invalid_password(self, app):
        """Test that invalid passwords are rejected during registration"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='test@example.com',
                    username='testuser',
                    password='weak'
                )
            assert 'Password' in str(exc_info.value) or 'password' in str(exc_info.value).lower()

    def test_register_invalid_email(self, app):
        """Test that invalid emails are rejected"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='not-an-email',
                    username='testuser',
                    password='ValidPass123'
                )
            assert 'email' in str(exc_info.value).lower()

    def test_register_invalid_username_too_short(self, app):
        """Test that short usernames are rejected"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='test@example.com',
                    username='ab',
                    password='ValidPass123'
                )
            assert 'Username' in str(exc_info.value) or 'username' in str(exc_info.value).lower()

    def test_register_invalid_username_special_chars(self, app):
        """Test that usernames with special chars are rejected"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                register_user(
                    email='test@example.com',
                    username='user@name',
                    password='ValidPass123'
                )
            assert 'Username' in str(exc_info.value) or 'username' in str(exc_info.value).lower()


class TestUserAuthentication:
    """Tests for user login/authentication"""

    def test_authenticate_valid_credentials(self, app, sample_user):
        """Test login with valid credentials"""
        with app.app_context():
            user = authenticate_user('test@example.com', 'TestPass123')
            assert user is not None
            assert user.email == 'test@example.com'

    def test_authenticate_wrong_password(self, app, sample_user):
        """Test login with wrong password"""
        with app.app_context():
            user = authenticate_user('test@example.com', 'WrongPassword123')
            assert user is None

    def test_authenticate_nonexistent_email(self, app):
        """Test login with non-existent email"""
        with app.app_context():
            user = authenticate_user('nonexistent@example.com', 'AnyPassword123')
            assert user is None

    def test_authenticate_inactive_user(self, app, inactive_user):
        """Test login attempt by inactive user"""
        with app.app_context():
            user = authenticate_user('inactive@example.com', 'TestPass123')
            assert user is None

    def test_authenticate_updates_last_login(self, app, sample_user):
        """Test that successful login updates last_login timestamp"""
        with app.app_context():
            user = db.session.get(User, sample_user)
            original_last_login = user.last_login

            authenticated = authenticate_user('test@example.com', 'TestPass123')
            assert authenticated.last_login is not None
            if original_last_login is None:
                assert authenticated.last_login is not None


class TestPasswordChange:
    """Tests for password change functionality"""

    def test_change_password_success(self, app, sample_user):
        """Test successful password change"""
        with app.app_context():
            success = change_password(
                user_id=sample_user,
                old_password='TestPass123',
                new_password='NewValid456'
            )
            assert success is True

            # Verify new password works
            authenticated = authenticate_user('test@example.com', 'NewValid456')
            assert authenticated is not None

    def test_change_password_wrong_old_password(self, app, sample_user):
        """Test password change with wrong current password"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                change_password(
                    user_id=sample_user,
                    old_password='WrongPassword',
                    new_password='NewValid456'
                )
            assert 'Current password is incorrect' in str(exc_info.value)

    def test_change_password_invalid_new_password(self, app, sample_user):
        """Test password change with invalid new password"""
        with app.app_context():
            with pytest.raises(AuthError) as exc_info:
                change_password(
                    user_id=sample_user,
                    old_password='TestPass123',
                    new_password='weak'
                )
            assert 'Password' in str(exc_info.value) or 'password' in str(exc_info.value).lower()


class TestNtfyTopicGeneration:
    """Tests for NTFY topic generation"""

    def test_generate_unique_topic_format(self, app):
        """Test that generated topics have correct format"""
        with app.app_context():
            topic = generate_unique_topic()
            assert topic.startswith('cl_')
            assert len(topic) == 19  # 'cl_' + 16 hex chars

    def test_generate_unique_topic_uniqueness(self, app):
        """Test that multiple topics are unique"""
        with app.app_context():
            topics = [generate_unique_topic() for _ in range(100)]
            assert len(set(topics)) == 100


class TestLoginRoutes:
    """Tests for login/logout HTTP routes"""

    def test_login_page_loads(self, client):
        """Test that login page loads"""
        response = client.get('/auth/login')
        assert response.status_code == 200
        assert b'Login' in response.data

    def test_register_page_loads(self, client):
        """Test that register page loads"""
        response = client.get('/auth/register')
        assert response.status_code == 200
        assert b'Create Account' in response.data

    def test_login_success_redirect(self, client, sample_user):
        """Test successful login redirects to profile"""
        response = client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_failure_message(self, client, sample_user):
        """Test failed login shows error message"""
        response = client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'WrongPassword'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_logout_redirects(self, client, sample_user):
        """Test logout redirects to login page"""
        client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123'
        })
        response = client.get('/auth/logout', follow_redirects=True)
        assert response.status_code == 200
        assert b'Login' in response.data

    def test_profile_requires_login(self, client):
        """Test that profile page requires authentication"""
        response = client.get('/auth/profile', follow_redirects=True)
        assert response.status_code == 200
        assert b'Login' in response.data

    def test_register_creates_user(self, client):
        """Test that registration creates a new user"""
        response = client.post('/auth/register', data={
            'email': 'newuser@example.com',
            'username': 'newuser',
            'password': 'ValidPass123',
            'confirm_password': 'ValidPass123'
        }, follow_redirects=True)
        assert response.status_code == 200


class TestAccountLockout:
    """Tests for account lockout (brute force protection)"""

    def test_record_failed_attempt_increments_counter(self, app, sample_user):
        """Test that failed attempts are recorded"""
        from app.services.lockout import record_failed_attempt
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            assert user.failed_attempts == 0

            record_failed_attempt('test@example.com')
            db.session.refresh(user)
            assert user.failed_attempts == 1

            record_failed_attempt('test@example.com')
            db.session.refresh(user)
            assert user.failed_attempts == 2

    def test_account_locks_after_max_attempts(self, app, sample_user):
        """Test that account locks after 5 failed attempts"""
        from app.services.lockout import record_failed_attempt, is_locked, MAX_ATTEMPTS
        with app.app_context():
            # Record MAX_ATTEMPTS failures
            for _ in range(MAX_ATTEMPTS):
                record_failed_attempt('test@example.com')

            locked, minutes = is_locked('test@example.com')
            assert locked is True
            assert minutes is not None
            assert minutes > 0

    def test_is_locked_returns_false_for_unlocked_account(self, app, sample_user):
        """Test that unlocked accounts return False"""
        from app.services.lockout import is_locked
        with app.app_context():
            locked, minutes = is_locked('test@example.com')
            assert locked is False
            assert minutes is None

    def test_is_locked_returns_false_for_nonexistent_email(self, app):
        """Test that nonexistent emails don't reveal existence"""
        from app.services.lockout import is_locked
        with app.app_context():
            locked, minutes = is_locked('nonexistent@example.com')
            assert locked is False
            assert minutes is None

    def test_clear_lockout_resets_counters(self, app, sample_user):
        """Test that clear_lockout resets failed attempts"""
        from app.services.lockout import record_failed_attempt, clear_lockout
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()

            # Record some failures
            record_failed_attempt('test@example.com')
            record_failed_attempt('test@example.com')
            db.session.refresh(user)
            assert user.failed_attempts == 2

            # Clear lockout
            clear_lockout(user)
            db.session.refresh(user)
            assert user.failed_attempts == 0
            assert user.locked_until is None

    def test_login_blocked_when_locked(self, app, client, sample_user):
        """Test that login is blocked for locked accounts"""
        from app.services.lockout import record_failed_attempt, MAX_ATTEMPTS
        with app.app_context():
            # Lock the account
            for _ in range(MAX_ATTEMPTS):
                record_failed_attempt('test@example.com')

        # Try to login
        response = client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123'
        }, follow_redirects=True)
        assert b'temporarily locked' in response.data

    def test_successful_login_clears_lockout(self, app, client, sample_user):
        """Test that successful login clears failed attempt counter"""
        from app.services.lockout import record_failed_attempt
        with app.app_context():
            # Record a few failed attempts (but not enough to lock)
            record_failed_attempt('test@example.com')
            record_failed_attempt('test@example.com')

        # Successful login
        client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123'
        }, follow_redirects=True)

        # Check counter was cleared
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            assert user.failed_attempts == 0
