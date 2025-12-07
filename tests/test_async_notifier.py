"""
Tests for Async Notification Service
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


class TestAsyncNotificationResult:
    """Tests for AsyncNotificationResult class"""

    def test_success_result(self):
        """Test creating a successful result"""
        from app.services.async_notifier import AsyncNotificationResult

        result = AsyncNotificationResult(user_id=1, success=True)
        assert result.user_id == 1
        assert result.success is True
        assert result.error is None

    def test_failed_result(self):
        """Test creating a failed result"""
        from app.services.async_notifier import AsyncNotificationResult

        result = AsyncNotificationResult(user_id=2, success=False, error="Connection timeout")
        assert result.user_id == 2
        assert result.success is False
        assert result.error == "Connection timeout"


class TestSendNotificationAsync:
    """Tests for send_notification_async function"""

    @pytest.mark.asyncio
    async def test_successful_send(self):
        """Test successful async notification send"""
        from app.services.async_notifier import send_notification_async

        # Mock aiohttp session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        result = await send_notification_async(
            session=mock_session,
            topic="test-topic",
            title="Test Title",
            message="Test Message",
            priority=3,
            tags=["test"]
        )

        assert result is True
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_send_non_200(self):
        """Test failed send with non-200 status"""
        from app.services.async_notifier import send_notification_async

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        result = await send_notification_async(
            session=mock_session,
            topic="test-topic",
            title="Test",
            message="Test"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test timeout is handled gracefully"""
        from app.services.async_notifier import send_notification_async

        mock_session = MagicMock()
        mock_session.post.side_effect = asyncio.TimeoutError()

        result = await send_notification_async(
            session=mock_session,
            topic="test-topic",
            title="Test",
            message="Test"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test connection error is handled gracefully"""
        import aiohttp
        from app.services.async_notifier import send_notification_async

        mock_session = MagicMock()
        mock_session.post.side_effect = aiohttp.ClientError()

        result = await send_notification_async(
            session=mock_session,
            topic="test-topic",
            title="Test",
            message="Test"
        )

        assert result is False


class TestSendToUserAsync:
    """Tests for send_to_user_async function"""

    @pytest.mark.asyncio
    async def test_successful_user_send(self):
        """Test successful send to user returns correct result"""
        from app.services.async_notifier import send_to_user_async

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        result = await send_to_user_async(
            session=mock_session,
            user_id=42,
            topic="user-42-topic",
            title="Test",
            message="Test message"
        )

        assert result.user_id == 42
        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_failed_user_send(self):
        """Test failed send to user returns error"""
        from app.services.async_notifier import send_to_user_async

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        result = await send_to_user_async(
            session=mock_session,
            user_id=42,
            topic="user-42-topic",
            title="Test",
            message="Test message"
        )

        assert result.user_id == 42
        assert result.success is False
        assert result.error == "Failed to send"


class TestSendToAllSubscribersAsync:
    """Tests for send_to_all_subscribers_async function"""

    @pytest.mark.asyncio
    async def test_empty_subscribers(self):
        """Test with empty subscriber list"""
        from app.services.async_notifier import send_to_all_subscribers_async

        result = await send_to_all_subscribers_async(
            subscribers=[],
            title="Test",
            message="Test"
        )

        assert result['total'] == 0
        assert result['success'] == 0
        assert result['failed'] == 0
        assert result['results'] == []

    def test_sync_wrapper_with_empty_list(self):
        """Test synchronous wrapper with empty subscriber list"""
        from app.services.async_notifier import notify_subscribers_async

        result = notify_subscribers_async(
            subscribers=[],
            title="Test",
            message="Test"
        )

        assert result['total'] == 0
        assert result['success'] == 0
        assert result['failed'] == 0


class TestNotifySubscribersAsync:
    """Tests for synchronous wrapper function"""

    @patch('app.services.async_notifier.asyncio.run')
    def test_wrapper_calls_async_function(self, mock_run):
        """Test that sync wrapper calls async function correctly"""
        from app.services.async_notifier import notify_subscribers_async

        mock_run.return_value = {'total': 2, 'success': 2, 'failed': 0, 'results': []}

        subscribers = [
            {'user_id': 1, 'ntfy_topic': 'topic-1'},
            {'user_id': 2, 'ntfy_topic': 'topic-2'},
        ]

        result = notify_subscribers_async(
            subscribers=subscribers,
            title="Test",
            message="Test"
        )

        assert mock_run.called
        assert result['total'] == 2
        assert result['success'] == 2


class TestConnectionPooling:
    """Tests for connection pool configuration"""

    def test_connector_limits_defined(self):
        """Test that connection pool limits are defined"""
        from app.services.async_notifier import CONNECTOR_LIMIT, CONNECTOR_LIMIT_PER_HOST

        assert CONNECTOR_LIMIT == 100
        assert CONNECTOR_LIMIT_PER_HOST == 30
