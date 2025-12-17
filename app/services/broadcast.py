"""
Broadcast Notification Service

Handles sending notifications to multiple users based on targeting criteria.
"""
from datetime import datetime, timezone
from app import db
from app.models import (
    User, Subscription, BroadcastNotification, ScheduledNotification
)
from app.services.notifier import send_notification
import logging

logger = logging.getLogger(__name__)


def get_target_users(target_audience: str, custom_topics: str = None) -> list:
    """
    Get list of users matching the target audience.

    Args:
        target_audience: 'all', 'free', 'pro', 'premium', 'verified', 'active'
        custom_topics: Comma-separated list of NTFY topics for custom targeting

    Returns:
        List of User objects
    """
    # Base query: active, verified users with ntfy_topic
    query = User.query.filter(
        User.is_active.is_(True),
        User.is_verified.is_(True),
        User.ntfy_topic.isnot(None),
        User.notify_enabled.is_(True)
    )

    if target_audience == 'free':
        query = query.join(Subscription).filter(Subscription.plan == 'free')
    elif target_audience == 'pro':
        query = query.join(Subscription).filter(Subscription.plan == 'pro')
    elif target_audience == 'premium':
        query = query.join(Subscription).filter(Subscription.plan == 'premium')
    elif target_audience == 'custom' and custom_topics:
        topics = [t.strip() for t in custom_topics.split(',')]
        query = query.filter(User.ntfy_topic.in_(topics))
    # 'all', 'verified', 'active' use the base query

    return query.all()


def send_broadcast(broadcast_id: int) -> dict:
    """
    Send a broadcast notification to all targeted users.

    Args:
        broadcast_id: ID of the BroadcastNotification record

    Returns:
        Dict with results: {'total': int, 'successful': int, 'failed': int}
    """
    broadcast = db.session.get(BroadcastNotification, broadcast_id)
    if not broadcast:
        return {'total': 0, 'successful': 0, 'failed': 0, 'error': 'Broadcast not found'}

    # Get target users
    users = get_target_users(broadcast.target_audience, broadcast.target_topics)
    broadcast.total_recipients = len(users)
    broadcast.status = 'sending'
    db.session.commit()

    successful = 0
    failed = 0
    errors = []

    for user in users:
        try:
            # Validate topic format
            if not user.ntfy_topic or len(user.ntfy_topic) < 3:
                errors.append(f"User {user.username}: invalid topic '{user.ntfy_topic}'")
                failed += 1
                continue

            success = send_notification(
                topic=user.ntfy_topic,
                title=broadcast.title,
                message=broadcast.message,
                priority=broadcast.priority,
                tags=broadcast.tags.split(',') if broadcast.tags else None
            )
            if success:
                successful += 1
            else:
                errors.append(f"User {user.username} ({user.ntfy_topic}): send failed")
                failed += 1
        except Exception as e:
            error_msg = f"User {user.username} ({user.ntfy_topic}): {str(e)}"
            logger.error(f"Failed to send broadcast: {error_msg}")
            errors.append(error_msg)
            failed += 1

    # Update broadcast record
    broadcast.successful = successful
    broadcast.failed = failed
    broadcast.status = 'completed' if failed == 0 else 'completed_with_errors'
    db.session.commit()

    # Log errors for debugging
    if errors:
        logger.warning(f"Broadcast {broadcast_id} errors: {'; '.join(errors[:5])}")

    return {
        'total': len(users),
        'successful': successful,
        'failed': failed,
        'errors': errors[:10]  # Return first 10 errors for debugging
    }


def process_scheduled_notifications():
    """
    Process all due scheduled notifications.
    This should be called by a cron job or background task.

    Returns:
        Number of notifications processed
    """
    # Find all pending notifications that are due
    now = datetime.now(timezone.utc)
    due_notifications = ScheduledNotification.query.filter(
        ScheduledNotification.status == 'pending',
        ScheduledNotification.scheduled_for <= now
    ).all()

    processed = 0

    for scheduled in due_notifications:
        try:
            # Create broadcast record
            broadcast = BroadcastNotification(
                title=scheduled.title,
                message=scheduled.message,
                priority=scheduled.priority,
                tags=scheduled.tags,
                target_audience=scheduled.target_audience,
                target_topics=scheduled.target_topics,
                template_id=scheduled.template_id,
                sent_by=scheduled.created_by,
                status='pending'
            )
            db.session.add(broadcast)
            db.session.commit()

            # Send the broadcast
            result = send_broadcast(broadcast.id)

            # Update scheduled notification
            scheduled.status = 'sent'
            scheduled.sent_at = datetime.now(timezone.utc)
            scheduled.broadcast_id = broadcast.id
            db.session.commit()

            processed += 1
            logger.info(f"Processed scheduled notification {scheduled.id}: {result}")

        except Exception as e:
            logger.error(f"Failed to process scheduled notification {scheduled.id}: {e}")
            scheduled.status = 'failed'
            db.session.commit()

    return processed


def send_to_topics(topics: list, title: str, message: str,
                   priority: int = 3, tags: list = None) -> dict:
    """
    Send a notification to multiple specific NTFY topics.

    Args:
        topics: List of NTFY topics
        title: Notification title
        message: Notification message
        priority: NTFY priority (1-5)
        tags: List of NTFY tags

    Returns:
        Dict with results
    """
    successful = 0
    failed = 0

    for topic in topics:
        try:
            success = send_notification(
                topic=topic,
                title=title,
                message=message,
                priority=priority,
                tags=tags
            )
            if success:
                successful += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Failed to send to topic {topic}: {e}")
            failed += 1

    return {
        'total': len(topics),
        'successful': successful,
        'failed': failed
    }
