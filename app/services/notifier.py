"""
Notification Service
Sends push notifications via NTFY.sh
Supports both single-topic mode (legacy) and per-user topic mode
"""
import time
import requests
import pybreaker
from datetime import datetime, timezone
from app.models import Signal, Symbol, Pattern, Notification, Setting, User, UserNotification
import json
from app.config import Config
from app import db
from app.services.logger import log_notify, log_error
from app.constants import (
    CIRCUIT_BREAKER_FAIL_MAX, CIRCUIT_BREAKER_RESET_TIMEOUT,
    HTTP_TIMEOUT_DEFAULT, PRIORITY_URGENT
)

# Circuit breaker for NTFY service
ntfy_breaker = pybreaker.CircuitBreaker(
    fail_max=CIRCUIT_BREAKER_FAIL_MAX,
    reset_timeout=CIRCUIT_BREAKER_RESET_TIMEOUT,
    name='ntfy'
)


@ntfy_breaker
def _send_ntfy_request(topic: str, title: str, message: str, priority: int, tags: list) -> bool:
    """Internal function wrapped by circuit breaker."""
    response = requests.post(
        f"{Config.NTFY_URL}",
        json={
            "topic": topic,
            "title": title,
            "message": message,
            "priority": priority,
            "tags": tags
        },
        timeout=HTTP_TIMEOUT_DEFAULT
    )
    if response.status_code == 200:
        return True
    raise Exception(f"HTTP {response.status_code}")


def send_notification(topic: str, title: str, message: str, priority: int = 3,
                      tags: str = "chart,money", max_retries: int = 3) -> bool:
    """
    Send a push notification via ntfy.sh with circuit breaker and retry

    Args:
        topic: NTFY topic to send to
        title: Notification title
        message: Notification body
        priority: 1=min, 2=low, 3=default, 4=high, 5=urgent
        tags: Comma-separated emoji tags
        max_retries: Maximum number of retry attempts

    Returns:
        True if successful
    """
    last_error = None
    tags_list = tags.split(",") if isinstance(tags, str) else (tags or [])

    for attempt in range(max_retries):
        try:
            return _send_ntfy_request(topic, title, message, priority, tags_list)
        except pybreaker.CircuitBreakerError:
            # Circuit is open, don't retry
            log_error("NTFY circuit breaker is open - notifications temporarily disabled")
            return False
        except requests.exceptions.Timeout:
            last_error = "Request timeout"
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)[:100]}"
        except Exception as e:
            last_error = str(e)[:200]

        # Exponential backoff: 1s, 2s, 4s
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            time.sleep(wait_time)

    log_error(f"NTFY notification failed after {max_retries} attempts: {last_error}")
    return False


def test_ntfy_connection(topic: str = None) -> dict:
    """
    Test NTFY connectivity.

    Args:
        topic: Optional topic to test with (defaults to a test topic)

    Returns:
        Dict with 'success', 'error', 'url', 'status_code'
    """
    test_topic = topic or 'cl_test_connection'

    try:
        response = requests.post(
            f"{Config.NTFY_URL}",
            json={
                "topic": test_topic,
                "title": "CryptoLens Connection Test",
                "message": f"Test at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                "priority": 1,  # Minimum priority for test
                "tags": ["test"]
            },
            timeout=10
        )
        return {
            'success': response.status_code == 200,
            'status_code': response.status_code,
            'url': Config.NTFY_URL,
            'response': response.text[:200] if response.text else None
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'success': False,
            'error': f'Connection error: {str(e)[:100]}',
            'url': Config.NTFY_URL
        }
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'Request timeout',
            'url': Config.NTFY_URL
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)[:200],
            'url': Config.NTFY_URL
        }


