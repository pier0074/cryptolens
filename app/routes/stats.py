"""
Statistics Routes
Database statistics with pre-computed cache for instant page loads.
"""
from flask import Blueprint, render_template, jsonify
from app.models import StatsCache
from app.decorators import login_required
import json

stats_bp = Blueprint('stats', __name__)


def _get_cached_stats():
    """Get stats from cache table."""
    cache = StatsCache.query.filter_by(key='global').first()
    if cache:
        return json.loads(cache.data)
    return None


@stats_bp.route('/')
@login_required
def index():
    """Stats page - renders skeleton, data loaded via AJAX."""
    return render_template('stats.html')


@stats_bp.route('/api')
@login_required
def api():
    """JSON API endpoint for stats data."""
    data = _get_cached_stats()
    if data is None:
        return jsonify({
            'error': 'Stats not computed yet. Run: python scripts/compute_stats.py',
            'symbol_stats': [],
            'total_candles': 0,
            'total_patterns': 0,
            'total_signals': 0,
            'overall_tf_counts': {},
            'db_size': 0,
            'symbols_count': 0,
            'verified_count': 0,
            'verification_pct': 0,
        })
    return jsonify(data)
