"""
Portfolio Routes
CRUD operations for portfolios, trades, and journal entries.
"""
from flask import Blueprint, render_template, request, jsonify, abort, redirect, url_for, flash
from datetime import datetime, timezone
from app.models import (
    Portfolio, Trade, JournalEntry, TradeTag, Signal, Symbol,
    TRADE_MOODS, TRADE_STATUSES
)
from app import db
from app.decorators import login_required, feature_required, check_feature_limit, get_current_user

portfolio_bp = Blueprint('portfolio', __name__)


# ==================== VALIDATION HELPERS ====================

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


def validate_positive_float(value, field_name, min_val=0.00000001, max_val=1_000_000_000):
    """Validate that a value is a positive float within bounds"""
    if value is None or value == '':
        raise ValidationError(f"{field_name} is required")
    try:
        val = float(value)
        if val < min_val:
            raise ValidationError(f"{field_name} must be at least {min_val}")
        if val > max_val:
            raise ValidationError(f"{field_name} must be less than {max_val:,}")
        return val
    except (ValueError, TypeError):
        raise ValidationError(f"{field_name} must be a valid number")


def validate_string(value, field_name, min_len=1, max_len=100):
    """Validate that a string is within length bounds"""
    if value is None or str(value).strip() == '':
        raise ValidationError(f"{field_name} is required")
    val = str(value).strip()
    if len(val) < min_len:
        raise ValidationError(f"{field_name} must be at least {min_len} characters")
    if len(val) > max_len:
        raise ValidationError(f"{field_name} must be less than {max_len} characters")
    return val


def validate_optional_positive_float(value, field_name, min_val=0.00000001, max_val=1_000_000_000):
    """Validate an optional positive float"""
    if value is None or value == '':
        return None
    return validate_positive_float(value, field_name, min_val, max_val)


# ==================== PORTFOLIO CRUD ====================

@portfolio_bp.route('/')
@login_required
@feature_required('portfolio')
def index():
    """Portfolio list and overview (Pro+ required)"""
    portfolios = Portfolio.query.filter_by(is_active=True).all()

    # Calculate summary stats
    total_balance = sum(p.current_balance for p in portfolios)
    total_pnl = sum(p.total_pnl for p in portfolios)

    return render_template('portfolio/index.html',
                          portfolios=portfolios,
                          total_balance=total_balance,
                          total_pnl=total_pnl)


@portfolio_bp.route('/create', methods=['GET', 'POST'])
@login_required
@feature_required('portfolio')
def create():
    """Create a new portfolio (Pro+ required)"""
    if request.method == 'POST':
        data = request.form
        try:
            # Validate inputs
            name = validate_string(data.get('name'), 'Portfolio name', min_len=1, max_len=100)
            initial_balance = validate_positive_float(
                data.get('initial_balance', 10000),
                'Initial balance',
                min_val=0.01,
                max_val=1_000_000_000
            )

            portfolio = Portfolio(
                name=name,
                description=data.get('description', '').strip()[:500] if data.get('description') else None,
                initial_balance=initial_balance,
                current_balance=initial_balance,
                currency=data.get('currency', 'USDT')[:10]
            )
            db.session.add(portfolio)
            db.session.commit()
            return redirect(url_for('portfolio.detail', portfolio_id=portfolio.id))
        except ValidationError as e:
            flash(str(e), 'error')
            return render_template('portfolio/create.html', error=str(e))

    return render_template('portfolio/create.html')


