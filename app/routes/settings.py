import re
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.models import Symbol, Setting, UserSymbolPreference
from app.config import Config
from app import db
from app.decorators import login_required, subscription_required, get_current_user
from app.services.auth import hash_api_key
from app.services.logger import log_user

# Valid symbol pattern: BASE/QUOTE format (e.g., BTC/USDT, ETH/BTC)
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$')

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
@login_required
def index():
    """Redirect old settings page to unified profile"""
    return redirect(url_for('auth.profile'))


@settings_bp.route('/save', methods=['POST'])
@login_required
@subscription_required
def save():
    """Save settings"""
    user = get_current_user()
    data = request.form

    # Track changed settings for logging
    changed_settings = []

    # Save each setting (except api_key which needs special handling)
    for key in ['ntfy_topic', 'ntfy_priority', 'scan_interval',
                'risk_per_trade', 'default_rr', 'min_confluence', 'log_level']:
        if key in data:
            old_value = Setting.get(key)
            new_value = data[key]
            if old_value != new_value:
                changed_settings.append(key)
            Setting.set(key, new_value)

    # Handle API key specially - hash it before storing
    if 'api_key' in data and data['api_key'].strip():
        api_key = data['api_key'].strip()
        Setting.set('api_key_hash', hash_api_key(api_key))
        changed_settings.append('api_key')

    # Handle checkbox
    Setting.set('notifications_enabled', 'true' if 'notifications_enabled' in data else 'false')

    if changed_settings:
        log_user(
            f"Settings updated by {user.username}",
            details={'user_id': user.id, 'changed_settings': changed_settings}
        )

    flash('Settings saved successfully!', 'success')
    return redirect(url_for('auth.profile'))


@settings_bp.route('/symbols', methods=['POST'])
@login_required
def manage_symbols():
    """Add or toggle symbols"""
    data = request.get_json()
    action = data.get('action')
    user = get_current_user()

    if action == 'add':
        symbol_name = data.get('symbol', '').strip().upper()

        # Validate symbol format
        if not symbol_name:
            return jsonify({'success': False, 'error': 'Symbol name is required'}), 400

        if not SYMBOL_PATTERN.match(symbol_name):
            return jsonify({'success': False, 'error': 'Invalid symbol format. Use BASE/QUOTE (e.g., BTC/USDT)'}), 400

        # Check if symbol already exists
        existing = Symbol.query.filter_by(symbol=symbol_name).first()
        if existing:
            if not existing.is_active:
                # Reactivate inactive symbol
                existing.is_active = True
                db.session.commit()
                return jsonify({'success': True, 'symbol': existing.to_dict(), 'reactivated': True})
            else:
                return jsonify({'success': False, 'error': 'Symbol already active'}), 400

        symbol = Symbol(symbol=symbol_name, exchange='binance')
        db.session.add(symbol)
        db.session.commit()
        log_user(f"Symbol added: {symbol_name}", details={'user_id': user.id, 'symbol': symbol_name})
        return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'toggle':
        symbol_id = data.get('id')
        symbol = db.session.get(Symbol, symbol_id)
        if symbol:
            symbol.is_active = not symbol.is_active
            db.session.commit()
            return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'toggle_notify':
        # User-specific notification preference (Premium/Admin only)
        symbol_id = data.get('id')
        symbol = db.session.get(Symbol, symbol_id)
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol not found'}), 404

        # Check user has premium access
        if not user.is_admin and user.subscription_tier != 'premium':
            return jsonify({'success': False, 'error': 'Premium required for mute/notify'}), 403

        # Toggle user-specific preference
        new_state = UserSymbolPreference.toggle_notify(user.id, symbol_id)
        return jsonify({
            'success': True,
            'symbol_id': symbol_id,
            'notify_enabled': new_state,
            'user_specific': True
        })

    elif action == 'delete':
        # Soft delete: just deactivate the symbol to preserve candle data
        symbol_id = data.get('id')
        symbol = db.session.get(Symbol, symbol_id)
        if symbol:
            symbol.is_active = False
            db.session.commit()
            return jsonify({'success': True, 'message': 'Symbol deactivated (candles preserved)'})

    return jsonify({'success': False, 'error': 'Invalid action'})


@settings_bp.route('/test-notification', methods=['POST'])
@login_required
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
