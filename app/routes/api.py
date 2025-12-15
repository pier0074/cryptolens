import os
from functools import wraps
from typing import Callable, Tuple, Any
from flask import Blueprint, request, jsonify, Response, session
from sqlalchemy.orm import joinedload
from app.models import Symbol, Candle, Pattern, Signal, Setting, User
from app.config import Config
from app import db, csrf, limiter, cache
from app.services.auth import verify_api_key

api_bp = Blueprint('api', __name__)

# Type alias for Flask route responses
JsonResponse = Tuple[Response, int] | Response

# Exempt API from CSRF (uses API key authentication instead)
csrf.exempt(api_bp)


def require_api_key(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to require API key OR Premium user session for API endpoints.

    Security: DENY by default. To allow unauthenticated access (dev only),
    set environment variable: ALLOW_UNAUTHENTICATED_API=true

    Accepts:
    - API key via X-API-Key header or api_key query param
    - Admin user session (full access)
    - Premium user session (API access enabled in tier)
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> JsonResponse:
        # Check if auth is explicitly disabled (development only)
        allow_unauth = os.getenv('ALLOW_UNAUTHENTICATED_API', 'false').lower() == 'true'
        flask_env = os.getenv('FLASK_ENV', 'development')

        if allow_unauth:
            # CRITICAL: Refuse in production even if flag is set
            if flask_env == 'production':
                from app.services.logger import log_system
                log_system(
                    "SECURITY ALERT: ALLOW_UNAUTHENTICATED_API is set in production - IGNORING",
                    level='ERROR'
                )
                # Fall through to normal auth flow
            else:
                # Development only - warn and allow
                import warnings
                warnings.warn(
                    "ALLOW_UNAUTHENTICATED_API is enabled - API endpoints are unauthenticated!",
                    UserWarning
                )
                return f(*args, **kwargs)

        # Check for user session
        user_id = session.get('user_id')
        if user_id:
            user = db.session.get(User, user_id)
            if user:
                # Admins always have full API access
                if user.is_admin:
                    return f(*args, **kwargs)

                # Check if user's tier has API access (Premium only)
                if user.can_access_feature('api_access'):
                    return f(*args, **kwargs)

                # User exists but doesn't have API access
                return jsonify({
                    'error': 'Forbidden',
                    'message': 'API access requires Premium subscription'
                }), 403

        # Get API key hash from settings
        api_key_hash = Setting.get('api_key_hash')
        if not api_key_hash:
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
            return jsonify({
                'error': 'Unauthorized',
                'message': 'API key required. Provide via X-API-Key header or api_key query param'
            }), 401

        # Verify API key against stored hash
        if not verify_api_key(provided_key, api_key_hash):
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Invalid API key'
            }), 401

        return f(*args, **kwargs)
    return decorated


@api_bp.route('/health')
def health_check() -> JsonResponse:
    """
    Health check endpoint for monitoring and load balancers.

    Returns JSON with:
    - status: 'healthy', 'degraded', or 'unhealthy'
    - timestamp: current UTC timestamp
    - version: application version
    - dependencies: status of all external dependencies

    Query params:
    - full=true: Include slow checks (exchange API, NTFY) - default for /health
    - quick=true: Only check database (for liveness probes)
    """
    from flask import request as flask_request
    from app.services.health import get_liveness_status, get_readiness_status

    # Quick liveness check or full readiness check
    quick_mode = flask_request.args.get('quick', 'false').lower() == 'true'

    if quick_mode:
        health = get_liveness_status()
    else:
        health = get_readiness_status()

    # Return appropriate status code
    if health['status'] == 'unhealthy':
        return jsonify(health), 503
    return jsonify(health), 200


@api_bp.route('/health/live')
def liveness_check() -> JsonResponse:
    """
    Kubernetes liveness probe - quick check if app is running.
    Only checks database connectivity.
    """
    from app.services.health import get_liveness_status

    health = get_liveness_status()
    if health['status'] == 'unhealthy':
        return jsonify(health), 503
    return jsonify(health), 200


@api_bp.route('/health/ready')
def readiness_check() -> JsonResponse:
    """
    Kubernetes readiness probe - full check if app is ready for traffic.
    Includes all dependency checks (database, cache, exchange, NTFY).
    """
    from app.services.health import get_readiness_status

    health = get_readiness_status()
    if health['status'] == 'unhealthy':
        return jsonify(health), 503
    return jsonify(health), 200


@api_bp.route('/symbols')
@require_api_key
def get_symbols() -> Response:
    """Get all symbols"""
    active_only = request.args.get('active', 'true') == 'true'
    query = Symbol.query
    if active_only:
        query = query.filter_by(is_active=True)
    symbols = query.all()
    return jsonify([s.to_dict() for s in symbols])


@api_bp.route('/candles/<symbol>/<timeframe>')
@require_api_key
def get_candles(symbol: str, timeframe: str) -> JsonResponse:
    """Get candles for a symbol/timeframe"""
    sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
    if not sym:
        return jsonify({
            'error': 'Not found',
            'message': f'Symbol {symbol} not found'
        }), 404

    limit = min(max(request.args.get('limit', 200, type=int), 1), 2000)

    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    return jsonify([c.to_dict() for c in reversed(candles)])


@api_bp.route('/patterns')
@require_api_key
def get_patterns() -> Response:
    """Get patterns with optional filters"""
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe')
    status = request.args.get('status', 'active')
    limit = min(max(request.args.get('limit', 100, type=int), 1), 1000)

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
@require_api_key
def get_signals() -> Response:
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
@require_api_key
@cache.cached(timeout=Config.CACHE_TTL_PATTERN_MATRIX, key_prefix='pattern_matrix')
def get_matrix() -> Response:
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

    return jsonify({
        'error': 'Bad request',
        'message': 'Symbol and timeframe are required'
    }), 400


@api_bp.route('/scheduler/status')
@require_api_key
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
