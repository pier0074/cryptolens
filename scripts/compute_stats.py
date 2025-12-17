#!/usr/bin/env python
"""
Compute and cache database statistics for fast page loads.

Usage:
  python scripts/compute_stats.py              # Compute stats (silent)
  python scripts/compute_stats.py --verbose    # Show detailed output

Options:
  --verbose, -v   Show detailed statistics output

Cron setup (every 5 minutes):
  */5 * * * * cd /path && venv/bin/python scripts/compute_stats.py
"""
import sys
import os
import json
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app import create_app, db
from app.models import Symbol, Candle, Pattern, Signal, StatsCache
from sqlalchemy import func


def compute_stats():
    """Compute all stats and store in cache table.

    Optimized to avoid full table scans:
    - Uses ORDER BY + LIMIT for MIN/MAX (uses indexes)
    - Combines queries where possible
    - Skips expensive verified_at scans (cached separately)
    """
    start_time = time.time()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day_ago_ms = now_ms - (24 * 60 * 60 * 1000)

    symbols = Symbol.query.filter_by(is_active=True).all()
    symbol_ids = [s.id for s in symbols]

    # Query 1: Get candle counts per timeframe (fast with index)
    # This gives us counts AND we can derive 1m count from it
    tf_counts_query = db.session.query(
        Candle.symbol_id,
        Candle.timeframe,
        func.count(Candle.id).label('count')
    ).filter(
        Candle.symbol_id.in_(symbol_ids)
    ).group_by(Candle.symbol_id, Candle.timeframe).all()

    tf_counts_map = {}
    candle_1m_counts = {}
    for row in tf_counts_query:
        if row.symbol_id not in tf_counts_map:
            tf_counts_map[row.symbol_id] = {}
        tf_counts_map[row.symbol_id][row.timeframe] = row.count
        if row.timeframe == '1m':
            candle_1m_counts[row.symbol_id] = row.count

    # Query 2: Get oldest/newest timestamps using efficient ORDER BY + LIMIT
    # Much faster than MIN/MAX aggregate on large tables
    oldest_map = {}
    newest_map = {}
    for sid in symbol_ids:
        # Oldest (uses index: symbol_id, timeframe, timestamp)
        oldest = Candle.query.filter_by(
            symbol_id=sid, timeframe='1m'
        ).order_by(Candle.timestamp.asc()).first()
        if oldest:
            oldest_map[sid] = oldest.timestamp

        # Newest (same index, DESC)
        newest = Candle.query.filter_by(
            symbol_id=sid, timeframe='1m'
        ).order_by(Candle.timestamp.desc()).first()
        if newest:
            newest_map[sid] = newest.timestamp

    # Query 3: Get pattern stats (fast - patterns table is small)
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

    # Query 4: Get signal counts (fast - signals table is small)
    signal_counts_query = db.session.query(
        Signal.symbol_id,
        func.count(Signal.id).label('count')
    ).filter(
        Signal.symbol_id.in_(symbol_ids)
    ).group_by(Signal.symbol_id).all()

    signal_counts_map = {row.symbol_id: row.count for row in signal_counts_query}

    # Query 5: Get latest candle price for each symbol (fast - uses index)
    latest_price_map = {}
    for sid in symbol_ids:
        latest = Candle.query.filter_by(
            symbol_id=sid, timeframe='1m'
        ).order_by(Candle.timestamp.desc()).first()
        if latest:
            latest_price_map[sid] = latest.close

    # Query 6: Get 24h ago price (fast - single row per symbol)
    price_24h_map = {}
    for sid in symbol_ids:
        candle_24h = Candle.query.filter(
            Candle.symbol_id == sid,
            Candle.timeframe == '1m',
            Candle.timestamp <= day_ago_ms
        ).order_by(Candle.timestamp.desc()).first()
        if candle_24h:
            price_24h_map[sid] = candle_24h.close

    # Skip verified_at query - it's expensive and rarely needed
    # Can be computed separately on demand
    last_verified_map = {}

    # Build per-symbol stats
    symbol_stats = []
    for sym in symbols:
        sid = sym.id
        tf_counts = tf_counts_map.get(sid, {})
        pattern_stats = pattern_stats_map.get(sid, {'active': 0, 'filled': 0, 'expired': 0, 'total': 0})

        count_1m = candle_1m_counts.get(sid, 0)
        oldest_ts = oldest_map.get(sid)
        newest_ts = newest_map.get(sid)

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

    # Overall stats - derive from per-symbol stats (already computed, no extra query)
    overall_tf_counts = {}
    for tf_counts in tf_counts_map.values():
        for tf, count in tf_counts.items():
            overall_tf_counts[tf] = overall_tf_counts.get(tf, 0) + count
    total_candles = sum(overall_tf_counts.values())

    # Pattern/signal totals from already-computed maps
    total_patterns_all = sum(ps.get('total', 0) for ps in pattern_stats_map.values())
    total_signals_all = sum(signal_counts_map.values())

    # Database size (MySQL) - fast query
    db_size = 0
    try:
        result = db.session.execute(db.text("""
            SELECT SUM(data_length + index_length) as size
            FROM information_schema.TABLES
            WHERE table_schema = DATABASE()
        """))
        row = result.fetchone()
        if row and row[0]:
            db_size = int(row[0])
    except Exception:
        db_size = 0

    # Skip expensive verified_count scan - use cached value or 0
    # This query alone takes 1s+ and verified_at is rarely used
    verified_count = 0
    verification_pct = 0

    # Find the most recent data timestamp across all symbols
    last_data_update = None
    for stat in symbol_stats:
        if stat['newest_ts'] and (last_data_update is None or stat['newest_ts'] > last_data_update):
            last_data_update = stat['newest_ts']

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
        'last_data_update': last_data_update,
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
    import argparse
    parser = argparse.ArgumentParser(description='Compute and cache database statistics')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Ensure table exists
        db.create_all()
        stats = compute_stats()

        if args.verbose and stats:
            print("\nDetailed Statistics:")
            print(f"  Active symbols: {stats.get('active_symbols', 0)}")
            print(f"  Total candles: {stats.get('total_candles', 0):,}")
            print(f"  Active patterns: {stats.get('active_patterns', 0)}")
            print(f"  Active signals: {stats.get('active_signals', 0)}")


if __name__ == '__main__':
    main()
