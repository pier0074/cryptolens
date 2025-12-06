from datetime import datetime, timezone, timedelta
from app import db


def _ensure_utc_naive(dt):
    """
    Ensure datetime is naive UTC for consistent comparisons.
    SQLite stores datetimes without timezone info, so we normalize all
    datetimes to naive UTC for comparison.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC and strip timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_now_naive():
    """Get current UTC time as a naive datetime (for SQLite compatibility)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Log categories
LOG_CATEGORIES = {
    'fetch': 'Data Fetching',
    'aggregate': 'Aggregation',
    'scan': 'Pattern Scanning',
    'signal': 'Signal Generation',
    'notify': 'Notifications',
    'system': 'System',
    'error': 'Errors'
}

# Log levels
LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']


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


class Symbol(db.Model):
    """Symbols to track"""
    __tablename__ = 'symbols'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), unique=True, nullable=False)  # e.g., "BTC/USDT"
    exchange = db.Column(db.String(20), default='kucoin')
    is_active = db.Column(db.Boolean, default=True)  # Whether to fetch candles
    notify_enabled = db.Column(db.Boolean, default=True)  # Whether to send notifications
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    candles = db.relationship('Candle', backref='symbol', lazy='dynamic')
    patterns = db.relationship('Pattern', backref='symbol', lazy='dynamic')
    signals = db.relationship('Signal', backref='symbol', lazy='dynamic')

    def __repr__(self):
        return f'<Symbol {self.symbol}>'

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'exchange': self.exchange,
            'is_active': self.is_active,
            'notify_enabled': self.notify_enabled
        }


class Candle(db.Model):
    """OHLC Candles"""
    __tablename__ = 'candles'

    id = db.Column(db.Integer, primary_key=True)
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id'), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)  # '1m', '5m', '15m', '1h', '4h', '1d'
    timestamp = db.Column(db.Integer, nullable=False)  # Unix timestamp in milliseconds
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    verified_at = db.Column(db.Integer, nullable=True)  # Timestamp when health check passed (ms)

    __table_args__ = (
        db.UniqueConstraint('symbol_id', 'timeframe', 'timestamp', name='uix_candle'),
        db.Index('idx_candle_lookup', 'symbol_id', 'timeframe', 'timestamp'),
        db.Index('idx_candle_unverified', 'symbol_id', 'timeframe', 'verified_at'),
        db.Index('idx_candle_timeframe', 'timeframe'),  # For GROUP BY timeframe queries
    )

    def __repr__(self):
        return f'<Candle {self.symbol_id} {self.timeframe} {self.timestamp}>'

    def to_dict(self):
        return {
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'verified_at': self.verified_at
        }


