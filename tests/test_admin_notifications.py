"""
Tests for admin notification features.

Tests cover:
- Unlock locked accounts
- Bulk user management actions
- Notification templates CRUD
- Broadcast notifications
- Scheduled notifications
"""
import pytest
from datetime import datetime, timezone, timedelta
from app import db
from app.models import (
    User, NotificationTemplate, ScheduledNotification, NOTIFICATION_TEMPLATE_TYPES, NOTIFICATION_TARGETS
)


class TestUnlockLockedAccounts:
    """Test unlocking locked user accounts"""

    @pytest.fixture
    def locked_user(self, app):
        """Create a locked user"""
        with app.app_context():
            locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
            user = User(
                email='locked@test.com',
                username='lockeduser',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_locked12345',
                failed_attempts=5,
                locked_until=locked_until
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()
            return user.id

    def test_unlock_user_clears_lockout(self, client, app, admin_user, locked_user):
        """Admin can unlock a locked user"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post(f'/admin/users/{locked_user}/unlock')
        assert response.status_code == 302

        with app.app_context():
            user = db.session.get(User, locked_user)
            assert user.failed_attempts == 0
            assert user.locked_until is None

    def test_locked_user_filter(self, client, app, admin_user, locked_user):
        """Admin can filter users by locked status"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/users?status=locked')
        assert response.status_code == 200
        assert b'lockeduser' in response.data


class TestBulkUserActions:
    """Test bulk user management actions"""

    @pytest.fixture
    def test_users(self, app):
        """Create multiple test users for bulk actions"""
        with app.app_context():
            user_ids = []
            for i in range(3):
                user = User(
                    email=f'bulktest{i}@test.com',
                    username=f'bulkuser{i}',
                    is_active=False,
                    is_verified=False,
                    ntfy_topic=f'cl_bulk{i}12345'
                )
                user.set_password('TestPass123')
                db.session.add(user)
                db.session.commit()
                user_ids.append(user.id)
            return user_ids

    def test_bulk_activate_users(self, client, app, admin_user, test_users):
        """Admin can bulk activate users"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/bulk-action', data={
            'user_ids': test_users,
            'action': 'activate'
        })
        assert response.status_code == 302

        with app.app_context():
            for user_id in test_users:
                user = db.session.get(User, user_id)
                assert user.is_active is True

    def test_bulk_verify_users(self, client, app, admin_user, test_users):
        """Admin can bulk verify users"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/bulk-action', data={
            'user_ids': test_users,
            'action': 'verify'
        })
        assert response.status_code == 302

        with app.app_context():
            for user_id in test_users:
                user = db.session.get(User, user_id)
                assert user.is_verified is True

    def test_bulk_action_no_users_selected(self, client, admin_user):
        """Bulk action with no users shows error"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/bulk-action', data={
            'action': 'activate'
        }, follow_redirects=True)
        assert b'No users selected' in response.data

    def test_bulk_action_no_action_selected(self, client, admin_user, test_users):
        """Bulk action with no action shows error"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/users/bulk-action', data={
            'user_ids': test_users
        }, follow_redirects=True)
        assert b'No action selected' in response.data


class TestNotificationTemplates:
    """Test notification template CRUD operations"""

    def test_create_template(self, client, app, admin_user):
        """Admin can create a notification template"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.post('/admin/notifications/templates/create', data={
            'name': 'Test Template',
            'template_type': 'announcement',
            'title': 'Test Title',
            'message': 'Test message content',
            'priority': '3',
            'tags': 'test,announcement'
        })
        assert response.status_code == 302

        with app.app_context():
            template = NotificationTemplate.query.filter_by(name='Test Template').first()
            assert template is not None
            assert template.template_type == 'announcement'
            assert template.title == 'Test Title'

    def test_edit_template(self, client, app, admin_user):
        """Admin can edit a notification template"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Create template first
        with app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            template = NotificationTemplate(
                name='Edit Test',
                template_type='update',
                title='Original Title',
                message='Original message',
                created_by=admin.id
            )
            db.session.add(template)
            db.session.commit()
            template_id = template.id

        # Edit it
        response = client.post(f'/admin/notifications/templates/{template_id}/edit', data={
            'name': 'Edit Test Updated',
            'template_type': 'downtime',
            'title': 'Updated Title',
            'message': 'Updated message',
            'priority': '4',
            'is_active': 'on'
        })
        assert response.status_code == 302

        with app.app_context():
            template = db.session.get(NotificationTemplate, template_id)
            assert template.name == 'Edit Test Updated'
            assert template.template_type == 'downtime'
            assert template.title == 'Updated Title'

    def test_delete_template(self, client, app, admin_user):
        """Admin can delete a notification template"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Create template first
        with app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            template = NotificationTemplate(
                name='Delete Test',
                template_type='promotion',
                title='To Delete',
                message='Will be deleted',
                created_by=admin.id
            )
            db.session.add(template)
            db.session.commit()
            template_id = template.id

        # Delete it
        response = client.post(f'/admin/notifications/templates/{template_id}/delete')
        assert response.status_code == 302

        with app.app_context():
            template = db.session.get(NotificationTemplate, template_id)
            assert template is None

    def test_templates_list(self, client, app, admin_user):
        """Admin can view templates list"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/notifications/templates')
        assert response.status_code == 200


