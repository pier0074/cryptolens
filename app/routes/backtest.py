from flask import Blueprint, render_template, request, jsonify
from app.models import Symbol, Backtest
from app.config import Config
from app import db

backtest_bp = Blueprint('backtest', __name__)


@backtest_bp.route('/')
def index():
    """Backtest interface"""
    symbols = Symbol.query.filter_by(is_active=True).all()
    backtests = Backtest.query.order_by(Backtest.created_at.desc()).limit(20).all()

    return render_template('backtest.html',
                           symbols=symbols,
                           timeframes=Config.TIMEFRAMES,
                           backtests=backtests)


@backtest_bp.route('/run', methods=['POST'])
def run():
    """Run a backtest"""
    data = request.get_json()

    symbol = data.get('symbol')
    timeframe = data.get('timeframe')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    pattern_type = data.get('pattern_type', 'imbalance')

    # Import backtester service
    from app.services.backtester import run_backtest

    result = run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        pattern_type=pattern_type
    )

    return jsonify(result)


@backtest_bp.route('/<int:backtest_id>')
def detail(backtest_id):
    """Backtest detail view"""
    backtest = Backtest.query.get_or_404(backtest_id)
    return render_template('backtest_detail.html', backtest=backtest)
