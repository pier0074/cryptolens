from datetime import datetime, timezone
from app import db


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
    is_active = db.Column(db.Boolean, default=True)
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
            'is_active': self.is_active
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

    __table_args__ = (
        db.Index('idx_pattern_active', 'symbol_id', 'timeframe', 'status'),
        db.Index('idx_pattern_detected', 'detected_at'),
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
            'fill_percentage': self.fill_percentage
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
