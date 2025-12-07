"""
Redis Queue Configuration and Helpers
"""
import os
import logging
from typing import Optional, Callable, Any
from redis import Redis
from rq import Queue
from rq.job import Job

logger = logging.getLogger('cryptolens')

# Queue names
QUEUE_HIGH = 'high'      # Urgent notifications, real-time updates
QUEUE_DEFAULT = 'default'  # Regular notifications, signal processing
QUEUE_LOW = 'low'        # Cleanup, stats updates, non-urgent tasks

# Default job timeout (seconds)
DEFAULT_TIMEOUT = 300  # 5 minutes
NOTIFICATION_TIMEOUT = 60  # 1 minute for notifications


def get_redis_connection() -> Redis:
    """Get Redis connection for queues."""
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return Redis.from_url(redis_url)


def get_queue(name: str = QUEUE_DEFAULT) -> Queue:
    """Get a queue by name."""
    return Queue(name, connection=get_redis_connection())


def enqueue_job(
    func: Callable,
    *args,
    queue_name: str = QUEUE_DEFAULT,
    timeout: int = DEFAULT_TIMEOUT,
    retry: int = 3,
    **kwargs
) -> Optional[Job]:
    """
    Enqueue a job for background processing.

    Args:
        func: The function to execute
        *args: Positional arguments for the function
        queue_name: Queue to use (high, default, low)
        timeout: Job timeout in seconds
        retry: Number of retries on failure
        **kwargs: Keyword arguments for the function

    Returns:
        Job object or None if queueing fails
    """
    try:
        queue = get_queue(queue_name)
        job = queue.enqueue(
            func,
            *args,
            job_timeout=timeout,
            retry=retry,
            **kwargs
        )
        logger.debug(f"Enqueued job {job.id} to {queue_name} queue")
        return job
    except Exception as e:
        logger.error(f"Failed to enqueue job: {e}")
        return None


def enqueue_notification(signal_id: int, test_mode: bool = False,
                         current_price: float = None) -> Optional[Job]:
    """
    Enqueue a signal notification job (high priority).

    Args:
        signal_id: ID of the signal
        test_mode: Whether in test mode
        current_price: Current market price

    Returns:
        Job object or None
    """
    from app.jobs.notifications import send_signal_notification_job

    return enqueue_job(
        send_signal_notification_job,
        signal_id,
        test_mode=test_mode,
        current_price=current_price,
        queue_name=QUEUE_HIGH,
        timeout=NOTIFICATION_TIMEOUT
    )


def enqueue_pattern_scan(symbol_id: int = None,
                         timeframes: list = None) -> Optional[Job]:
    """
    Enqueue a pattern scan job.

    Args:
        symbol_id: Optional specific symbol
        timeframes: Optional specific timeframes

    Returns:
        Job object or None
    """
    from app.jobs.scanner import scan_patterns_job

    return enqueue_job(
        scan_patterns_job,
        symbol_id=symbol_id,
        timeframes=timeframes,
        queue_name=QUEUE_DEFAULT
    )


def enqueue_signal_processing(min_confluence: int = 2,
                              notify: bool = True) -> Optional[Job]:
    """
    Enqueue signal processing job.

    Args:
        min_confluence: Minimum confluence score
        notify: Whether to send notifications

    Returns:
        Job object or None
    """
    from app.jobs.scanner import process_signals_job

    return enqueue_job(
        process_signals_job,
        min_confluence=min_confluence,
        notify=notify,
        queue_name=QUEUE_DEFAULT
    )


def enqueue_cleanup() -> Optional[Job]:
    """Enqueue cleanup job (low priority)."""
    from app.jobs.maintenance import cleanup_old_data_job

    return enqueue_job(
        cleanup_old_data_job,
        queue_name=QUEUE_LOW
    )


def enqueue_stats_update() -> Optional[Job]:
    """Enqueue stats cache update job (low priority)."""
    from app.jobs.maintenance import update_stats_cache_job

    return enqueue_job(
        update_stats_cache_job,
        queue_name=QUEUE_LOW
    )


def get_queue_stats() -> dict:
    """Get statistics about all queues."""
    redis = get_redis_connection()
    stats = {}

    for queue_name in [QUEUE_HIGH, QUEUE_DEFAULT, QUEUE_LOW]:
        queue = Queue(queue_name, connection=redis)
        stats[queue_name] = {
            'count': queue.count,
            'failed': queue.failed_job_registry.count,
            'scheduled': queue.scheduled_job_registry.count,
            'started': queue.started_job_registry.count,
        }

    return stats


def clear_failed_jobs(queue_name: str = None) -> int:
    """
    Clear failed jobs from queue(s).

    Args:
        queue_name: Specific queue or None for all

    Returns:
        Number of jobs cleared
    """
    redis = get_redis_connection()
    queues = [queue_name] if queue_name else [QUEUE_HIGH, QUEUE_DEFAULT, QUEUE_LOW]
    total_cleared = 0

    for name in queues:
        queue = Queue(name, connection=redis)
        count = queue.failed_job_registry.count
        queue.failed_job_registry.remove_jobs()
        total_cleared += count

    return total_cleared
