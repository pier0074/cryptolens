from flask import Blueprint, request, jsonify
from app.models import Symbol, Candle, Pattern, Signal
from app.config import Config
from app import db

api_bp = Blueprint('api', __name__)


@api_bp.route('/symbols')
def get_symbols():
    """Get all symbols"""
    active_only = request.args.get('active', 'true') == 'true'
    query = Symbol.query
    if active_only:
        query = query.filter_by(is_active=True)
    symbols = query.all()
    return jsonify([s.to_dict() for s in symbols])


@api_bp.route('/candles/<symbol>/<timeframe>')
def get_candles(symbol, timeframe):
    """Get candles for a symbol/timeframe"""
    sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
    if not sym:
        return jsonify({'error': 'Symbol not found'}), 404

    limit = request.args.get('limit', 200, type=int)

    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    return jsonify([c.to_dict() for c in reversed(candles)])


@api_bp.route('/patterns')
def get_patterns():
    """Get patterns with optional filters"""
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe')
    status = request.args.get('status', 'active')
    limit = request.args.get('limit', 100, type=int)

    query = Pattern.query

    if symbol:
        sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
        if sym:
            query = query.filter_by(symbol_id=sym.id)

    if timeframe:
        query = query.filter_by(timeframe=timeframe)

    if status:
        query = query.filter_by(status=status)

    patterns = query.order_by(Pattern.detected_at.desc()).limit(limit).all()
    return jsonify([p.to_dict() for p in patterns])


@api_bp.route('/signals')
def get_signals():
    """Get signals with optional filters"""
    status = request.args.get('status')
    direction = request.args.get('direction')
    limit = request.args.get('limit', 50, type=int)

    query = Signal.query

    if status:
        query = query.filter_by(status=status)

    if direction:
        query = query.filter_by(direction=direction)

    signals = query.order_by(Signal.created_at.desc()).limit(limit).all()

    result = []
    for signal in signals:
        data = signal.to_dict()
        symbol = Symbol.query.get(signal.symbol_id)
        data['symbol'] = symbol.symbol if symbol else None
        result.append(data)

    return jsonify(result)


@api_bp.route('/matrix')
def get_matrix():
    """Get the symbol/timeframe pattern matrix"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    timeframes = Config.TIMEFRAMES

    matrix = {}
    for symbol in symbols:
        matrix[symbol.symbol] = {}
        for tf in timeframes:
            pattern = Pattern.query.filter_by(
                symbol_id=symbol.id,
                timeframe=tf,
                status='active'
            ).order_by(Pattern.detected_at.desc()).first()

            if pattern:
                matrix[symbol.symbol][tf] = pattern.direction
            else:
                matrix[symbol.symbol][tf] = 'neutral'

    return jsonify(matrix)


@api_bp.route('/scan', methods=['POST'])
def trigger_scan():
    """Manually trigger a pattern scan"""
    from app.services.patterns import scan_all_patterns

    result = scan_all_patterns()
    return jsonify(result)


@api_bp.route('/fetch', methods=['POST'])
def trigger_fetch():
    """Manually trigger data fetch"""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    timeframe = data.get('timeframe')

    from app.services.data_fetcher import fetch_candles

    if symbol and timeframe:
        new_count, _ = fetch_candles(symbol, timeframe)
        return jsonify({'success': True, 'candles_fetched': new_count})

    return jsonify({'error': 'Symbol and timeframe required'}), 400


@api_bp.route('/scheduler/status')
def scheduler_status():
    """Get current scheduler status"""
    from app.services.scheduler import get_scheduler_status
    return jsonify(get_scheduler_status())


@api_bp.route('/scheduler/start', methods=['POST'])
def scheduler_start():
    """Start the background scheduler"""
    from app.services.scheduler import start_scheduler, get_scheduler_status
    from flask import current_app

    start_scheduler(current_app)
    return jsonify(get_scheduler_status())


@api_bp.route('/scheduler/stop', methods=['POST'])
def scheduler_stop():
    """Stop the background scheduler"""
    from app.services.scheduler import stop_scheduler, get_scheduler_status

    stop_scheduler()
    return jsonify(get_scheduler_status())


@api_bp.route('/scheduler/toggle', methods=['POST'])
def scheduler_toggle():
    """Toggle the scheduler on/off"""
    from app.services.scheduler import start_scheduler, stop_scheduler, get_scheduler_status
    from flask import current_app

    status = get_scheduler_status()
    if status['running']:
        stop_scheduler()
    else:
        start_scheduler(current_app)

    return jsonify(get_scheduler_status())