def notify_signal(signal: Signal, test_mode: bool = False, current_price: float = None) -> bool:
    """
    Send notification for a trading signal

    Args:
        signal: The signal to notify about
        test_mode: If True, adds 'Test' to tags and title
        current_price: Current market price for % calculation

    Returns:
        True if successful
    """
    # Check if notifications are enabled
    if Setting.get('notifications_enabled', 'true') != 'true':
        return False

    # Get settings
    topic = Setting.get('ntfy_topic', Config.NTFY_TOPIC)
    priority = int(Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)))

    # Get symbol
    from app import db
    symbol = db.session.get(Symbol, signal.symbol_id)
    symbol_name = symbol.symbol if symbol else 'Unknown'

    # Get pattern type and abbreviation for tags
    pattern = db.session.get(Pattern, signal.pattern_id) if signal.pattern_id else None
    pattern_type = 'Unknown'
    pattern_abbrev = 'SIG'  # Default abbreviation
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

    # Get aligned timeframes
    aligned_tfs = []
    if signal.timeframes_aligned:
        try:
            aligned_tfs = json.loads(signal.timeframes_aligned)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    tfs_str = ', '.join(aligned_tfs) if aligned_tfs else pattern_tf

    # Build notification
    direction_emoji = "🟢" if signal.direction == 'long' else "🔴"
    direction_text = "LONG" if signal.direction == 'long' else "SHORT"

    # Title: emoji + direction + symbol + pattern + TF
    test_prefix = "[TEST] " if test_mode else ""
    title = f"{test_prefix}{direction_emoji} {direction_text}: {symbol_name} | {pattern_type} [{pattern_tf}]"

    # Extract base symbol (e.g., BTC from BTC/USDT)
    base_symbol = symbol_name.split('/')[0] if '/' in symbol_name else symbol_name

    # Build tags: direction, base symbol, pattern abbreviation (with test if test_mode)
    tags = f"{signal.direction},{base_symbol},{pattern_abbrev}"
    if test_mode:
        tags = f"test,{tags}"

    # Timestamp (European format: DD/MM/YYYY HH:MM)
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")

    # Format timeframes with brackets for confluence line
    tfs_bracketed = f"[{tfs_str}]" if tfs_str else ""

    # Calculate percentages
    entry = signal.entry_price
    sl = signal.stop_loss
    tp1 = signal.take_profit_1

    # Entry % from current price
    entry_pct = ""
    if current_price and current_price > 0:
        pct_diff = ((entry - current_price) / current_price) * 100
        entry_pct = f" ({pct_diff:+.2f}%)"

    # Calculate % from entry (with correct signs for long/short)
    # SL: For long it's negative (price down), for short it's positive (price up)
    # TP: For long it's positive (price up), for short it's negative (price down)
    sl_pct = ((sl - entry) / entry * 100) if entry > 0 else 0
    tp1_pct = ((tp1 - entry) / entry * 100) if entry > 0 else 0

    # Build message
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

    # Send notification
    success = send_notification(
        topic=topic,
        title=title,
        message=message,
        priority=priority,
        tags=tags
    )

    # Log notification
    notification = Notification(
        signal_id=signal.id,
        channel='ntfy',
        success=success,
        error_message=None if success else "Failed to send"
    )
    db.session.add(notification)

    # Update signal status
    if success:
        signal.status = 'notified'
        signal.notified_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        log_notify(
            f"Sent {direction_text} signal: {pattern_type} [{pattern_tf}] Entry ${entry:,.4f}{entry_pct}",
            symbol=symbol_name,
            details={'direction': direction_text, 'pattern': pattern_type, 'tf': pattern_tf, 'entry': entry, 'confluence': signal.confluence_score}
        )
    else:
        log_notify(f"Failed to send notification", symbol=symbol_name, level='ERROR')

    db.session.commit()

    return success


