"""
Authentication Service
Handles user registration, login, and password management
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from app import db
from app.models import User, Subscription, SUBSCRIPTION_PLANS


# Password validation rules
PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$')

# Email validation
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# Username validation
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,30}$')


class AuthError(Exception):
    """Authentication error with user-friendly message"""
    pass


def generate_unique_topic() -> str:
    """
    Generate a cryptographically secure unique NTFY topic.
    Format: cl_{16_char_hex} (e.g., cl_a1b2c3d4e5f6g7h8)
    """
    return f"cl_{uuid.uuid4().hex[:16]}"


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """Validate email format"""
    if not email:
        return False, "Email is required"
    if not EMAIL_PATTERN.match(email):
        return False, "Invalid email format"
    return True, None


def validate_username(username: str) -> Tuple[bool, Optional[str]]:
    """Validate username format"""
    if not username:
        return False, "Username is required"
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 30:
        return False, "Username must be at most 30 characters"
    if not USERNAME_PATTERN.match(username):
        return False, "Username can only contain letters, numbers, and underscores"
    return True, None


def validate_password(password: str) -> Tuple[bool, Optional[str]]:
    """
    Validate password strength.
    Requirements:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    """
    if not password:
        return False, "Password is required"
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters"
    if not PASSWORD_PATTERN.match(password):
        return False, "Password must contain uppercase, lowercase, and a digit"
    return True, None


def register_user(email: str, username: str, password: str,
                  auto_verify: bool = False) -> User:
    """
    Register a new user with a free trial subscription.

    Args:
        email: User's email address
        username: Unique username
        password: Plain text password (will be hashed)
        auto_verify: If True, mark user as verified (for admin-created accounts)

    Returns:
        The created User object

    Raises:
        AuthError: If validation fails or user already exists
    """
    # Validate inputs
    valid, error = validate_email(email)
    if not valid:
        raise AuthError(error)

    valid, error = validate_username(username)
    if not valid:
        raise AuthError(error)

    valid, error = validate_password(password)
    if not valid:
        raise AuthError(error)

    # Normalize email
    email = email.lower().strip()
    username = username.strip()

    # Check for existing user
    if User.query.filter_by(email=email).first():
        raise AuthError("Email already registered")

    if User.query.filter_by(username=username).first():
        raise AuthError("Username already taken")

    # Generate unique NTFY topic
    ntfy_topic = generate_unique_topic()

    # Ensure topic is unique (extremely unlikely to collide, but check anyway)
    while User.query.filter_by(ntfy_topic=ntfy_topic).first():
        ntfy_topic = generate_unique_topic()

    # Create user
    user = User(
        email=email,
        username=username,
        ntfy_topic=ntfy_topic,
        is_verified=auto_verify,
    )
    user.set_password(password)

    db.session.add(user)
    db.session.flush()  # Get user ID for subscription

    # Create free trial subscription
    from app.services.subscription import create_subscription
    create_subscription(user.id, plan='free')

    db.session.commit()

    return user


def authenticate_user(email: str, password: str) -> Optional[User]:
    """
    Authenticate a user with email and password.

    Args:
        email: User's email address
        password: Plain text password

    Returns:
        User object if authentication successful, None otherwise
    """
    if not email or not password:
        return None

    email = email.lower().strip()
    user = User.query.filter_by(email=email).first()

    if not user:
        return None

    if not user.check_password(password):
        return None

    if not user.is_active:
        return None

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    return user


def change_password(user_id: int, old_password: str, new_password: str) -> bool:
    """
    Change a user's password.

    Args:
        user_id: User ID
        old_password: Current password for verification
        new_password: New password to set

    Returns:
        True if successful

    Raises:
        AuthError: If validation fails or old password incorrect
    """
    user = db.session.get(User, user_id)
    if not user:
        raise AuthError("User not found")

    if not user.check_password(old_password):
        raise AuthError("Current password is incorrect")

    valid, error = validate_password(new_password)
    if not valid:
        raise AuthError(error)

    user.set_password(new_password)
    db.session.commit()

    return True


def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by ID"""
    return db.session.get(User, user_id)


def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email"""
    return User.query.filter_by(email=email.lower().strip()).first()


def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username"""
    return User.query.filter_by(username=username.strip()).first()


def verify_user(user_id: int) -> bool:
    """Mark user as email-verified"""
    user = db.session.get(User, user_id)
    if not user:
        return False
    user.is_verified = True
    db.session.commit()
    return True


def deactivate_user(user_id: int) -> bool:
    """Deactivate user account"""
    user = db.session.get(User, user_id)
    if not user:
        return False
    user.is_active = False
    db.session.commit()
    return True


def activate_user(user_id: int) -> bool:
    """Reactivate user account"""
    user = db.session.get(User, user_id)
    if not user:
        return False
    user.is_active = True
    db.session.commit()
    return True


def make_admin(user_id: int) -> bool:
    """Grant admin privileges to user"""
    user = db.session.get(User, user_id)
    if not user:
        return False
    user.is_admin = True
    db.session.commit()
    return True


def revoke_admin(user_id: int) -> bool:
    """Revoke admin privileges from user"""
    user = db.session.get(User, user_id)
    if not user:
        return False
    user.is_admin = False
    db.session.commit()
    return True


def get_eligible_subscribers():
    """
    Get all users who should receive notifications.

    Criteria:
    - is_active = True
    - is_verified = True
    - has valid subscription (active, not expired beyond grace)

    Returns:
        List of User objects
    """
    users = User.query.filter(
        User.is_active == True,
        User.is_verified == True
    ).all()

    return [u for u in users if u.has_valid_subscription]
