from flask import Blueprint, render_template, request, jsonify
import json
from app.models import Symbol, Pattern, Candle, StatsCache
from app.config import Config
from app import db
from app.decorators import feature_required, login_required, limit_query_results, get_current_user, check_feature_limit


def _get_cached_prices():
    """Get current prices from stats cache (fast)."""
    cache = StatsCache.query.filter_by(key='global').first()
    if cache:
        data = json.loads(cache.data)
        return {stat['symbol']: stat['current_price'] for stat in data.get('symbol_stats', [])}
    return {}


patterns_bp = Blueprint('patterns', __name__)

# Pagination settings
PATTERNS_PER_PAGE = 50


@patterns_bp.route('/')
@login_required
@feature_required('patterns_page')
def index():
    """Pattern list and visualization with pagination (Pro+ required)"""
    symbol_filter = request.args.get('symbol', None)
    timeframe_filter = request.args.get('timeframe', None)
    status_filter = request.args.get('status', 'active')
    page = request.args.get('page', 1, type=int)

    query = Pattern.query

    if symbol_filter:
        symbol = Symbol.query.filter_by(symbol=symbol_filter).first()
        if symbol:
            query = query.filter_by(symbol_id=symbol.id)

    if timeframe_filter:
        query = query.filter_by(timeframe=timeframe_filter)

    if status_filter:
        query = query.filter_by(status=status_filter)

    # Get tier-based patterns limit (Pro: 100, Premium: unlimited)
    _, patterns_limit, _ = check_feature_limit('patterns_limit')

    # Apply ordering
    query = query.order_by(Pattern.detected_at.desc())

    # Apply pagination with tier-based limits
    if patterns_limit is not None and patterns_limit > 0:
        # For limited tiers, calculate max pages allowed
        per_page = min(PATTERNS_PER_PAGE, patterns_limit)
        max_pages = (patterns_limit + per_page - 1) // per_page
        # Clamp page to max allowed
        page = min(page, max_pages) if max_pages > 0 else 1

        # Paginate normally but only return items within the limit
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # Ensure we don't exceed the tier limit
        total_offset = (page - 1) * per_page
        if total_offset >= patterns_limit:
            patterns = []
        else:
            remaining = patterns_limit - total_offset
            patterns = pagination.items[:remaining]
    else:
        # Unlimited - normal pagination
        pagination = query.paginate(page=page, per_page=PATTERNS_PER_PAGE, error_out=False)
        patterns = pagination.items
    symbols = Symbol.query.filter_by(is_active=True).all()

    # Get current prices from cache (fast - ~1ms instead of ~3s)
    cached_prices = _get_cached_prices()

    # Build symbol_id -> price map
    symbol_map = {s.id: s.symbol for s in symbols}

    # Attach current price to each pattern (trading_levels already stored in DB)
    for pattern in patterns:
        sym_name = symbol_map.get(pattern.symbol_id) or pattern.symbol.symbol
        pattern.current_price = cached_prices.get(sym_name)

    return render_template('patterns.html',
                           patterns=patterns,
                           pagination=pagination,
                           symbols=symbols,
                           timeframes=Config.TIMEFRAMES,
                           current_symbol=symbol_filter,
                           current_timeframe=timeframe_filter,
                           current_status=status_filter)


@patterns_bp.route('/chart/<symbol>/<timeframe>')
def chart(symbol, timeframe):
    """Get chart data with patterns for a specific symbol/timeframe"""
    sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
    if not sym:
        return jsonify({'error': 'Symbol not found'}), 404

    # Adjust candle limit based on timeframe
    limits = {
        '1m': 500,
        '5m': 400,
        '15m': 300,
        '1h': 250,
        '4h': 200,
        '1d': 150,
        '1w': 100
    }
    limit = limits.get(timeframe, 200)

    # Get candles
    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    # Get active patterns
    patterns = Pattern.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe,
        status='active'
    ).all()

    return jsonify({
        'candles': [c.to_dict() for c in reversed(candles)],
        'patterns': [p.to_dict() for p in patterns]
    })