def notify_confluence(symbol: str, direction: str, aligned_timeframes: list,
                      entry: float, stop_loss: float, take_profits: list,
                      risk_reward: float = 3.0) -> bool:
    """
    Send notification when multiple timeframes align

    Args:
        symbol: Trading pair
        direction: 'long' or 'short'
        aligned_timeframes: List of aligned timeframe strings
        entry: Entry price
        stop_loss: Stop loss price
        take_profits: List of take profit prices
        risk_reward: Risk/reward ratio

    Returns:
        True if successful
    """
    topic = Setting.get('ntfy_topic', Config.NTFY_TOPIC)
    priority = 5  # Urgent for high confluence

    # Timestamp (European format: DD/MM/YYYY HH:MM)
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")

    direction_emoji = "🟢" if direction == 'long' else "🔴"
    direction_text = "LONG" if direction == 'long' else "SHORT"

    confluence = len(aligned_timeframes)
    tfs_bracketed = f"[{', '.join(aligned_timeframes)}]"

    # Title with colored emoji
    title = f"{direction_emoji} HIGH CONFLUENCE: {symbol} {direction_text}"

    # Extract base symbol (e.g., BTC from BTC/USDT)
    base_symbol = symbol.split('/')[0] if '/' in symbol else symbol

    # Build tags: direction, base symbol
    tags = f"{direction},{base_symbol},confluence"

    sl_pct = abs((stop_loss - entry) / entry * 100)
    rr_percent = risk_reward * 100

    message = (
        f"{timestamp_str}\n"
        f"Entry: ${entry:,.2f}\n"
        f"SL: ${stop_loss:,.2f} ({sl_pct:.2f}%)\n"
    )

    for i, tp in enumerate(take_profits[:3], 1):
        tp_pct = abs((tp - entry) / entry * 100)
        message += f"TP{i}: ${tp:,.2f} ({tp_pct:.2f}%)\n"

    message += f"R:R: {risk_reward:.1f} ({rr_percent:.0f}%)\n"
    message += f"Confluence: {confluence}/6 {tfs_bracketed}"

    return send_notification(
        topic=topic,
        title=title,
        message=message,
        priority=priority,
        tags=tags
    )


def get_eligible_subscribers(pattern_type: str = None):
    """
    Get all users who are eligible to receive notifications.
    A user is eligible if:
    - Account is active
    - Account is verified
    - Has a valid subscription (active or in grace period)
    - Has not exceeded daily notification limit
    - Can view the pattern type (if specified)

    Args:
        pattern_type: Optional pattern type to filter by tier access

    Returns:
        List of User objects
    """
    from sqlalchemy.orm import joinedload

    # Eager load subscriptions to avoid N+1 queries
    users = User.query.options(
        joinedload(User.subscription)
    ).filter_by(is_active=True, is_verified=True).all()

    eligible = []
    for u in users:
        # Check basic notification eligibility
        if not u.can_receive_notification_now():
            continue

        # Check pattern type access if specified
        if pattern_type:
            allowed_types = u.get_allowed_pattern_types()
            if allowed_types and pattern_type not in allowed_types:
                continue

        eligible.append(u)

    return eligible


def get_subscribers_with_delay():
    """
    Get eligible subscribers grouped by notification delay.

    Returns:
        Dict with delay_seconds as keys and list of users as values
    """
    from sqlalchemy.orm import joinedload

    users = User.query.options(
        joinedload(User.subscription)
    ).filter_by(is_active=True, is_verified=True).all()

    by_delay = {}
    for u in users:
        if not u.can_receive_notification_now():
            continue

        delay = u.get_notification_delay_seconds()
        if delay not in by_delay:
            by_delay[delay] = []
        by_delay[delay].append(u)

    return by_delay


def send_notification_to_user(user: User, signal_id: int, title: str, message: str,
                               priority: int = 3, tags: str = "chart,money") -> bool:
    """
    Send notification to a specific user and track delivery.

    Args:
        user: User object to send to
        signal_id: ID of the signal being notified
        title: Notification title
        message: Notification body
        priority: NTFY priority level
        tags: Comma-separated tags

    Returns:
        True if successful
    """
    success = send_notification(
        topic=user.ntfy_topic,
        title=title,
        message=message,
        priority=priority,
        tags=tags
    )

    # Track notification delivery
    user_notification = UserNotification(
        user_id=user.id,
        signal_id=signal_id,
        success=success,
        error=None if success else "Failed to send"
    )
    db.session.add(user_notification)

    return success