@portfolio_bp.route('/<int:portfolio_id>')
def detail(portfolio_id):
    """Portfolio detail view with trades"""
    from app.models import Candle
    from sqlalchemy import func, and_

    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        abort(404)

    # Get trades with filters
    status_filter = request.args.get('status', None)

    trades_query = portfolio.trades
    if status_filter:
        trades_query = trades_query.filter_by(status=status_filter)

    trades = trades_query.order_by(Trade.created_at.desc()).limit(50).all()

    # Get current prices for symbols in trades
    trade_symbols = list(set(t.symbol for t in trades))
    current_prices = {}

    if trade_symbols:
        # Get symbol IDs
        symbols = Symbol.query.filter(Symbol.symbol.in_(trade_symbols)).all()
        symbol_map = {s.symbol: s.id for s in symbols}
        symbol_ids = list(symbol_map.values())

        if symbol_ids:
            # Get latest 1m candle for each symbol
            latest_subq = db.session.query(
                Candle.symbol_id,
                func.max(Candle.timestamp).label('max_ts')
            ).filter(
                Candle.symbol_id.in_(symbol_ids),
                Candle.timeframe == '1m'
            ).group_by(Candle.symbol_id).subquery()

            latest_candles = db.session.query(Candle).join(
                latest_subq,
                and_(
                    Candle.symbol_id == latest_subq.c.symbol_id,
                    Candle.timestamp == latest_subq.c.max_ts,
                    Candle.timeframe == '1m'
                )
            ).all()

            # Map symbol name to price
            id_to_symbol = {v: k for k, v in symbol_map.items()}
            current_prices = {id_to_symbol[c.symbol_id]: c.close for c in latest_candles}

    # Attach current price to each trade
    for trade in trades:
        trade.current_price = current_prices.get(trade.symbol)

    # Calculate stats
    closed_trades = portfolio.trades.filter_by(status='closed').all()
    winning_trades = [t for t in closed_trades if t.pnl_amount and t.pnl_amount > 0]
    losing_trades = [t for t in closed_trades if t.pnl_amount and t.pnl_amount < 0]

    win_rate = len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = sum(t.pnl_amount for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t.pnl_amount for t in losing_trades) / len(losing_trades) if losing_trades else 0

    stats = {
        'total_trades': len(closed_trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': round(win_rate, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(abs(avg_loss), 2),
        'profit_factor': abs(sum(t.pnl_amount for t in winning_trades) / sum(t.pnl_amount for t in losing_trades)) if losing_trades and sum(t.pnl_amount for t in losing_trades) != 0 else 0
    }

    return render_template('portfolio/detail.html',
                          portfolio=portfolio,
                          trades=trades,
                          stats=stats,
                          trade_statuses=TRADE_STATUSES,
                          current_status=status_filter)


@portfolio_bp.route('/<int:portfolio_id>/edit', methods=['GET', 'POST'])
def edit(portfolio_id):
    """Edit portfolio"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        abort(404)

    if request.method == 'POST':
        data = request.form
        portfolio.name = data.get('name', portfolio.name)
        portfolio.description = data.get('description')
        portfolio.currency = data.get('currency', portfolio.currency)
        db.session.commit()
        return redirect(url_for('portfolio.detail', portfolio_id=portfolio.id))

    return render_template('portfolio/edit.html', portfolio=portfolio)


@portfolio_bp.route('/<int:portfolio_id>/delete', methods=['POST'])
def delete(portfolio_id):
    """Delete portfolio (soft delete by setting is_active=False)"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        abort(404)

    portfolio.is_active = False
    db.session.commit()
    return redirect(url_for('portfolio.index'))


# ==================== TRADE CRUD ====================

def _get_current_prices():
    """Get current prices for all active symbols"""
    from app.models import Candle
    from sqlalchemy import func, and_

    symbols = Symbol.query.filter_by(is_active=True).all()
    symbol_ids = [s.id for s in symbols]

    if not symbol_ids:
        return {}

    # Get latest 1m candle for each symbol
    latest_subq = db.session.query(
        Candle.symbol_id,
        func.max(Candle.timestamp).label('max_ts')
    ).filter(
        Candle.symbol_id.in_(symbol_ids),
        Candle.timeframe == '1m'
    ).group_by(Candle.symbol_id).subquery()

    latest_candles = db.session.query(Candle).join(
        latest_subq,
        and_(
            Candle.symbol_id == latest_subq.c.symbol_id,
            Candle.timestamp == latest_subq.c.max_ts,
            Candle.timeframe == '1m'
        )
    ).all()

    return {c.symbol_id: c.close for c in latest_candles}


@portfolio_bp.route('/<int:portfolio_id>/trades/new', methods=['GET', 'POST'])
def new_trade(portfolio_id):
    """Create a new trade"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        abort(404)

    if request.method == 'POST':
        data = request.form

        try:
            # Validate required inputs
            symbol = validate_string(data.get('symbol'), 'Symbol', min_len=3, max_len=20)
            entry_price = validate_positive_float(data.get('entry_price'), 'Entry price')
            entry_quantity = validate_positive_float(data.get('entry_quantity'), 'Entry quantity')

            # Validate optional price fields
            stop_loss = validate_optional_positive_float(data.get('stop_loss'), 'Stop loss')
            take_profit = validate_optional_positive_float(data.get('take_profit'), 'Take profit')

            # Calculate risk amount if percentage given
            risk_percent = validate_optional_positive_float(data.get('risk_percent'), 'Risk percent', max_val=100)
            risk_amount = portfolio.current_balance * (risk_percent / 100) if risk_percent else None

            trade = Trade(
                portfolio_id=portfolio_id,
                signal_id=int(data.get('signal_id')) if data.get('signal_id') else None,
                symbol=symbol,
                direction=data.get('direction', 'long'),
                timeframe=data.get('timeframe'),
                pattern_type=data.get('pattern_type'),
                entry_price=entry_price,
                entry_quantity=entry_quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=risk_amount,
                risk_percent=risk_percent,
                setup_notes=data.get('setup_notes'),
                lessons_learned=data.get('lessons_learned')
            )
            db.session.add(trade)
            db.session.commit()

            return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade.id))
        except ValidationError as e:
            flash(str(e), 'error')
            # Re-render form with error
            symbols = Symbol.query.filter_by(is_active=True).all()
            current_prices = _get_current_prices()
            return render_template('portfolio/trade_form.html',
                                  portfolio=portfolio,
                                  symbols=symbols,
                                  current_prices=current_prices,
                                  trade=None,
                                  is_edit=False,
                                  error=str(e))

    # Get symbols and current prices
    symbols = Symbol.query.filter_by(is_active=True).all()
    current_prices = _get_current_prices()

    return render_template('portfolio/trade_form.html',
                          portfolio=portfolio,
                          symbols=symbols,
                          current_prices=current_prices,
                          trade=None,
                          is_edit=False)


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>')
def trade_detail(portfolio_id, trade_id):
    """Trade detail view with journal entries"""
    from app.models import Candle
    from sqlalchemy import func, and_

    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    # Get current price for this symbol
    current_price = None
    symbol = Symbol.query.filter_by(symbol=trade.symbol).first()
    if symbol:
        latest_candle = Candle.query.filter_by(
            symbol_id=symbol.id,
            timeframe='1m'
        ).order_by(Candle.timestamp.desc()).first()
        if latest_candle:
            current_price = latest_candle.close

    trade.current_price = current_price

    journal_entries = trade.journal_entries.order_by(JournalEntry.created_at.desc()).all()

    return render_template('portfolio/trade_detail.html',
                          portfolio=portfolio,
                          trade=trade,
                          journal_entries=journal_entries,
                          trade_moods=TRADE_MOODS)


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/open', methods=['POST'])
def open_trade(portfolio_id, trade_id):
    """Open a pending trade"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    if trade.status != 'pending':
        abort(400)

    data = request.form
    trade.entry_price = float(data.get('entry_price'))
    trade.entry_quantity = float(data.get('entry_quantity'))
    trade.status = 'open'
    trade.entry_time = datetime.now(timezone.utc)

    db.session.commit()

    return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/cancel', methods=['POST'])
def cancel_trade(portfolio_id, trade_id):
    """Cancel a pending trade"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    if trade.status != 'pending':
        abort(400)

    trade.status = 'cancelled'
    db.session.commit()

    return redirect(url_for('portfolio.detail', portfolio_id=portfolio_id))


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/close', methods=['POST'])
def close_trade(portfolio_id, trade_id):
    """Close an open trade at specified price"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    if trade.status != 'open':
        abort(400)

    data = request.form
    exit_price = float(data.get('exit_price'))
    reason = data.get('reason', 'Manual')

    trade.close(exit_price, f"Closed: {reason}")

    db.session.commit()

    return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/close-market', methods=['POST'])
def close_trade_market(portfolio_id, trade_id):
    """Close an open trade at current market price"""
    from app.models import Candle

    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    if trade.status != 'open':
        abort(400)

    # Get current market price
    symbol = Symbol.query.filter_by(symbol=trade.symbol).first()
    if symbol:
        latest_candle = Candle.query.filter_by(
            symbol_id=symbol.id,
            timeframe='1m'
        ).order_by(Candle.timestamp.desc()).first()

        if latest_candle:
            exit_price = latest_candle.close
            trade.close(exit_price, "Closed at market price")
            db.session.commit()
            return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))

    # If we can't get market price, redirect back with error
    return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/edit', methods=['GET', 'POST'])
