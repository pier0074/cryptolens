"""
Statistics Routes
Database statistics and analytics per symbol - Optimized with caching
"""
from flask import Blueprint, render_template, current_app
from app.models import Symbol, Candle, Pattern, Signal
from app import db
from sqlalchemy import func, and_
from datetime import datetime, timezone
import os
import time

stats_bp = Blueprint('stats', __name__)

# Simple in-memory cache
_stats_cache = {'data': None, 'timestamp': 0}
CACHE_TTL = 60  # Cache for 60 seconds


def _build_stats():
    """Build stats data (cached)"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    symbol_ids = [s.id for s in symbols]
    symbol_map = {s.id: s for s in symbols}

    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    day_ago_ts = now_ts - (24 * 60 * 60 * 1000)

    # Batch query 1: Get 1m candle counts and time range (fast - uses index)
    candle_stats_query = db.session.query(
        Candle.symbol_id,
        func.count(Candle.id).label('count'),
        func.min(Candle.timestamp).label('oldest'),
        func.max(Candle.timestamp).label('newest')
    ).filter(
        Candle.symbol_id.in_(symbol_ids),
        Candle.timeframe == '1m'
    ).group_by(Candle.symbol_id).all()

    candle_stats_map = {row.symbol_id: row for row in candle_stats_query}

    # Batch query 2: Get candle counts per timeframe for all symbols
    tf_counts_query = db.session.query(
        Candle.symbol_id,
        Candle.timeframe,
        func.count(Candle.id).label('count')
    ).filter(
        Candle.symbol_id.in_(symbol_ids)
    ).group_by(Candle.symbol_id, Candle.timeframe).all()

    tf_counts_map = {}
    for row in tf_counts_query:
        if row.symbol_id not in tf_counts_map:
            tf_counts_map[row.symbol_id] = {}
        tf_counts_map[row.symbol_id][row.timeframe] = row.count

    # Batch query 3: Get pattern stats for all symbols
    pattern_stats_query = db.session.query(
        Pattern.symbol_id,
        Pattern.status,
        func.count(Pattern.id).label('count')
    ).filter(
        Pattern.symbol_id.in_(symbol_ids)
    ).group_by(Pattern.symbol_id, Pattern.status).all()

    pattern_stats_map = {}
    for row in pattern_stats_query:
        if row.symbol_id not in pattern_stats_map:
            pattern_stats_map[row.symbol_id] = {'active': 0, 'filled': 0, 'expired': 0, 'total': 0}
        pattern_stats_map[row.symbol_id][row.status] = row.count
        pattern_stats_map[row.symbol_id]['total'] += row.count

    # Batch query 4: Get signal counts for all symbols
    signal_counts_query = db.session.query(
        Signal.symbol_id,
        func.count(Signal.id).label('count')
    ).filter(
        Signal.symbol_id.in_(symbol_ids)
    ).group_by(Signal.symbol_id).all()

    signal_counts_map = {row.symbol_id: row.count for row in signal_counts_query}

    # Batch query 5: Get latest candle for each symbol (subquery approach)
    latest_subq = db.session.query(
        Candle.symbol_id,
        func.max(Candle.timestamp).label('max_ts')
    ).filter(
        Candle.symbol_id.in_(symbol_ids),
        Candle.timeframe == '1m'
    ).group_by(Candle.symbol_id).subquery()

    latest_candles = db.session.query(Candle).join(
        latest_subq,
        and_(
            Candle.symbol_id == latest_subq.c.symbol_id,
            Candle.timestamp == latest_subq.c.max_ts,
            Candle.timeframe == '1m'
        )
    ).all()

    latest_price_map = {c.symbol_id: c.close for c in latest_candles}

    # Batch query 6: Get 24h ago candles for price change calculation
    candles_24h_subq = db.session.query(
        Candle.symbol_id,
        func.max(Candle.timestamp).label('max_ts')
    ).filter(
        Candle.symbol_id.in_(symbol_ids),
        Candle.timeframe == '1m',
        Candle.timestamp <= day_ago_ts
    ).group_by(Candle.symbol_id).subquery()

    candles_24h = db.session.query(Candle).join(
        candles_24h_subq,
        and_(
            Candle.symbol_id == candles_24h_subq.c.symbol_id,
            Candle.timestamp == candles_24h_subq.c.max_ts,
            Candle.timeframe == '1m'
        )
    ).all()

    price_24h_map = {c.symbol_id: c.close for c in candles_24h}

    # Build results
    symbol_stats = []
    for sym in symbols:
        sid = sym.id
        stats = candle_stats_map.get(sid)
        tf_counts = tf_counts_map.get(sid, {})
        pattern_stats = pattern_stats_map.get(sid, {'active': 0, 'filled': 0, 'expired': 0, 'total': 0})

        count_1m = stats.count if stats else 0
        oldest_ts = stats.oldest if stats else None
        newest_ts = stats.newest if stats else None

        current_price = latest_price_map.get(sid)
        price_24h_ago = price_24h_map.get(sid)

        # Calculate data freshness
        if newest_ts:
            age_minutes = (now_ts - newest_ts) // 60000
            if age_minutes < 5:
                freshness = 'live'
            elif age_minutes < 60:
                freshness = 'recent'
            elif age_minutes < 1440:
                freshness = 'stale'
            else:
                freshness = 'old'
        else:
            freshness = 'none'
            age_minutes = None

        # Calculate price change (24h)
        price_change_24h = None
        if current_price and price_24h_ago:
            price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100

        # Ensure all timeframes have a count (even if 0)
        for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
            if tf not in tf_counts:
                tf_counts[tf] = 0

        symbol_stats.append({
            'symbol': sym.symbol,
            'is_active': sym.is_active,
            'candles_1m': count_1m,
            'candles_by_tf': tf_counts,
            'oldest_ts': oldest_ts,
            'newest_ts': newest_ts,
            'oldest_date': datetime.fromtimestamp(oldest_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if oldest_ts else None,
            'newest_date': datetime.fromtimestamp(newest_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if newest_ts else None,
            'current_price': current_price,
            'price_change_24h': price_change_24h,
            'active_patterns': pattern_stats.get('active', 0),
            'total_patterns': pattern_stats.get('total', 0),
            'filled_patterns': pattern_stats.get('filled', 0),
            'expired_patterns': pattern_stats.get('expired', 0),
            'total_signals': signal_counts_map.get(sid, 0),
            'freshness': freshness,
            'age_minutes': age_minutes
        })

    # Overall database stats (2 efficient queries)
    overall_counts = db.session.query(
        Candle.timeframe,
        func.count(Candle.id).label('count')
    ).group_by(Candle.timeframe).all()

    overall_tf_counts = {row.timeframe: row.count for row in overall_counts}
    total_candles = sum(overall_tf_counts.values())

    total_patterns_all = Pattern.query.count()
    total_signals_all = Signal.query.count()

    # Database file size
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'cryptolens.db')
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    return {
        'symbol_stats': symbol_stats,
        'total_candles': total_candles,
        'total_patterns': total_patterns_all,
        'total_signals': total_signals_all,
        'overall_tf_counts': overall_tf_counts,
        'db_size': db_size,
        'symbols_count': len(symbols)
    }


@stats_bp.route('/')
def index():
    """Database statistics page - Cached for performance"""
    global _stats_cache

    # Skip caching in test mode
    if current_app.config.get('TESTING'):
        data = _build_stats()
        return render_template('stats.html', **data)

    now = time.time()
    if _stats_cache['data'] is None or (now - _stats_cache['timestamp']) > CACHE_TTL:
        _stats_cache['data'] = _build_stats()
        _stats_cache['timestamp'] = now

    data = _stats_cache['data']
    return render_template('stats.html', **data)
