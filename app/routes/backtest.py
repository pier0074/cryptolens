from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, abort
from app.models import Symbol, Backtest
from app.config import Config
from app import db
from app.decorators import login_required, feature_required

backtest_bp = Blueprint('backtest', __name__)


@backtest_bp.route('/')
@login_required
@feature_required('backtest')
def index():
    """Backtest interface (Premium only)"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    backtests = Backtest.query.order_by(Backtest.created_at.desc()).limit(20).all()

    return render_template('backtest.html',
                           symbols=symbols,
                           timeframes=Config.TIMEFRAMES,
                           backtests=backtests)


@backtest_bp.route('/run', methods=['POST'])
@login_required
@feature_required('backtest')
def run():
    """Run a backtest (Premium only)"""
    from app.services.patterns import PATTERN_TYPES

    # Validate JSON body
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'Invalid or missing JSON body'
        }), 400

    symbol = data.get('symbol')
    timeframe = data.get('timeframe')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    pattern_type = data.get('pattern_type', 'imbalance')
    rr_target = data.get('rr_target', 2.0)
    sl_buffer_pct = data.get('sl_buffer_pct', 10.0)
    slippage_pct = data.get('slippage_pct', 0.0)

    # Validate required fields
    if not all([symbol, timeframe, start_date, end_date]):
        return jsonify({
            'success': False,
            'error': 'Missing required fields: symbol, timeframe, start_date, end_date'
        }), 400

    # Validate date format
    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Invalid date format. Use YYYY-MM-DD'
        }), 400

    if end_dt <= start_dt:
        return jsonify({
            'success': False,
            'error': 'end_date must be after start_date'
        }), 400

    # Validate timeframe
    if timeframe not in Config.TIMEFRAMES:
        return jsonify({
            'success': False,
            'error': f'Invalid timeframe. Must be one of: {Config.TIMEFRAMES}'
        }), 400

    # Validate pattern type
    if pattern_type not in PATTERN_TYPES:
        return jsonify({
            'success': False,
            'error': f'Invalid pattern type. Must be one of: {PATTERN_TYPES}'
        }), 400

    # Validate numeric parameters
    try:
        rr_target = float(rr_target)
        sl_buffer_pct = float(sl_buffer_pct)
        slippage_pct = float(slippage_pct)
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'error': 'rr_target, sl_buffer_pct, and slippage_pct must be numbers'
        }), 400

    if rr_target <= 0:
        return jsonify({
            'success': False,
            'error': 'rr_target must be positive'
        }), 400

    if sl_buffer_pct < 0:
        return jsonify({
            'success': False,
            'error': 'sl_buffer_pct cannot be negative'
        }), 400

    if slippage_pct < 0:
        return jsonify({
            'success': False,
            'error': 'slippage_pct cannot be negative'
        }), 400

    # Import backtester service
    from app.services.backtester import run_backtest

    result = run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        pattern_type=pattern_type,
        rr_target=rr_target,
        sl_buffer_pct=sl_buffer_pct,
        slippage_pct=slippage_pct
    )

    return jsonify(result)


@backtest_bp.route('/<int:backtest_id>')
@login_required
@feature_required('backtest')
def detail(backtest_id):
    """Backtest detail view (Premium only)"""
    backtest = db.session.get(Backtest, backtest_id)
    if backtest is None:
        abort(404)
    return render_template('backtest_detail.html', backtest=backtest)
