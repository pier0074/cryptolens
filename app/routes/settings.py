from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.models import Symbol, Setting
from app.config import Config
from app import db

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
                'risk_per_trade', 'default_rr', 'min_confluence']:
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
        symbol_name = data.get('symbol')
        if symbol_name and symbol_name not in [s.symbol for s in Symbol.query.all()]:
            symbol = Symbol(symbol=symbol_name, exchange='kucoin')
            db.session.add(symbol)
            db.session.commit()
            return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'toggle':
        symbol_id = data.get('id')
        symbol = Symbol.query.get(symbol_id)
        if symbol:
            symbol.is_active = not symbol.is_active
            db.session.commit()
            return jsonify({'success': True, 'symbol': symbol.to_dict()})

    elif action == 'delete':
        symbol_id = data.get('id')
        symbol = Symbol.query.get(symbol_id)
        if symbol:
            db.session.delete(symbol)
            db.session.commit()
            return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Invalid action'})


@settings_bp.route('/test-notification', methods=['POST'])
def test_notification():
    """Send a test notification"""
    from app.services.notifier import send_notification

    topic = Setting.get('ntfy_topic', Config.NTFY_TOPIC)
    priority = int(Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)))

    success = send_notification(
        topic=topic,
        title='Test Notification',
        message='CryptoLens notifications are working!',
        priority=priority
    )

    return jsonify({'success': success})
