from flask import Blueprint, render_template, request, jsonify, abort
from app.models import Symbol, Signal, Pattern
from app import db

signals_bp = Blueprint('signals', __name__)


@signals_bp.route('/')
def index():
    """Signal list"""
    symbol_filter = request.args.get('symbol', '').strip()
    direction_filter = request.args.get('direction', None)

    query = Signal.query

    # Symbol filter (search by symbol name)
    if symbol_filter:
        matching_symbols = Symbol.query.filter(
            Symbol.symbol.ilike(f'%{symbol_filter}%')
        ).all()
        symbol_ids = [s.id for s in matching_symbols]
        if symbol_ids:
            query = query.filter(Signal.symbol_id.in_(symbol_ids))
        else:
            query = query.filter(Signal.symbol_id == -1)  # No matches

    if direction_filter:
        # Convert 'long' to 'bullish', 'short' to 'bearish'
        db_direction = 'bullish' if direction_filter == 'long' else 'bearish'
        query = query.filter_by(direction=db_direction)

    signals = query.order_by(Signal.created_at.desc()).limit(50).all()

    # Get all symbols for dropdown
    symbols = Symbol.query.filter_by(is_active=True).order_by(Symbol.symbol).all()

    # Enrich with symbol and pattern data
    for signal in signals:
        signal.symbol_obj = db.session.get(Symbol, signal.symbol_id)
        if signal.pattern_id:
            signal.pattern_obj = db.session.get(Pattern, signal.pattern_id)
        else:
            signal.pattern_obj = None

    return render_template('signals.html',
                           signals=signals,
                           symbols=symbols,
                           current_symbol=symbol_filter,
                           current_direction=direction_filter)


@signals_bp.route('/<int:signal_id>')
def detail(signal_id):
    """Signal detail view"""
    signal = db.session.get(Signal, signal_id)
    if signal is None:
        abort(404)
    signal.symbol_obj = db.session.get(Symbol, signal.symbol_id)

    return render_template('signal_detail.html', signal=signal)


@signals_bp.route('/<int:signal_id>/status', methods=['POST'])
def update_status(signal_id):
    """Update signal status"""
    signal = db.session.get(Signal, signal_id)
    if signal is None:
        abort(404)
    data = request.get_json()

    if 'status' in data:
        signal.status = data['status']
        db.session.commit()

    return jsonify({'success': True, 'signal': signal.to_dict()})
