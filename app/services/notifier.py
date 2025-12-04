"""
Notification Service
Sends push notifications via NTFY.sh
"""
import time
import requests
from datetime import datetime, timezone
from app.models import Signal, Symbol, Pattern, Notification, Setting
import json
from app.config import Config
from app import db
from app.services.logger import log_notify, log_error


def send_notification(topic: str, title: str, message: str, priority: int = 3,
                      tags: str = "chart,money", max_retries: int = 3) -> bool:
    """
    Send a push notification via ntfy.sh with exponential backoff retry

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

    for attempt in range(max_retries):
        try:
            # Use JSON API to properly handle UTF-8 titles with emojis
            response = requests.post(
                f"{Config.NTFY_URL}",
                json={
                    "topic": topic,
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "tags": tags.split(",")
                },
                timeout=10
            )
            if response.status_code == 200:
                return True

            last_error = f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            last_error = "Request timeout"
        except requests.exceptions.ConnectionError:
            last_error = "Connection error"
        except Exception as e:
            last_error = str(e)

        # Exponential backoff: 1s, 2s, 4s
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            time.sleep(wait_time)

    log_error(f"NTFY notification failed after {max_retries} attempts: {last_error}")
    return False


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
        except:
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
        signal.notified_at = datetime.now(timezone.utc)
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
