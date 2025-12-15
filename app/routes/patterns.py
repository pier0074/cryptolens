"""
Pattern routes for viewing and analyzing detected patterns.

Provides paginated pattern list with filtering and chart data for visualization.
"""
from flask import Blueprint, render_template, request, jsonify
import json
from app.models import Symbol, Pattern, Candle, StatsCache
from app.config import Config
from app import db
from app.decorators import feature_required, login_required, limit_query_results, get_current_user, check_feature_limit, filter_symbols_by_tier


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
    """
    Pattern list page with filtering and pagination.

    Displays all detected patterns with support for filtering by symbol,
    timeframe, and status. Results are paginated and limited by user tier.

    Query Parameters:
        symbol: Filter by symbol name (e.g., 'BTC/USDT')
        timeframe: Filter by timeframe (e.g., '1h', '4h')
        status: Filter by pattern status ('active', 'filled', 'expired')
        page: Page number for pagination

    Returns:
        Rendered patterns.html template with filtered, paginated patterns.
    """
    user = get_current_user()
    symbol_filter = request.args.get('symbol', None)
    timeframe_filter = request.args.get('timeframe', None)
    status_filter = request.args.get('status', 'active')
    page = request.args.get('page', 1, type=int)

    # Get symbols filtered by tier (Pro: 5, Premium: all)
    all_symbols = Symbol.query.filter_by(is_active=True).all()
    allowed_symbols = filter_symbols_by_tier(all_symbols, user)
    allowed_symbol_ids = [s.id for s in allowed_symbols]

    query = Pattern.query

    # Filter patterns to only allowed symbols
    if allowed_symbol_ids:
        query = query.filter(Pattern.symbol_id.in_(allowed_symbol_ids))

    if symbol_filter:
        symbol = Symbol.query.filter_by(symbol=symbol_filter).first()
        if symbol and symbol.id in allowed_symbol_ids:
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
        orig_pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # Cap the total to the tier limit for display (create wrapper since properties are read-only)
        actual_total = min(orig_pagination.total, patterns_limit)

        # Ensure we don't exceed the tier limit
        total_offset = (page - 1) * per_page
        if total_offset >= patterns_limit:
            patterns = []
        else:
            remaining = patterns_limit - total_offset
            patterns = orig_pagination.items[:remaining]

        # Create a simple wrapper with capped values for template
        class PaginationWrapper:
            def __init__(self, orig, total, pages):
                self._orig = orig
                self.total = total
                self.pages = pages
                self.page = orig.page
                self.per_page = orig.per_page
                self.has_prev = orig.has_prev
                self.has_next = page < pages
                self.prev_num = orig.prev_num
                self.next_num = orig.next_num if page < pages else None

            def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
                last = 0
                for num in range(1, self.pages + 1):
                    if num <= left_edge or \
                       (self.page - left_current <= num <= self.page + right_current) or \
                       num > self.pages - right_edge:
                        if last + 1 != num:
                            yield None
                        yield num
                        last = num

        pagination = PaginationWrapper(orig_pagination, actual_total, max_pages)
    else:
        # Unlimited - normal pagination
        pagination = query.paginate(page=page, per_page=PATTERNS_PER_PAGE, error_out=False)
        patterns = pagination.items
    symbols = allowed_symbols  # Only show allowed symbols in dropdown

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
    """
    Get chart data with patterns for a specific symbol/timeframe.

    Returns OHLC candle data and active patterns for charting.
    Supports lazy loading via 'before' parameter for infinite scroll.

    Args:
        symbol: Trading pair (e.g., 'BTC-USDT' or 'BTC/USDT')
        timeframe: Candle timeframe (e.g., '1h', '4h', '1d')

    Query Parameters:
        before: Unix timestamp in ms - fetch candles before this time (lazy loading)
        limit: Number of candles to return (default varies by timeframe, max 2000)

    Returns:
        JSON with 'candles' (OHLC data), 'patterns' (active zones),
        and 'has_more' (boolean for lazy loading indicator)
    """
    sym = Symbol.query.filter_by(symbol=symbol.replace('-', '/')).first()
    if not sym:
        return jsonify({'error': 'Symbol not found'}), 404

    # Adjust candle limit based on timeframe
    default_limits = {
        '1m': 500,
        '5m': 400,
        '15m': 300,
        '1h': 250,
        '4h': 200,
        '1d': 150,
        '1w': 100
    }
    limit = request.args.get('limit', type=int) or default_limits.get(timeframe, 200)
    limit = min(max(limit, 1), 2000)  # Bound limit between 1 and 2000
    before = request.args.get('before', type=int)  # Timestamp in ms

    # Build query
    query = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    )

    # If 'before' specified, fetch older candles (for lazy loading)
    if before:
        query = query.filter(Candle.timestamp < before)

    candles = query.order_by(Candle.timestamp.desc()).limit(limit).all()

    # Get active patterns (only on initial load, not for lazy loading)
    patterns = []
    if not before:
        patterns = Pattern.query.filter_by(
            symbol_id=sym.id,
            timeframe=timeframe,
            status='active'
        ).all()

    # Check if there's more data available (for lazy loading indicator)
    has_more = False
    if candles:
        oldest_ts = candles[-1].timestamp
        has_more = Candle.query.filter(
            Candle.symbol_id == sym.id,
            Candle.timeframe == timeframe,
            Candle.timestamp < oldest_ts
        ).first() is not None

    return jsonify({
        'candles': [c.to_dict() for c in reversed(candles)],
        'patterns': [p.to_dict() for p in patterns],
        'has_more': has_more
    })
