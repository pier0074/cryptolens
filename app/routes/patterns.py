from flask import Blueprint, render_template, request, jsonify
from app.models import Symbol, Pattern, Candle
from app.config import Config
from app import db

patterns_bp = Blueprint('patterns', __name__)


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

    return render_template('patterns.html',
                           patterns=patterns,
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
