"""
User models: User, Subscription, UserNotification
"""
from datetime import datetime, timezone, timedelta
from app import db
from app.models.base import (
    _ensure_utc_naive, _utc_now_naive,
    SUBSCRIPTION_PLANS, SUBSCRIPTION_TIERS
)


class User(db.Model):
    """User accounts for notification access"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Status flags
    is_active = db.Column(db.Boolean, default=True)  # Account enabled
    is_verified = db.Column(db.Boolean, default=False)  # Email verified
    is_admin = db.Column(db.Boolean, default=False)  # Admin privileges

    # Unique NTFY topic for this user (generated on registration)
    ntfy_topic = db.Column(db.String(64), unique=True, nullable=False)

    # Email verification
    email_verification_token = db.Column(db.String(64), nullable=True)
    email_verification_expires = db.Column(db.DateTime, nullable=True)

    # Password reset
    password_reset_token = db.Column(db.String(64), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    # Two-factor authentication (TOTP) - secret is encrypted at rest
    totp_secret = db.Column(db.String(256), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False)

    # Account lockout (brute force protection)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    # Notification preferences
    notify_enabled = db.Column(db.Boolean, default=True)  # Master toggle
    notify_signals = db.Column(db.Boolean, default=True)  # Receive signal notifications
    notify_patterns = db.Column(db.Boolean, default=False)  # Receive pattern notifications
    notify_priority = db.Column(db.Integer, default=3)  # NTFY priority 1-5 (3=default)
    notify_min_confluence = db.Column(db.Integer, default=2)  # Min confluence to notify
    notify_directions = db.Column(db.String(20), default='both')  # 'long', 'short', 'both'
    quiet_hours_enabled = db.Column(db.Boolean, default=False)
    quiet_hours_start = db.Column(db.Integer, default=22)  # 0-23 hour UTC
    quiet_hours_end = db.Column(db.Integer, default=7)  # 0-23 hour UTC

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    subscription = db.relationship('Subscription', backref='user', uselist=False,
                                   cascade='all, delete-orphan')
    notifications = db.relationship('UserNotification', backref='user', lazy='dynamic',
                                    cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_user_email', 'email'),
        db.Index('idx_user_active', 'is_active', 'is_verified'),
    )

    def __repr__(self):
        return f'<User {self.username}>'

    def set_password(self, password):
        """Hash and set the password"""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify password against hash"""
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def generate_email_verification_token(self):
        """Generate a token for email verification"""
        import secrets
        from app.config import Config
        self.email_verification_token = secrets.token_urlsafe(32)
        self.email_verification_expires = (
            datetime.now(timezone.utc) +
            timedelta(hours=Config.EMAIL_VERIFICATION_EXPIRY_HOURS)
        )
        return self.email_verification_token

    def verify_email_token(self, token):
        """Verify the email verification token"""
        if not self.email_verification_token or not self.email_verification_expires:
            return False
        if self.email_verification_token != token:
            return False
        expires = _ensure_utc_naive(self.email_verification_expires)
        now = _utc_now_naive()
        if now > expires:
            return False
        return True

    def clear_email_verification_token(self):
        """Clear the email verification token after use"""
        self.email_verification_token = None
        self.email_verification_expires = None

    def generate_password_reset_token(self):
        """Generate a token for password reset"""
        import secrets
        from app.config import Config
        self.password_reset_token = secrets.token_urlsafe(32)
        self.password_reset_expires = (
            datetime.now(timezone.utc) +
            timedelta(hours=Config.PASSWORD_RESET_EXPIRY_HOURS)
        )
        return self.password_reset_token

    def verify_password_reset_token(self, token):
        """Verify the password reset token"""
        if not self.password_reset_token or not self.password_reset_expires:
            return False
        if self.password_reset_token != token:
            return False
        expires = _ensure_utc_naive(self.password_reset_expires)
        now = _utc_now_naive()
        if now > expires:
            return False
        return True

    def clear_password_reset_token(self):
        """Clear the password reset token after use"""
        self.password_reset_token = None
        self.password_reset_expires = None

    def _get_decrypted_totp_secret(self):
        """Decrypt and return the TOTP secret"""
        if not self.totp_secret:
            return None
        from app.services.encryption import decrypt_value
        try:
            return decrypt_value(self.totp_secret)
        except Exception:
            # If decryption fails, assume it's a legacy unencrypted value
            return self.totp_secret

    def generate_totp_secret(self):
        """Generate a new TOTP secret for 2FA (stored encrypted)"""
        import pyotp
        from app.services.encryption import encrypt_value
        secret = pyotp.random_base32()
        self.totp_secret = encrypt_value(secret)
        return secret  # Return plaintext for QR code generation

    def get_totp_uri(self):
        """Get the TOTP provisioning URI for QR code"""
        import pyotp
        secret = self._get_decrypted_totp_secret()
        if not secret:
            return None
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=self.email,
            issuer_name='CryptoLens'
        )

    def verify_totp(self, token):
        """Verify a TOTP token"""
        import pyotp
        secret = self._get_decrypted_totp_secret()
        if not secret:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(token)

    @property
    def has_valid_subscription(self):
        """Check if user has a valid subscription for receiving notifications"""
        if not self.subscription:
            return False
        return self.subscription.is_valid

    @property
    def can_receive_notifications(self):
        """Check all criteria for receiving notifications"""
        return (
            self.is_active and
            self.is_verified and
            self.has_valid_subscription and
            self.notify_enabled
        )

    def should_notify_signal(self, signal):
        """Check if user should receive notification for a specific signal"""
        if not self.can_receive_notifications:
            return False
        if not self.notify_signals:
            return False
        # Check direction preference
        if self.notify_directions != 'both':
            if self.notify_directions != signal.direction:
                return False
        # Check confluence minimum
        if signal.confluence_score < self.notify_min_confluence:
            return False
        # Check quiet hours
        if self.quiet_hours_enabled:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            start = self.quiet_hours_start
            end = self.quiet_hours_end
            # Handle wrap-around (e.g., 22:00 to 07:00)
            if start > end:
                if current_hour >= start or current_hour < end:
                    return False
            else:
                if start <= current_hour < end:
                    return False
        return True

    @property
    def subscription_tier(self):
        """Get the user's subscription tier (free, pro, premium)"""
        if not self.subscription or not self.subscription.is_valid:
            return 'free'
        plan = self.subscription.plan
        plan_config = SUBSCRIPTION_PLANS.get(plan, {})
        return plan_config.get('tier', 'free')

    @property
    def tier_features(self):
        """Get the user's tier feature limits"""
        tier = self.subscription_tier
        return SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS['free'])

    def can_access_feature(self, feature_name):
        """Check if user can access a specific feature. Admins have full access."""
        # Admins bypass all feature restrictions
        if self.is_admin:
            return True
        features = self.tier_features
        value = features.get(feature_name)
        # For boolean features, return the value directly
        if isinstance(value, bool):
            return value
        # For string features (like 'limited', 'full'), return True if set
        if isinstance(value, str):
            return value != 'none'
        # For int/None features, return True if > 0 or None (unlimited)
        if value is None:
            return True
        return value > 0

    def get_feature_limit(self, feature_name):
        """Get the limit for a specific feature (None = unlimited)"""
        return self.tier_features.get(feature_name)

    def to_dict(self, include_subscription=True):
        result = {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'is_admin': self.is_admin,
            'ntfy_topic': self.ntfy_topic,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'can_receive_notifications': self.can_receive_notifications,
        }
        if include_subscription and self.subscription:
            result['subscription'] = self.subscription.to_dict()
        return result


