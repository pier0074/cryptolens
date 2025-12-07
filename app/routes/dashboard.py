from flask import Blueprint, render_template, jsonify
from app.models import Symbol, Pattern, Signal, Candle, SUBSCRIPTION_TIERS
from app.config import Config
from app.services.patterns import PATTERN_TYPES
from app.decorators import login_required, feature_required, get_current_user, get_effective_tier, filter_symbols_by_tier
from app import db
from sqlalchemy import func
from datetime import datetime, timedelta, timezone


def get_allowed_pattern_types(user):
    """Get pattern types allowed for user's tier."""
    tier = get_effective_tier(user)
    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS['free'])
    allowed = tier_config.get('pattern_types')
    if allowed is None:
        return None  # All types allowed
    return allowed

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard with symbol/timeframe matrix"""
    user = get_current_user()
    all_symbols = Symbol.query.filter_by(is_active=True).all()

    # Filter symbols by user tier (Free: BTC/USDT only, Pro: 5, Premium: unlimited)
    symbols = filter_symbols_by_tier(all_symbols, user)

    # Get allowed pattern types for user tier (Free: FVG only)
    allowed_pattern_types = get_allowed_pattern_types(user)

    timeframes = Config.TIMEFRAMES

    # Build matrix data with tier-filtered pattern types
    matrix = {}
    for symbol in symbols:
        matrix[symbol.symbol] = {}
        for tf in timeframes:
            # Get all active patterns for this symbol/timeframe
            query = Pattern.query.filter_by(
                symbol_id=symbol.id,
                timeframe=tf,
                status='active'
            )

            # Filter by allowed pattern types for user tier
            if allowed_pattern_types:
                query = query.filter(Pattern.pattern_type.in_(allowed_pattern_types))

            patterns = query.order_by(Pattern.detected_at.desc()).all()

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

    # Get recent signals with tier-based restrictions
    symbol_ids = [s.id for s in symbols]
    tier = get_effective_tier(user)

    # Determine signal limit based on tier
    if tier == 'free':
        # Free: Only 1 recent signal, BTC only
        signal_limit = 1
    elif tier == 'pro':
        # Pro: 5 symbols max, 10 recent signals shown
        signal_limit = 10
    else:
        # Premium/Admin: No limit
        signal_limit = 10  # Still cap UI at 10 for performance

    recent_signals = Signal.query.filter(
        Signal.symbol_id.in_(symbol_ids)
    ).order_by(Signal.created_at.desc()).limit(signal_limit).all()

    # Enrich signals with symbol and pattern info
    for signal in recent_signals:
        signal.symbol_obj = db.session.get(Symbol, signal.symbol_id)
        if signal.pattern_id:
            signal.pattern_obj = db.session.get(Pattern, signal.pattern_id)
        else:
            signal.pattern_obj = None

    # Filter pattern types shown in legend based on tier
    display_pattern_types = allowed_pattern_types if allowed_pattern_types else PATTERN_TYPES

    return render_template('dashboard.html',
                           symbols=symbols,
                           timeframes=timeframes,
                           matrix=matrix,
                           recent_signals=recent_signals,
                           pattern_types=display_pattern_types)


@dashboard_bp.route('/analytics')
@login_required
@feature_required('analytics_page')
def analytics():
    """Performance analytics dashboard - Pro+ required"""
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
                           top_symbols=top_symbols)
