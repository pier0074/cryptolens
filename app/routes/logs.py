"""
Logs Routes
View and filter system logs (Admin only)
"""
from flask import Blueprint, render_template, request, jsonify
from app.models import Log, LOG_CATEGORIES, LOG_LEVELS, Symbol
from app.services.logger import get_recent_logs, get_log_stats
from app.decorators import admin_required

logs_bp = Blueprint('logs', __name__)


@logs_bp.route('/')
@admin_required
def index():
    """Logs page with filtering"""
    # Get filter parameters
    category = request.args.get('category', '')
    level = request.args.get('level', '')
    symbol = request.args.get('symbol', '')

    # Get symbols for filter dropdown
    symbols = Symbol.query.filter_by(is_active=True).order_by(Symbol.symbol).all()

    # Get stats
    stats = get_log_stats()

    return render_template('logs.html',
                           categories=LOG_CATEGORIES,
                           levels=LOG_LEVELS,
                           symbols=symbols,
                           stats=stats,
                           current_category=category,
                           current_level=level,
                           current_symbol=symbol)


@logs_bp.route('/api/logs')
@admin_required
def api_logs():
    """API endpoint for logs with filtering"""
    category = request.args.get('category', None)
    level = request.args.get('level', None)
    symbol = request.args.get('symbol', None)
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    # Empty string means no filter
    if category == '':
        category = None
    if level == '':
        level = None
    if symbol == '':
        symbol = None

    logs = get_recent_logs(
        limit=limit,
        category=category,
        level=level,
        symbol=symbol,
        offset=offset
    )

    return jsonify({
        'logs': logs,
        'count': len(logs),
        'offset': offset,
        'limit': limit
    })


@logs_bp.route('/api/stats')
@admin_required
def api_stats():
    """API endpoint for log statistics"""
    return jsonify(get_log_stats())
