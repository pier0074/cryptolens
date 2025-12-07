"""
Notification Background Jobs
Handles async notification delivery via RQ
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger('cryptolens')


def send_signal_notification_job(
    signal_id: int,
    test_mode: bool = False,
    current_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    Background job to send signal notification to all subscribers.

    Args:
        signal_id: ID of the signal to notify about
        test_mode: If True, adds test prefix
        current_price: Current market price

    Returns:
        Dict with notification results
    """
    # Import inside job to avoid circular imports and ensure app context
    from app import create_app, db
    from app.models import Signal, Symbol, Pattern, Setting, UserNotification, Notification
    from app.services.notifier import get_eligible_subscribers
    from app.services.async_notifier import notify_subscribers_async
    from app.config import Config
    import json

    app = create_app()
    with app.app_context():
        signal = db.session.get(Signal, signal_id)
        if not signal:
            logger.error(f"Signal {signal_id} not found")
            return {'error': 'Signal not found'}

        # Check if notifications enabled
        if Setting.get('notifications_enabled', 'true') != 'true':
            return {'skipped': True, 'reason': 'Notifications disabled'}

        # Get subscribers
        subscribers = get_eligible_subscribers()
        if not subscribers:
            logger.warning("No eligible subscribers")
            return {'total': 0, 'success': 0, 'failed': 0}

        # Build notification content
        priority = int(Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)))
        symbol = db.session.get(Symbol, signal.symbol_id)
        symbol_name = symbol.symbol if symbol else 'Unknown'

        pattern = db.session.get(Pattern, signal.pattern_id) if signal.pattern_id else None
        pattern_type = 'Unknown'
        pattern_abbrev = 'SIG'
        pattern_tf = ''
        if pattern:
            pattern_types = {
                'imbalance': 'FVG',
                'order_block': 'OB',
                'liquidity_sweep': 'LS'
            }
            pattern_type = pattern_types.get(pattern.pattern_type, pattern.pattern_type)
            pattern_abbrev = pattern_type
            pattern_tf = pattern.timeframe

        aligned_tfs = []
        if signal.timeframes_aligned:
            try:
                aligned_tfs = json.loads(signal.timeframes_aligned)
            except:
                pass
        tfs_str = ', '.join(aligned_tfs) if aligned_tfs else pattern_tf

        direction_emoji = "🟢" if signal.direction == 'long' else "🔴"
        direction_text = "LONG" if signal.direction == 'long' else "SHORT"

        test_prefix = "[TEST] " if test_mode else ""
        title = f"{test_prefix}{direction_emoji} {direction_text}: {symbol_name} | {pattern_type} [{pattern_tf}]"

        base_symbol = symbol_name.split('/')[0] if '/' in symbol_name else symbol_name
        tags = [signal.direction, base_symbol, pattern_abbrev]
        if test_mode:
            tags.insert(0, "test")

        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")
        tfs_bracketed = f"[{tfs_str}]" if tfs_str else ""

        entry = signal.entry_price
        sl = signal.stop_loss
        tp1 = signal.take_profit_1

        entry_pct = ""
        if current_price and current_price > 0:
            pct_diff = ((entry - current_price) / current_price) * 100
            entry_pct = f" ({pct_diff:+.2f}%)"

        sl_pct = ((sl - entry) / entry * 100) if entry > 0 else 0
        tp1_pct = ((tp1 - entry) / entry * 100) if entry > 0 else 0

        current_price_line = f"Current: ${current_price:,.4f}\n" if current_price else ""

        message = (
            f"{timestamp_str}\n"
            f"{current_price_line}"
            f"Limit Entry: ${entry:,.4f}{entry_pct}\n"
            f"Stop Loss: ${sl:,.4f} ({sl_pct:+.2f}%)\n"
            f"TP1: ${tp1:,.4f} ({tp1_pct:+.2f}%)\n"
            f"R:R: {signal.risk_reward:.1f}\n"
            f"Confluence: {signal.confluence_score}/6 {tfs_bracketed}"
        )

        # Prepare subscriber data for async sending
        subscriber_data = [
            {'user_id': user.id, 'ntfy_topic': user.ntfy_topic}
            for user in subscribers
        ]

        # Send notifications concurrently
        result = notify_subscribers_async(
            subscribers=subscriber_data,
            title=title,
            message=message,
            priority=priority,
            tags=tags
        )

        # Record individual notification results
        for res in result.get('results', []):
            user_notification = UserNotification(
                user_id=res.user_id,
                signal_id=signal_id,
                success=res.success,
                error=res.error
            )
            db.session.add(user_notification)

        # Record general notification
        notification = Notification(
            signal_id=signal_id,
            channel='ntfy',
            success=result['success'] > 0,
            error_message=None if result['success'] > 0 else f"Failed for all {result['failed']} subscribers"
        )
        db.session.add(notification)

        # Update signal status
        if result['success'] > 0:
            signal.status = 'notified'
            signal.notified_at = datetime.now(timezone.utc)

        db.session.commit()

        logger.info(
            f"[JOB] Sent signal notification to {result['success']}/{result['total']} subscribers"
        )

        return {
            'total': result['total'],
            'success': result['success'],
            'failed': result['failed']
        }


def send_bulk_notifications_job(
    notifications: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Background job to send multiple different notifications.

    Args:
        notifications: List of notification dicts with:
            - user_id: int
            - topic: str
            - title: str
            - message: str
            - priority: int (optional)
            - tags: List[str] (optional)
            - signal_id: int (optional, for tracking)

    Returns:
        Dict with results
    """
    from app import create_app, db
    from app.models import UserNotification
    from app.services.async_notifier import send_batch_notifications_async
    import asyncio

    app = create_app()
    with app.app_context():
        # Run async batch send
        results = asyncio.run(send_batch_notifications_async(notifications))

        # Record results for notifications with signal_id
        for i, res in enumerate(results):
            if i < len(notifications) and 'signal_id' in notifications[i]:
                user_notification = UserNotification(
                    user_id=res.user_id,
                    signal_id=notifications[i]['signal_id'],
                    success=res.success,
                    error=res.error
                )
                db.session.add(user_notification)

        db.session.commit()

        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        logger.info(f"[JOB] Bulk notification: {success_count}/{len(results)} successful")

        return {
            'total': len(results),
            'success': success_count,
            'failed': failed_count
        }
