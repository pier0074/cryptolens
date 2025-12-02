from flask import Blueprint, render_template, request, jsonify
import pandas as pd
from app.models import Symbol, Pattern, Candle
from app.config import Config
from app import db
from app.services.trading import get_trading_levels_for_pattern, calculate_atr

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

    # Calculate trading levels for each pattern
    patterns_with_levels = []
    candle_cache = {}  # Cache candles by (symbol_id, timeframe)

    for pattern in patterns:
        cache_key = (pattern.symbol_id, pattern.timeframe)

        # Get candles (cached)
        if cache_key not in candle_cache:
            candle_cache[cache_key] = get_candles_df(pattern.symbol_id, pattern.timeframe)

        df = candle_cache[cache_key]

        # Calculate trading levels
        levels = get_trading_levels_for_pattern(pattern, df)

        # Attach levels to pattern object
        pattern.trading_levels = levels
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

    # Get candles
    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(200).all()

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
