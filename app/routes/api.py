"""
API Routes with standardized responses and proper API key authentication.

All endpoints return responses in the format:
{
    "success": true/false,
    "data": <payload>,
    "error": null or {"code": "...", "message": "..."},
    "meta": {"timestamp": "...", "request_id": "...", ...}
}
"""
import os
from functools import wraps
from typing import Callable, Any
from flask import Blueprint, request, session, g
from sqlalchemy.orm import joinedload
from app.models import (
    Symbol, Candle, Pattern, Signal, Setting, User,
    ApiKey, ApiResponse
)
from app.config import Config
from app import db, csrf, limiter, cache

api_bp = Blueprint('api', __name__)

# Exempt API from CSRF (uses API key authentication instead)
csrf.exempt(api_bp)

# Scope mappings for endpoints
ENDPOINT_SCOPES = {
    'get_symbols': 'read:symbols',
    'get_candles': 'read:candles',
    'get_patterns': 'read:patterns',
    'get_signals': 'read:signals',
    'get_matrix': 'read:matrix',
    'trigger_scan': 'write:scan',
    'trigger_fetch': 'write:fetch',
    'scheduler_status': 'admin:scheduler',
    'scheduler_start': 'admin:scheduler',
    'scheduler_stop': 'admin:scheduler',
    'scheduler_toggle': 'admin:scheduler',
    'run_scan_now': 'write:scan',
}


def require_api_key(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to require API key OR Premium user session for API endpoints.

    Features:
    - API key authentication with new ApiKey model
    - User session fallback (admin/premium users)
    - Per-key rate limiting
    - IP whitelist/blacklist
    - Scope-based permissions
    - Usage tracking

    Security: DENY by default. To allow unauthenticated access (dev only),
    set environment variable: ALLOW_UNAUTHENTICATED_API=true
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any):
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

        # Check for user session first
        user_id = session.get('user_id')
        if user_id:
            user = db.session.get(User, user_id)
            if user:
                # Admins always have full API access
                if user.is_admin:
                    g.api_user = user
                    g.api_key = None
                    return f(*args, **kwargs)

                # Check if user's tier has API access (Premium only)
                if user.can_access_feature('api_access'):
                    g.api_user = user
                    g.api_key = None
                    return f(*args, **kwargs)

                # User exists but doesn't have API access
                return ApiResponse.forbidden('API access requires Premium subscription')

        # Get API key from header or query param
        provided_key = request.headers.get('X-API-Key')
        if not provided_key:
            provided_key = request.args.get('api_key')

        if not provided_key:
            # Check if any API keys exist (new system or legacy)
            legacy_hash = Setting.get('api_key_hash')
            has_new_keys = ApiKey.query.filter_by(status='active').first() is not None

            if legacy_hash or has_new_keys:
                return ApiResponse.unauthorized(
                    'API key required. Provide via X-API-Key header or api_key query param'
                )
            # No API keys configured at all
            return ApiResponse.service_unavailable(
                'API not configured. Create an API key in admin settings.'
            )

        # Look up API key in new table
        api_key = ApiKey.find_by_key(provided_key)

        # Fallback: check legacy setting-based key
        if not api_key:
            from app.services.auth import verify_api_key as legacy_verify
            legacy_hash = Setting.get('api_key_hash')
            if legacy_hash and legacy_verify(provided_key, legacy_hash):
                # Legacy key valid - allow but don't track
                g.api_user = None
                g.api_key = None
                return f(*args, **kwargs)

            return ApiResponse.unauthorized('Invalid API key')

        # Check if key is valid (status and expiry)
        if not api_key.is_valid:
            if api_key.status == 'revoked':
                return ApiResponse.unauthorized('API key has been revoked')
            if api_key.is_expired:
                return ApiResponse.unauthorized('API key has expired')
            return ApiResponse.unauthorized('API key is inactive')

        # Check IP restrictions
        client_ip = request.remote_addr or '0.0.0.0'
        ip_allowed, ip_reason = api_key.check_ip_allowed(client_ip)
        if not ip_allowed:
            return ApiResponse.forbidden(ip_reason)

        # Check rate limits
        is_limited, limit_reason = api_key.is_rate_limited()
        if is_limited:
            return ApiResponse.rate_limited(limit_reason)

        # Check scope for this endpoint
        endpoint_name = f.__name__
        required_scope = ENDPOINT_SCOPES.get(endpoint_name)
        if required_scope and not api_key.has_scope(required_scope):
            return ApiResponse.forbidden(
                f'API key lacks required scope: {required_scope}'
            )

        # Store in g for access in endpoint
        g.api_user = api_key.user
        g.api_key = api_key

        # Execute the endpoint
        result = f(*args, **kwargs)

        # Record usage (after successful execution)
        try:
            response_code = result[1] if isinstance(result, tuple) else 200
            api_key.record_usage(
                ip_address=client_ip,
                endpoint=request.path,
                method=request.method,
                response_code=response_code
            )
        except Exception as e:
            import logging
            logging.getLogger('cryptolens').warning(f"Failed to record API usage: {e}")

        return result

    return decorated


