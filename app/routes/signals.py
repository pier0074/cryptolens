from flask import Blueprint, render_template, request, jsonify, abort
from app.models import Symbol, Signal, Pattern
from app import db
from app.decorators import login_required, feature_required, limit_query_results, get_current_user, filter_symbols_by_tier

signals_bp = Blueprint('signals', __name__)


@signals_bp.route('/')
@login_required
@feature_required('signals_page')
def index():
    """Signal list (Pro+ required)"""
    user = get_current_user()
    symbol_filter = request.args.get('symbol', '').strip()
    direction_filter = request.args.get('direction', None)

    # Get symbols filtered by tier (Pro: 5, Premium: all)
    all_symbols = Symbol.query.filter_by(is_active=True).order_by(Symbol.symbol).all()
    allowed_symbols = filter_symbols_by_tier(all_symbols, user)
    allowed_symbol_ids = [s.id for s in allowed_symbols]

    query = Signal.query

    # Filter signals to only allowed symbols
    if allowed_symbol_ids:
        query = query.filter(Signal.symbol_id.in_(allowed_symbol_ids))

    # Additional symbol filter (search by symbol name)
    if symbol_filter:
        matching_symbols = [s for s in allowed_symbols if symbol_filter.lower() in s.symbol.lower()]
        symbol_ids = [s.id for s in matching_symbols]
        if symbol_ids:
            query = query.filter(Signal.symbol_id.in_(symbol_ids))
        else:
            query = query.filter(Signal.symbol_id == -1)  # No matches

    if direction_filter:
        # Signals use 'long'/'short' directly
        query = query.filter_by(direction=direction_filter)

    # Apply tier-based limit (Pro: 50, Premium: unlimited)
    query = query.order_by(Signal.created_at.desc())
    query = limit_query_results(query, 'signals_limit')
    signals = query.all()

    # Enrich with symbol and pattern data
    for signal in signals:
        signal.symbol_obj = db.session.get(Symbol, signal.symbol_id)
        if signal.pattern_id:
            signal.pattern_obj = db.session.get(Pattern, signal.pattern_id)
        else:
            signal.pattern_obj = None

    return render_template('signals.html',
                           signals=signals,
                           symbols=allowed_symbols,  # Only show allowed symbols in dropdown
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
