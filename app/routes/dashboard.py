"""
Dashboard routes for the main application interface.

Provides the main dashboard with symbol/timeframe matrix and analytics views.
"""
from flask import Blueprint, render_template
from app.models import Symbol, Pattern, Signal, Candle, SUBSCRIPTION_TIERS
from app.config import Config
from app.services.patterns import PATTERN_TYPES
from app.decorators import login_required, feature_required, get_current_user, get_effective_tier, filter_symbols_by_tier
from app import db
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from collections import defaultdict


def get_allowed_pattern_types(user):
    """Get pattern types allowed for user's tier."""
    tier = get_effective_tier(user)
    # None means full admin access - all patterns allowed
    if tier is None:
        return None
    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS['free'])
    allowed = tier_config.get('pattern_types')
    if allowed is None:
        return None  # All types allowed
    return allowed


def build_pattern_matrix(symbols, timeframes, allowed_pattern_types=None):
    """
    Build the pattern matrix with a single optimized query.

    Instead of N*M queries (symbols × timeframes), fetches all patterns in one query
    and builds the matrix in Python.

    Args:
        symbols: List of Symbol objects to include
        timeframes: List of timeframe strings
        allowed_pattern_types: Optional list of pattern types to filter by

    Returns:
        dict: Matrix mapping symbol -> timeframe -> pattern data
    """
    symbol_ids = [s.id for s in symbols]
    symbol_map = {s.id: s.symbol for s in symbols}

    # Initialize empty matrix
    matrix = {s.symbol: {tf: None for tf in timeframes} for s in symbols}

    if not symbol_ids:
        return matrix

    # Single query to get all active patterns for allowed symbols
    query = Pattern.query.filter(
        Pattern.symbol_id.in_(symbol_ids),
        Pattern.timeframe.in_(timeframes),
        Pattern.status == 'active'
    )

    # Filter by allowed pattern types if specified
    if allowed_pattern_types:
        query = query.filter(Pattern.pattern_type.in_(allowed_pattern_types))

    # Order by detected_at desc so first pattern per group is most recent
    all_patterns = query.order_by(Pattern.detected_at.desc()).all()

    # Group patterns by (symbol_id, timeframe)
    grouped = defaultdict(list)
    for p in all_patterns:
        key = (p.symbol_id, p.timeframe)
        grouped[key].append(p)

    # Build matrix from grouped results
    for (symbol_id, tf), patterns in grouped.items():
        symbol_name = symbol_map.get(symbol_id)
        if not symbol_name:
            continue

        # Group by pattern type (first occurrence wins due to desc order)
        by_type = {}
        for p in patterns:
            if p.pattern_type not in by_type:
                by_type[p.pattern_type] = p

        matrix[symbol_name][tf] = {
            'patterns': by_type,
            'count': len(patterns),
            'direction': patterns[0].direction,
            'pattern_type': patterns[0].pattern_type,
            'zone_high': patterns[0].zone_high,
            'zone_low': patterns[0].zone_low
        }

    return matrix


dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """
    Main dashboard with symbol/timeframe pattern matrix.

    Displays a grid of symbols vs timeframes showing active patterns,
    filtered by user's subscription tier.
    """
    user = get_current_user()
    all_symbols = Symbol.query.filter_by(is_active=True).all()

    # Filter symbols by user tier (Free: BTC/USDT only, Pro: 5, Premium: unlimited)
    symbols = filter_symbols_by_tier(all_symbols, user)

    # Get allowed pattern types for user tier (Free: FVG only)
    allowed_pattern_types = get_allowed_pattern_types(user)

    timeframes = Config.TIMEFRAMES

    # Build matrix with single optimized query (was 30 queries, now 1)
    matrix = build_pattern_matrix(symbols, timeframes, allowed_pattern_types)

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

    # Bulk fetch symbols and patterns to avoid N+1 queries
    if recent_signals:
        # Get unique IDs
        signal_symbol_ids = list(set(s.symbol_id for s in recent_signals))
        signal_pattern_ids = [s.pattern_id for s in recent_signals if s.pattern_id]

        # Bulk load symbols and patterns
        symbols_map = {s.id: s for s in Symbol.query.filter(Symbol.id.in_(signal_symbol_ids)).all()}
        patterns_map = {p.id: p for p in Pattern.query.filter(Pattern.id.in_(signal_pattern_ids)).all()} if signal_pattern_ids else {}

        # Enrich signals
        for signal in recent_signals:
            signal.symbol_obj = symbols_map.get(signal.symbol_id)
            signal.pattern_obj = patterns_map.get(signal.pattern_id) if signal.pattern_id else None
    else:
        pass  # No signals to enrich

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
    """
    Performance analytics dashboard.

    Displays aggregate statistics about patterns, signals, and symbol performance.
    Requires Pro or Premium subscription.

    Returns:
        Rendered analytics.html template with stats, pattern breakdowns,
        and top performing symbols.
    """
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

    # Patterns by type (single aggregation query instead of N+1)
    pattern_type_counts = db.session.query(
        Pattern.pattern_type,
        func.count(Pattern.id)
    ).group_by(Pattern.pattern_type).all()
    patterns_by_type = {pt: 0 for pt in PATTERN_TYPES}
    for pt, count in pattern_type_counts:
        if pt in patterns_by_type:
            patterns_by_type[pt] = count

    # Patterns by direction
    bullish_count = Pattern.query.filter_by(direction='bullish', status='active').count()
    bearish_count = Pattern.query.filter_by(direction='bearish', status='active').count()

    # Recent pattern activity (last 24h)
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    recent_patterns = Pattern.query.filter(Pattern.created_at >= day_ago).count()

    # Top performing symbols (single aggregation query instead of N+1)
    top_symbols_query = db.session.query(
        Symbol.symbol,
        func.count(Pattern.id).label('pattern_count')
    ).join(Pattern, Pattern.symbol_id == Symbol.id).filter(
        Symbol.is_active.is_(True),
        Pattern.status == 'active'
    ).group_by(Symbol.id, Symbol.symbol).order_by(
        func.count(Pattern.id).desc()
    ).limit(10).all()
    top_symbols = [{'symbol': s, 'patterns': c} for s, c in top_symbols_query]

    return render_template('analytics.html',
                           stats=stats,
                           patterns_by_type=patterns_by_type,
                           bullish_count=bullish_count,
                           bearish_count=bearish_count,
                           recent_patterns=recent_patterns,
                           top_symbols=top_symbols)