# =============================================================================
# HEALTH CHECK ENDPOINTS (No auth required)
# =============================================================================

@api_bp.route('/health')
def health_check():
    """
    Health check endpoint for monitoring and load balancers.

    Returns JSON with:
    - status: 'healthy', 'degraded', or 'unhealthy'
    - timestamp: current UTC timestamp
    - version: application version
    - dependencies: status of all external dependencies
    """
    from app.services.health import get_liveness_status, get_readiness_status

    quick_mode = request.args.get('quick', 'false').lower() == 'true'

    if quick_mode:
        health = get_liveness_status()
    else:
        health = get_readiness_status()

    status_code = 503 if health['status'] == 'unhealthy' else 200
    return ApiResponse.success(health, status_code=status_code)


@api_bp.route('/health/live')
def liveness_check():
    """Kubernetes liveness probe - quick check if app is running."""
    from app.services.health import get_liveness_status

    health = get_liveness_status()
    status_code = 503 if health['status'] == 'unhealthy' else 200
    return ApiResponse.success(health, status_code=status_code)


@api_bp.route('/health/ready')
def readiness_check():
    """Kubernetes readiness probe - full check if app is ready for traffic."""
    from app.services.health import get_readiness_status

    health = get_readiness_status()
    status_code = 503 if health['status'] == 'unhealthy' else 200
    return ApiResponse.success(health, status_code=status_code)


# =============================================================================
# DATA ENDPOINTS (Read operations)
# =============================================================================

@api_bp.route('/symbols')
@require_api_key
def get_symbols():
    """
    Get all trading symbols.

    Returns a list of all configured trading pairs with their settings.
    Requires scope: read:symbols

    Query Parameters:
        active (bool): If true (default), return only active symbols.
                       If false, return all symbols including inactive.

    Returns:
        List of symbol objects with id, symbol, exchange, is_active, notify_enabled.
    """
    active_only = request.args.get('active', 'true').lower() == 'true'

    query = Symbol.query
    if active_only:
        query = query.filter_by(is_active=True)

    symbols = query.all()

    return ApiResponse.success(
        [s.to_dict() for s in symbols],
        meta={'count': len(symbols), 'active_only': active_only}
    )


@api_bp.route('/candles/<symbol>/<timeframe>')
@require_api_key
def get_candles(symbol: str, timeframe: str):
    """
    Get OHLCV candle data for a symbol/timeframe.

    Returns historical price data in chronological order (oldest first).
    Requires scope: read:candles

    Args:
        symbol: Trading pair (e.g., 'BTC-USDT' or 'BTC/USDT')
        timeframe: Candle timeframe (5m, 15m, 30m, 1h, 2h, 4h, 1d)

    Query Parameters:
        limit (int): Number of candles to return (default: 200, max: 2000)

    Returns:
        List of candle objects with timestamp, open, high, low, close, volume.
    """
    # Normalize symbol format
    symbol_normalized = symbol.replace('-', '/')

    sym = Symbol.query.filter_by(symbol=symbol_normalized).first()
    if not sym:
        return ApiResponse.not_found(f'Symbol {symbol} not found')

    # Validate timeframe
    if timeframe not in Config.TIMEFRAMES:
        return ApiResponse.bad_request(
            f'Invalid timeframe. Valid options: {", ".join(Config.TIMEFRAMES)}'
        )

    # Parse limit with bounds
    limit = request.args.get('limit', 200, type=int)
    limit = min(max(limit, 1), 2000)

    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    return ApiResponse.success(
        [c.to_dict() for c in reversed(candles)],
        meta={
            'symbol': symbol_normalized,
            'timeframe': timeframe,
            'count': len(candles),
            'limit': limit
        }
    )