def notify_all_subscribers(signal: Signal, test_mode: bool = False,
                          current_price: float = None) -> dict:
    """
    Send notification to all eligible subscribers.

    Args:
        signal: The signal to notify about
        test_mode: If True, adds 'Test' prefix
        current_price: Current market price

    Returns:
        Dict with 'total', 'success', 'failed' counts
    """
    # Check if notifications are enabled
    if Setting.get('notifications_enabled', 'true') != 'true':
        return {'total': 0, 'success': 0, 'failed': 0, 'skipped': True}

    # Check if per-user mode is enabled
    per_user_mode = Setting.get('per_user_notifications', 'false') == 'true'

    if not per_user_mode:
        # Fall back to legacy single-topic mode
        success = notify_signal(signal, test_mode, current_price)
        return {'total': 1, 'success': 1 if success else 0, 'failed': 0 if success else 1}

    # Get pattern type for tier-based filtering
    pattern = db.session.get(Pattern, signal.pattern_id) if signal.pattern_id else None
    pattern_type = pattern.pattern_type if pattern else None

    # Get eligible subscribers (filtered by rate limits and pattern type access)
    subscribers = get_eligible_subscribers(pattern_type=pattern_type)

    if not subscribers:
        log_notify("No eligible subscribers for notification", level='WARNING')
        return {'total': 0, 'success': 0, 'failed': 0}

    # Build notification content once
    priority = int(Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)))

    # Get symbol
    symbol = db.session.get(Symbol, signal.symbol_id)
    symbol_name = symbol.symbol if symbol else 'Unknown'

    # Get pattern info
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

    # Get aligned timeframes
    aligned_tfs = []
    if signal.timeframes_aligned:
        try:
            aligned_tfs = json.loads(signal.timeframes_aligned)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    tfs_str = ', '.join(aligned_tfs) if aligned_tfs else pattern_tf

    # Build notification content
    direction_emoji = "🟢" if signal.direction == 'long' else "🔴"
    direction_text = "LONG" if signal.direction == 'long' else "SHORT"

    test_prefix = "[TEST] " if test_mode else ""
    title = f"{test_prefix}{direction_emoji} {direction_text}: {symbol_name} | {pattern_type} [{pattern_tf}]"

    base_symbol = symbol_name.split('/')[0] if '/' in symbol_name else symbol_name
    tags = f"{signal.direction},{base_symbol},{pattern_abbrev}"
    if test_mode:
        tags = f"test,{tags}"

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

    # Send to all subscribers using async for better performance
    from app.services.async_notifier import notify_subscribers_async

    # Prepare subscriber data for async sending
    subscriber_data = [
        {'user_id': user.id, 'ntfy_topic': user.ntfy_topic}
        for user in subscribers
    ]

    # Send notifications concurrently
    tags_list = tags.split(",") if isinstance(tags, str) else tags
    async_result = notify_subscribers_async(
        subscribers=subscriber_data,
        title=title,
        message=message,
        priority=priority,
        tags=tags_list
    )

    success_count = async_result['success']
    failed_count = async_result['failed']

    # Record individual notification results
    for res in async_result.get('results', []):
        user_notification = UserNotification(
            user_id=res.user_id,
            signal_id=signal.id,
            success=res.success,
            error=res.error
        )
        db.session.add(user_notification)

    # Log general notification record
    notification = Notification(
        signal_id=signal.id,
        channel='ntfy',
        success=success_count > 0,
        error_message=None if success_count > 0 else f"Failed for all {failed_count} subscribers"
    )
    db.session.add(notification)

    # Update signal status
    if success_count > 0:
        signal.status = 'notified'
        signal.notified_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        log_notify(
            f"Sent {direction_text} signal to {success_count}/{len(subscribers)} subscribers: "
            f"{pattern_type} [{pattern_tf}] Entry ${entry:,.4f}{entry_pct}",
            symbol=symbol_name,
            details={
                'direction': direction_text,
                'pattern': pattern_type,
                'tf': pattern_tf,
                'entry': entry,
                'confluence': signal.confluence_score,
                'subscribers': len(subscribers),
                'success': success_count,
                'failed': failed_count
            }
        )
    else:
        log_notify(
            f"Failed to send notification to any subscriber",
            symbol=symbol_name,
            level='ERROR'
        )

    db.session.commit()

    return {
        'total': len(subscribers),
        'success': success_count,
        'failed': failed_count
    }


