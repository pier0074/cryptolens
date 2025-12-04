from flask import Blueprint, render_template, request, jsonify
import pandas as pd
from sqlalchemy import func, and_
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

    # Get current prices for all symbols with patterns (batch query)
    symbol_ids = list(set(p.symbol_id for p in patterns))
    current_prices = {}
    if symbol_ids:
        # Get latest 1m candle for each symbol
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

        current_prices = {c.symbol_id: c.close for c in latest_candles}

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
