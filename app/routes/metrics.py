"""
Prometheus Metrics Endpoint
Exposes application metrics for monitoring
"""
from flask import Blueprint, Response
from prometheus_client import (
    Counter, Gauge, Histogram, Info,
    generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
)
import time

metrics_bp = Blueprint('metrics', __name__)

# Create a custom registry to avoid conflicts
REGISTRY = CollectorRegistry()

# Application info
APP_INFO = Info('cryptolens', 'CryptoLens application info', registry=REGISTRY)
APP_INFO.info({
    'version': '1.0.0',
    'environment': 'production'
})

# Request metrics
REQUEST_COUNT = Counter(
    'cryptolens_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status'],
    registry=REGISTRY
)

REQUEST_LATENCY = Histogram(
    'cryptolens_http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY
)

# Business metrics
ACTIVE_PATTERNS = Gauge(
    'cryptolens_patterns_active',
    'Number of active patterns',
    ['pattern_type'],
    registry=REGISTRY
)

SIGNALS_TOTAL = Counter(
    'cryptolens_signals_total',
    'Total signals generated',
    ['direction', 'symbol'],
    registry=REGISTRY
)

NOTIFICATIONS_SENT = Counter(
    'cryptolens_notifications_sent_total',
    'Total notifications sent',
    ['status'],  # success, failed
    registry=REGISTRY
)

ACTIVE_USERS = Gauge(
    'cryptolens_users_active',
    'Number of active verified users',
    registry=REGISTRY
)

ACTIVE_SUBSCRIPTIONS = Gauge(
    'cryptolens_subscriptions_active',
    'Number of active subscriptions',
    ['plan'],
    registry=REGISTRY
)

# Database metrics
DB_CONNECTIONS = Gauge(
    'cryptolens_db_connections',
    'Database connection pool status',
    ['status'],  # active, idle
    registry=REGISTRY
)

# Cache metrics
CACHE_HITS = Counter(
    'cryptolens_cache_hits_total',
    'Cache hit count',
    registry=REGISTRY
)

CACHE_MISSES = Counter(
    'cryptolens_cache_misses_total',
    'Cache miss count',
    registry=REGISTRY
)

# Background job metrics
JOB_QUEUE_SIZE = Gauge(
    'cryptolens_job_queue_size',
    'Number of jobs in queue',
    ['queue'],
    registry=REGISTRY
)

JOB_PROCESSING_TIME = Histogram(
    'cryptolens_job_processing_seconds',
    'Job processing time',
    ['job_type'],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY
)


def update_metrics():
    """Update gauge metrics with current values from database"""
    from flask import current_app
    from app.models import Pattern, User, Subscription

    try:
        # Pattern counts by type
        pattern_types = ['imbalance', 'order_block', 'liquidity_sweep']
        for ptype in pattern_types:
            count = Pattern.query.filter_by(status='active', pattern_type=ptype).count()
            ACTIVE_PATTERNS.labels(pattern_type=ptype).set(count)

        # User counts
        active_users = User.query.filter_by(is_active=True, is_verified=True).count()
        ACTIVE_USERS.set(active_users)

        # Subscription counts by plan
        for plan in ['free', 'pro', 'premium']:
            count = Subscription.query.filter_by(status='active', plan=plan).count()
            ACTIVE_SUBSCRIPTIONS.labels(plan=plan).set(count)

        # Try to get job queue stats
        try:
            from app.jobs.queue import get_queue_stats
            stats = get_queue_stats()
            for queue_name, queue_stats in stats.items():
                JOB_QUEUE_SIZE.labels(queue=queue_name).set(queue_stats['count'])
        except Exception:
            pass  # Redis not available

    except Exception as e:
        current_app.logger.warning(f"Failed to update metrics: {e}")


@metrics_bp.route('/metrics')
def metrics():
    """Prometheus metrics endpoint"""
    # Update metrics before serving
    update_metrics()

    # Generate and return metrics
    return Response(
        generate_latest(REGISTRY),
        mimetype=CONTENT_TYPE_LATEST
    )


# Middleware functions to record request metrics
def before_request():
    """Record request start time"""
    from flask import g
    g.start_time = time.time()


def after_request(response):
    """Record request metrics"""
    from flask import g, request

    if hasattr(g, 'start_time'):
        latency = time.time() - g.start_time

        # Get endpoint name, fallback to path
        endpoint = request.endpoint or request.path

        # Record latency
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint
        ).observe(latency)

        # Record request count
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=response.status_code
        ).inc()

    return response


def record_notification_sent(success: bool):
    """Record a notification send attempt"""
    NOTIFICATIONS_SENT.labels(status='success' if success else 'failed').inc()


def record_signal_generated(direction: str, symbol: str):
    """Record a signal generation"""
    SIGNALS_TOTAL.labels(direction=direction, symbol=symbol).inc()


def record_cache_hit():
    """Record a cache hit"""
    CACHE_HITS.inc()


def record_cache_miss():
    """Record a cache miss"""
    CACHE_MISSES.inc()


def record_job_processing_time(job_type: str, duration: float):
    """Record job processing time"""
    JOB_PROCESSING_TIME.labels(job_type=job_type).observe(duration)
