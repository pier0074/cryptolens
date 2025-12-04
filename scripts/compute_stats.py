#!/usr/bin/env python
"""
Compute and cache database statistics for fast page loads.

Run periodically via cron (e.g., every 5 minutes):
  */5 * * * * cd /path && venv/bin/python scripts/compute_stats.py

Or manually:
  python scripts/compute_stats.py
"""
import sys
import os
import json
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app import create_app, db
from app.models import Symbol, Candle, Pattern, Signal, StatsCache
from sqlalchemy import func, and_


def compute_stats():
    """Compute all stats and store in cache table."""
    start_time = time.time()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day_ago_ms = now_ms - (24 * 60 * 60 * 1000)

    symbols = Symbol.query.filter_by(is_active=True).all()
    symbol_ids = [s.id for s in symbols]
    symbol_map = {s.id: s for s in symbols}

    # Batch query 1: Get 1m candle counts and time range
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

    # Batch query 2: Get candle counts per timeframe
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

    # Batch query 3: Get pattern stats
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

    # Batch query 4: Get signal counts
    signal_counts_query = db.session.query(
        Signal.symbol_id,
        func.count(Signal.id).label('count')
    ).filter(
        Signal.symbol_id.in_(symbol_ids)
    ).group_by(Signal.symbol_id).all()

    signal_counts_map = {row.symbol_id: row.count for row in signal_counts_query}

    # Batch query 5: Get latest candle for each symbol
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

    # Batch query 6: Get 24h ago candles
    candles_24h_subq = db.session.query(
        Candle.symbol_id,
        func.max(Candle.timestamp).label('max_ts')
    ).filter(
        Candle.symbol_id.in_(symbol_ids),
        Candle.timeframe == '1m',
        Candle.timestamp <= day_ago_ms
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

    # Batch query 7: Get last verified timestamp per symbol
    last_verified_query = db.session.query(
        Candle.symbol_id,
        func.max(Candle.timestamp).label('last_verified_ts')
    ).filter(
        Candle.timeframe == '1m',
        Candle.verified_at.isnot(None)
    ).group_by(Candle.symbol_id).all()

    last_verified_map = {row.symbol_id: row.last_verified_ts for row in last_verified_query}

    # Build per-symbol stats
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
            age_minutes = (now_ms - newest_ts) // 60000
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

        # Calculate price change
        price_change_24h = None
        if current_price and price_24h_ago:
            price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100

        # Ensure all timeframes have a count
        for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
            if tf not in tf_counts:
                tf_counts[tf] = 0

        # Verification info
        last_verified_ts = last_verified_map.get(sid)

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
            'age_minutes': age_minutes,
            'last_verified_ts': last_verified_ts,
            'last_verified_date': datetime.fromtimestamp(last_verified_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if last_verified_ts else None,
        })

    # Overall stats
    overall_counts = db.session.query(
        Candle.timeframe,
        func.count(Candle.id).label('count')
    ).group_by(Candle.timeframe).all()

    overall_tf_counts = {row.timeframe: row.count for row in overall_counts}
    total_candles = sum(overall_tf_counts.values())

    total_patterns_all = Pattern.query.count()
    total_signals_all = Signal.query.count()

    # Database file size
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cryptolens.db')
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    # Verification stats
    verified_count = db.session.query(func.count(Candle.id)).filter(
        Candle.verified_at.isnot(None)
    ).scalar() or 0

    verification_pct = (verified_count / total_candles * 100) if total_candles > 0 else 0

    # Build global stats
    global_stats = {
        'symbol_stats': symbol_stats,
        'total_candles': total_candles,
        'total_patterns': total_patterns_all,
        'total_signals': total_signals_all,
        'overall_tf_counts': overall_tf_counts,
        'db_size': db_size,
        'symbols_count': len(symbols),
        'verified_count': verified_count,
        'verification_pct': verification_pct,
        'computed_at': now_ms,
        'computed_at_formatted': datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    }

    # Store in cache
    cache_entry = StatsCache.query.filter_by(key='global').first()
    if cache_entry:
        cache_entry.data = json.dumps(global_stats)
        cache_entry.computed_at = now_ms
    else:
        cache_entry = StatsCache(
            key='global',
            data=json.dumps(global_stats),
            computed_at=now_ms
        )
        db.session.add(cache_entry)

    db.session.commit()

    elapsed = time.time() - start_time
    print(f"Stats computed and cached in {elapsed:.2f}s")
    print(f"  Symbols: {len(symbols)}, Candles: {total_candles:,}, Patterns: {total_patterns_all}, Signals: {total_signals_all}")

    return global_stats


def main():
    app = create_app()
    with app.app_context():
        # Ensure table exists
        db.create_all()
        compute_stats()


if __name__ == '__main__':
    main()
