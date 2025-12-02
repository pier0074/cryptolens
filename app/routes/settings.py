import re
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.models import Symbol, Setting
from app.config import Config
from app import db

# Valid symbol pattern: BASE/QUOTE format (e.g., BTC/USDT, ETH/BTC)
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$')

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
def index():
    """Settings page"""
    symbols = Symbol.query.all()

    # Get current settings
    settings = {
        'ntfy_topic': Setting.get('ntfy_topic', Config.NTFY_TOPIC),
        'ntfy_priority': Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)),
        'scan_interval': Setting.get('scan_interval', str(Config.SCAN_INTERVAL_MINUTES)),
        'risk_per_trade': Setting.get('risk_per_trade', '1.0'),
        'default_rr': Setting.get('default_rr', '3.0'),
        'min_confluence': Setting.get('min_confluence', '2'),
        'notifications_enabled': Setting.get('notifications_enabled', 'true'),
        'api_key': Setting.get('api_key', ''),
    }

    return render_template('settings.html',
                           symbols=symbols,
                           settings=settings,
                           available_symbols=Config.SYMBOLS)


@settings_bp.route('/save', methods=['POST'])
def save():
    """Save settings"""
    data = request.form

    # Save each setting
    for key in ['ntfy_topic', 'ntfy_priority', 'scan_interval',
                'risk_per_trade', 'default_rr', 'min_confluence', 'api_key']:
        if key in data:
            Setting.set(key, data[key])

    # Handle checkbox
    Setting.set('notifications_enabled', 'true' if 'notifications_enabled' in data else 'false')

    flash('Settings saved successfully!', 'success')
    return redirect(url_for('settings.index'))


@settings_bp.route('/symbols', methods=['POST'])
def manage_symbols():
    """Add or toggle symbols"""
    data = request.get_json()
    action = data.get('action')

    if action == 'add':
        symbol_name = data.get('symbol', '').strip().upper()

        # Validate symbol format
        if not symbol_name:
            return jsonify({'success': False, 'error': 'Symbol name is required'}), 400

        if not SYMBOL_PATTERN.match(symbol_name):
            return jsonify({'success': False, 'error': 'Invalid symbol format. Use BASE/QUOTE (e.g., BTC/USDT)'}), 400

        # Check if symbol already exists
        if symbol_name in [s.symbol for s in Symbol.query.all()]:
            return jsonify({'success': False, 'error': 'Symbol already exists'}), 400

        symbol = Symbol(symbol=symbol_name, exchange='kucoin')
        db.session.add(symbol)
        db.session.commit()
        return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'toggle':
        symbol_id = data.get('id')
        symbol = db.session.get(Symbol, symbol_id)
        if symbol:
            symbol.is_active = not symbol.is_active
            db.session.commit()
            return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'delete':
        symbol_id = data.get('id')
        symbol = db.session.get(Symbol, symbol_id)
        if symbol:
            db.session.delete(symbol)
            db.session.commit()
            return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Invalid action'})


@settings_bp.route('/test-notification', methods=['POST'])
def test_notification():
    """Send 3 varied test notifications to verify all notification types work"""
    from app.services.notifier import send_notification
    from datetime import datetime, timezone
    import random

    topic = Setting.get('ntfy_topic', Config.NTFY_TOPIC)
    priority = int(Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)))

    # Timestamp
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")

    # 3 varied test notifications
    test_signals = [
        {
            'direction': 'long', 'emoji': '🟢', 'symbol': 'BTC/USDT',
            'pattern': 'FVG (Fair Value Gap)', 'abbrev': 'FVG',
            'entry': 97500.0, 'sl': 95000.0, 'tp1': 100000.0,
            'rr': 3.0, 'confluence': 4, 'tfs': '15m, 1h, 4h, 1d'
        },
        {
            'direction': 'short', 'emoji': '🔴', 'symbol': 'ETH/USDT',
            'pattern': 'Order Block', 'abbrev': 'OB',
            'entry': 3800.0, 'sl': 3900.0, 'tp1': 3700.0,
            'rr': 2.5, 'confluence': 3, 'tfs': '1h, 4h, 1d'
        },
        {
            'direction': 'long', 'emoji': '🟢', 'symbol': 'SOL/USDT',
            'pattern': 'Liquidity Sweep', 'abbrev': 'LS',
            'entry': 180.0, 'sl': 172.0, 'tp1': 188.0,
            'rr': 2.0, 'confluence': 5, 'tfs': '5m, 15m, 1h, 4h, 1d'
        }
    ]

    results = []
    for sig in test_signals:
        base = sig['symbol'].split('/')[0]
        sl_pct = abs((sig['sl'] - sig['entry']) / sig['entry'] * 100)
        tp1_pct = abs((sig['tp1'] - sig['entry']) / sig['entry'] * 100)
        rr_pct = sig['rr'] * 100

        title = f"[TEST] {sig['emoji']} {sig['direction'].upper()}: {sig['symbol']}"
        message = (
            f"{timestamp_str}\n"
            f"Symbol: {sig['symbol']}\n"
            f"Direction: {sig['direction'].upper()}\n"
            f"Pattern: {sig['pattern']}\n"
            f"Limit Entry: ${sig['entry']:,.4f}\n"
            f"Stop Loss: ${sig['sl']:,.4f} ({sl_pct:.2f}%)\n"
            f"TP1: ${sig['tp1']:,.4f} ({tp1_pct:.2f}%)\n"
            f"R:R: {sig['rr']:.1f} ({rr_pct:.0f}%)\n"
            f"Confluence: {sig['confluence']}/6 [{sig['tfs']}]"
        )
        tags = f"test,{sig['direction']},{base},{sig['abbrev']}"

        success = send_notification(
            topic=topic, title=title, message=message,
            priority=priority, tags=tags
        )
        results.append(success)

    return jsonify({'success': all(results), 'sent': sum(results)})
