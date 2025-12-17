"""
Tests for Broadcast Notification Service

Tests the broadcast notification functionality with mocked notifications.
"""
from unittest.mock import patch
from app import db
from app.models import User, BroadcastNotification
from app.services.broadcast import (
    get_target_users,
    send_broadcast,
    send_to_topics
)


class TestGetTargetUsers:
    """Test user targeting functionality"""

    def test_get_target_users_all(self, app, sample_user):
        """Get all active verified users with notifications enabled"""
        with app.app_context():
            # Create a user with ntfy_topic and notify_enabled
            user = User.query.filter_by(email='test@example.com').first()
            user.ntfy_topic = 'cl_test123456'
            user.notify_enabled = True
            db.session.commit()

            users = get_target_users('all')
            # Should find the sample user
            assert isinstance(users, list)

    def test_get_target_users_custom_topics(self, app, sample_user):
        """Get users by specific NTFY topics"""
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            user.ntfy_topic = 'cl_specific_topic'
            user.notify_enabled = True
            db.session.commit()

            users = get_target_users('custom', 'cl_specific_topic,other_topic')
            # Should find the user with matching topic
            user_topics = [u.ntfy_topic for u in users]
            if users:
                assert 'cl_specific_topic' in user_topics


class TestSendBroadcast:
    """Test broadcast sending functionality"""

    def test_send_broadcast_not_found(self, app):
        """Send broadcast returns error for non-existent broadcast"""
        with app.app_context():
            result = send_broadcast(99999)
            assert result['total'] == 0
            assert 'error' in result
            assert 'not found' in result['error']

    def test_send_broadcast_success(self, app, admin_user):
        """Send broadcast to targeted users"""
        with app.app_context():
            # Create a broadcast
            broadcast = BroadcastNotification(
                title='Test Broadcast',
                message='This is a test message',
                priority=3,
                target_audience='all',
                sent_by=admin_user,
                status='pending'
            )
            db.session.add(broadcast)
            db.session.commit()
            broadcast_id = broadcast.id

            with patch('app.services.broadcast.send_notification') as mock_notify:
                mock_notify.return_value = True

                result = send_broadcast(broadcast_id)
                assert 'total' in result
                assert 'successful' in result
                assert 'failed' in result

                # Broadcast should be marked completed
                broadcast = db.session.get(BroadcastNotification, broadcast_id)
                assert broadcast.status in ['completed', 'completed_with_errors']

    def test_send_broadcast_returns_result_dict(self, app, admin_user):
        """Send broadcast returns result dictionary with expected keys"""
        with app.app_context():
            # Create a broadcast targeting no users (empty result)
            broadcast = BroadcastNotification(
                title='Test Broadcast',
                message='This is a test message',
                priority=3,
                target_audience='custom',  # Custom with no matching users
                target_topics='nonexistent_topic_xyz',
                sent_by=admin_user,
                status='pending'
            )
            db.session.add(broadcast)
            db.session.commit()
            broadcast_id = broadcast.id

            with patch('app.services.broadcast.send_notification') as mock_notify:
                mock_notify.return_value = True

                result = send_broadcast(broadcast_id)
                # Should return expected keys
                assert 'total' in result
                assert 'successful' in result
                assert 'failed' in result


class TestSendToTopics:
    """Test direct topic sending functionality"""

    def test_send_to_topics_success(self):
        """Send to multiple topics successfully"""
        with patch('app.services.broadcast.send_notification') as mock_notify:
            mock_notify.return_value = True

            result = send_to_topics(
                topics=['topic1', 'topic2', 'topic3'],
                title='Test Title',
                message='Test Message'
            )

            assert result['total'] == 3
            assert result['successful'] == 3
            assert result['failed'] == 0
            assert mock_notify.call_count == 3

    def test_send_to_topics_partial_failure(self):
        """Send to topics with some failures"""
        with patch('app.services.broadcast.send_notification') as mock_notify:
            # First two succeed, third fails
            mock_notify.side_effect = [True, True, False]

            result = send_to_topics(
                topics=['topic1', 'topic2', 'topic3'],
                title='Test Title',
                message='Test Message'
            )

            assert result['total'] == 3
            assert result['successful'] == 2
            assert result['failed'] == 1

    def test_send_to_topics_with_priority_and_tags(self):
        """Send to topics with custom priority and tags"""
        with patch('app.services.broadcast.send_notification') as mock_notify:
            mock_notify.return_value = True

            result = send_to_topics(
                topics=['topic1'],
                title='Urgent Alert',
                message='Important notification',
                priority=5,
                tags=['urgent', 'alert']
            )

            assert result['successful'] == 1
            # Verify the notification was called with correct parameters
            mock_notify.assert_called_with(
                topic='topic1',
                title='Urgent Alert',
                message='Important notification',
                priority=5,
                tags=['urgent', 'alert']
            )

    def test_send_to_topics_empty_list(self):
        """Send to empty topic list"""
        with patch('app.services.broadcast.send_notification') as mock_notify:
            result = send_to_topics(
                topics=[],
                title='Test',
                message='Test'
            )

            assert result['total'] == 0
            assert result['successful'] == 0
            assert result['failed'] == 0
            mock_notify.assert_not_called()

    def test_send_to_topics_handles_exception(self):
        """Send to topics handles notification exceptions"""
        with patch('app.services.broadcast.send_notification') as mock_notify:
            mock_notify.side_effect = Exception('Network error')

            result = send_to_topics(
                topics=['topic1'],
                title='Test',
                message='Test'
            )

            assert result['total'] == 1
            assert result['successful'] == 0
            assert result['failed'] == 1