@api_bp.route('/patterns')
@require_api_key
def get_patterns():
    """
    Get detected patterns with optional filters.

    Returns Fair Value Gaps (FVG), Order Blocks, and other pattern types.
    Requires scope: read:patterns

    Query Parameters:
        symbol (str): Filter by trading pair (e.g., 'BTC/USDT')
        timeframe (str): Filter by timeframe (e.g., '1h', '4h')
        status (str): Filter by status - 'active' (default), 'filled', 'expired'
        limit (int): Number of patterns to return (default: 100, max: 1000)

    Returns:
        List of pattern objects with zone_high, zone_low, direction, etc.
    """
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
        if timeframe not in Config.TIMEFRAMES:
            return ApiResponse.bad_request(
                f'Invalid timeframe. Valid options: {", ".join(Config.TIMEFRAMES)}'
            )
        query = query.filter_by(timeframe=timeframe)

    if status:
        query = query.filter_by(status=status)

    patterns = query.order_by(Pattern.detected_at.desc()).limit(limit).all()

    return ApiResponse.success(
        [p.to_dict() for p in patterns],
        meta={
            'count': len(patterns),
            'limit': limit,
            'filters': {
                'symbol': symbol,
                'timeframe': timeframe,
                'status': status
            }
        }
    )


@api_bp.route('/signals')
@require_api_key
def get_signals():
    """
    Get trade signals with optional filters.

    Returns generated trade signals with entry, stop loss, and take profit levels.
    Requires scope: read:signals

    Query Parameters:
        status (str): Filter by status - 'pending', 'notified', 'filled', 'stopped', 'tp_hit'
        direction (str): Filter by direction - 'long' or 'short'
        limit (int): Number of signals to return (default: 50, max: 500)

    Returns:
        List of signal objects with entry_price, stop_loss, take_profit levels, etc.
    """
    status = request.args.get('status')
    direction = request.args.get('direction')
    limit = min(max(request.args.get('limit', 50, type=int), 1), 500)

    query = Signal.query.options(joinedload(Signal.symbol))

    if status:
        query = query.filter_by(status=status)

    if direction:
        if direction not in ['long', 'short']:
            return ApiResponse.bad_request('Invalid direction. Use "long" or "short"')
        query = query.filter_by(direction=direction)

    signals = query.order_by(Signal.created_at.desc()).limit(limit).all()

    result = []
    for signal in signals:
        data = signal.to_dict()
        data['symbol'] = signal.symbol.symbol if signal.symbol else None
        result.append(data)

    return ApiResponse.success(
        result,
        meta={
            'count': len(result),
            'limit': limit,
            'filters': {
                'status': status,
                'direction': direction
            }
        }
    )


@api_bp.route('/matrix')
@require_api_key
@cache.cached(timeout=Config.CACHE_TTL_PATTERN_MATRIX, key_prefix='pattern_matrix')
def get_matrix():
    """
    Get the symbol/timeframe pattern direction matrix.

    Returns a grid showing the most recent pattern direction for each
    symbol/timeframe combination. Used for the dashboard heatmap.
    Requires scope: read:matrix

    Returns:
        Dict mapping symbol -> timeframe -> direction ('bullish', 'bearish', 'neutral')
        Meta includes symbol count and available timeframes.

    Note:
        Results are cached for performance. Cache TTL configured in Config.
    """
    from sqlalchemy import func

    symbols = Symbol.query.filter_by(is_active=True).all()
    timeframes = Config.TIMEFRAMES

    # Initialize matrix with neutral values
    matrix = {s.symbol: {tf: 'neutral' for tf in timeframes} for s in symbols}

    # Get all active patterns with their symbol in a single query
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

    return ApiResponse.success(
        matrix,
        meta={
            'symbols': len(symbols),
            'timeframes': timeframes
        }
    )


# =============================================================================
# ACTION ENDPOINTS (Write operations)
# =============================================================================

@api_bp.route('/scan', methods=['POST'])
@limiter.limit("1 per minute")
@require_api_key
def trigger_scan():
    """
    Manually trigger a pattern scan across all symbols.

    Scans all active symbols and timeframes for new patterns.
    Requires scope: write:scan
    Rate limited: 1 request per minute.

    Returns:
        Scan results with counts of patterns found/updated.
    """
    from app.services.patterns import scan_all_patterns

    result = scan_all_patterns()

    return ApiResponse.success(
        result,
        meta={'action': 'scan_triggered'}
    )


