from flask import Blueprint, render_template
from app.models import Symbol, Pattern, Signal
from app.config import Config

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    """Main dashboard with symbol/timeframe matrix"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    timeframes = Config.TIMEFRAMES

    # Build matrix data
    matrix = {}
    for symbol in symbols:
        matrix[symbol.symbol] = {}
        for tf in timeframes:
            # Get latest pattern for this symbol/timeframe
            pattern = Pattern.query.filter_by(
                symbol_id=symbol.id,
                timeframe=tf,
                status='active'
            ).order_by(Pattern.detected_at.desc()).first()

            if pattern:
                matrix[symbol.symbol][tf] = {
                    'direction': pattern.direction,
                    'pattern_type': pattern.pattern_type,
                    'zone_high': pattern.zone_high,
                    'zone_low': pattern.zone_low
                }
            else:
                matrix[symbol.symbol][tf] = None

    # Get recent signals
    recent_signals = Signal.query.order_by(Signal.created_at.desc()).limit(10).all()

    return render_template('dashboard.html',
                           symbols=symbols,
                           timeframes=timeframes,
                           matrix=matrix,
                           recent_signals=recent_signals)