class Pattern(db.Model):
    """Detected Patterns"""
    __tablename__ = 'patterns'

    id = db.Column(db.Integer, primary_key=True)
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id'), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    pattern_type = db.Column(db.String(30), nullable=False)  # 'imbalance', 'order_block', etc.
    direction = db.Column(db.String(10), nullable=False)  # 'bullish', 'bearish'
    zone_high = db.Column(db.Float, nullable=False)
    zone_low = db.Column(db.Float, nullable=False)
    detected_at = db.Column(db.Integer, nullable=False)  # Candle timestamp when detected
    status = db.Column(db.String(15), default='active')  # 'active', 'filled', 'expired'
    filled_at = db.Column(db.Integer, nullable=True)
    fill_percentage = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Pre-computed trading levels (computed at detection time)
    entry = db.Column(db.Float, nullable=True)
    stop_loss = db.Column(db.Float, nullable=True)
    take_profit_1 = db.Column(db.Float, nullable=True)
    take_profit_2 = db.Column(db.Float, nullable=True)
    take_profit_3 = db.Column(db.Float, nullable=True)
    risk = db.Column(db.Float, nullable=True)
    risk_reward_1 = db.Column(db.Float, nullable=True)
    risk_reward_2 = db.Column(db.Float, nullable=True)
    risk_reward_3 = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.Index('idx_pattern_active', 'symbol_id', 'timeframe', 'status'),
        db.Index('idx_pattern_detected', 'detected_at'),
        db.Index('idx_pattern_list', 'status', 'detected_at'),  # For pattern list page queries
    )

    def __repr__(self):
        return f'<Pattern {self.pattern_type} {self.direction} {self.symbol_id}>'

    @property
    def detected_at_formatted(self):
        """Return human-readable detected_at timestamp"""
        if self.detected_at:
            return datetime.fromtimestamp(self.detected_at / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        return None

    @property
    def expires_at(self):
        """Calculate expiry timestamp based on timeframe"""
        from app.config import Config
        expiry_hours = Config.PATTERN_EXPIRY_HOURS.get(self.timeframe, Config.DEFAULT_PATTERN_EXPIRY_HOURS)
        expiry_ms = expiry_hours * 60 * 60 * 1000
        return self.detected_at + expiry_ms

    @property
    def expires_at_formatted(self):
        """Return human-readable expiry timestamp"""
        expires = self.expires_at
        if expires:
            return datetime.fromtimestamp(expires / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        return None

    @property
    def is_expired(self):
        """Check if pattern has expired based on timeframe"""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return now_ms > self.expires_at

    @property
    def time_remaining(self):
        """Return time remaining before expiry in human-readable format"""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        remaining_ms = self.expires_at - now_ms
        if remaining_ms <= 0:
            return "Expired"
        hours = remaining_ms // (60 * 60 * 1000)
        minutes = (remaining_ms % (60 * 60 * 1000)) // (60 * 1000)
        if hours > 24:
            days = hours // 24
            return f"{days}d {hours % 24}h"
        return f"{hours}h {minutes}m"

    def to_dict(self):
        return {
            'id': self.id,
            'symbol_id': self.symbol_id,
            'timeframe': self.timeframe,
            'pattern_type': self.pattern_type,
            'direction': self.direction,
            'zone_high': self.zone_high,
            'zone_low': self.zone_low,
            'detected_at': self.detected_at,
            'detected_at_formatted': self.detected_at_formatted,
            'expires_at': self.expires_at,
            'expires_at_formatted': self.expires_at_formatted,
            'is_expired': self.is_expired,
            'time_remaining': self.time_remaining,
            'status': self.status,
            'fill_percentage': self.fill_percentage,
            # Trading levels
            'entry': self.entry,
            'stop_loss': self.stop_loss,
            'take_profit_1': self.take_profit_1,
            'take_profit_2': self.take_profit_2,
            'take_profit_3': self.take_profit_3,
            'risk': self.risk,
            'risk_reward_1': self.risk_reward_1,
            'risk_reward_2': self.risk_reward_2,
            'risk_reward_3': self.risk_reward_3,
        }

    @property
    def trading_levels(self):
        """Return trading levels as a dict (for template compatibility)."""
        return {
            'entry': self.entry,
            'stop_loss': self.stop_loss,
            'take_profit_1': self.take_profit_1,
            'take_profit_2': self.take_profit_2,
            'take_profit_3': self.take_profit_3,
            'risk': self.risk,
            'risk_reward_1': round(self.risk_reward_1, 2) if self.risk_reward_1 else 0,
            'risk_reward_2': round(self.risk_reward_2, 2) if self.risk_reward_2 else 0,
            'risk_reward_3': round(self.risk_reward_3, 2) if self.risk_reward_3 else 0,
        }


class Signal(db.Model):
    """Trade Signals"""
    __tablename__ = 'signals'

    id = db.Column(db.Integer, primary_key=True)
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'long', 'short'
    entry_price = db.Column(db.Float, nullable=False)
    stop_loss = db.Column(db.Float, nullable=False)
    take_profit_1 = db.Column(db.Float, nullable=False)
    take_profit_2 = db.Column(db.Float, nullable=True)
    take_profit_3 = db.Column(db.Float, nullable=True)
    risk_reward = db.Column(db.Float, nullable=False)
    confluence_score = db.Column(db.Integer, default=1)  # How many timeframes agree
    timeframes_aligned = db.Column(db.Text, nullable=True)  # JSON array of aligned TFs
    pattern_id = db.Column(db.Integer, db.ForeignKey('patterns.id'), nullable=True)
    status = db.Column(db.String(15), default='pending')  # 'pending', 'notified', 'filled', 'stopped', 'tp_hit'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    pattern = db.relationship('Pattern', backref='signals')

    __table_args__ = (
        db.Index('idx_signal_symbol', 'symbol_id'),
    )

    def __repr__(self):
        return f'<Signal {self.direction} {self.symbol_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'symbol_id': self.symbol_id,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit_1': self.take_profit_1,
            'take_profit_2': self.take_profit_2,
            'take_profit_3': self.take_profit_3,
            'risk_reward': self.risk_reward,
            'confluence_score': self.confluence_score,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Notification(db.Model):
    """Notifications sent"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    signal_id = db.Column(db.Integer, db.ForeignKey('signals.id'), nullable=False)
    channel = db.Column(db.String(20), nullable=False)  # 'ntfy', 'telegram', 'email'
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text, nullable=True)

    # Relationship
    signal = db.relationship('Signal', backref='notifications')

    def __repr__(self):
        return f'<Notification {self.channel} {self.signal_id}>'


class Setting(db.Model):
    """User Settings"""
    __tablename__ = 'settings'

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

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


# Trade mood options for journal entries
TRADE_MOODS = ['confident', 'neutral', 'fearful', 'greedy', 'fomo', 'revenge']

# Trade status options
TRADE_STATUSES = ['pending', 'open', 'closed', 'cancelled']


class Portfolio(db.Model):
    """Trading Portfolio"""
    __tablename__ = 'portfolios'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    initial_balance = db.Column(db.Float, default=10000.0)
    current_balance = db.Column(db.Float, default=10000.0)
    currency = db.Column(db.String(10), default='USDT')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    trades = db.relationship('Trade', backref='portfolio', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Portfolio {self.name}>'

    @property
    def total_pnl(self):
        """Calculate total PnL"""
        return self.current_balance - self.initial_balance

    @property
    def total_pnl_percent(self):
        """Calculate total PnL percentage"""
        if self.initial_balance == 0:
            return 0.0
        return ((self.current_balance - self.initial_balance) / self.initial_balance) * 100

    @property
    def open_trades_count(self):
        """Count of open trades"""
        return self.trades.filter_by(status='open').count()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'currency': self.currency,
            'is_active': self.is_active,
            'total_pnl': self.total_pnl,
            'total_pnl_percent': round(self.total_pnl_percent, 2),
            'open_trades_count': self.open_trades_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class TradeTag(db.Model):
    """Tags for categorizing trades"""
    __tablename__ = 'trade_tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6366f1')  # Hex color
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<TradeTag {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'description': self.description
        }


# Association table for Trade-Tag many-to-many
trade_tags = db.Table('trade_tag_association',
    db.Column('trade_id', db.Integer, db.ForeignKey('trades.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('trade_tags.id'), primary_key=True)
)


class Trade(db.Model):
    """Trade Journal Entry"""
    __tablename__ = 'trades'

    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolios.id'), nullable=False)
    signal_id = db.Column(db.Integer, db.ForeignKey('signals.id'), nullable=True)  # Optional link to signal

    # Trade details
    symbol = db.Column(db.String(20), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'long', 'short'
    timeframe = db.Column(db.String(5), nullable=True)  # e.g., '1h'
    pattern_type = db.Column(db.String(30), nullable=True)  # e.g., 'imbalance'

    # Entry
    entry_price = db.Column(db.Float, nullable=False)
    entry_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    entry_quantity = db.Column(db.Float, nullable=False)

    # Risk management
    stop_loss = db.Column(db.Float, nullable=True)
    take_profit = db.Column(db.Float, nullable=True)
    risk_amount = db.Column(db.Float, nullable=True)  # Amount risked in currency
    risk_percent = db.Column(db.Float, nullable=True)  # Percent of portfolio risked

    # Exit
    exit_price = db.Column(db.Float, nullable=True)
    exit_time = db.Column(db.DateTime, nullable=True)

    # Results
    status = db.Column(db.String(15), default='open')  # 'open', 'closed', 'cancelled'
    pnl_amount = db.Column(db.Float, nullable=True)  # Profit/loss in currency
    pnl_percent = db.Column(db.Float, nullable=True)  # Profit/loss percentage
    pnl_r = db.Column(db.Float, nullable=True)  # Profit/loss in R multiples
    fees = db.Column(db.Float, default=0.0)

    # Notes
    setup_notes = db.Column(db.Text, nullable=True)  # Why I took this trade
    exit_notes = db.Column(db.Text, nullable=True)  # Post-trade review
    lessons_learned = db.Column(db.Text, nullable=True)  # Key takeaways

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    signal = db.relationship('Signal', backref='trades')
    tags = db.relationship('TradeTag', secondary=trade_tags, lazy='subquery',
                          backref=db.backref('trades', lazy=True))
    journal_entries = db.relationship('JournalEntry', backref='trade', lazy='dynamic',
                                     cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_trade_portfolio_status', 'portfolio_id', 'status'),
        db.Index('idx_trade_symbol', 'symbol'),
    )

    def __repr__(self):
        return f'<Trade {self.symbol} {self.direction} {self.status}>'

    def calculate_pnl(self):
        """Calculate PnL when closing a trade"""
        if self.exit_price is None or self.entry_price is None:
            return

        if self.direction == 'long':
            self.pnl_amount = (self.exit_price - self.entry_price) * self.entry_quantity - self.fees
        else:  # short
            self.pnl_amount = (self.entry_price - self.exit_price) * self.entry_quantity - self.fees

        self.pnl_percent = (self.pnl_amount / (self.entry_price * self.entry_quantity)) * 100

        # Calculate R multiple if stop loss was set
        if self.stop_loss and self.risk_amount:
            self.pnl_r = self.pnl_amount / self.risk_amount

    def close(self, exit_price: float, exit_notes: str = None):
        """Close the trade"""
        self.exit_price = exit_price
        self.exit_time = datetime.now(timezone.utc)
        self.status = 'closed'
        self.exit_notes = exit_notes
        self.calculate_pnl()

        # Update portfolio balance
        if self.portfolio:
            self.portfolio.current_balance += self.pnl_amount

    def to_dict(self):
        return {
            'id': self.id,
            'portfolio_id': self.portfolio_id,
            'signal_id': self.signal_id,
            'symbol': self.symbol,
            'direction': self.direction,
            'timeframe': self.timeframe,
            'pattern_type': self.pattern_type,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'entry_quantity': self.entry_quantity,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'risk_amount': self.risk_amount,
            'risk_percent': self.risk_percent,
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'status': self.status,
            'pnl_amount': self.pnl_amount,
            'pnl_percent': round(self.pnl_percent, 2) if self.pnl_percent else None,
            'pnl_r': round(self.pnl_r, 2) if self.pnl_r else None,
            'fees': self.fees,
            'setup_notes': self.setup_notes,
            'exit_notes': self.exit_notes,
            'lessons_learned': self.lessons_learned,
            'tags': [tag.to_dict() for tag in self.tags],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class JournalEntry(db.Model):
    """Journal entries for trades"""
    __tablename__ = 'journal_entries'

    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trades.id'), nullable=False)

    # Entry type
    entry_type = db.Column(db.String(20), nullable=False)  # 'pre_trade', 'during', 'post_trade', 'lesson'

    # Content
    content = db.Column(db.Text, nullable=False)
    mood = db.Column(db.String(20), nullable=True)  # 'confident', 'neutral', 'fearful', 'greedy', etc.

    # Optional attachments
    screenshots = db.Column(db.Text, nullable=True)  # JSON array of file paths

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.Index('idx_journal_trade', 'trade_id', 'entry_type'),
    )

    def __repr__(self):
        return f'<JournalEntry {self.entry_type} for Trade {self.trade_id}>'

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'entry_type': self.entry_type,
            'content': self.content,
            'mood': self.mood,
            'screenshots': json.loads(self.screenshots) if self.screenshots else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class StatsCache(db.Model):
    """Pre-computed statistics cache for fast page loads"""
    __tablename__ = 'stats_cache'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # 'global' or symbol name
    data = db.Column(db.Text, nullable=False)  # JSON blob
    computed_at = db.Column(db.Integer, nullable=False)  # Timestamp in ms

    def __repr__(self):
        return f'<StatsCache {self.key}>'


# =============================================================================
# USER AUTHENTICATION & SUBSCRIPTION MODELS
# =============================================================================

# Subscription plan definitions (3-tier system)
SUBSCRIPTION_PLANS = {
    'free': {
        'name': 'Free',
        'price': 0,
        'price_yearly': 0,
        'days': None,  # Unlimited duration with limited features
        'tier': 'free',
    },
    'pro': {
        'name': 'Pro',
        'price': 19,  # Monthly
        'price_yearly': 190,  # ~$15.83/mo
        'days': 30,
        'tier': 'pro',
    },
    'premium': {
        'name': 'Premium',
        'price': 49,  # Monthly
        'price_yearly': 490,  # ~$40.83/mo
        'days': 30,
        'tier': 'premium',
    },
    # Legacy plans for backwards compatibility
    'monthly': {'name': 'Pro (Legacy)', 'price': 19, 'days': 30, 'tier': 'pro'},
    'yearly': {'name': 'Pro Yearly (Legacy)', 'price': 190, 'days': 365, 'tier': 'pro'},
    'lifetime': {'name': 'Premium Lifetime', 'price': 499, 'days': None, 'tier': 'premium'},
}

# Subscription tier feature limits
SUBSCRIPTION_TIERS = {
    'free': {
        'name': 'Free',
        'symbols': ['BTC/USDT'],  # Only BTC
        'max_symbols': 1,
        'daily_notifications': 3,
        'dashboard': 'limited',  # BTC only
        'patterns_page': False,
        'patterns_limit': 0,
        'signals_page': False,
        'signals_limit': 0,
        'analytics_page': False,
        'portfolio': False,
        'portfolio_limit': 0,
        'transactions_limit': 0,
        'backtest': False,
        'stats_page': 'limited',  # BTC only
        'api_access': False,
        'priority_support': False,
        'settings': ['ntfy'],  # Only NTFY settings
        'risk_parameters': False,
    },
    'pro': {
        'name': 'Pro',
        'symbols': None,  # Any symbol
        'max_symbols': 10,
        'daily_notifications': 100,
        'dashboard': 'full',
        'patterns_page': True,
        'patterns_limit': 100,  # Last 100 entries
        'signals_page': True,
        'signals_limit': 100,  # Last 100 entries
        'analytics_page': True,  # No recent backtest
        'portfolio': True,
        'portfolio_limit': 1,
        'transactions_limit': 10,
        'backtest': False,
        'stats_page': 'full',
        'api_access': False,
        'priority_support': False,
        'settings': ['ntfy', 'risk'],  # NTFY + Risk Parameters
        'risk_parameters': True,
    },
    'premium': {
        'name': 'Premium',
        'symbols': None,  # Any symbol
        'max_symbols': None,  # Unlimited
        'daily_notifications': None,  # Unlimited
        'dashboard': 'full',
        'patterns_page': True,
        'patterns_limit': None,  # Full history
        'signals_page': True,
        'signals_limit': None,  # Full history
        'analytics_page': True,  # Full with backtest
        'portfolio': True,
        'portfolio_limit': None,  # Unlimited
        'transactions_limit': None,  # Unlimited
        'backtest': True,
        'stats_page': 'full',
        'api_access': True,
        'priority_support': True,
        'settings': ['ntfy', 'risk'],  # NTFY + Risk Parameters
        'risk_parameters': True,
    },
}

# Subscription status options
SUBSCRIPTION_STATUSES = ['active', 'expired', 'cancelled', 'suspended']


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

    # Two-factor authentication (TOTP)
    totp_secret = db.Column(db.String(32), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False)

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

    def generate_totp_secret(self):
        """Generate a new TOTP secret for 2FA"""
        import pyotp
        self.totp_secret = pyotp.random_base32()
        return self.totp_secret

    def get_totp_uri(self):
        """Get the TOTP provisioning URI for QR code"""
        import pyotp
        if not self.totp_secret:
            return None
        return pyotp.totp.TOTP(self.totp_secret).provisioning_uri(
            name=self.email,
            issuer_name='CryptoLens'
        )

    def verify_totp(self, token):
        """Verify a TOTP token"""
        import pyotp
        if not self.totp_secret:
            return False
        totp = pyotp.TOTP(self.totp_secret)
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


# Payment status options
PAYMENT_STATUSES = ['pending', 'completed', 'failed', 'refunded', 'expired']
PAYMENT_PROVIDERS = ['lemonsqueezy', 'nowpayments']


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
