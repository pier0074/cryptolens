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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    __table_args__ = (
        db.UniqueConstraint('symbol_id', 'timeframe', 'timestamp', name='uix_candle'),
        db.Index('idx_candle_lookup', 'symbol_id', 'timeframe', 'timestamp'),
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
            'volume': self.volume
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
    status = db.Column(db.String(15), default='active')  # 'active', 'filled', 'invalidated'
    filled_at = db.Column(db.Integer, nullable=True)
    fill_percentage = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_pattern_active', 'symbol_id', 'timeframe', 'status'),
    )

    def __repr__(self):
        return f'<Pattern {self.pattern_type} {self.direction} {self.symbol_id}>'

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    pattern = db.relationship('Pattern', backref='signals')

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
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, key, default=None):
        """Get a setting value"""
        setting = cls.query.get(key)
        return setting.value if setting else default

    @classmethod
    def set(cls, key, value):
        """Set a setting value"""
        from app import db
        setting = cls.query.get(key)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
