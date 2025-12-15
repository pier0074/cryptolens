"""
Trading models: Symbol, Candle, Pattern, Signal, Notification
"""
from datetime import datetime, timezone
from app import db


class Symbol(db.Model):
    """Symbols to track"""
    __tablename__ = 'symbols'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), unique=True, nullable=False)  # e.g., "BTC/USDT"
    exchange = db.Column(db.String(20), default='kucoin')
    is_active = db.Column(db.Boolean, default=True)  # Whether to fetch candles
    notify_enabled = db.Column(db.Boolean, default=True)  # Whether to send notifications
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships - cascade delete ensures child records are removed when symbol is deleted
    candles = db.relationship('Candle', backref='symbol', lazy='dynamic',
                              cascade='all, delete-orphan', passive_deletes=True)
    patterns = db.relationship('Pattern', backref='symbol', lazy='dynamic',
                               cascade='all, delete-orphan', passive_deletes=True)
    signals = db.relationship('Signal', backref='symbol', lazy='dynamic',
                              cascade='all, delete-orphan', passive_deletes=True)

    __table_args__ = (
        db.Index('idx_symbol_is_active', 'is_active'),
    )

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
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id', ondelete='CASCADE'), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)  # '1m', '5m', '15m', '1h', '4h', '1d'
    timestamp = db.Column(db.BigInteger, nullable=False)  # Unix timestamp in milliseconds
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    verified_at = db.Column(db.BigInteger, nullable=True)  # Timestamp when health check passed (ms)

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
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id', ondelete='CASCADE'), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    pattern_type = db.Column(db.String(30), nullable=False)  # 'imbalance', 'order_block', etc.
    direction = db.Column(db.String(10), nullable=False)  # 'bullish', 'bearish'
    zone_high = db.Column(db.Float, nullable=False)
    zone_low = db.Column(db.Float, nullable=False)
    detected_at = db.Column(db.BigInteger, nullable=False)  # Candle timestamp when detected (ms)
    status = db.Column(db.String(15), default='active')  # 'active', 'filled', 'expired'
    filled_at = db.Column(db.BigInteger, nullable=True)  # Timestamp when filled (ms)
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
        db.Index('idx_pattern_direction', 'direction'),
        db.Index('idx_pattern_type', 'pattern_type'),
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
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id', ondelete='CASCADE'), nullable=False)
    direction = db.Column(db.String(10), nullable=False)  # 'long', 'short'
    entry_price = db.Column(db.Float, nullable=False)
    stop_loss = db.Column(db.Float, nullable=False)
    take_profit_1 = db.Column(db.Float, nullable=False)
    take_profit_2 = db.Column(db.Float, nullable=True)
    take_profit_3 = db.Column(db.Float, nullable=True)
    risk_reward = db.Column(db.Float, nullable=False)
    confluence_score = db.Column(db.Integer, default=1)  # How many timeframes agree
    timeframes_aligned = db.Column(db.Text, nullable=True)  # JSON array of aligned TFs
    pattern_id = db.Column(db.Integer, db.ForeignKey('patterns.id', ondelete='CASCADE'), nullable=True)
    status = db.Column(db.String(15), default='pending')  # 'pending', 'notified', 'filled', 'stopped', 'tp_hit'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = db.Column(db.DateTime, nullable=True)

    # Relationship - signals are deleted when pattern is deleted
    pattern = db.relationship('Pattern', backref=db.backref('signals', cascade='all, delete-orphan',
                                                            passive_deletes=True))

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
    signal_id = db.Column(db.Integer, db.ForeignKey('signals.id', ondelete='CASCADE'), nullable=False)
    channel = db.Column(db.String(20), nullable=False)  # 'ntfy', 'telegram', 'email'
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text, nullable=True)

    # Relationship - notifications are deleted when signal is deleted
    signal = db.relationship('Signal', backref=db.backref('notifications', cascade='all, delete-orphan',
                                                          passive_deletes=True))

    def __repr__(self):
        return f'<Notification {self.channel} {self.signal_id}>'


