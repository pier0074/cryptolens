"""
Error Tracking Models

Self-hosted error tracking using MySQL.
No external dependencies required.
"""
from datetime import datetime, timezone
from app import db


class ErrorLog(db.Model):
    """Store application errors for tracking and analysis"""
    __tablename__ = 'error_logs'

    id = db.Column(db.Integer, primary_key=True)

    # Error identification
    error_hash = db.Column(db.String(64), index=True)  # SHA256 hash for grouping
    error_type = db.Column(db.String(100), nullable=False)  # Exception class name
    message = db.Column(db.Text, nullable=False)

    # Stack trace
    traceback = db.Column(db.Text)

    # Context
    endpoint = db.Column(db.String(200))  # Request endpoint
    method = db.Column(db.String(10))  # HTTP method
    url = db.Column(db.Text)  # Full URL
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address = db.Column(db.String(45))  # IPv6 compatible

    # Request data (sanitized - no passwords/tokens)
    request_headers = db.Column(db.Text)  # JSON
    request_data = db.Column(db.Text)  # JSON (sanitized)

    # Environment
    environment = db.Column(db.String(20), default='production')
    server_name = db.Column(db.String(100))
    python_version = db.Column(db.String(20))
    app_version = db.Column(db.String(20))

    # Status
    status = db.Column(db.String(20), default='new')  # new, acknowledged, resolved, ignored
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    notes = db.Column(db.Text)

    # Occurrence tracking
    occurrence_count = db.Column(db.Integer, default=1)
    first_seen = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships - errors are kept for audit but user reference is cleared on user delete
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('errors', passive_deletes=True))
    resolver = db.relationship('User', foreign_keys=[resolved_by])

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'error_type': self.error_type,
            'message': self.message,
            'endpoint': self.endpoint,
            'method': self.method,
            'status': self.status,
            'occurrence_count': self.occurrence_count,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'user_id': self.user_id,
        }

    def __repr__(self):
        return f'<ErrorLog {self.id}: {self.error_type}>'


class ErrorStats(db.Model):
    """Aggregated error statistics for dashboard"""
    __tablename__ = 'error_stats'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Integer)  # 0-23, nullable for daily stats

    error_count = db.Column(db.Integer, default=0)
    unique_errors = db.Column(db.Integer, default=0)
    affected_users = db.Column(db.Integer, default=0)

    # By severity
    critical_count = db.Column(db.Integer, default=0)
    warning_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('date', 'hour', name='unique_date_hour'),
    )
