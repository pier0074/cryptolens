"""
Notification Service
Sends push notifications via NTFY.sh
"""
import requests
from datetime import datetime, timezone
from app.models import Signal, Symbol, Pattern, Notification, Setting
import json
from app.config import Config
from app import db


def send_notification(topic: str, title: str, message: str, priority: int = 3,
                      tags: str = "chart,money") -> bool:
    """
    Send a push notification via ntfy.sh

    Args:
        topic: NTFY topic to send to
        title: Notification title
        message: Notification body
        priority: 1=min, 2=low, 3=default, 4=high, 5=urgent
        tags: Comma-separated emoji tags

    Returns:
        True if successful
    """
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
        return response.status_code == 200
    except Exception as e:
        print(f"Notification error: {e}")
        return False


def notify_signal(signal: Signal) -> bool:
    """
    Send notification for a trading signal

    Args:
        signal: The signal to notify about

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
    symbol = Symbol.query.get(signal.symbol_id)
    symbol_name = symbol.symbol if symbol else 'Unknown'

    # Get pattern type
    pattern = Pattern.query.get(signal.pattern_id) if signal.pattern_id else None
    pattern_type = 'Unknown'
    pattern_tf = ''
    if pattern:
        pattern_types = {
            'imbalance': 'FVG (Fair Value Gap)',
            'order_block': 'Order Block',
            'liquidity_sweep': 'Liquidity Sweep'
        }
        pattern_type = pattern_types.get(pattern.pattern_type, pattern.pattern_type)
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

    title = f"{direction_emoji} {direction_text}: {symbol_name}"

    # Calculate percentages
    entry = signal.entry_price
    sl = signal.stop_loss
    tp1 = signal.take_profit_1

    sl_pct = abs((sl - entry) / entry * 100) if entry > 0 else 0
    tp1_pct = abs((tp1 - entry) / entry * 100) if entry > 0 else 0

    message = (
        f"📊 Symbol: {symbol_name}\n"
        f"📈 Direction: {direction_text}\n"
        f"🔍 Pattern: {pattern_type}\n"
        f"⏱️ Timeframes: {tfs_str}\n"
        f"💰 Limit Entry: ${entry:,.4f}\n"
        f"🛑 Stop Loss: ${sl:,.4f} ({sl_pct:.2f}%)\n"
        f"🎯 TP1: ${tp1:,.4f} ({tp1_pct:.2f}%)\n"
        f"⚖️ R:R {signal.risk_reward:.1f}\n"
        f"🔗 Confluence: {signal.confluence_score}/6 TFs"
    )

    # Send notification
    success = send_notification(
        topic=topic,
        title=title,
        message=message,
        priority=priority,
        tags="chart,money,cryptocurrency"
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

    db.session.commit()

    return success


def notify_confluence(symbol: str, direction: str, aligned_timeframes: list,
                      entry: float, stop_loss: float, take_profits: list) -> bool:
    """
    Send notification when multiple timeframes align

    Args:
        symbol: Trading pair
        direction: 'long' or 'short'
        aligned_timeframes: List of aligned timeframe strings
        entry: Entry price
        stop_loss: Stop loss price
        take_profits: List of take profit prices

    Returns:
        True if successful
    """
    topic = Setting.get('ntfy_topic', Config.NTFY_TOPIC)
    priority = 5  # Urgent for high confluence

    direction_emoji = "🟢" if direction == 'long' else "🔴"
    direction_text = "LONG" if direction == 'long' else "SHORT"

    confluence = len(aligned_timeframes)
    tfs = ", ".join(aligned_timeframes)

    title = f"🎯 HIGH CONFLUENCE: {symbol} {direction_text}"

    sl_pct = abs((stop_loss - entry) / entry * 100)

    message = (
        f"⚡ {confluence}/6 Timeframes Aligned!\n"
        f"TFs: {tfs}\n\n"
        f"📍 Entry: ${entry:,.2f}\n"
        f"🛑 SL: ${stop_loss:,.2f} ({sl_pct:.2f}%)\n"
    )

    for i, tp in enumerate(take_profits[:3], 1):
        tp_pct = abs((tp - entry) / entry * 100)
        message += f"✅ TP{i}: ${tp:,.2f} ({tp_pct:.2f}%)\n"

    return send_notification(
        topic=topic,
        title=title,
        message=message,
        priority=priority,
        tags="rotating_light,chart,fire"
    )