class KnownGap(db.Model):
    """
    Known/Accepted gaps in candle data.

    When the exchange has no data for a time range (e.g., no trades, maintenance),
    we record it here so verification can continue past it.
    """
    __tablename__ = 'known_gaps'

    id = db.Column(db.Integer, primary_key=True)
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id', ondelete='CASCADE'), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    gap_start = db.Column(db.BigInteger, nullable=False)  # First missing timestamp (ms)
    gap_end = db.Column(db.BigInteger, nullable=False)    # Last missing timestamp (ms)
    missing_candles = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(50), default='no_exchange_data')  # 'no_exchange_data', 'accepted', 'maintenance'
    verified_empty = db.Column(db.Boolean, default=False)  # True if we confirmed exchange has no data
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship - gaps are deleted when symbol is deleted
    symbol = db.relationship('Symbol', backref=db.backref('known_gaps', lazy='dynamic',
                                                          cascade='all, delete-orphan',
                                                          passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('symbol_id', 'timeframe', 'gap_start', name='uix_known_gap'),
        db.Index('idx_known_gap_lookup', 'symbol_id', 'timeframe', 'gap_start', 'gap_end'),
    )

    def __repr__(self):
        return f'<KnownGap {self.symbol_id} {self.timeframe} {self.gap_start}-{self.gap_end}>'

    @classmethod
    def is_known_gap(cls, symbol_id, timeframe, timestamp):
        """Check if a timestamp falls within a known gap."""
        return cls.query.filter(
            cls.symbol_id == symbol_id,
            cls.timeframe == timeframe,
            cls.gap_start <= timestamp,
            cls.gap_end >= timestamp
        ).first() is not None

    @classmethod
    def get_gaps_in_range(cls, symbol_id, timeframe, start_ts, end_ts):
        """Get all known gaps that overlap with a time range."""
        return cls.query.filter(
            cls.symbol_id == symbol_id,
            cls.timeframe == timeframe,
            cls.gap_start <= end_ts,
            cls.gap_end >= start_ts
        ).all()


class UserSymbolPreference(db.Model):
    """User-specific symbol notification preferences (for Premium users)"""
    __tablename__ = 'user_symbol_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    symbol_id = db.Column(db.Integer, db.ForeignKey('symbols.id', ondelete='CASCADE'), nullable=False)
    notify_enabled = db.Column(db.Boolean, default=True)  # User's notification preference
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    # Relationships - preferences are deleted when user or symbol is deleted
    user = db.relationship('User', backref=db.backref('symbol_preferences', lazy='dynamic',
                                                      cascade='all, delete-orphan',
                                                      passive_deletes=True))
    symbol = db.relationship('Symbol', backref=db.backref('user_preferences', lazy='dynamic',
                                                          cascade='all, delete-orphan',
                                                          passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'symbol_id', name='uix_user_symbol_pref'),
        db.Index('idx_user_symbol_pref', 'user_id', 'symbol_id'),
    )

    def __repr__(self):
        return f'<UserSymbolPreference user={self.user_id} symbol={self.symbol_id} notify={self.notify_enabled}>'

    @classmethod
    def get_or_create(cls, user_id, symbol_id):
        """Get or create a preference, defaulting to notify_enabled=True"""
        pref = cls.query.filter_by(user_id=user_id, symbol_id=symbol_id).first()
        if not pref:
            pref = cls(user_id=user_id, symbol_id=symbol_id, notify_enabled=True)
            db.session.add(pref)
            db.session.commit()
        return pref

    @classmethod
    def is_notify_enabled(cls, user_id, symbol_id):
        """Check if notifications are enabled for a user-symbol pair"""
        pref = cls.query.filter_by(user_id=user_id, symbol_id=symbol_id).first()
        # Default to True if no preference exists
        return pref.notify_enabled if pref else True

    @classmethod
    def toggle_notify(cls, user_id, symbol_id):
        """Toggle notification preference for a user-symbol pair"""
        pref = cls.get_or_create(user_id, symbol_id)
        pref.notify_enabled = not pref.notify_enabled
        db.session.commit()
        return pref.notify_enabled
