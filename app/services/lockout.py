"""
Account Lockout Service
Brute force protection for user accounts
"""
from datetime import datetime, timezone, timedelta
from app import db
from app.models import User

MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def record_failed_attempt(email: str) -> None:
    """
    Record a failed login attempt for the given email.
    Locks the account after MAX_ATTEMPTS failures.
    """
    user = User.query.filter_by(email=email.lower()).first()
    if not user:
        return  # Don't reveal if email exists

    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= MAX_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + LOCKOUT_DURATION
    db.session.commit()


def is_locked(email: str) -> tuple[bool, int | None]:
    """
    Check if account is locked.
    Returns (is_locked, minutes_remaining) tuple.
    """
    user = User.query.filter_by(email=email.lower()).first()
    if not user:
        return False, None  # Don't reveal if email exists

    if not user.locked_until:
        return False, None

    now = datetime.now(timezone.utc)
    # Handle both naive and aware datetimes from DB
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if now > locked_until:
        # Lockout expired, clear it
        user.locked_until = None
        user.failed_attempts = 0
        db.session.commit()
        return False, None

    # Calculate remaining minutes (use converted locked_until)
    remaining = locked_until - now
    minutes = int(remaining.total_seconds() / 60) + 1
    return True, minutes


def clear_lockout(user: User) -> None:
    """Clear lockout counters on successful login."""
    if user.failed_attempts or user.locked_until:
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
