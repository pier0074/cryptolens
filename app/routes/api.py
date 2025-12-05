import hmac
import os
from functools import wraps
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import joinedload
from app.models import Symbol, Candle, Pattern, Signal, Setting
from app.config import Config
from app import db, csrf, limiter

api_bp = Blueprint('api', __name__)

# Exempt API from CSRF (uses API key authentication instead)
csrf.exempt(api_bp)


def require_api_key(f):
    """
    Decorator to require API key for sensitive endpoints.

    Security: DENY by default. To allow unauthenticated access (dev only),
    set environment variable: ALLOW_UNAUTHENTICATED_API=true
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if auth is explicitly disabled (development only)
        if os.getenv('ALLOW_UNAUTHENTICATED_API', 'false').lower() == 'true':
            return f(*args, **kwargs)

        # Get API key from settings
        api_key = Setting.get('api_key')
        if not api_key:
            # No API key configured - DENY access (secure default)
            return jsonify({
                'error': 'API not configured',
                'message': 'Set an API key in Settings, or set ALLOW_UNAUTHENTICATED_API=true for development'
            }), 503

        # Check header first, then query param
        provided_key = request.headers.get('X-API-Key')
        if not provided_key:
            provided_key = request.args.get('api_key')

        if not provided_key:
            return jsonify({'error': 'Unauthorized - API key required'}), 401

        # Use timing-safe comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key, api_key):
            return jsonify({'error': 'Unauthorized - Invalid API key'}), 401

        return f(*args, **kwargs)
    return decorated


@api_bp.route('/health')
def health_check():
    """
    Health check endpoint for monitoring and load balancers.

    Returns JSON with:
    - status: 'healthy' or 'unhealthy'
    - database: 'connected' or 'error'
    - timestamp: current UTC timestamp
    """
    import time
    from datetime import datetime, timezone

    health = {
        'status': 'healthy',
        'database': 'connected',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version': '2.0.0'
    }

    # Check database connectivity
    try:
        db.session.execute(db.text('SELECT 1'))
        health['database'] = 'connected'
    except Exception as e:
        health['status'] = 'unhealthy'
        health['database'] = 'error'
        health['database_error'] = str(e)
        return jsonify(health), 503

    return jsonify(health), 200


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

    query = Signal.query.options(joinedload(Signal.symbol))

    if status:
        query = query.filter_by(status=status)

    if direction:
        query = query.filter_by(direction=direction)

    signals = query.order_by(Signal.created_at.desc()).limit(limit).all()

    result = []
    for signal in signals:
        data = signal.to_dict()
        data['symbol'] = signal.symbol.symbol if signal.symbol else None
        result.append(data)

    return jsonify(result)


@api_bp.route('/matrix')
def get_matrix():
    """Get the symbol/timeframe pattern matrix (optimized: 1 query instead of 180)"""
    from sqlalchemy import func

    symbols = Symbol.query.filter_by(is_active=True).all()
    timeframes = Config.TIMEFRAMES

    # Initialize matrix with neutral values
    matrix = {s.symbol: {tf: 'neutral' for tf in timeframes} for s in symbols}

    # Get all active patterns with their symbol in a single query
    # Subquery to get max detected_at per symbol/timeframe
    subq = db.session.query(
        Pattern.symbol_id,
        Pattern.timeframe,
        func.max(Pattern.detected_at).label('max_detected')
    ).filter(
        Pattern.status == 'active'
    ).group_by(
        Pattern.symbol_id,
        Pattern.timeframe
    ).subquery()

    # Join to get the actual pattern data
    patterns = db.session.query(Pattern).join(
        subq,
        db.and_(
            Pattern.symbol_id == subq.c.symbol_id,
            Pattern.timeframe == subq.c.timeframe,
            Pattern.detected_at == subq.c.max_detected,
            Pattern.status == 'active'
        )
    ).options(joinedload(Pattern.symbol)).all()

    # Build matrix from results
    for pattern in patterns:
        if pattern.symbol and pattern.symbol.symbol in matrix:
            matrix[pattern.symbol.symbol][pattern.timeframe] = pattern.direction

    return jsonify(matrix)


@api_bp.route('/scan', methods=['POST'])
@limiter.limit("1 per minute")
@require_api_key
def trigger_scan():
    """Manually trigger a pattern scan"""
    from app.services.patterns import scan_all_patterns

    result = scan_all_patterns()
    return jsonify(result)


@api_bp.route('/fetch', methods=['POST'])
@limiter.limit("5 per minute")
@require_api_key
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
@limiter.limit("2 per minute")
@require_api_key
def scheduler_start():
    """Start the background scheduler"""
    from app.services.scheduler import start_scheduler, get_scheduler_status
    from flask import current_app

    start_scheduler(current_app)
    return jsonify(get_scheduler_status())


@api_bp.route('/scheduler/stop', methods=['POST'])
@limiter.limit("2 per minute")
@require_api_key
def scheduler_stop():
    """Stop the background scheduler"""
    from app.services.scheduler import stop_scheduler, get_scheduler_status

    stop_scheduler()
    return jsonify(get_scheduler_status())


@api_bp.route('/scheduler/toggle', methods=['POST'])
@limiter.limit("2 per minute")
@require_api_key
def scheduler_toggle():
    """Legacy endpoint - scheduler is now cron-based"""
    from app.services.scheduler import get_scheduler_status
    return jsonify({
        **get_scheduler_status(),
        'note': 'Scheduler is now managed via cron. Use /api/scan/run to trigger a manual scan.'
    })


@api_bp.route('/scan/run', methods=['POST'])
@limiter.limit("1 per minute")
@require_api_key
def run_scan_now():
    """Trigger a manual scan"""
    from app.services.scheduler import run_once
    result = run_once()
    return jsonify(result)