class Subscription(db.Model):
    """User subscription for notification access"""
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)

    # Plan type
    plan = db.Column(db.String(20), default='free')  # free, monthly, yearly, lifetime

    # Subscription period
    starts_at = db.Column(db.DateTime, nullable=False,
                         default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)  # NULL = lifetime/never expires

    # Status
    status = db.Column(db.String(20), default='active')  # active, expired, cancelled, suspended

    # Grace period (days after expiry before losing access)
    grace_period_days = db.Column(db.Integer, default=3)

    # Audit timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))
    cancelled_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('idx_subscription_status', 'status'),
        db.Index('idx_subscription_expires', 'expires_at'),
    )

    def __repr__(self):
        return f'<Subscription {self.user_id} {self.plan} {self.status}>'

    @property
    def tier(self):
        """Get the subscription tier (free, pro, premium)"""
        plan_config = SUBSCRIPTION_PLANS.get(self.plan, {})
        return plan_config.get('tier', 'free')

    @property
    def is_lifetime(self):
        """Check if this is a lifetime subscription"""
        return self.plan == 'lifetime' or self.expires_at is None

    @property
    def plan_name(self):
        """Get human-readable plan name"""
        return SUBSCRIPTION_PLANS.get(self.plan, {}).get('name', self.plan.title())

    @property
    def days_remaining(self):
        """Calculate days until expiry (negative if expired)"""
        if self.is_lifetime:
            return float('inf')
        if not self.expires_at:
            return 0
        now = _utc_now_naive()
        expires = _ensure_utc_naive(self.expires_at)
        delta = expires - now
        return delta.days

    @property
    def is_expired(self):
        """Check if subscription has expired"""
        if self.is_lifetime:
            return False
        if not self.expires_at:
            return True
        now = _utc_now_naive()
        expires = _ensure_utc_naive(self.expires_at)
        return now > expires

    @property
    def is_in_grace_period(self):
        """Check if currently in grace period"""
        if self.is_lifetime or not self.is_expired:
            return False
        if not self.expires_at:
            return False
        now = _utc_now_naive()
        expires = _ensure_utc_naive(self.expires_at)
        grace_end = expires + timedelta(days=self.grace_period_days)
        return now <= grace_end

    @property
    def grace_period_end(self):
        """Get the end of grace period"""
        if self.is_lifetime or not self.expires_at:
            return None
        expires = _ensure_utc_naive(self.expires_at)
        return expires + timedelta(days=self.grace_period_days)

    @property
    def is_valid(self):
        """Check if subscription grants access (active + not expired beyond grace)"""
        if self.status not in ['active', 'expired']:
            return False  # cancelled or suspended
        if self.is_lifetime:
            return True
        if not self.is_expired:
            return True
        return self.is_in_grace_period

    @property
    def status_display(self):
        """Human-readable status"""
        if self.status == 'suspended':
            return 'Suspended'
        if self.status == 'cancelled':
            return 'Cancelled'
        if self.is_lifetime:
            return 'Lifetime'
        if not self.is_expired:
            days = self.days_remaining
            if days <= 7:
                return f'Active ({days} days left)'
            return 'Active'
        if self.is_in_grace_period:
            return 'Grace Period'
        return 'Expired'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'plan': self.plan,
            'plan_name': SUBSCRIPTION_PLANS.get(self.plan, {}).get('name', self.plan),
            'starts_at': self.starts_at.isoformat() if self.starts_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'status': self.status,
            'status_display': self.status_display,
            'is_valid': self.is_valid,
            'is_lifetime': self.is_lifetime,
            'is_expired': self.is_expired,
            'is_in_grace_period': self.is_in_grace_period,
            'days_remaining': self.days_remaining if not self.is_lifetime else None,
            'grace_period_days': self.grace_period_days,
            'grace_period_end': self.grace_period_end.isoformat() if self.grace_period_end else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class UserNotification(db.Model):
    """Track notifications sent to individual users"""
    __tablename__ = 'user_notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    signal_id = db.Column(db.Integer, db.ForeignKey('signals.id'), nullable=False)

    # Delivery status
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    success = db.Column(db.Boolean, default=True)
    error = db.Column(db.Text, nullable=True)

    # Relationships
    signal = db.relationship('Signal', backref='user_notifications')

    __table_args__ = (
        db.Index('idx_user_notification_lookup', 'user_id', 'signal_id'),
        db.Index('idx_user_notification_sent', 'sent_at'),
    )

    def __repr__(self):
        return f'<UserNotification {self.user_id} {self.signal_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'signal_id': self.signal_id,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'success': self.success,
            'error': self.error,
        }
