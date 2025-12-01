from flask import Blueprint, render_template, request, jsonify
from app.models import Symbol, Signal
from app import db

signals_bp = Blueprint('signals', __name__)


@signals_bp.route('/')
def index():
    """Signal list"""
    status_filter = request.args.get('status', None)
    direction_filter = request.args.get('direction', None)

    query = Signal.query

    if status_filter:
        query = query.filter_by(status=status_filter)

    if direction_filter:
        query = query.filter_by(direction=direction_filter)

    signals = query.order_by(Signal.created_at.desc()).limit(50).all()

    # Enrich with symbol data
    for signal in signals:
        signal.symbol_obj = Symbol.query.get(signal.symbol_id)

    return render_template('signals.html',
                           signals=signals,
                           current_status=status_filter,
                           current_direction=direction_filter)


@signals_bp.route('/<int:signal_id>')
def detail(signal_id):
    """Signal detail view"""
    signal = Signal.query.get_or_404(signal_id)
    signal.symbol_obj = Symbol.query.get(signal.symbol_id)

    return render_template('signal_detail.html', signal=signal)


@signals_bp.route('/<int:signal_id>/status', methods=['POST'])
def update_status(signal_id):
    """Update signal status"""
    signal = Signal.query.get_or_404(signal_id)
    data = request.get_json()

    if 'status' in data:
        signal.status = data['status']
        db.session.commit()

    return jsonify({'success': True, 'signal': signal.to_dict()})
