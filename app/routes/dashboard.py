from flask import Blueprint, render_template, jsonify
from app.models import Symbol, Pattern, Signal, Candle, Backtest
from app.config import Config
from app.services.patterns import PATTERN_TYPES
from app.decorators import login_required, tier_required
from sqlalchemy import func
from datetime import datetime, timedelta, timezone

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard with symbol/timeframe matrix"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    timeframes = Config.TIMEFRAMES

    # Build matrix data with ALL pattern types
    matrix = {}
    for symbol in symbols:
        matrix[symbol.symbol] = {}
        for tf in timeframes:
            # Get all active patterns for this symbol/timeframe
            patterns = Pattern.query.filter_by(
                symbol_id=symbol.id,
                timeframe=tf,
                status='active'
            ).order_by(Pattern.detected_at.desc()).all()

            if patterns:
                # Group by pattern type
                by_type = {}
                for p in patterns:
                    if p.pattern_type not in by_type:
                        by_type[p.pattern_type] = p

                matrix[symbol.symbol][tf] = {
                    'patterns': by_type,
                    'count': len(patterns),
                    'direction': patterns[0].direction if patterns else None,
                    'pattern_type': patterns[0].pattern_type if patterns else None,
                    'zone_high': patterns[0].zone_high if patterns else None,
                    'zone_low': patterns[0].zone_low if patterns else None
                }
            else:
                matrix[symbol.symbol][tf] = None

    # Get recent signals
    recent_signals = Signal.query.order_by(Signal.created_at.desc()).limit(10).all()

    # Enrich signals with symbol info
    for signal in recent_signals:
        signal.symbol_obj = Symbol.query.get(signal.symbol_id)

    return render_template('dashboard.html',
                           symbols=symbols,
                           timeframes=timeframes,
                           matrix=matrix,
                           recent_signals=recent_signals,
                           pattern_types=PATTERN_TYPES)


@dashboard_bp.route('/analytics')
@tier_required('premium')
def analytics():
    """Performance analytics dashboard - Premium only"""
    # Get statistics
    stats = {
        'total_symbols': Symbol.query.filter_by(is_active=True).count(),
        'total_candles': Candle.query.count(),
        'total_patterns': Pattern.query.count(),
        'active_patterns': Pattern.query.filter_by(status='active').count(),
        'filled_patterns': Pattern.query.filter_by(status='filled').count(),
        'total_signals': Signal.query.count(),
        'notified_signals': Signal.query.filter_by(status='notified').count(),
    }

    # Patterns by type
    patterns_by_type = {}
    for pt in PATTERN_TYPES:
        patterns_by_type[pt] = Pattern.query.filter_by(pattern_type=pt).count()

    # Patterns by direction
    bullish_count = Pattern.query.filter_by(direction='bullish', status='active').count()
    bearish_count = Pattern.query.filter_by(direction='bearish', status='active').count()

    # Recent pattern activity (last 24h)
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    recent_patterns = Pattern.query.filter(Pattern.created_at >= day_ago).count()

    # Backtest stats
    backtests = Backtest.query.order_by(Backtest.created_at.desc()).limit(10).all()
    avg_win_rate = 0
    if backtests:
        avg_win_rate = sum(b.win_rate for b in backtests) / len(backtests)

    # Top performing symbols (by pattern count)
    top_symbols = []
    symbols = Symbol.query.filter_by(is_active=True).all()
    for s in symbols:
        count = Pattern.query.filter_by(symbol_id=s.id, status='active').count()
        if count > 0:
            top_symbols.append({'symbol': s.symbol, 'patterns': count})
    top_symbols.sort(key=lambda x: x['patterns'], reverse=True)
    top_symbols = top_symbols[:10]

    return render_template('analytics.html',
                           stats=stats,
                           patterns_by_type=patterns_by_type,
                           bullish_count=bullish_count,
                           bearish_count=bearish_count,
                           recent_patterns=recent_patterns,
                           avg_win_rate=avg_win_rate,
                           top_symbols=top_symbols,
                           backtests=backtests)