class TestBroadcastNotifications:
    """Test broadcast notification sending"""

    def test_broadcast_page_loads(self, client, admin_user):
        """Broadcast page loads for admin"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/notifications/broadcast')
        assert response.status_code == 200
        assert b'Send Broadcast' in response.data

    def test_notifications_dashboard(self, client, admin_user):
        """Notifications dashboard loads for admin"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/notifications')
        assert response.status_code == 200
        assert b'Notification Management' in response.data

    def test_audience_count_api(self, client, app, admin_user):
        """Audience count API returns user count"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/api/notifications/audience-count?target=all')
        assert response.status_code == 200
        data = response.get_json()
        assert 'count' in data
        assert 'target' in data


class TestScheduledNotifications:
    """Test scheduled notification management"""

    def test_schedule_page_loads(self, client, admin_user):
        """Schedule notification page loads for admin"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        response = client.get('/admin/notifications/schedule')
        assert response.status_code == 200
        assert b'Schedule Notification' in response.data

    def test_cancel_scheduled_notification(self, client, app, admin_user):
        """Admin can cancel a scheduled notification"""
        from tests.test_routes import login_user
        login_user(client, 'admin@example.com', 'AdminPass123')

        # Create scheduled notification
        with app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            scheduled = ScheduledNotification(
                title='Cancel Test',
                message='Will be cancelled',
                target_audience='all',
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1),
                created_by=admin.id,
                status='pending'
            )
            db.session.add(scheduled)
            db.session.commit()
            scheduled_id = scheduled.id

        # Cancel it
        response = client.post(f'/admin/notifications/scheduled/{scheduled_id}/cancel')
        assert response.status_code == 302

        with app.app_context():
            scheduled = db.session.get(ScheduledNotification, scheduled_id)
            assert scheduled.status == 'cancelled'


class TestNotificationModels:
    """Test notification model properties"""

    def test_template_types_defined(self):
        """Notification template types are defined"""
        assert 'promotion' in NOTIFICATION_TEMPLATE_TYPES
        assert 'downtime' in NOTIFICATION_TEMPLATE_TYPES
        assert 'update' in NOTIFICATION_TEMPLATE_TYPES

    def test_notification_targets_defined(self):
        """Notification targets are defined"""
        assert 'all' in NOTIFICATION_TARGETS
        assert 'free' in NOTIFICATION_TARGETS
        assert 'pro' in NOTIFICATION_TARGETS
        assert 'premium' in NOTIFICATION_TARGETS

    def test_scheduled_notification_is_due(self, app):
        """ScheduledNotification.is_due property works correctly"""
        with app.app_context():
            # Past time - should be due
            past = ScheduledNotification(
                title='Past',
                message='msg',
                target_audience='all',
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
                created_by=1,
                status='pending'
            )
            assert past.is_due is True

            # Future time - should not be due
            future = ScheduledNotification(
                title='Future',
                message='msg',
                target_audience='all',
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1),
                created_by=1,
                status='pending'
            )
            assert future.is_due is False

            # Already sent - should not be due
            sent = ScheduledNotification(
                title='Sent',
                message='msg',
                target_audience='all',
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
                created_by=1,
                status='sent'
            )
            assert sent.is_due is False
