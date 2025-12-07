"""
Subscription Service
Handles subscription creation, management, and expiry
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from app import db
from app.models import User, Subscription, SUBSCRIPTION_PLANS, _ensure_utc_naive, _utc_now_naive


class SubscriptionError(Exception):
    """Subscription-related error"""
    pass


def create_subscription(user_id: int, plan: str = 'free') -> Subscription:
    """
    Create a new subscription for a user.

    Args:
        user_id: User ID
        plan: Plan type ('free', 'monthly', 'yearly', 'lifetime')

    Returns:
        Created Subscription object

    Raises:
        SubscriptionError: If user not found or invalid plan
    """
    user = db.session.get(User, user_id)
    if not user:
        raise SubscriptionError("User not found")

    if plan not in SUBSCRIPTION_PLANS:
        raise SubscriptionError(f"Invalid plan: {plan}")

    # Check if user already has subscription
    if user.subscription:
        raise SubscriptionError("User already has a subscription")

    # Calculate expiry date
    plan_config = SUBSCRIPTION_PLANS[plan]
    now = datetime.now(timezone.utc)

    if plan_config['days'] is None:  # Lifetime
        expires_at = None
    else:
        expires_at = now + timedelta(days=plan_config['days'])

    subscription = Subscription(
        user_id=user_id,
        plan=plan,
        starts_at=now,
        expires_at=expires_at,
        status='active',
    )

    db.session.add(subscription)
    db.session.commit()

    return subscription


def extend_subscription(user_id: int, plan: str, custom_days: int = None) -> Subscription:
    """
    Extend an existing subscription.
    Adds days to current expiry (or from now if expired).

    Args:
        user_id: User ID
        plan: Plan type to add
        custom_days: Optional custom number of days (overrides plan default)

    Returns:
        Updated Subscription object

    Raises:
        SubscriptionError: If user/subscription not found or invalid plan
    """
    user = db.session.get(User, user_id)
    if not user:
        raise SubscriptionError("User not found")

    if not user.subscription:
        # Create new subscription if none exists
        return create_subscription(user_id, plan)

    if plan not in SUBSCRIPTION_PLANS:
        raise SubscriptionError(f"Invalid plan: {plan}")

    subscription = user.subscription
    plan_config = SUBSCRIPTION_PLANS[plan]
    now = _utc_now_naive()

    # Lifetime plan
    if plan_config['days'] is None:
        subscription.plan = 'lifetime'
        subscription.expires_at = None
        subscription.status = 'active'
        subscription.cancelled_at = None
        db.session.commit()
        return subscription

    # Use custom_days if provided, otherwise use plan default
    days_to_add = custom_days if custom_days else plan_config['days']

    # Calculate new expiry date
    expires = _ensure_utc_naive(subscription.expires_at) if subscription.expires_at else None
    if expires and expires > now:
        # Add to current expiry
        new_expiry = expires + timedelta(days=days_to_add)
    else:
        # Start from now
        new_expiry = now + timedelta(days=days_to_add)

    subscription.plan = plan
    subscription.expires_at = new_expiry
    subscription.status = 'active'
    subscription.cancelled_at = None

    db.session.commit()

    return subscription


def cancel_subscription(user_id: int) -> Subscription:
    """
    Cancel a subscription.
    User retains access until expires_at.

    Args:
        user_id: User ID

    Returns:
        Updated Subscription object

    Raises:
        SubscriptionError: If user/subscription not found
    """
    user = db.session.get(User, user_id)
    if not user:
        raise SubscriptionError("User not found")

    if not user.subscription:
        raise SubscriptionError("No subscription found")

    subscription = user.subscription
    subscription.status = 'cancelled'
    subscription.cancelled_at = datetime.now(timezone.utc)

    db.session.commit()

    return subscription


def suspend_subscription(user_id: int, reason: str = None) -> Subscription:
    """
    Immediately suspend a subscription (admin action).
    User loses access immediately.

    Args:
        user_id: User ID
        reason: Optional reason for suspension

    Returns:
        Updated Subscription object

    Raises:
        SubscriptionError: If user/subscription not found
    """
    user = db.session.get(User, user_id)
    if not user:
        raise SubscriptionError("User not found")

    if not user.subscription:
        raise SubscriptionError("No subscription found")

    subscription = user.subscription
    subscription.status = 'suspended'

    db.session.commit()

    return subscription


def reactivate_subscription(user_id: int) -> Subscription:
    """
    Reactivate a cancelled or suspended subscription.

    Args:
        user_id: User ID

    Returns:
        Updated Subscription object

    Raises:
        SubscriptionError: If user/subscription not found
    """
    user = db.session.get(User, user_id)
    if not user:
        raise SubscriptionError("User not found")

    if not user.subscription:
        raise SubscriptionError("No subscription found")

    subscription = user.subscription
    subscription.status = 'active'
    subscription.cancelled_at = None

    db.session.commit()

    return subscription


def check_subscription_status(user_id: int) -> Dict:
    """
    Get detailed subscription status for a user.

    Args:
        user_id: User ID

    Returns:
        Dict with status details
    """
    user = db.session.get(User, user_id)
    if not user:
        return {
            'status': 'error',
            'message': 'User not found',
            'has_access': False,
        }

    if not user.subscription:
        return {
            'status': 'none',
            'message': 'No subscription',
            'has_access': False,
        }

    sub = user.subscription

    return {
        'status': sub.status,
        'plan': sub.plan,
        'plan_name': SUBSCRIPTION_PLANS.get(sub.plan, {}).get('name', sub.plan),
        'is_valid': sub.is_valid,
        'is_expired': sub.is_expired,
        'is_in_grace_period': sub.is_in_grace_period,
        'is_lifetime': sub.is_lifetime,
        'days_remaining': sub.days_remaining if not sub.is_lifetime else None,
        'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
        'grace_period_end': sub.grace_period_end.isoformat() if sub.grace_period_end else None,
        'has_access': sub.is_valid,
        'status_display': sub.status_display,
    }


def expire_subscriptions() -> int:
    """
    Mark expired subscriptions.
    Run as a cron job.

    Returns:
        Number of subscriptions marked as expired
    """
    now = datetime.now(timezone.utc)

    # Find active subscriptions that have expired (beyond grace period)
    expired = Subscription.query.filter(
        Subscription.status == 'active',
        Subscription.expires_at.isnot(None),
        Subscription.expires_at < now - timedelta(days=3)  # Default grace period
    ).all()

    count = 0
    for sub in expired:
        # Check if actually expired beyond grace
        if not sub.is_in_grace_period and sub.is_expired:
            sub.status = 'expired'
            count += 1

    db.session.commit()

    return count


def get_expiring_soon(days: int = 7) -> List[Subscription]:
    """
    Get subscriptions expiring within N days.
    Useful for sending reminder notifications.

    Args:
        days: Number of days to look ahead

    Returns:
        List of Subscription objects
    """
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days)

    return Subscription.query.filter(
        Subscription.status == 'active',
        Subscription.expires_at.isnot(None),
        Subscription.expires_at > now,
        Subscription.expires_at <= future
    ).all()


def get_in_grace_period() -> List[Subscription]:
    """
    Get subscriptions currently in grace period.

    Returns:
        List of Subscription objects in grace period
    """
    now = datetime.now(timezone.utc)

    # Get all subscriptions with expiry in the past
    candidates = Subscription.query.filter(
        Subscription.status.in_(['active', 'expired']),
        Subscription.expires_at.isnot(None),
        Subscription.expires_at < now
    ).all()

    return [sub for sub in candidates if sub.is_in_grace_period]


def get_subscription_stats() -> Dict:
    """
    Get subscription statistics for admin dashboard.

    Returns:
        Dict with subscription counts
    """
    total = Subscription.query.count()

    active = Subscription.query.filter(
        Subscription.status == 'active'
    ).count()

    expired = Subscription.query.filter(
        Subscription.status == 'expired'
    ).count()

    cancelled = Subscription.query.filter(
        Subscription.status == 'cancelled'
    ).count()

    suspended = Subscription.query.filter(
        Subscription.status == 'suspended'
    ).count()

    # Count by plan
    plans = {}
    for plan_key in SUBSCRIPTION_PLANS.keys():
        plans[plan_key] = Subscription.query.filter(
            Subscription.plan == plan_key,
            Subscription.status == 'active'
        ).count()

    # Expiring soon (within 7 days)
    expiring_soon = len(get_expiring_soon(7))

    # In grace period
    in_grace = len(get_in_grace_period())

    return {
        'total': total,
        'active': active,
        'expired': expired,
        'cancelled': cancelled,
        'suspended': suspended,
        'by_plan': plans,
        'expiring_soon': expiring_soon,
        'in_grace_period': in_grace,
    }


def send_expiry_warnings(days: List[int] = None) -> int:
    """
    Send warning notifications to users with expiring subscriptions.
    Should be run daily via cron.

    Args:
        days: List of days before expiry to warn (default: [7, 3, 1])

    Returns:
        Number of warnings sent
    """
    if days is None:
        days = [7, 3, 1]

    from app.services.notifier import send_notification
    from app.models import Setting
    from app.config import Config

    count = 0
    now = datetime.now(timezone.utc)

    for day_threshold in days:
        # Find subscriptions expiring in exactly N days
        target_date = now + timedelta(days=day_threshold)
        start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        expiring = Subscription.query.filter(
            Subscription.status == 'active',
            Subscription.expires_at.isnot(None),
            Subscription.expires_at >= start,
            Subscription.expires_at < end
        ).all()

        for sub in expiring:
            user = sub.user
            if not user or not user.is_active:
                continue

            # Send to user's personal topic
            title = f"Subscription Expiring in {day_threshold} Day{'s' if day_threshold != 1 else ''}"
            message = (
                f"Your CryptoLens subscription expires on "
                f"{sub.expires_at.strftime('%d %B %Y')}.\n\n"
                f"Renew now to continue receiving trading signals."
            )

            success = send_notification(
                topic=user.ntfy_topic,
                title=title,
                message=message,
                priority=3,
                tags="warning,subscription"
            )

            if success:
                count += 1

    return count