def edit_trade(portfolio_id, trade_id):
    """Edit trade details"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    if request.method == 'POST':
        data = request.form

        trade.symbol = data.get('symbol', trade.symbol)
        trade.direction = data.get('direction', trade.direction)
        trade.timeframe = data.get('timeframe')
        trade.pattern_type = data.get('pattern_type')
        trade.stop_loss = float(data.get('stop_loss')) if data.get('stop_loss') else None
        trade.take_profit = float(data.get('take_profit')) if data.get('take_profit') else None
        trade.setup_notes = data.get('setup_notes')
        trade.lessons_learned = data.get('lessons_learned')

        # Update entry details if provided
        if data.get('entry_price'):
            trade.entry_price = float(data.get('entry_price'))
        if data.get('entry_quantity'):
            trade.entry_quantity = float(data.get('entry_quantity'))
        if data.get('risk_percent'):
            trade.risk_percent = float(data.get('risk_percent'))
            trade.risk_amount = portfolio.current_balance * (trade.risk_percent / 100)

        db.session.commit()
        return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))

    symbols = Symbol.query.filter_by(is_active=True).all()
    current_prices = _get_current_prices()

    return render_template('portfolio/trade_form.html',
                          portfolio=portfolio,
                          trade=trade,
                          symbols=symbols,
                          current_prices=current_prices,
                          is_edit=True)


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/delete', methods=['POST'])
def delete_trade(portfolio_id, trade_id):
    """Delete a trade"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    trade = db.session.get(Trade, trade_id)

    if not portfolio or not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    # Revert balance if trade was closed
    if trade.status == 'closed' and trade.pnl_amount:
        portfolio.current_balance -= trade.pnl_amount

    db.session.delete(trade)
    db.session.commit()

    return redirect(url_for('portfolio.detail', portfolio_id=portfolio_id))


