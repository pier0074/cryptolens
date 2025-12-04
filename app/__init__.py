import os
import time
from flask import Flask, g, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()


def format_price(value):
    """Smart price formatting based on magnitude.

    Returns formatted price string with appropriate decimal places:
    - < 0.0001: 8 decimals (micro-cap meme coins)
    - < 0.01: 6 decimals (small meme coins)
    - < 1: 4 decimals (altcoins)
    - < 100: 3 decimals (mid-range)
    - < 10000: 2 decimals (BTC, ETH)
    - >= 10000: 0 decimals (large values)
    """
    if value is None:
        return '-'
    try:
        val = float(value)
        if val == 0:
            return '0'
        if val < 0.0001:
            return f'{val:.8f}'
        if val < 0.01:
            return f'{val:.6f}'
        if val < 1:
            return f'{val:.4f}'
        if val < 100:
            return f'{val:.3f}'
        if val < 10000:
            return f'{val:.2f}'
        return f'{val:.0f}'
    except (ValueError, TypeError):
        return '-'


def create_app(config_name=None):
    """Flask application factory"""
    app = Flask(__name__)

    # Load config
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    from app.config import config
    app.config.from_object(config[config_name])

    # Ensure data directory exists
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    os.makedirs(data_dir, exist_ok=True)

    # Fix database path to be absolute
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///data/'):
        db_path = os.path.join(data_dir, 'cryptolens.db')
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)

    # Register custom Jinja2 filters
    app.jinja_env.filters['price'] = format_price

    # Context processor - inject last_update into all templates (from cache)
    @app.context_processor
    def inject_last_update():
        from app.models import StatsCache
        import json
        try:
            cache = StatsCache.query.filter_by(key='global').first()
            if cache:
                data = json.loads(cache.data)
                return {'last_data_update': data.get('last_data_update')}
            return {'last_data_update': None}
        except Exception:
            return {'last_data_update': None}

    # Request timing middleware
    @app.before_request
    def before_request():
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            import sys
            elapsed_ms = (time.time() - g.start_time) * 1000
            # Color code based on response time
            if elapsed_ms < 100:
                color = '\033[92m'  # Green
            elif elapsed_ms < 500:
                color = '\033[93m'  # Yellow
            else:
                color = '\033[91m'  # Red
            reset = '\033[0m'
            # Log with timing (to stderr for immediate display)
            print(f"{color}[{elapsed_ms:7.1f}ms]{reset} {request.method} {request.path}", file=sys.stderr, flush=True)
        return response

    # Register blueprints
    from app.routes.dashboard import dashboard_bp
    from app.routes.patterns import patterns_bp
    from app.routes.signals import signals_bp
    from app.routes.backtest import backtest_bp
    from app.routes.settings import settings_bp
    from app.routes.api import api_bp
    from app.routes.logs import logs_bp
    from app.routes.stats import stats_bp
    from app.routes.portfolio import portfolio_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patterns_bp, url_prefix='/patterns')
    app.register_blueprint(signals_bp, url_prefix='/signals')
    app.register_blueprint(backtest_bp, url_prefix='/backtest')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(logs_bp, url_prefix='/logs')
    app.register_blueprint(stats_bp, url_prefix='/stats')
    app.register_blueprint(portfolio_bp, url_prefix='/portfolio')

    # Exempt API and test endpoints from CSRF
    csrf.exempt(api_bp)
    csrf.exempt(settings_bp)

    # Create database tables and enable WAL mode for better concurrency
    with app.app_context():
        db.create_all()
        # Enable WAL mode - allows concurrent reads/writes
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            db.session.execute(db.text('PRAGMA journal_mode=WAL'))
            db.session.commit()

    return app
