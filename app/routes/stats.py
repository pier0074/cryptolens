"""
Statistics Routes
Database statistics and analytics per symbol
"""
from flask import Blueprint, render_template
from app.models import Symbol, Candle, Pattern, Signal
from app import db
from sqlalchemy import func
from datetime import datetime, timezone, timedelta

stats_bp = Blueprint('stats', __name__)


@stats_bp.route('/')
def index():
    """Database statistics page"""
    symbols = Symbol.query.filter_by(is_active=True).all()

    # Get stats per symbol
    symbol_stats = []
    for sym in symbols:
        # 1m candle stats
        candle_stats = db.session.query(
            func.count(Candle.id),
            func.min(Candle.timestamp),
            func.max(Candle.timestamp),
            func.min(Candle.low),
            func.max(Candle.high),
            func.avg(Candle.volume)
        ).filter(
            Candle.symbol_id == sym.id,
            Candle.timeframe == '1m'
        ).first()

        count_1m = candle_stats[0] or 0
        oldest_ts = candle_stats[1]
        newest_ts = candle_stats[2]
        all_time_low = candle_stats[3]
        all_time_high = candle_stats[4]
        avg_volume = candle_stats[5] or 0

        # Get latest price
        latest_candle = Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe='1m'
        ).order_by(Candle.timestamp.desc()).first()

        current_price = latest_candle.close if latest_candle else None

        # Candle counts per timeframe
        tf_counts = {}
        for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
            tf_counts[tf] = Candle.query.filter_by(
                symbol_id=sym.id,
                timeframe=tf
            ).count()

        # Pattern stats
        active_patterns = Pattern.query.filter_by(
            symbol_id=sym.id,
            status='active'
        ).count()

        total_patterns = Pattern.query.filter_by(symbol_id=sym.id).count()
        filled_patterns = Pattern.query.filter_by(symbol_id=sym.id, status='filled').count()

        # Signal stats
        total_signals = Signal.query.filter_by(symbol_id=sym.id).count()

        # Calculate data freshness
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
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
        if current_price and oldest_ts:
            day_ago_ts = now_ts - (24 * 60 * 60 * 1000)
            candle_24h_ago = Candle.query.filter(
                Candle.symbol_id == sym.id,
                Candle.timeframe == '1m',
                Candle.timestamp <= day_ago_ts
            ).order_by(Candle.timestamp.desc()).first()

            if candle_24h_ago:
                price_change_24h = ((current_price - candle_24h_ago.close) / candle_24h_ago.close) * 100

        # Distance from ATH/ATL
        ath_distance = None
        atl_distance = None
        if current_price and all_time_high and all_time_low:
            ath_distance = ((all_time_high - current_price) / all_time_high) * 100
            atl_distance = ((current_price - all_time_low) / all_time_low) * 100

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
            'all_time_high': all_time_high,
            'all_time_low': all_time_low,
            'ath_distance': ath_distance,
            'atl_distance': atl_distance,
            'avg_volume': avg_volume,
            'price_change_24h': price_change_24h,
            'active_patterns': active_patterns,
            'total_patterns': total_patterns,
            'filled_patterns': filled_patterns,
            'total_signals': total_signals,
            'freshness': freshness,
            'age_minutes': age_minutes
        })

    # Overall database stats
    total_candles = Candle.query.count()
    total_patterns_all = Pattern.query.count()
    total_signals_all = Signal.query.count()

    # Candles by timeframe (overall)
    overall_tf_counts = {}
    for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
        overall_tf_counts[tf] = Candle.query.filter_by(timeframe=tf).count()

    # Database file size (approximate)
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'cryptolens.db')
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    return render_template('stats.html',
        symbol_stats=symbol_stats,
        total_candles=total_candles,
        total_patterns=total_patterns_all,
        total_signals=total_signals_all,
        overall_tf_counts=overall_tf_counts,
        db_size=db_size,
        symbols_count=len(symbols)
    )