# ==================== JOURNAL ENTRIES ====================

@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/journal', methods=['POST'])
def add_journal_entry(portfolio_id, trade_id):
    """Add a journal entry to a trade"""
    trade = db.session.get(Trade, trade_id)

    if not trade or trade.portfolio_id != portfolio_id:
        abort(404)

    data = request.form

    entry = JournalEntry(
        trade_id=trade_id,
        entry_type=data.get('entry_type', 'during'),
        content=data.get('content'),
        mood=data.get('mood')
    )
    db.session.add(entry)
    db.session.commit()

    return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))


@portfolio_bp.route('/<int:portfolio_id>/trades/<int:trade_id>/journal/<int:entry_id>/delete', methods=['POST'])
def delete_journal_entry(portfolio_id, trade_id, entry_id):
    """Delete a journal entry"""
    entry = db.session.get(JournalEntry, entry_id)

    if not entry or entry.trade_id != trade_id:
        abort(404)

    db.session.delete(entry)
    db.session.commit()

    return redirect(url_for('portfolio.trade_detail', portfolio_id=portfolio_id, trade_id=trade_id))


# ==================== TAGS ====================

@portfolio_bp.route('/tags')
def tags():
    """List and manage tags"""
    tags = TradeTag.query.all()
    return render_template('portfolio/tags.html', tags=tags)


@portfolio_bp.route('/tags/create', methods=['POST'])
def create_tag():
    """Create a new tag"""
    data = request.form
    tag = TradeTag(
        name=data.get('name'),
        color=data.get('color', '#6366f1'),
        description=data.get('description')
    )
    db.session.add(tag)
    db.session.commit()
    return redirect(url_for('portfolio.tags'))


