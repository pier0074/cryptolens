"""
Portfolio models: Portfolio, Trade, TradeTag, JournalEntry
"""
from datetime import datetime, timezone
from app import db


# Association table for Trade-Tag many-to-many
trade_tags = db.Table('trade_tag_association',
    db.Column('trade_id', db.Integer, db.ForeignKey('trades.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('trade_tags.id'), primary_key=True)
)


class Portfolio(db.Model):
    """Trading Portfolio"""
    __tablename__ = 'portfolios'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Owner of the portfolio
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    initial_balance = db.Column(db.Float, default=10000.0)
    current_balance = db.Column(db.Float, default=10000.0)
    currency = db.Column(db.String(10), default='USDT')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('portfolios', lazy='dynamic'))
    trades = db.relationship('Trade', backref='portfolio', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_portfolio_user', 'user_id', 'is_active'),
    )

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
            'user_id': self.user_id,
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
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    signal = db.relationship('Signal', backref='trades')
    tags = db.relationship('TradeTag', secondary=trade_tags, lazy='subquery',
                          backref=db.backref('trades', lazy=True))
    journal_entries = db.relationship('JournalEntry', backref='trade', lazy='dynamic',
                                     cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_trade_portfolio_status', 'portfolio_id', 'status'),
        db.Index('idx_trade_symbol', 'symbol'),
        db.Index('idx_trade_signal', 'signal_id'),
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
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

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
