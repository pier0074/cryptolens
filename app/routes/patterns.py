from flask import Blueprint, render_template, request, jsonify
import json
import pandas as pd
from sqlalchemy import func, and_
from app.models import Symbol, Pattern, Candle, StatsCache
from app.config import Config
from app import db
from app.services.trading import get_trading_levels_for_pattern, calculate_atr


def _get_cached_prices():
    """Get current prices from stats cache (fast)."""
    cache = StatsCache.query.filter_by(key='global').first()
    if cache:
        data = json.loads(cache.data)
        # Build symbol -> price map
        return {stat['symbol']: stat['current_price'] for stat in data.get('symbol_stats', [])}
    return {}

patterns_bp = Blueprint('patterns', __name__)


def get_candles_df(symbol_id: int, timeframe: str, limit: int = 100) -> pd.DataFrame:
    """Get candles as DataFrame for trading calculations"""
    candles = Candle.query.filter_by(
        symbol_id=symbol_id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    if not candles:
        return pd.DataFrame()

    data = [{
        'timestamp': c.timestamp,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'volume': c.volume
    } for c in reversed(candles)]

    return pd.DataFrame(data)


@patterns_bp.route('/')
def index():
    """Pattern list and visualization"""
    symbol_filter = request.args.get('symbol', None)
    timeframe_filter = request.args.get('timeframe', None)
    status_filter = request.args.get('status', 'active')

    query = Pattern.query

    if symbol_filter:
        symbol = Symbol.query.filter_by(symbol=symbol_filter).first()
        if symbol:
            query = query.filter_by(symbol_id=symbol.id)

    if timeframe_filter:
        query = query.filter_by(timeframe=timeframe_filter)

    if status_filter:
        query = query.filter_by(status=status_filter)

    patterns = query.order_by(Pattern.detected_at.desc()).limit(100).all()
    symbols = Symbol.query.filter_by(is_active=True).all()

    # Get current prices from cache (fast - ~1ms instead of ~3s)
    cached_prices = _get_cached_prices()

    # Build symbol_id -> price map
    symbol_map = {s.id: s.symbol for s in symbols}
    current_prices = {}
    for pattern in patterns:
        sym_name = symbol_map.get(pattern.symbol_id) or pattern.symbol.symbol
        current_prices[pattern.symbol_id] = cached_prices.get(sym_name)

    # Calculate trading levels for each pattern
    # Cache candles AND pre-computed ATR/swings by (symbol_id, timeframe)
    patterns_with_levels = []
    candle_cache = {}
    levels_cache = {}  # Cache ATR, swing_high, swing_low per (symbol, tf)

    for pattern in patterns:
        cache_key = (pattern.symbol_id, pattern.timeframe)

        # Get candles (cached)
        if cache_key not in candle_cache:
            candle_cache[cache_key] = get_candles_df(pattern.symbol_id, pattern.timeframe)

        df = candle_cache[cache_key]

        # Get pre-computed ATR/swings (cached per symbol/tf)
        if cache_key not in levels_cache:
            from app.services.trading import calculate_atr, find_swing_high, find_swing_low
            if df is not None and not df.empty:
                levels_cache[cache_key] = {
                    'atr': calculate_atr(df),
                    'swing_high': find_swing_high(df, len(df) - 1),
                    'swing_low': find_swing_low(df, len(df) - 1),
                }
            else:
                levels_cache[cache_key] = {'atr': 0, 'swing_high': None, 'swing_low': None}

        cached_levels = levels_cache[cache_key]

        # Calculate trading levels using cached ATR/swings
        from app.services.trading import calculate_trading_levels
        tl = calculate_trading_levels(
            pattern_type=pattern.pattern_type,
            zone_low=pattern.zone_low,
            zone_high=pattern.zone_high,
            direction=pattern.direction,
            atr=cached_levels['atr'],
            swing_high=cached_levels['swing_high'],
            swing_low=cached_levels['swing_low']
        )

        levels = {
            'entry': tl.entry,
            'stop_loss': tl.stop_loss,
            'take_profit_1': tl.take_profit_1,
            'take_profit_2': tl.take_profit_2,
            'take_profit_3': tl.take_profit_3,
            'risk': tl.risk,
            'risk_reward_1': round(tl.risk_reward_1, 2),
            'risk_reward_2': round(tl.risk_reward_2, 2),
            'risk_reward_3': round(tl.risk_reward_3, 2),
        }

        # Attach levels and current price to pattern object
        pattern.trading_levels = levels
        pattern.current_price = current_prices.get(pattern.symbol_id)
        patterns_with_levels.append(pattern)

    return render_template('patterns.html',
                           patterns=patterns_with_levels,
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
