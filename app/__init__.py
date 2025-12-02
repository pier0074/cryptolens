import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()


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

    # Register blueprints
    from app.routes.dashboard import dashboard_bp
    from app.routes.patterns import patterns_bp
    from app.routes.signals import signals_bp
    from app.routes.backtest import backtest_bp
    from app.routes.settings import settings_bp
    from app.routes.api import api_bp
    from app.routes.logs import logs_bp
    from app.routes.stats import stats_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patterns_bp, url_prefix='/patterns')
    app.register_blueprint(signals_bp, url_prefix='/signals')
    app.register_blueprint(backtest_bp, url_prefix='/backtest')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(logs_bp, url_prefix='/logs')
    app.register_blueprint(stats_bp, url_prefix='/stats')

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
