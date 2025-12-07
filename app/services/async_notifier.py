"""
Async Notification Service
Provides concurrent notification delivery using asyncio and aiohttp
"""
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import json

from app.config import Config
from app.constants import HTTP_TIMEOUT_DEFAULT, CIRCUIT_BREAKER_FAIL_MAX


# Connection pool settings
CONNECTOR_LIMIT = 100  # Max simultaneous connections
CONNECTOR_LIMIT_PER_HOST = 30  # Max connections per host


class AsyncNotificationResult:
    """Result of an async notification attempt"""
    def __init__(self, user_id: int, success: bool, error: Optional[str] = None):
        self.user_id = user_id
        self.success = success
        self.error = error


async def send_notification_async(
    session: aiohttp.ClientSession,
    topic: str,
    title: str,
    message: str,
    priority: int = 3,
    tags: List[str] = None
) -> bool:
    """
    Send a single notification asynchronously.

    Args:
        session: aiohttp ClientSession with connection pooling
        topic: NTFY topic
        title: Notification title
        message: Notification body
        priority: NTFY priority (1-5)
        tags: List of tags

    Returns:
        True if successful
    """
    if tags is None:
        tags = ["chart", "money"]

    try:
        async with session.post(
            Config.NTFY_URL,
            json={
                "topic": topic,
                "title": title,
                "message": message,
                "priority": priority,
                "tags": tags
            },
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_DEFAULT)
        ) as response:
            return response.status == 200
    except asyncio.TimeoutError:
        return False
    except aiohttp.ClientError:
        return False
    except Exception:
        return False


async def send_to_user_async(
    session: aiohttp.ClientSession,
    user_id: int,
    topic: str,
    title: str,
    message: str,
    priority: int = 3,
    tags: List[str] = None
) -> AsyncNotificationResult:
    """
    Send notification to a specific user asynchronously.

    Args:
        session: aiohttp ClientSession
        user_id: User ID for tracking
        topic: User's NTFY topic
        title: Notification title
        message: Notification body
        priority: NTFY priority
        tags: List of tags

    Returns:
        AsyncNotificationResult with success status
    """
    try:
        success = await send_notification_async(
            session, topic, title, message, priority, tags
        )
        return AsyncNotificationResult(
            user_id=user_id,
            success=success,
            error=None if success else "Failed to send"
        )
    except Exception as e:
        return AsyncNotificationResult(
            user_id=user_id,
            success=False,
            error=str(e)
        )


async def send_to_all_subscribers_async(
    subscribers: List[Dict[str, Any]],
    title: str,
    message: str,
    priority: int = 3,
    tags: List[str] = None
) -> Dict[str, Any]:
    """
    Send notifications to all subscribers concurrently.

    Args:
        subscribers: List of dicts with 'user_id' and 'ntfy_topic'
        title: Notification title
        message: Notification body
        priority: NTFY priority
        tags: List of tags

    Returns:
        Dict with 'total', 'success', 'failed', 'results'
    """
    if not subscribers:
        return {'total': 0, 'success': 0, 'failed': 0, 'results': []}

    if tags is None:
        tags = ["chart", "money"]

    # Create connection pool with limits
    connector = aiohttp.TCPConnector(
        limit=CONNECTOR_LIMIT,
        limit_per_host=CONNECTOR_LIMIT_PER_HOST
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        # Create tasks for all subscribers
        tasks = [
            send_to_user_async(
                session=session,
                user_id=sub['user_id'],
                topic=sub['ntfy_topic'],
                title=title,
                message=message,
                priority=priority,
                tags=tags
            )
            for sub in subscribers
        ]

        # Execute all concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    success_count = 0
    failed_count = 0
    result_list = []

    for result in results:
        if isinstance(result, Exception):
            failed_count += 1
            result_list.append(AsyncNotificationResult(
                user_id=0, success=False, error=str(result)
            ))
        elif result.success:
            success_count += 1
            result_list.append(result)
        else:
            failed_count += 1
            result_list.append(result)

    return {
        'total': len(subscribers),
        'success': success_count,
        'failed': failed_count,
        'results': result_list
    }


def notify_subscribers_async(
    subscribers: List[Dict[str, Any]],
    title: str,
    message: str,
    priority: int = 3,
    tags: List[str] = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for async notification sending.
    Use this from synchronous code to send notifications concurrently.

    Args:
        subscribers: List of dicts with 'user_id' and 'ntfy_topic'
        title: Notification title
        message: Notification body
        priority: NTFY priority
        tags: List of tags

    Returns:
        Dict with 'total', 'success', 'failed', 'results'
    """
    return asyncio.run(
        send_to_all_subscribers_async(
            subscribers, title, message, priority, tags
        )
    )


async def send_batch_notifications_async(
    notifications: List[Dict[str, Any]]
) -> List[AsyncNotificationResult]:
    """
    Send a batch of different notifications concurrently.
    Each notification can have different content.

    Args:
        notifications: List of dicts with:
            - user_id: int
            - topic: str
            - title: str
            - message: str
            - priority: int (optional)
            - tags: List[str] (optional)

    Returns:
        List of AsyncNotificationResult
    """
    if not notifications:
        return []

    connector = aiohttp.TCPConnector(
        limit=CONNECTOR_LIMIT,
        limit_per_host=CONNECTOR_LIMIT_PER_HOST
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            send_to_user_async(
                session=session,
                user_id=n['user_id'],
                topic=n['topic'],
                title=n['title'],
                message=n['message'],
                priority=n.get('priority', 3),
                tags=n.get('tags', ["chart", "money"])
            )
            for n in notifications
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

    processed = []
    for result in results:
        if isinstance(result, Exception):
            processed.append(AsyncNotificationResult(
                user_id=0, success=False, error=str(result)
            ))
        else:
            processed.append(result)

    return processed
