"""
Logging Service
Centralized logging to database and console
"""
import json
import logging
from datetime import datetime, timezone
from functools import wraps

# Console logger
console_logger = logging.getLogger('cryptolens')
console_logger.setLevel(logging.INFO)
if not console_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))
    console_logger.addHandler(handler)


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
    # Console log
    log_func = getattr(console_logger, level.lower(), console_logger.info)
    prefix = f"[{category.upper()}]"
    if symbol:
        prefix += f" {symbol}"
    if timeframe:
        prefix += f" ({timeframe})"
    log_func(f"{prefix} {message}")

    # Database log (in try/except to not break if DB unavailable)
    try:
        from flask import current_app, has_app_context
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
        # Don't spam console with DB errors
        pass


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


def cleanup_old_logs(days: int = 7):
    """Delete logs older than specified days"""
    from app import db
    from app.models import Log
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = Log.query.filter(Log.timestamp < cutoff).delete()
    db.session.commit()

    log_system(f"Cleaned up {deleted} logs older than {days} days")
    return deleted
