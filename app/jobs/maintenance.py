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
    Background job to report on old data (NO DELETION).

    All historical data is preserved for analysis:
    - Logs: kept indefinitely
    - Patterns: kept indefinitely (status changes to 'expired')
    - Signals: kept indefinitely
    - Notifications: kept indefinitely

    This job only reports statistics, it does NOT delete anything.

    Returns:
        Dict with data statistics (no deletions)
    """
    from app import create_app
    from app.models import Log, Pattern, Signal, Notification, UserNotification

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)
        results = {}

        # Count old logs (NOT deleted)
        log_cutoff = datetime.now(timezone.utc) - timedelta(days=log_retention_days)
        old_logs = Log.query.filter(Log.timestamp < log_cutoff).count()
        results['old_logs_count'] = old_logs
        results['total_logs'] = Log.query.count()

        # Count expired patterns (NOT deleted)
        pattern_cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=pattern_retention_days)).timestamp() * 1000
        )
        old_expired_patterns = Pattern.query.filter(
            Pattern.status == 'expired',
            Pattern.detected_at < pattern_cutoff_ms
        ).count()
        results['old_expired_patterns_count'] = old_expired_patterns
        results['total_patterns'] = Pattern.query.count()
        results['active_patterns'] = Pattern.query.filter_by(status='active').count()
        results['expired_patterns'] = Pattern.query.filter_by(status='expired').count()

        # Count signals
        results['total_signals'] = Signal.query.count()

        # Count old notifications (NOT deleted)
        notification_cutoff = datetime.now(timezone.utc) - timedelta(days=notification_retention_days)
        old_notifications = Notification.query.filter(
            Notification.sent_at < notification_cutoff
        ).count()
        results['old_notifications_count'] = old_notifications
        results['total_notifications'] = Notification.query.count()

        # Count old user notifications (NOT deleted)
        old_user_notifications = UserNotification.query.filter(
            UserNotification.sent_at < notification_cutoff
        ).count()
        results['old_user_notifications_count'] = old_user_notifications
        results['total_user_notifications'] = UserNotification.query.count()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        results['elapsed_seconds'] = elapsed

        # No deletions - data is preserved
        results['deleted'] = 0
        results['policy'] = 'Data preservation enabled - no automatic deletion'

        logger.info(
            f"[JOB] Data check complete: {results['total_patterns']} patterns, "
            f"{results['total_signals']} signals, {results['total_logs']} logs "
            f"(all preserved, no deletions)"
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
                Signal.created_at >= int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
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
                    Signal.created_at >= int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
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
