"""
System models: Log, Setting, StatsCache, Backtest, Payment, CronJob, CronRun
"""
from datetime import datetime, timezone, timedelta
from app import db
from app.models.base import CRON_JOB_TYPES


class Log(db.Model):
    """System Logs"""
    __tablename__ = 'logs'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # fetch, aggregate, scan, signal, notify, system, error
    level = db.Column(db.String(10), default='INFO')  # DEBUG, INFO, WARNING, ERROR
    message = db.Column(db.Text, nullable=False)
    symbol = db.Column(db.String(20), nullable=True)  # Optional: related symbol
    timeframe = db.Column(db.String(5), nullable=True)  # Optional: related timeframe
    details = db.Column(db.Text, nullable=True)  # Optional: JSON with extra details

    __table_args__ = (
        db.Index('idx_log_lookup', 'timestamp', 'category', 'level'),
    )

    def __repr__(self):
        return f'<Log {self.category} {self.level} {self.message[:50]}>'

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'category': self.category,
            'level': self.level,
            'message': self.message,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'details': self.details
        }


class Setting(db.Model):
    """User Settings"""
    __tablename__ = 'settings'

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get(cls, key, default=None):
        """Get a setting value"""
        setting = db.session.get(cls, key)
        return setting.value if setting else default

    @classmethod
    def set(cls, key, value):
        """Set a setting value"""
        setting = db.session.get(cls, key)
        if setting:
            setting.value = value
        else:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        db.session.commit()

    def __repr__(self):
        return f'<Setting {self.key}>'


class StatsCache(db.Model):
    """Pre-computed statistics cache for fast page loads"""
    __tablename__ = 'stats_cache'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # 'global' or symbol name
    data = db.Column(db.Text, nullable=False)  # JSON blob
    computed_at = db.Column(db.Integer, nullable=False)  # Timestamp in ms

    def __repr__(self):
        return f'<StatsCache {self.key}>'


class Backtest(db.Model):
    """Backtest Results"""
    __tablename__ = 'backtests'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    pattern_type = db.Column(db.String(30), nullable=False)
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    avg_rr = db.Column(db.Float, default=0.0)
    total_profit_pct = db.Column(db.Float, default=0.0)
    max_drawdown = db.Column(db.Float, default=0.0)
    results_json = db.Column(db.Text, nullable=True)  # Detailed results
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Backtest {self.name} {self.symbol}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'pattern_type': self.pattern_type,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'avg_rr': self.avg_rr,
            'total_profit_pct': self.total_profit_pct,
            'max_drawdown': self.max_drawdown,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Payment(db.Model):
    """Payment transactions"""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Payment details
    provider = db.Column(db.String(20), nullable=False)  # 'lemonsqueezy', 'nowpayments'
    external_id = db.Column(db.String(100), nullable=True)  # Provider's payment ID
    plan = db.Column(db.String(20), nullable=False)  # 'pro', 'premium', etc.
    billing_cycle = db.Column(db.String(20), default='monthly')  # 'monthly', 'yearly'

    # Amount
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='USD')

    # For crypto payments
    crypto_currency = db.Column(db.String(10), nullable=True)  # BTC, ETH, USDT, etc.
    crypto_amount = db.Column(db.Float, nullable=True)
    wallet_address = db.Column(db.String(100), nullable=True)

    # Status
    status = db.Column(db.String(20), default='pending')

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # For pending crypto payments

    # Relationships
    user = db.relationship('User', backref='payments')

    __table_args__ = (
        db.Index('idx_payment_user', 'user_id'),
        db.Index('idx_payment_status', 'status'),
        db.Index('idx_payment_external', 'provider', 'external_id'),
    )

    def __repr__(self):
        return f'<Payment {self.id} {self.provider} {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'provider': self.provider,
            'external_id': self.external_id,
            'plan': self.plan,
            'billing_cycle': self.billing_cycle,
            'amount': self.amount,
            'currency': self.currency,
            'crypto_currency': self.crypto_currency,
            'crypto_amount': self.crypto_amount,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class CronJob(db.Model):
    """Cron job definitions and status"""
    __tablename__ = 'cron_jobs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 'fetch', 'gaps', 'cleanup'
    description = db.Column(db.String(200), nullable=True)
    schedule = db.Column(db.String(50), nullable=False)  # Cron expression

    # Status
    is_enabled = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    runs = db.relationship('CronRun', backref='job', lazy='dynamic',
                          cascade='all, delete-orphan')

    def __repr__(self):
        return f'<CronJob {self.name}>'

    @property
    def last_run(self):
        """Get the most recent run"""
        return self.runs.order_by(CronRun.started_at.desc()).first()

    @property
    def last_successful_run(self):
        """Get the most recent successful run"""
        return self.runs.filter_by(success=True).order_by(CronRun.started_at.desc()).first()

    @property
    def recent_errors(self):
        """Get recent failed runs (last 5)"""
        return self.runs.filter_by(success=False).order_by(
            CronRun.started_at.desc()
        ).limit(5).all()

    @property
    def success_rate_24h(self):
        """Calculate success rate over last 24 hours"""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        total = self.runs.filter(CronRun.started_at >= since).count()
        if total == 0:
            return None
        success = self.runs.filter(
            CronRun.started_at >= since,
            CronRun.success == True
        ).count()
        return round((success / total) * 100, 1)

    @property
    def avg_duration_24h(self):
        """Calculate average duration over last 24 hours (in seconds)"""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        runs = self.runs.filter(
            CronRun.started_at >= since,
            CronRun.duration_ms.isnot(None)
        ).all()
        if not runs:
            return None
        total_ms = sum(r.duration_ms for r in runs)
        return round(total_ms / len(runs) / 1000, 2)

    def to_dict(self):
        last = self.last_run
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'schedule': self.schedule,
            'is_enabled': self.is_enabled,
            'last_run': last.to_dict() if last else None,
            'success_rate_24h': self.success_rate_24h,
            'avg_duration_24h': self.avg_duration_24h,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CronRun(db.Model):
    """Cron job execution history"""
    __tablename__ = 'cron_runs'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('cron_jobs.id'), nullable=False)

    # Execution timing
    started_at = db.Column(db.DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)  # Duration in milliseconds

    # Result
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text, nullable=True)

    # Statistics from the run
    symbols_processed = db.Column(db.Integer, default=0)
    candles_fetched = db.Column(db.Integer, default=0)
    patterns_found = db.Column(db.Integer, default=0)
    signals_generated = db.Column(db.Integer, default=0)
    notifications_sent = db.Column(db.Integer, default=0)

    # Additional details (JSON)
    details = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index('idx_cron_run_job', 'job_id', 'started_at'),
        db.Index('idx_cron_run_success', 'success', 'started_at'),
    )

    def __repr__(self):
        return f'<CronRun {self.job_id} {self.started_at}>'

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration_ms': self.duration_ms,
            'duration_str': f'{self.duration_ms / 1000:.2f}s' if self.duration_ms else None,
            'success': self.success,
            'error_message': self.error_message,
            'symbols_processed': self.symbols_processed,
            'candles_fetched': self.candles_fetched,
            'patterns_found': self.patterns_found,
            'signals_generated': self.signals_generated,
            'notifications_sent': self.notifications_sent,
            'details': self.details,
        }