def notify_subscribers_confluence(symbol: str, direction: str, aligned_timeframes: list,
                                  entry: float, stop_loss: float, take_profits: list,
                                  risk_reward: float = 3.0, signal_id: int = None) -> dict:
    """
    Send high confluence notification to all eligible subscribers.

    Args:
        symbol: Trading pair
        direction: 'long' or 'short'
        aligned_timeframes: List of aligned timeframe strings
        entry: Entry price
        stop_loss: Stop loss price
        take_profits: List of take profit prices
        risk_reward: Risk/reward ratio
        signal_id: Optional signal ID for tracking

    Returns:
        Dict with 'total', 'success', 'failed' counts
    """
    per_user_mode = Setting.get('per_user_notifications', 'false') == 'true'

    if not per_user_mode:
        # Fall back to legacy mode
        success = notify_confluence(symbol, direction, aligned_timeframes,
                                   entry, stop_loss, take_profits, risk_reward)
        return {'total': 1, 'success': 1 if success else 0, 'failed': 0 if success else 1}

    subscribers = get_eligible_subscribers()

    if not subscribers:
        return {'total': 0, 'success': 0, 'failed': 0}

    priority = 5  # Urgent for high confluence

    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")

    direction_emoji = "🟢" if direction == 'long' else "🔴"
    direction_text = "LONG" if direction == 'long' else "SHORT"

    confluence = len(aligned_timeframes)
    tfs_bracketed = f"[{', '.join(aligned_timeframes)}]"

    title = f"{direction_emoji} HIGH CONFLUENCE: {symbol} {direction_text}"

    base_symbol = symbol.split('/')[0] if '/' in symbol else symbol
    tags = f"{direction},{base_symbol},confluence"

    sl_pct = abs((stop_loss - entry) / entry * 100)

    message = (
        f"{timestamp_str}\n"
        f"Entry: ${entry:,.2f}\n"
        f"SL: ${stop_loss:,.2f} ({sl_pct:.2f}%)\n"
    )

    for i, tp in enumerate(take_profits[:3], 1):
        tp_pct = abs((tp - entry) / entry * 100)
        message += f"TP{i}: ${tp:,.2f} ({tp_pct:.2f}%)\n"

    message += f"R:R: {risk_reward:.1f}\n"
    message += f"Confluence: {confluence}/6 {tfs_bracketed}"

    # Send to all subscribers using async for better performance
    from app.services.async_notifier import notify_subscribers_async

    subscriber_data = [
        {'user_id': user.id, 'ntfy_topic': user.ntfy_topic}
        for user in subscribers
    ]

    tags_list = tags.split(",") if isinstance(tags, str) else tags
    async_result = notify_subscribers_async(
        subscribers=subscriber_data,
        title=title,
        message=message,
        priority=priority,
        tags=tags_list
    )

    success_count = async_result['success']
    failed_count = async_result['failed']

    # Record individual notification results if signal_id provided
    if signal_id:
        for res in async_result.get('results', []):
            user_notification = UserNotification(
                user_id=res.user_id,
                signal_id=signal_id,
                success=res.success,
                error=res.error
            )
            db.session.add(user_notification)
        db.session.commit()

    log_notify(
        f"Sent HIGH CONFLUENCE {direction_text} to {success_count}/{len(subscribers)} subscribers",
        symbol=symbol,
        details={
            'confluence': confluence,
            'timeframes': aligned_timeframes,
            'subscribers': len(subscribers),
            'success': success_count,
            'failed': failed_count
        }
    )

    return {
        'total': len(subscribers),
        'success': success_count,
        'failed': failed_count
    }
