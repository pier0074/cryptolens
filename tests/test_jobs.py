"""
Tests for Background Jobs
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestQueueConfiguration:
    """Tests for queue configuration"""

    def test_queue_names_defined(self):
        """Test queue names are properly defined"""
        from app.jobs.queue import QUEUE_HIGH, QUEUE_DEFAULT, QUEUE_LOW

        assert QUEUE_HIGH == 'high'
        assert QUEUE_DEFAULT == 'default'
        assert QUEUE_LOW == 'low'

    def test_timeout_values_defined(self):
        """Test timeout values are defined"""
        from app.jobs.queue import DEFAULT_TIMEOUT, NOTIFICATION_TIMEOUT

        assert DEFAULT_TIMEOUT == 300  # 5 minutes
        assert NOTIFICATION_TIMEOUT == 60  # 1 minute

    @patch('app.jobs.queue.Redis')
    def test_get_redis_connection(self, mock_redis):
        """Test Redis connection factory"""
        from app.jobs.queue import get_redis_connection

        mock_redis.from_url.return_value = MagicMock()
        conn = get_redis_connection()

        mock_redis.from_url.assert_called_once()

    @patch('app.jobs.queue.get_redis_connection')
    @patch('app.jobs.queue.Queue')
    def test_get_queue(self, mock_queue_class, mock_redis):
        """Test queue factory"""
        from app.jobs.queue import get_queue, QUEUE_DEFAULT

        mock_redis.return_value = MagicMock()
        get_queue(QUEUE_DEFAULT)

        mock_queue_class.assert_called_once_with(QUEUE_DEFAULT, connection=mock_redis.return_value)

    @patch('app.jobs.queue.get_queue')
    def test_enqueue_job(self, mock_get_queue):
        """Test job enqueueing"""
        from app.jobs.queue import enqueue_job

        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = MagicMock(id='test-job-123')
        mock_get_queue.return_value = mock_queue

        def test_func():
            pass

        job = enqueue_job(test_func, queue_name='default')

        assert job is not None
        mock_queue.enqueue.assert_called_once()

    @patch('app.jobs.queue.get_queue')
    def test_enqueue_job_failure(self, mock_get_queue):
        """Test job enqueueing handles failures"""
        from app.jobs.queue import enqueue_job

        mock_get_queue.side_effect = Exception("Redis connection failed")

        def test_func():
            pass

        job = enqueue_job(test_func)

        assert job is None


class TestNotificationJobs:
    """Tests for notification background jobs"""

    def test_send_signal_notification_job_structure(self, app):
        """Test signal notification job with missing signal"""
        from app.jobs.notifications import send_signal_notification_job

        with app.app_context():
            # Test with non-existent signal
            result = send_signal_notification_job(signal_id=999999)
            assert result.get('error') == 'Signal not found'

    def test_send_bulk_notifications_job_empty(self, app):
        """Test bulk notification job with empty list"""
        from app.jobs.notifications import send_bulk_notifications_job

        with app.app_context():
            result = send_bulk_notifications_job([])
            assert result['total'] == 0
            assert result['success'] == 0


class TestScannerJobs:
    """Tests for scanner background jobs"""

    def test_scan_patterns_job_no_symbols(self, app):
        """Test pattern scan with no active symbols"""
        from app.jobs.scanner import scan_patterns_job

        with app.app_context():
            # Test with non-existent symbol
            result = scan_patterns_job(symbol_id=999999)
            assert 'error' in result

    def test_process_signals_job_import_check(self):
        """Test signal processing job module imports correctly"""
        # Just verify the module structure is correct
        from app.jobs.scanner import process_signals_job
        assert callable(process_signals_job)


class TestMaintenanceJobs:
    """Tests for maintenance background jobs"""

    def test_cleanup_old_data_job(self, app):
        """Test cleanup job execution"""
        from app.jobs.maintenance import cleanup_old_data_job

        with app.app_context():
            result = cleanup_old_data_job()

            assert 'logs_deleted' in result
            assert 'patterns_deleted' in result
            assert 'notifications_deleted' in result
            assert 'elapsed_seconds' in result

    def test_update_stats_cache_job(self, app):
        """Test stats cache update job"""
        from app.jobs.maintenance import update_stats_cache_job

        with app.app_context():
            result = update_stats_cache_job()

            assert result['global_stats_updated'] is True
            assert 'symbol_stats_updated' in result
            assert 'elapsed_seconds' in result

    def test_expire_patterns_job(self, app):
        """Test pattern expiry job"""
        from app.jobs.maintenance import expire_patterns_job

        with app.app_context():
            result = expire_patterns_job()

            assert 'patterns_checked' in result
            assert 'patterns_expired' in result
            assert 'elapsed_seconds' in result


class TestQueueHelpers:
    """Tests for queue helper functions"""

    @patch('app.jobs.queue.enqueue_job')
    def test_enqueue_notification(self, mock_enqueue):
        """Test notification enqueueing helper"""
        from app.jobs.queue import enqueue_notification, QUEUE_HIGH

        mock_enqueue.return_value = MagicMock(id='job-123')

        job = enqueue_notification(signal_id=42, test_mode=True)

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs['queue_name'] == QUEUE_HIGH

    @patch('app.jobs.queue.enqueue_job')
    def test_enqueue_pattern_scan(self, mock_enqueue):
        """Test pattern scan enqueueing helper"""
        from app.jobs.queue import enqueue_pattern_scan, QUEUE_DEFAULT

        mock_enqueue.return_value = MagicMock(id='job-123')

        job = enqueue_pattern_scan(symbol_id=1)

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs['queue_name'] == QUEUE_DEFAULT

    @patch('app.jobs.queue.enqueue_job')
    def test_enqueue_cleanup(self, mock_enqueue):
        """Test cleanup enqueueing helper"""
        from app.jobs.queue import enqueue_cleanup, QUEUE_LOW

        mock_enqueue.return_value = MagicMock(id='job-123')

        job = enqueue_cleanup()

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs['queue_name'] == QUEUE_LOW

    @patch('app.jobs.queue.get_redis_connection')
    @patch('app.jobs.queue.Queue')
    def test_get_queue_stats(self, mock_queue_class, mock_redis):
        """Test queue stats retrieval"""
        from app.jobs.queue import get_queue_stats

        mock_queue = MagicMock()
        mock_queue.count = 5
        mock_queue.failed_job_registry.count = 1
        mock_queue.scheduled_job_registry.count = 2
        mock_queue.started_job_registry.count = 1
        mock_queue_class.return_value = mock_queue

        stats = get_queue_stats()

        assert 'high' in stats
        assert 'default' in stats
        assert 'low' in stats
        assert stats['high']['count'] == 5