@api_bp.route('/fetch', methods=['POST'])
@limiter.limit("5 per minute")
@require_api_key
def trigger_fetch():
    """
    Manually trigger candle data fetch for a specific symbol/timeframe.

    Fetches the latest candle data from the exchange API.
    Requires scope: write:fetch
    Rate limited: 5 requests per minute.

    Request Body (JSON):
        symbol (str): Trading pair (e.g., 'BTC/USDT') - required
        timeframe (str): Candle timeframe (e.g., '1h') - required

    Returns:
        Object with 'candles_fetched' count.
    """
    data = request.get_json() or {}
    symbol = data.get('symbol')
    timeframe = data.get('timeframe')

    if not symbol or not timeframe:
        return ApiResponse.bad_request('Symbol and timeframe are required')

    # Validate symbol exists
    sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
    if not sym:
        return ApiResponse.not_found(f'Symbol {symbol} not found')

    # Validate timeframe
    if timeframe not in Config.TIMEFRAMES:
        return ApiResponse.bad_request(
            f'Invalid timeframe. Valid options: {", ".join(Config.TIMEFRAMES)}'
        )

    from app.services.data_fetcher import fetch_candles

    new_count, _ = fetch_candles(symbol.replace('-', '/'), timeframe)

    return ApiResponse.success(
        {'candles_fetched': new_count},
        meta={
            'action': 'fetch_triggered',
            'symbol': symbol,
            'timeframe': timeframe
        }
    )


# =============================================================================
# SCHEDULER ENDPOINTS (Admin operations)
# =============================================================================

@api_bp.route('/scheduler/status')
@require_api_key
def scheduler_status():
    """
    Get current scheduler/cron status.

    Returns information about the background job scheduler configuration.
    Requires scope: admin:scheduler

    Returns:
        Object with scheduler mode, status, and cron configuration details.
    """
    from app.services.scheduler import get_scheduler_status

    return ApiResponse.success(get_scheduler_status())


@api_bp.route('/scheduler/start', methods=['POST'])
@limiter.limit("2 per minute")
@require_api_key
def scheduler_start():
    """
    Start the background scheduler.

    Starts the APScheduler-based background job scheduler.
    Requires scope: admin:scheduler
    Rate limited: 2 requests per minute.

    Returns:
        Updated scheduler status after starting.
    """
    from app.services.scheduler import start_scheduler, get_scheduler_status
    from flask import current_app

    start_scheduler(current_app)

    return ApiResponse.success(
        get_scheduler_status(),
        meta={'action': 'scheduler_started'}
    )


@api_bp.route('/scheduler/stop', methods=['POST'])
@limiter.limit("2 per minute")
@require_api_key
def scheduler_stop():
    """
    Stop the background scheduler.

    Stops the APScheduler-based background job scheduler.
    Requires scope: admin:scheduler
    Rate limited: 2 requests per minute.

    Returns:
        Updated scheduler status after stopping.
    """
    from app.services.scheduler import stop_scheduler, get_scheduler_status

    stop_scheduler()

    return ApiResponse.success(
        get_scheduler_status(),
        meta={'action': 'scheduler_stopped'}
    )


@api_bp.route('/scheduler/toggle', methods=['POST'])
@limiter.limit("2 per minute")
@require_api_key
def scheduler_toggle():
    """
    Legacy endpoint - scheduler is now cron-based.

    This endpoint is deprecated. The scheduler is now managed via system cron.
    Use POST /api/scan/run to trigger a manual scan instead.
    Requires scope: admin:scheduler

    Returns:
        Current scheduler status with deprecation notice.
    """
    from app.services.scheduler import get_scheduler_status

    status = get_scheduler_status()
    status['note'] = 'Scheduler is now managed via cron. Use /api/scan/run to trigger a manual scan.'

    return ApiResponse.success(status)


@api_bp.route('/scan/run', methods=['POST'])
@limiter.limit("1 per minute")
@require_api_key
def run_scan_now():
    """
    Trigger a manual full scan immediately.

    Executes a complete data fetch and pattern scan cycle.
    Requires scope: write:scan
    Rate limited: 1 request per minute.

    Returns:
        Scan execution results with timing and pattern counts.
    """
    from app.services.scheduler import run_once

    result = run_once()

    return ApiResponse.success(
        result,
        meta={'action': 'manual_scan_executed'}
    )
