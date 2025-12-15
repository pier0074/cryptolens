"""
API Key Models

Proper API key management with:
- User association (optional - can be global keys)
- Expiry dates
- Rate limiting per key
- IP whitelist/blacklist
- Usage tracking
- Scopes/permissions
"""
import secrets
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from app import db


# API Key status values
API_KEY_STATUS = ['active', 'inactive', 'expired', 'revoked']

# API Key scopes (permissions)
API_KEY_SCOPES = [
    'read:symbols',      # Read symbols list
    'read:candles',      # Read candle data
    'read:patterns',     # Read patterns
    'read:signals',      # Read signals
    'read:matrix',       # Read pattern matrix
    'write:scan',        # Trigger scans
    'write:fetch',       # Trigger data fetch
    'admin:scheduler',   # Control scheduler
    'all',               # Full access
]

# IP rule types
IP_RULE_TYPES = ['whitelist', 'blacklist']


class ApiKey(db.Model):
    """
    API Key for authentication.

    Can be:
    - User-specific (linked to a user account)
    - Global (no user, for system/service access)
    """
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)

    # Key identification
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    key_prefix = db.Column(db.String(8), nullable=False, unique=True)  # First 8 chars for identification
    key_hash = db.Column(db.String(64), nullable=False)  # SHA-256 hash of full key

    # Optional user association
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)

    # Status and validity
    status = db.Column(db.String(20), default='active', nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)  # NULL = never expires

    # Rate limiting (per key)
    rate_limit_per_minute = db.Column(db.Integer, default=60, nullable=False)
    rate_limit_per_hour = db.Column(db.Integer, default=1000, nullable=False)
    rate_limit_per_day = db.Column(db.Integer, default=10000, nullable=False)

    # Scopes/permissions (comma-separated)
    scopes = db.Column(db.Text, default='all', nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # Usage counters (updated periodically, not real-time)
    total_requests = db.Column(db.BigInteger, default=0, nullable=False)

    # Relationships
    user = db.relationship('User', backref=db.backref('api_keys', lazy='dynamic',
                                                       cascade='all, delete-orphan',
                                                       passive_deletes=True))
    ip_rules = db.relationship('IpRule', backref='api_key', lazy='dynamic',
                               cascade='all, delete-orphan')
    usage_logs = db.relationship('ApiKeyUsage', backref='api_key', lazy='dynamic',
                                 cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_api_key_prefix', 'key_prefix'),
        db.Index('idx_api_key_user', 'user_id'),
        db.Index('idx_api_key_status', 'status'),
    )

    def __repr__(self):
        return f'<ApiKey {self.name} ({self.key_prefix}...)>'

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new API key (URL-safe, 43 chars)."""
        return secrets.token_urlsafe(32)

    @classmethod
    def hash_key(cls, key: str) -> str:
        """Hash an API key using SHA-256."""
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def create(cls, name: str, user_id: int = None, description: str = None,
               expires_in_days: int = None, rate_limit_per_minute: int = 60,
               rate_limit_per_hour: int = 1000, rate_limit_per_day: int = 10000,
               scopes: List[str] = None) -> tuple['ApiKey', str]:
        """
        Create a new API key.

        Returns: (ApiKey instance, raw key string)

        IMPORTANT: The raw key is only returned once at creation!
        """
        raw_key = cls.generate_key()
        key_hash = cls.hash_key(raw_key)
        key_prefix = raw_key[:8]

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        scope_str = ','.join(scopes) if scopes else 'all'

        api_key = cls(
            name=name,
            description=description,
            key_prefix=key_prefix,
            key_hash=key_hash,
            user_id=user_id,
            expires_at=expires_at,
            rate_limit_per_minute=rate_limit_per_minute,
            rate_limit_per_hour=rate_limit_per_hour,
            rate_limit_per_day=rate_limit_per_day,
            scopes=scope_str,
        )

        db.session.add(api_key)
        db.session.commit()

        return api_key, raw_key

    @classmethod
    def find_by_key(cls, raw_key: str) -> Optional['ApiKey']:
        """Find an API key by raw key string."""
        if not raw_key or len(raw_key) < 8:
            return None

        prefix = raw_key[:8]
        key_hash = cls.hash_key(raw_key)

        # Find by prefix first (fast index lookup)
        api_key = cls.query.filter_by(key_prefix=prefix).first()
        if not api_key:
            return None

        # Verify full hash with timing-safe comparison
        if hmac.compare_digest(api_key.key_hash, key_hash):
            return api_key

        return None

    @property
    def is_valid(self) -> bool:
        """Check if key is valid (active and not expired)."""
        if self.status != 'active':
            return False
        if self.is_expired:
            return False
        return True

    @property
    def is_expired(self) -> bool:
        """Check if key is expired."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        # Handle both timezone-aware and naive datetimes
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    @property
    def days_until_expiry(self) -> Optional[int]:
        """Days until expiry, or None if no expiry."""
        if self.expires_at is None:
            return None
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        delta = expires - now
        return max(0, delta.days)

    @property
    def scope_list(self) -> List[str]:
        """Get scopes as a list."""
        if not self.scopes:
            return []
        return [s.strip() for s in self.scopes.split(',')]

    def has_scope(self, scope: str) -> bool:
        """Check if key has a specific scope."""
        scopes = self.scope_list
        return 'all' in scopes or scope in scopes

    def record_usage(self, ip_address: str = None, endpoint: str = None,
                    method: str = None, response_code: int = None):
        """Record API key usage."""
        self.last_used_at = datetime.now(timezone.utc)
        self.total_requests += 1

        # Log detailed usage
        usage = ApiKeyUsage(
            api_key_id=self.id,
            timestamp=datetime.now(timezone.utc),
            ip_address=ip_address,
            endpoint=endpoint,
            method=method,
            response_code=response_code,
        )
        db.session.add(usage)
        db.session.commit()

    def get_usage_count(self, minutes: int = None, hours: int = None, days: int = None) -> int:
        """Get usage count for a time period."""
        since = datetime.now(timezone.utc)
        if minutes:
            since -= timedelta(minutes=minutes)
        elif hours:
            since -= timedelta(hours=hours)
        elif days:
            since -= timedelta(days=days)
        else:
            since -= timedelta(minutes=1)

        return self.usage_logs.filter(ApiKeyUsage.timestamp >= since).count()

    def is_rate_limited(self) -> tuple[bool, str]:
        """
        Check if key is rate limited.

        Returns: (is_limited, reason)
        """
        # Check per-minute limit
        minute_count = self.get_usage_count(minutes=1)
        if minute_count >= self.rate_limit_per_minute:
            return True, f'Rate limit exceeded: {self.rate_limit_per_minute}/minute'

        # Check per-hour limit
        hour_count = self.get_usage_count(hours=1)
        if hour_count >= self.rate_limit_per_hour:
            return True, f'Rate limit exceeded: {self.rate_limit_per_hour}/hour'

        # Check per-day limit
        day_count = self.get_usage_count(days=1)
        if day_count >= self.rate_limit_per_day:
            return True, f'Rate limit exceeded: {self.rate_limit_per_day}/day'

        return False, ''

    def check_ip_allowed(self, ip_address: str) -> tuple[bool, str]:
        """
        Check if an IP address is allowed for this key.

        Returns: (is_allowed, reason)
        """
        # Get IP rules for this key
        whitelist = self.ip_rules.filter_by(rule_type='whitelist', is_active=True).all()
        blacklist = self.ip_rules.filter_by(rule_type='blacklist', is_active=True).all()

        # Check blacklist first
        for rule in blacklist:
            if rule.matches_ip(ip_address):
                return False, f'IP {ip_address} is blacklisted'

        # If whitelist exists, IP must be in it
        if whitelist:
            for rule in whitelist:
                if rule.matches_ip(ip_address):
                    return True, ''
            return False, f'IP {ip_address} not in whitelist'

        # No whitelist = all IPs allowed (except blacklisted)
        return True, ''

    def revoke(self, reason: str = None):
        """Revoke this API key."""
        self.status = 'revoked'
        if reason:
            self.description = f'{self.description or ""}\n[REVOKED: {reason}]'
        db.session.commit()

    def to_dict(self, include_usage: bool = False) -> dict:
        """Convert to dictionary for API response."""
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'key_prefix': f'{self.key_prefix}...',
            'user_id': self.user_id,
            'user_email': self.user.email if self.user else None,
            'status': self.status,
            'is_valid': self.is_valid,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'days_until_expiry': self.days_until_expiry,
            'rate_limits': {
                'per_minute': self.rate_limit_per_minute,
                'per_hour': self.rate_limit_per_hour,
                'per_day': self.rate_limit_per_day,
            },
            'scopes': self.scope_list,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'total_requests': self.total_requests,
        }

        if include_usage:
            result['usage'] = {
                'last_minute': self.get_usage_count(minutes=1),
                'last_hour': self.get_usage_count(hours=1),
                'last_day': self.get_usage_count(days=1),
            }
            result['ip_rules'] = [r.to_dict() for r in self.ip_rules.filter_by(is_active=True).all()]

        return result


