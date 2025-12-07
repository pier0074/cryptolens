"""
Maintenance Background Jobs
Cleanup, cache updates, and other maintenance tasks
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

logger = logging.getLogger('cryptolens')


def cleanup_old_data_job(
    log_retention_days: int = 7,
    pattern_retention_days: int = 30,
    notification_retention_days: int = 30
) -> Dict[str, Any]:
    """
    Background job to clean up old data.

    Args:
        log_retention_days: Days to keep logs
        pattern_retention_days: Days to keep expired patterns
        notification_retention_days: Days to keep notification records

    Returns:
        Dict with cleanup results
    """
    from app import create_app, db
    from app.models import Log, Pattern, Notification, UserNotification

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)
        results = {}

        # Clean old logs
        log_cutoff = datetime.now(timezone.utc) - timedelta(days=log_retention_days)
        deleted_logs = Log.query.filter(Log.timestamp < log_cutoff).delete()
        results['logs_deleted'] = deleted_logs

        # Clean old expired patterns
        pattern_cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=pattern_retention_days)).timestamp() * 1000
        )
        deleted_patterns = Pattern.query.filter(
            Pattern.status == 'expired',
            Pattern.detected_at < pattern_cutoff_ms
        ).delete()
        results['patterns_deleted'] = deleted_patterns

        # Clean old notifications
        notification_cutoff = datetime.now(timezone.utc) - timedelta(days=notification_retention_days)
        deleted_notifications = Notification.query.filter(
            Notification.sent_at < notification_cutoff
        ).delete()
        results['notifications_deleted'] = deleted_notifications

        # Clean old user notifications
        deleted_user_notifications = UserNotification.query.filter(
            UserNotification.sent_at < notification_cutoff
        ).delete()
        results['user_notifications_deleted'] = deleted_user_notifications

        db.session.commit()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        results['elapsed_seconds'] = elapsed

        total_deleted = (
            deleted_logs + deleted_patterns +
            deleted_notifications + deleted_user_notifications
        )

        logger.info(
            f"[JOB] Cleanup complete: {total_deleted} records deleted in {elapsed:.2f}s"
        )

        return results


def update_stats_cache_job() -> Dict[str, Any]:
    """
    Background job to update statistics cache.

    Returns:
        Dict with cache update results
    """
    from app import create_app, db
    from app.models import Symbol, Pattern, Signal, StatsCache, User, Subscription
    import json

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)
        now_ms = int(start_time.timestamp() * 1000)

        # Global stats
        global_stats = {
            'total_symbols': Symbol.query.filter_by(is_active=True).count(),
            'active_patterns': Pattern.query.filter_by(status='active').count(),
            'total_signals': Signal.query.count(),
            'signals_24h': Signal.query.filter(
                Signal.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            ).count(),
            'total_users': User.query.filter_by(is_active=True, is_verified=True).count(),
            'active_subscriptions': Subscription.query.filter_by(status='active').count(),
            'last_data_update': now_ms,
            'computed_at': start_time.isoformat()
        }

        # Update or create global stats cache
        global_cache = StatsCache.query.filter_by(key='global').first()
        if global_cache:
            global_cache.data = json.dumps(global_stats)
            global_cache.computed_at = now_ms
        else:
            global_cache = StatsCache(
                key='global',
                data=json.dumps(global_stats),
                computed_at=now_ms
            )
            db.session.add(global_cache)

        # Per-symbol stats
        symbols = Symbol.query.filter_by(is_active=True).all()
        symbol_stats_updated = 0

        for symbol in symbols:
            symbol_stats = {
                'active_patterns': Pattern.query.filter_by(
                    symbol_id=symbol.id, status='active'
                ).count(),
                'total_signals': Signal.query.filter_by(symbol_id=symbol.id).count(),
                'signals_24h': Signal.query.filter(
                    Signal.symbol_id == symbol.id,
                    Signal.created_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                ).count(),
                'computed_at': start_time.isoformat()
            }

            cache_key = f'symbol:{symbol.symbol}'
            symbol_cache = StatsCache.query.filter_by(key=cache_key).first()
            if symbol_cache:
                symbol_cache.data = json.dumps(symbol_stats)
                symbol_cache.computed_at = now_ms
            else:
                symbol_cache = StatsCache(
                    key=cache_key,
                    data=json.dumps(symbol_stats),
                    computed_at=now_ms
                )
                db.session.add(symbol_cache)
            symbol_stats_updated += 1

        db.session.commit()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(
            f"[JOB] Stats cache updated: global + {symbol_stats_updated} symbols in {elapsed:.2f}s"
        )

        return {
            'global_stats_updated': True,
            'symbol_stats_updated': symbol_stats_updated,
            'elapsed_seconds': elapsed
        }


def expire_patterns_job() -> Dict[str, Any]:
    """
    Background job to expire old patterns.

    Returns:
        Dict with expiry results
    """
    from app import create_app, db
    from app.models import Pattern
    from app.config import Config

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)
        now_ms = int(start_time.timestamp() * 1000)

        # Get all active patterns
        active_patterns = Pattern.query.filter_by(status='active').all()
        expired_count = 0

        for pattern in active_patterns:
            # Calculate expiry based on timeframe
            expiry_hours = Config.PATTERN_EXPIRY_HOURS.get(
                pattern.timeframe,
                Config.DEFAULT_PATTERN_EXPIRY_HOURS
            )
            expiry_ms = expiry_hours * 60 * 60 * 1000
            expires_at = pattern.detected_at + expiry_ms

            if now_ms > expires_at:
                pattern.status = 'expired'
                expired_count += 1

        db.session.commit()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(
            f"[JOB] Pattern expiry: {expired_count}/{len(active_patterns)} patterns expired"
        )

        return {
            'patterns_checked': len(active_patterns),
            'patterns_expired': expired_count,
            'elapsed_seconds': elapsed
        }
