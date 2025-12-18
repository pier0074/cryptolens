import os
import time
import uuid
import logging
import warnings
from datetime import timedelta
from flask import Flask, g, request

# Suppress flask-limiter in-memory storage warning (fine for development)
warnings.filterwarnings('ignore', message='Using the in-memory storage')
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
cache = Cache()

# Configure logging
class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging in production."""
    def format(self, record):
        import json
        log_data = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        # Add extra fields if present
        if hasattr(record, 'symbol'):
            log_data['symbol'] = record.symbol
        if hasattr(record, 'timeframe'):
            log_data['timeframe'] = record.timeframe
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        return json.dumps(log_data)


def setup_logging(app, db_log_level=None):
    """Configure application logging based on environment or database setting."""
    # Priority: db setting > env var > default
    log_level = db_log_level or os.getenv('LOG_LEVEL', 'INFO')
    log_level = log_level.upper()
    log_format = os.getenv('LOG_FORMAT', 'colored')

    # Map string to logging level
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    level = level_map.get(log_level, logging.INFO)

    # Create logger for the app
    logger = logging.getLogger('cryptolens')
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(level)

    # Create formatter based on format preference
    if log_format == 'json':
        # JSON format for production log aggregation
        formatter = JSONFormatter(datefmt='%Y-%m-%dT%H:%M:%S')
    else:
        # Simple format for development
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Store logger on app for easy access
    app.logger_cryptolens = logger

    return logger


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

    # Error tracking is enabled by default using built-in tracker
    # No external services required - uses MySQL for storage
    app.config['ERROR_TRACKING_ENABLED'] = os.getenv('ERROR_TRACKING_ENABLED', 'true').lower() == 'true'
    if app.config['ERROR_TRACKING_ENABLED']:
        logging.getLogger('cryptolens').info("Logging system active")

    # Session security configuration
    # Secure cookies in production (HTTPS), always HttpOnly, SameSite=Lax
    app.config.update(
        SESSION_COOKIE_SECURE=not app.debug,  # True in production (HTTPS only)
        SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript access to session cookie
        SESSION_COOKIE_SAMESITE='Lax',  # Prevent CSRF via cross-site requests
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # Session expires after 7 days
        SESSION_REFRESH_EACH_REQUEST=True,  # Refresh session on each request
    )

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    cache.init_app(app)

    # Register custom Jinja2 filters
    app.jinja_env.filters['price'] = format_price

    # Context processor - inject last_update into all templates (cached)
    @app.context_processor
    def inject_last_update():
        # Use Flask-Caching to avoid DB query on every request
        cached_value = cache.get('last_data_update')
        if cached_value is not None:
            return {'last_data_update': cached_value}

        # Cache miss - fetch from DB and cache for 60 seconds
        from app.models import StatsCache
        import json
        try:
            stats_cache = StatsCache.query.filter_by(key='global').first()
            if stats_cache:
                data = json.loads(stats_cache.data)
                last_update = data.get('last_data_update')
                cache.set('last_data_update', last_update, timeout=60)
                return {'last_data_update': last_update}
            cache.set('last_data_update', None, timeout=60)
            return {'last_data_update': None}
        except Exception as e:
            logging.getLogger('cryptolens').debug(f"Failed to get last_data_update: {e}")
            return {'last_data_update': None}

    # Request ID and timing middleware
    @app.before_request
    def before_request():
        # Generate unique request ID for tracing
        # Check if client provided one (e.g., from load balancer)
        g.request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())[:8]
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        # Add request ID to response headers for client-side tracing
        request_id = getattr(g, 'request_id', None)
        if request_id:
            response.headers['X-Request-ID'] = request_id

        if hasattr(g, 'start_time'):
            elapsed_ms = (time.time() - g.start_time) * 1000
            elapsed_sec = elapsed_ms / 1000

            # Log with request ID for tracing
            req_id_prefix = f"[{request_id}] " if request_id else ""
            log_msg = f"{req_id_prefix}[{elapsed_ms:7.1f}ms] {request.method} {request.path} -> {response.status_code}"

            # Get the cryptolens logger
            req_logger = logging.getLogger('cryptolens')
            if elapsed_ms < 100:
                req_logger.debug(log_msg)
            elif elapsed_ms < 500:
                req_logger.info(log_msg)
            else:
                req_logger.warning(log_msg)

            # Record Prometheus metrics (skip /metrics endpoint itself)
            if request.path != '/metrics':
                try:
                    from app.routes.metrics import REQUEST_COUNT, REQUEST_LATENCY
                    endpoint = request.endpoint or request.path
                    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed_sec)
                    REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status=response.status_code).inc()
                except Exception as e:
                    logging.getLogger('cryptolens').debug(f"Failed to record metrics: {e}")
        return response

    # Register error handlers for domain exceptions
    from app.exceptions import CryptoLensError

    @app.errorhandler(CryptoLensError)
    def handle_domain_error(error):
        from flask import jsonify, request
        if request.is_json or request.path.startswith('/api/'):
            return jsonify(error.to_dict()), error.status_code
        # For HTML requests, flash and redirect
        from flask import flash, redirect, url_for
        flash(error.message, 'error')
        return redirect(request.referrer or url_for('dashboard.index'))

    @app.errorhandler(404)
    def handle_not_found(error):
        from flask import jsonify, request, render_template
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'Not found', 'message': 'Resource not found'}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        from flask import jsonify, request, render_template
        import logging
        logging.getLogger('cryptolens').error(f"Server error: {error}")

        # Capture error with built-in tracker
        if app.config.get('ERROR_TRACKING_ENABLED'):
            try:
                from app.services.error_tracker import capture_exception
                capture_exception(error)
            except Exception as e:
                logging.getLogger('cryptolens').warning(f"Failed to capture error: {e}")

        if request.is_json or request.path.startswith('/api/'):
            return jsonify({'error': 'Server error', 'message': 'An unexpected error occurred'}), 500
        return render_template('errors/500.html'), 500

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
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.payments import payments_bp
    from app.routes.main import main_bp
    from app.routes.metrics import metrics_bp
    from app.routes.docs import docs_bp

    app.register_blueprint(main_bp)  # Public pages (landing, pricing, etc.)
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')  # Protected dashboard
    app.register_blueprint(patterns_bp, url_prefix='/patterns')
    app.register_blueprint(signals_bp, url_prefix='/signals')
    app.register_blueprint(backtest_bp, url_prefix='/backtest')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(logs_bp, url_prefix='/logs')
    app.register_blueprint(stats_bp, url_prefix='/stats')
    app.register_blueprint(portfolio_bp, url_prefix='/portfolio')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(payments_bp)
    app.register_blueprint(metrics_bp)  # Prometheus metrics at /metrics
    app.register_blueprint(docs_bp, url_prefix='/api')  # API docs at /api/docs

    # Exempt API blueprint from CSRF (uses API key auth for machine-to-machine)
    # Payment webhooks are exempted individually with @csrf.exempt decorator
    csrf.exempt(api_bp)
    csrf.exempt(metrics_bp)  # Metrics endpoint is scraped by Prometheus

    # Security headers for all responses
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # HSTS only in production (requires HTTPS)
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Create database tables
    with app.app_context():
        db.create_all()

        # Setup logging (after DB is ready, so we can read settings)
        from app.models import Setting
        db_log_level = Setting.get('log_level')
        setup_logging(app, db_log_level)

    return app