class IpRule(db.Model):
    """
    IP whitelist/blacklist rules for API keys.

    Supports:
    - Single IPs: 192.168.1.1
    - CIDR notation: 192.168.1.0/24
    - Wildcards: 192.168.*.*
    """
    __tablename__ = 'api_key_ip_rules'

    id = db.Column(db.Integer, primary_key=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id', ondelete='CASCADE'), nullable=False)

    rule_type = db.Column(db.String(20), nullable=False)  # whitelist, blacklist
    ip_pattern = db.Column(db.String(50), nullable=False)  # IP, CIDR, or wildcard
    description = db.Column(db.String(200), nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.Index('idx_ip_rule_key', 'api_key_id', 'rule_type'),
    )

    def __repr__(self):
        return f'<IpRule {self.rule_type}: {self.ip_pattern}>'

    def matches_ip(self, ip_address: str) -> bool:
        """Check if an IP address matches this rule."""
        import ipaddress

        pattern = self.ip_pattern.strip()

        # Handle wildcards (convert to CIDR)
        if '*' in pattern:
            parts = pattern.split('.')
            non_wildcard = [p for p in parts if p != '*']
            if len(non_wildcard) == 0:
                return True  # *.*.*.* matches everything

            # Convert to CIDR
            cidr_parts = []
            for p in parts:
                if p == '*':
                    cidr_parts.append('0')
                else:
                    cidr_parts.append(p)

            prefix_len = len(non_wildcard) * 8
            cidr = f"{'.'.join(cidr_parts)}/{prefix_len}"
            pattern = cidr

        try:
            # Try CIDR notation
            if '/' in pattern:
                network = ipaddress.ip_network(pattern, strict=False)
                return ipaddress.ip_address(ip_address) in network

            # Exact IP match
            return ipaddress.ip_address(pattern) == ipaddress.ip_address(ip_address)
        except ValueError:
            # Invalid pattern or IP - no match
            return False

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'rule_type': self.rule_type,
            'ip_pattern': self.ip_pattern,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ApiKeyUsage(db.Model):
    """
    API Key usage log for rate limiting and analytics.

    Note: Old entries should be periodically cleaned up (e.g., keep last 7 days).
    """
    __tablename__ = 'api_key_usage'

    id = db.Column(db.BigInteger, primary_key=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id', ondelete='CASCADE'), nullable=False)

    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 can be 45 chars
    endpoint = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    response_code = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.Index('idx_usage_key_time', 'api_key_id', 'timestamp'),
        db.Index('idx_usage_timestamp', 'timestamp'),  # For cleanup queries
    )

    def __repr__(self):
        return f'<ApiKeyUsage {self.api_key_id} {self.timestamp}>'

    @classmethod
    def cleanup_old_entries(cls, days: int = 7) -> int:
        """Delete usage entries older than N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = cls.query.filter(cls.timestamp < cutoff).delete()
        db.session.commit()
        return count


# =============================================================================
# API RESPONSE HELPERS
# =============================================================================

class ApiResponse:
    """
    Standardized API response format.

    All API endpoints should return responses in this format:
    {
        "success": true/false,
        "data": <payload>,
        "error": null or {"code": "ERROR_CODE", "message": "Human readable"},
        "meta": {
            "timestamp": "ISO-8601",
            "request_id": "uuid",
            "pagination": {...}  // if applicable
        }
    }
    """

    @staticmethod
    def success(data, meta: dict = None, status_code: int = 200) -> tuple:
        """Create a successful response."""
        from flask import jsonify
        import uuid

        response = {
            'success': True,
            'data': data,
            'error': None,
            'meta': {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'request_id': str(uuid.uuid4()),
                **(meta or {})
            }
        }
        return jsonify(response), status_code

    @staticmethod
    def error(code: str, message: str, status_code: int = 400, details: dict = None) -> tuple:
        """Create an error response."""
        from flask import jsonify
        import uuid

        error_obj = {
            'code': code,
            'message': message,
        }
        if details:
            error_obj['details'] = details

        response = {
            'success': False,
            'data': None,
            'error': error_obj,
            'meta': {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'request_id': str(uuid.uuid4()),
            }
        }
        return jsonify(response), status_code

    @staticmethod
    def paginated(items: list, total: int, page: int, per_page: int,
                  status_code: int = 200) -> tuple:
        """Create a paginated response."""
        from flask import jsonify
        import uuid
        import math

        total_pages = math.ceil(total / per_page) if per_page > 0 else 0

        response = {
            'success': True,
            'data': items,
            'error': None,
            'meta': {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'request_id': str(uuid.uuid4()),
                'pagination': {
                    'total': total,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1,
                }
            }
        }
        return jsonify(response), status_code

    # Common error responses
    @classmethod
    def unauthorized(cls, message: str = 'Authentication required'):
        return cls.error('UNAUTHORIZED', message, 401)

    @classmethod
    def forbidden(cls, message: str = 'Access denied'):
        return cls.error('FORBIDDEN', message, 403)

    @classmethod
    def not_found(cls, message: str = 'Resource not found'):
        return cls.error('NOT_FOUND', message, 404)

    @classmethod
    def rate_limited(cls, message: str = 'Rate limit exceeded'):
        return cls.error('RATE_LIMITED', message, 429)

    @classmethod
    def bad_request(cls, message: str = 'Invalid request'):
        return cls.error('BAD_REQUEST', message, 400)

    @classmethod
    def server_error(cls, message: str = 'Internal server error'):
        return cls.error('SERVER_ERROR', message, 500)

    @classmethod
    def service_unavailable(cls, message: str = 'Service temporarily unavailable'):
        return cls.error('SERVICE_UNAVAILABLE', message, 503)
