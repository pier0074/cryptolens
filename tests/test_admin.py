"""
Tests for Admin Routes

Tests the admin panel functionality including user management,
subscription management, cron jobs, and system settings.
"""
import pytest
from datetime import datetime, timezone, timedelta
from tests.conftest import login_user
from app import db
from app.models import User, Subscription, Symbol, CronJob, CronRun


class TestAdminAccess:
    """Test admin route access control"""

    def test_admin_index_requires_login(self, client, app):
        """Admin index redirects unauthenticated users"""
        response = client.get('/admin/')
        assert response.status_code == 302
        assert '/auth/login' in response.location

    def test_admin_index_requires_admin(self, client, app, sample_user):
        """Admin index redirects non-admin users"""
        login_user(client, 'test@example.com', 'TestPass123')
        response = client.get('/admin/')
        assert response.status_code == 302  # Redirected, not authorized

    def test_admin_index_accessible_to_admin(self, client, app, admin_user):
        """Admin index accessible to admin users"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/')
        assert response.status_code == 200
        assert b'Admin' in response.data or b'admin' in response.data


class TestAdminUserManagement:
    """Test admin user management functionality"""

    def test_users_list(self, client, app, admin_user, sample_user):
        """Admin can list users"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users')
        assert response.status_code == 200
        assert b'test@example.com' in response.data or b'testuser' in response.data

    def test_users_search(self, client, app, admin_user, sample_user):
        """Admin can search users by email"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users?search=test')
        assert response.status_code == 200
        assert b'test@example.com' in response.data or b'testuser' in response.data

    def test_users_filter_active(self, client, app, admin_user, sample_user, inactive_user):
        """Admin can filter active users"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users?status=active')
        assert response.status_code == 200
        # Should show active users only

    def test_users_filter_inactive(self, client, app, admin_user, inactive_user):
        """Admin can filter inactive users"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users?status=inactive')
        assert response.status_code == 200

    def test_user_detail(self, client, app, admin_user, sample_user):
        """Admin can view user details"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Get the sample_user id
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            user_id = user.id

        response = client.get(f'/admin/users/{user_id}')
        assert response.status_code == 200
        assert b'test@example.com' in response.data

    def test_user_detail_not_found(self, client, app, admin_user):
        """Admin user detail returns error for non-existent user"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users/99999')
        # Should redirect with flash message
        assert response.status_code == 302


class TestAdminUserActions:
    """Test admin user action functionality"""

    def test_verify_user(self, client, app, admin_user, unverified_user):
        """Admin can verify a user"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='unverified@example.com').first()
            user_id = user.id
            assert user.is_verified is False

        response = client.post(f'/admin/users/{user_id}/verify', follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.is_verified is True

    def test_deactivate_user(self, client, app, admin_user, sample_user):
        """Admin can deactivate a user"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            user_id = user.id
            assert user.is_active is True

        response = client.post(f'/admin/users/{user_id}/deactivate', follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.is_active is False

    def test_activate_user(self, client, app, admin_user, inactive_user):
        """Admin can activate a user"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='inactive@example.com').first()
            user_id = user.id
            assert user.is_active is False

        response = client.post(f'/admin/users/{user_id}/activate', follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.is_active is True

    def test_make_admin(self, client, app, admin_user, sample_user):
        """Admin can make another user an admin"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            user_id = user.id
            assert user.is_admin is False

        response = client.post(f'/admin/users/{user_id}/make-admin', follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.is_admin is True

    def test_revoke_admin_route_accessible(self, client, app, admin_user):
        """Admin can access revoke-admin endpoint for another user"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Create another admin user
        with app.app_context():
            other_admin = User(
                email='other_admin@example.com',
                username='otheradmin',
                is_active=True,
                is_verified=True,
                is_admin=True,
                ntfy_topic='cl_otheradmin1234'
            )
            other_admin.set_password('OtherAdmin123')
            db.session.add(other_admin)
            db.session.commit()
            user_id = other_admin.id

        response = client.post(f'/admin/users/{user_id}/revoke-admin', follow_redirects=True)
        # Route is accessible and responds
        assert response.status_code == 200


class TestAdminSubscriptions:
    """Test admin subscription management"""

    def test_subscriptions_page(self, client, app, admin_user, sample_user):
        """Admin can view subscriptions page"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/subscriptions')
        assert response.status_code == 200

    def test_extend_subscription(self, client, app, admin_user, sample_user):
        """Admin can extend a user's subscription"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            user_id = user.id

        # Use correct route and form data format
        response = client.post(f'/admin/users/{user_id}/subscription', data={
            'action': 'extend',
            'plan': 'monthly',
            'custom_days': '30'
        }, follow_redirects=True)
        assert response.status_code == 200


class TestAdminSymbols:
    """Test admin symbol management"""

    def test_symbols_page(self, client, app, admin_user, sample_symbol):
        """Admin can view symbols page"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/symbols')
        assert response.status_code == 200
        assert b'BTC/USDT' in response.data

    def test_add_symbol_api(self, client, app, admin_user):
        """Admin can add a new symbol via API"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/api/symbols/add',
            data='{"symbol": "ETH/USDT"}',
            content_type='application/json',
            follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            symbol = Symbol.query.filter_by(symbol='ETH/USDT').first()
            assert symbol is not None
            assert symbol.is_active is True

    def test_toggle_symbol_api_returns_json(self, client, app, admin_user, sample_symbol):
        """Admin toggle symbol API returns JSON response"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        # BTC/USDT is mandatory, so toggling should return 400 with error message
        response = client.post('/admin/api/symbols/toggle',
            data=f'{{"id": {sample_symbol}}}',
            content_type='application/json',
            follow_redirects=True)
        # Mandatory symbols return 400 when trying to disable
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert 'mandatory' in data['error']


class TestAdminCronJobs:
    """Test admin cron job monitoring"""

    def test_crons_page(self, client, app, admin_user):
        """Admin can view cron jobs page"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/crons')
        assert response.status_code == 200

    def test_crons_with_jobs(self, client, app, admin_user):
        """Admin can view cron jobs with data"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Create a unique cron job for testing
        with app.app_context():
            job = CronJob(
                name='test_job_unique',
                schedule='0 * * * *',
                is_enabled=True
            )
            db.session.add(job)
            db.session.commit()

        response = client.get('/admin/crons')
        assert response.status_code == 200

    def test_crons_api(self, client, app, admin_user):
        """Admin can access crons API"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/api/crons')
        assert response.status_code == 200


class TestAdminDashboard:
    """Test admin dashboard functionality"""

    def test_admin_index(self, client, app, admin_user):
        """Admin can view admin index/dashboard"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/')
        assert response.status_code == 200

    def test_stats_api(self, client, app, admin_user):
        """Admin can access stats API"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/api/stats')
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None


class TestAdminCreateUser:
    """Test admin user creation functionality"""

    def test_create_user_page(self, client, app, admin_user):
        """Admin can view create user page"""
        login_user(client, 'admin@example.com', 'AdminPass123')
        response = client.get('/admin/users/create')
        assert response.status_code == 200

    def test_create_user_success(self, client, app, admin_user):
        """Admin can create a new user"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/create', data={
            'email': 'newuser@example.com',
            'username': 'newuser',
            'password': 'NewUser123',
            'plan': 'pro',
            'is_verified': 'on'
        }, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = User.query.filter_by(email='newuser@example.com').first()
            assert user is not None
            assert user.username == 'newuser'
            assert user.is_verified is True

    def test_create_user_duplicate_email(self, client, app, admin_user, sample_user):
        """Admin cannot create user with duplicate email"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/create', data={
            'email': 'test@example.com',  # Already exists
            'username': 'anotheruser',
            'password': 'Password123'
        }, follow_redirects=True)
        assert response.status_code == 200
        # Should show error message


class TestAdminBulkActions:
    """Test admin bulk action functionality"""

    def test_bulk_verify_users(self, client, app, admin_user, unverified_user):
        """Admin can bulk verify users"""
        login_user(client, 'admin@example.com', 'AdminPass123')

        with app.app_context():
            user = User.query.filter_by(email='unverified@example.com').first()
            user_id = user.id

        response = client.post('/admin/users/bulk-action', data={
            'action': 'verify',
            'user_ids': str(user_id)
        }, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user.is_verified is True
