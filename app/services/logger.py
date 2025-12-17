"""
Logging Service
Centralized logging to database and console
"""
import sys
import json
import logging
from datetime import datetime, timezone

# Console logger
console_logger = logging.getLogger('cryptolens')
console_logger.setLevel(logging.INFO)
if not console_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))
    console_logger.addHandler(handler)

# Track database logging failures to avoid spamming
_db_log_failures = 0
_MAX_DB_FAILURES_LOGGED = 3


def get_request_id() -> str:
    """Get the current request ID if in request context."""
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, 'request_id'):
            return g.request_id
    except Exception:
        # Expected in non-request contexts (CLI scripts, background jobs)
        pass
    return None


def log(category: str, message: str, level: str = 'INFO',
        symbol: str = None, timeframe: str = None, details: dict = None):
    """
    Log a message to both console and database

    Args:
        category: fetch, aggregate, scan, signal, notify, system, error
        message: Log message
        level: DEBUG, INFO, WARNING, ERROR
        symbol: Optional related symbol
        timeframe: Optional related timeframe
        details: Optional dict with extra details
    """
    # Get request ID for tracing
    request_id = get_request_id()

    # Console log with request ID if available
    log_func = getattr(console_logger, level.lower(), console_logger.info)
    req_prefix = f"[{request_id}] " if request_id else ""
    prefix = f"{req_prefix}[{category.upper()}]"
    if symbol:
        prefix += f" {symbol}"
    if timeframe:
        prefix += f" ({timeframe})"
    log_func(f"{prefix} {message}")

    # Database log (in try/except to not break if DB unavailable)
    try:
        from flask import has_app_context
        from app import db, create_app
        from app.models import Log

        # Create app context if needed
        if has_app_context():
            log_entry = Log(
                timestamp=datetime.now(timezone.utc),
                category=category,
                level=level,
                message=message,
                symbol=symbol,
                timeframe=timeframe,
                details=json.dumps(details) if details else None
            )
            db.session.add(log_entry)
            db.session.commit()
        else:
            # Background task - create own context
            app = create_app()
            with app.app_context():
                log_entry = Log(
                    timestamp=datetime.now(timezone.utc),
                    category=category,
                    level=level,
                    message=message,
                    symbol=symbol,
                    timeframe=timeframe,
                    details=json.dumps(details) if details else None
                )
                db.session.add(log_entry)
                db.session.commit()
    except Exception as e:
        # Log to stderr but limit spam
        global _db_log_failures
        _db_log_failures += 1
        if _db_log_failures <= _MAX_DB_FAILURES_LOGGED:
            print(f"[DB LOG ERROR] Failed to write log to database: {e}", file=sys.stderr)
            if _db_log_failures == _MAX_DB_FAILURES_LOGGED:
                print("[DB LOG ERROR] Suppressing further database logging errors", file=sys.stderr)


def log_fetch(message: str, symbol: str = None, timeframe: str = None, **kwargs):
    """Log data fetching events"""
    log('fetch', message, symbol=symbol, timeframe=timeframe, **kwargs)


def log_aggregate(message: str, symbol: str = None, timeframe: str = None, **kwargs):
    """Log aggregation events"""
    log('aggregate', message, symbol=symbol, timeframe=timeframe, **kwargs)


def log_scan(message: str, symbol: str = None, timeframe: str = None, **kwargs):
    """Log pattern scanning events"""
    log('scan', message, symbol=symbol, timeframe=timeframe, **kwargs)


def log_signal(message: str, symbol: str = None, **kwargs):
    """Log signal generation events"""
    log('signal', message, symbol=symbol, **kwargs)


def log_notify(message: str, symbol: str = None, level: str = 'INFO', **kwargs):
    """Log notification events"""
    log('notify', message, symbol=symbol, level=level, **kwargs)


def log_system(message: str, level: str = 'INFO', **kwargs):
    """Log system events"""
    log('system', message, level=level, **kwargs)


def log_error(message: str, symbol: str = None, timeframe: str = None, details: dict = None):
    """Log error events"""
    log('error', message, level='ERROR', symbol=symbol, timeframe=timeframe, details=details)


def log_auth(message: str, level: str = 'INFO', details: dict = None):
    """Log authentication events (login, logout, register, password changes)"""
    log('auth', message, level=level, details=details)


def log_user(message: str, level: str = 'INFO', details: dict = None):
    """Log user action events (profile updates, settings changes, preferences)"""
    log('user', message, level=level, details=details)


def log_trade(message: str, symbol: str = None, level: str = 'INFO', details: dict = None):
    """Log trading events (portfolio, trades, positions)"""
    log('trade', message, symbol=symbol, level=level, details=details)


def log_payment(message: str, level: str = 'INFO', details: dict = None):
    """Log payment and subscription events"""
    log('payment', message, level=level, details=details)


def log_backtest(message: str, symbol: str = None, timeframe: str = None, level: str = 'INFO', details: dict = None):
    """Log backtesting events"""
    log('backtest', message, symbol=symbol, timeframe=timeframe, level=level, details=details)


def log_api(message: str, level: str = 'INFO', details: dict = None):
    """Log API access events"""
    log('api', message, level=level, details=details)


def log_admin(message: str, level: str = 'INFO', details: dict = None):
    """Log admin action events"""
    log('admin', message, level=level, details=details)


def get_recent_logs(limit: int = 100, category: str = None, level: str = None,
                    symbol: str = None, offset: int = 0):
    """
    Get recent logs with optional filtering

    Returns:
        List of log dicts
    """
    from app.models import Log

    query = Log.query

    if category:
        query = query.filter(Log.category == category)
    if level:
        query = query.filter(Log.level == level)
    if symbol:
        query = query.filter(Log.symbol == symbol)

    logs = query.order_by(Log.timestamp.desc()).offset(offset).limit(limit).all()
    return [log.to_dict() for log in logs]


def get_log_stats():
    """Get log statistics"""
    from app.models import Log
    from sqlalchemy import func
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    stats = {
        'total': Log.query.count(),
        'last_hour': Log.query.filter(Log.timestamp >= hour_ago).count(),
        'last_day': Log.query.filter(Log.timestamp >= day_ago).count(),
        'errors_today': Log.query.filter(
            Log.timestamp >= day_ago,
            Log.level == 'ERROR'
        ).count(),
        'by_category': {}
    }

    # Count by category
    category_counts = Log.query.with_entities(
        Log.category, func.count(Log.id)
    ).group_by(Log.category).all()

    for cat, count in category_counts:
        stats['by_category'][cat] = count

    return stats