@portfolio_bp.route('/tags/<int:tag_id>/delete', methods=['POST'])
def delete_tag(tag_id):
    """Delete a tag"""
    tag = db.session.get(TradeTag, tag_id)
    if tag:
        db.session.delete(tag)
        db.session.commit()
    return redirect(url_for('portfolio.tags'))


# ==================== API ENDPOINTS ====================

@portfolio_bp.route('/api/portfolios')
def api_portfolios():
    """API: Get all portfolios"""
    portfolios = Portfolio.query.filter_by(is_active=True).all()
    return jsonify([p.to_dict() for p in portfolios])


@portfolio_bp.route('/api/portfolios/<int:portfolio_id>')
def api_portfolio_detail(portfolio_id):
    """API: Get portfolio detail"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        return jsonify({'error': 'Portfolio not found'}), 404
    return jsonify(portfolio.to_dict())


@portfolio_bp.route('/api/portfolios/<int:portfolio_id>/trades')
def api_portfolio_trades(portfolio_id):
    """API: Get trades for a portfolio"""
    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        return jsonify({'error': 'Portfolio not found'}), 404

    trades = portfolio.trades.order_by(Trade.created_at.desc()).limit(100).all()
    return jsonify([t.to_dict() for t in trades])


@portfolio_bp.route('/api/trade-from-pattern', methods=['POST'])
def api_trade_from_pattern():
    """Create a trade from a pattern with pre-filled data"""
    from app.models import Pattern
    from app.services.trading import get_trading_levels_for_pattern
    from app.routes.patterns import get_candles_df

    data = request.get_json()
    pattern_id = data.get('pattern_id')
    portfolio_id = data.get('portfolio_id')

    if not pattern_id:
        return jsonify({'error': 'pattern_id is required'}), 400

    pattern = db.session.get(Pattern, pattern_id)
    if not pattern:
        return jsonify({'error': 'Pattern not found'}), 404

    # Get or create default portfolio
    if portfolio_id:
        portfolio = db.session.get(Portfolio, portfolio_id)
    else:
        portfolio = Portfolio.query.filter_by(is_active=True).first()

    if not portfolio:
        # Create a default portfolio if none exists
        portfolio = Portfolio(
            name='Default Portfolio',
            initial_balance=10000,
            current_balance=10000,
            currency='USDT'
        )
        db.session.add(portfolio)
        db.session.commit()

    # Get trading levels for this pattern
    df = get_candles_df(pattern.symbol_id, pattern.timeframe)
    levels = get_trading_levels_for_pattern(pattern, df)

    # Create the trade with status 'pending' (user needs to confirm)
    trade = Trade(
        portfolio_id=portfolio.id,
        symbol=pattern.symbol.symbol,
        direction='long' if pattern.direction == 'bullish' else 'short',
        timeframe=pattern.timeframe,
        pattern_type=pattern.pattern_type,
        entry_price=levels['entry'],
        entry_quantity=0,  # User must set this
        stop_loss=levels['stop_loss'],
        take_profit=levels['take_profit_2'],  # Use TP2 as default
        status='pending',
        setup_notes=f"Auto-created from {pattern.pattern_type} pattern on {pattern.timeframe}"
    )
    db.session.add(trade)
    db.session.commit()

    return jsonify({
        'success': True,
        'trade_id': trade.id,
        'portfolio_id': portfolio.id,
        'redirect_url': f'/portfolio/{portfolio.id}/trades/{trade.id}/edit'
    })


@portfolio_bp.route('/api/trade-from-signal', methods=['POST'])
def api_trade_from_signal():
    """Create a trade from a signal with pre-filled data"""
    data = request.get_json()
    signal_id = data.get('signal_id')
    portfolio_id = data.get('portfolio_id')

    if not signal_id:
        return jsonify({'error': 'signal_id is required'}), 400

    signal = db.session.get(Signal, signal_id)
    if not signal:
        return jsonify({'error': 'Signal not found'}), 404

    # Get or create default portfolio
    if portfolio_id:
        portfolio = db.session.get(Portfolio, portfolio_id)
    else:
        portfolio = Portfolio.query.filter_by(is_active=True).first()

    if not portfolio:
        portfolio = Portfolio(
            name='Default Portfolio',
            initial_balance=10000,
            current_balance=10000,
            currency='USDT'
        )
        db.session.add(portfolio)
        db.session.commit()

    # Create the trade with status 'pending'
    trade = Trade(
        portfolio_id=portfolio.id,
        signal_id=signal.id,
        symbol=signal.symbol.symbol,
        direction=signal.direction,
        timeframe=signal.pattern.timeframe if signal.pattern else None,
        pattern_type=signal.pattern.pattern_type if signal.pattern else None,
        entry_price=signal.entry_price,
        entry_quantity=0,  # User must set this
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit_2,  # Use TP2 as default
        status='pending',
        setup_notes=f"Auto-created from {signal.direction} signal (confluence: {signal.confluence_score})"
    )
    db.session.add(trade)
    db.session.commit()

    return jsonify({
        'success': True,
        'trade_id': trade.id,
        'portfolio_id': portfolio.id,
        'redirect_url': f'/portfolio/{portfolio.id}/trades/{trade.id}/edit'
    })


@portfolio_bp.route('/api/portfolios/<int:portfolio_id>/stats')
def api_portfolio_stats(portfolio_id):
    """API: Get portfolio statistics (optimized with SQL aggregation)"""
    from sqlalchemy import func, case

    portfolio = db.session.get(Portfolio, portfolio_id)
    if not portfolio:
        return jsonify({'error': 'Portfolio not found'}), 404

    # Main stats query - single SQL aggregation instead of loading all trades
    stats = db.session.query(
        func.count(Trade.id).label('total_trades'),
        func.sum(case((Trade.pnl_amount > 0, 1), else_=0)).label('winning_trades'),
        func.sum(case((Trade.pnl_amount < 0, 1), else_=0)).label('losing_trades'),
        func.coalesce(func.sum(Trade.pnl_amount), 0).label('total_pnl'),
        func.coalesce(func.sum(case((Trade.pnl_amount > 0, Trade.pnl_amount), else_=0)), 0).label('gross_profit'),
        func.coalesce(func.sum(case((Trade.pnl_amount < 0, func.abs(Trade.pnl_amount)), else_=0)), 0).label('gross_loss'),
        func.coalesce(func.avg(Trade.pnl_r), 0).label('avg_r')
    ).filter(
        Trade.portfolio_id == portfolio_id,
        Trade.status == 'closed'
    ).first()

    total_trades = stats.total_trades or 0
    winning_trades = int(stats.winning_trades or 0)
    losing_trades = int(stats.losing_trades or 0)
    total_pnl = float(stats.total_pnl or 0)
    gross_profit = float(stats.gross_profit or 0)
    gross_loss = float(stats.gross_loss or 0)
    avg_r = float(stats.avg_r or 0)

    # By-symbol stats - single query with GROUP BY
    symbol_stats = db.session.query(
        Trade.symbol,
        func.count(Trade.id).label('trades'),
        func.coalesce(func.sum(Trade.pnl_amount), 0).label('pnl'),
        func.sum(case((Trade.pnl_amount > 0, 1), else_=0)).label('wins')
    ).filter(
        Trade.portfolio_id == portfolio_id,
        Trade.status == 'closed'
    ).group_by(Trade.symbol).all()

    by_symbol = {
        row.symbol: {
            'trades': row.trades,
            'pnl': float(row.pnl),
            'wins': int(row.wins)
        }
        for row in symbol_stats
    }

    return jsonify({
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': round(winning_trades / total_trades * 100, 1) if total_trades else 0,
        'total_pnl': round(total_pnl, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        'avg_win': round(gross_profit / winning_trades, 2) if winning_trades else 0,
        'avg_loss': round(gross_loss / losing_trades, 2) if losing_trades else 0,
        'avg_r': round(avg_r, 2),
        'by_symbol': by_symbol
    })
