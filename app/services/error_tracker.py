"""
Self-Hosted Error Tracking Service

A simple, self-hosted alternative to Sentry.
Uses MySQL for storage and existing email service for alerts.
No Docker or external services required.

Usage:
    from app.services.error_tracker import capture_exception, capture_message

    try:
        risky_operation()
    except Exception as e:
        capture_exception(e)

    capture_message("Something noteworthy happened", level='warning')
"""
import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from flask import request, has_request_context, session

logger = logging.getLogger('cryptolens.errors')

# Sensitive fields to redact from request data
SENSITIVE_FIELDS = {
    'password', 'password_confirm', 'token', 'api_key', 'secret',
    'credit_card', 'card_number', 'cvv', 'ssn', 'authorization',
    'x-api-key', 'cookie', 'session'
}

# Error types that should trigger email alerts
CRITICAL_ERROR_TYPES = {
    'DatabaseError', 'OperationalError', 'IntegrityError',
    'ConnectionError', 'TimeoutError', 'AuthenticationError',
    'PaymentError', 'SecurityError'
}


def _generate_error_hash(error_type: str, message: str, endpoint: str) -> str:
    """Generate a hash to group similar errors"""
    # Use first line of message to avoid grouping by dynamic data
    first_line = message.split('\n')[0][:200]
    content = f"{error_type}:{endpoint}:{first_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _sanitize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive fields from data"""
    if not data:
        return {}

    sanitized = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
            sanitized[key] = '[REDACTED]'
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_data(value)
        elif isinstance(value, str) and len(value) > 1000:
            sanitized[key] = value[:1000] + '...[truncated]'
        else:
            sanitized[key] = value
    return sanitized


def _get_request_context() -> Dict[str, Any]:
    """Extract context from current request"""
    context = {
        'endpoint': None,
        'method': None,
        'url': None,
        'ip_address': None,
        'user_id': None,
        'headers': {},
        'data': {}
    }

    if not has_request_context():
        return context

    try:
        context['endpoint'] = request.endpoint
        context['method'] = request.method
        context['url'] = request.url[:500] if request.url else None
        context['ip_address'] = request.remote_addr

        # Get user ID from session
        context['user_id'] = session.get('user_id')

        # Sanitize headers
        headers = dict(request.headers)
        context['headers'] = _sanitize_data(headers)

        # Sanitize request data
        if request.is_json:
            context['data'] = _sanitize_data(request.get_json(silent=True) or {})
        elif request.form:
            context['data'] = _sanitize_data(dict(request.form))
        elif request.args:
            context['data'] = _sanitize_data(dict(request.args))

    except Exception as e:
        logger.warning(f"Failed to extract request context: {e}")

    return context


def capture_exception(
    exception: Exception,
    extra: Optional[Dict[str, Any]] = None,
    send_alert: bool = True
) -> Optional[int]:
    """
    Capture and store an exception.

    Args:
        exception: The exception to capture
        extra: Additional context data
        send_alert: Whether to send email alert for critical errors

    Returns:
        Error log ID if stored successfully, None otherwise
    """
    from flask import current_app
    from app import db
    from app.models.errors import ErrorLog

    try:
        error_type = type(exception).__name__
        message = str(exception)
        tb = ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))

        # Get request context
        context = _get_request_context()

        # Generate hash for grouping
        error_hash = _generate_error_hash(error_type, message, context['endpoint'] or 'unknown')

        # Check if we've seen this error recently (within 1 hour)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        existing = ErrorLog.query.filter(
            ErrorLog.error_hash == error_hash,
            ErrorLog.last_seen > one_hour_ago
        ).first()

        if existing:
            # Update occurrence count
            existing.occurrence_count += 1
            existing.last_seen = datetime.now(timezone.utc)
            db.session.commit()
            error_id = existing.id
            is_new = False
        else:
            # Create new error log
            error_log = ErrorLog(
                error_hash=error_hash,
                error_type=error_type,
                message=message[:2000],  # Limit message size
                traceback=tb[:10000],  # Limit traceback size
                endpoint=context['endpoint'],
                method=context['method'],
                url=context['url'],
                user_id=context['user_id'],
                ip_address=context['ip_address'],
                request_headers=json.dumps(context['headers'])[:5000],
                request_data=json.dumps(context['data'])[:5000],
                environment=os.getenv('FLASK_ENV', 'production'),
                server_name=os.getenv('SERVER_NAME', 'cryptolens'),
                python_version=sys.version.split()[0],
                app_version=os.getenv('APP_VERSION', '1.0.0'),
            )
            db.session.add(error_log)
            db.session.commit()
            error_id = error_log.id
            is_new = True

        # Log to console/file
        logger.error(f"[{error_type}] {message} (Error #{error_id})")

        # Send email alert for critical errors (new ones only)
        if send_alert and is_new and _is_critical_error(error_type):
            _send_error_alert(error_id, error_type, message, context)

        return error_id

    except Exception as e:
        # Don't let error tracking errors crash the app
        logger.exception(f"Failed to capture exception: {e}")
        return None


def capture_message(
    message: str,
    level: str = 'info',
    extra: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """
    Capture a message (not an exception).

    Args:
        message: The message to capture
        level: Log level ('debug', 'info', 'warning', 'error', 'critical')
        extra: Additional context data

    Returns:
        Error log ID if stored, None otherwise
    """
    if level not in ('warning', 'error', 'critical'):
        # Only store warnings and above
        logger.log(getattr(logging, level.upper()), message)
        return None

    from app import db
    from app.models.errors import ErrorLog

    try:
        context = _get_request_context()
        error_hash = _generate_error_hash('Message', message, context['endpoint'] or 'unknown')

        error_log = ErrorLog(
            error_hash=error_hash,
            error_type=f'Message.{level.capitalize()}',
            message=message[:2000],
            endpoint=context['endpoint'],
            method=context['method'],
            url=context['url'],
            user_id=context['user_id'],
            ip_address=context['ip_address'],
            environment=os.getenv('FLASK_ENV', 'production'),
        )
        db.session.add(error_log)
        db.session.commit()

        return error_log.id

    except Exception as e:
        logger.exception(f"Failed to capture message: {e}")
        return None


def _is_critical_error(error_type: str) -> bool:
    """Check if error type should trigger an alert"""
    return any(critical in error_type for critical in CRITICAL_ERROR_TYPES)


def _send_error_alert(error_id: int, error_type: str, message: str, context: Dict[str, Any]):
    """Send email alert for critical errors"""
    try:
        from app.services.email import send_email
        from app.models import Setting

        # Get admin email from settings
        admin_email = Setting.get('admin_email')
        if not admin_email:
            logger.warning("No admin email configured for error alerts")
            return

        subject = f"[CryptoLens Error] {error_type}"
        body = f"""
A critical error occurred in CryptoLens:

Error ID: #{error_id}
Type: {error_type}
Message: {message[:500]}

Endpoint: {context.get('endpoint', 'N/A')}
Method: {context.get('method', 'N/A')}
URL: {context.get('url', 'N/A')}
User ID: {context.get('user_id', 'N/A')}
IP: {context.get('ip_address', 'N/A')}

Time: {datetime.now(timezone.utc).isoformat()}

View details in the admin panel: /admin/errors/{error_id}
"""
        send_email(admin_email, subject, body)
        logger.info(f"Error alert sent for error #{error_id}")

    except Exception as e:
        logger.warning(f"Failed to send error alert: {e}")


def get_error_stats(days: int = 7) -> Dict[str, Any]:
    """Get error statistics for the dashboard"""
    from app import db
    from app.models.errors import ErrorLog
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # Total errors
        total = ErrorLog.query.filter(ErrorLog.created_at > cutoff).count()

        # Unique errors (by hash)
        unique = db.session.query(func.count(func.distinct(ErrorLog.error_hash))).filter(
            ErrorLog.created_at > cutoff
        ).scalar()

        # Unresolved errors
        unresolved = ErrorLog.query.filter(
            ErrorLog.status.in_(['new', 'acknowledged']),
            ErrorLog.created_at > cutoff
        ).count()

        # Errors by type
        by_type = db.session.query(
            ErrorLog.error_type,
            func.sum(ErrorLog.occurrence_count).label('count')
        ).filter(
            ErrorLog.created_at > cutoff
        ).group_by(ErrorLog.error_type).order_by(func.sum(ErrorLog.occurrence_count).desc()).limit(10).all()

        # Errors by endpoint
        by_endpoint = db.session.query(
            ErrorLog.endpoint,
            func.sum(ErrorLog.occurrence_count).label('count')
        ).filter(
            ErrorLog.created_at > cutoff,
            ErrorLog.endpoint.isnot(None)
        ).group_by(ErrorLog.endpoint).order_by(func.sum(ErrorLog.occurrence_count).desc()).limit(10).all()

        return {
            'total': total,
            'unique': unique,
            'unresolved': unresolved,
            'by_type': [{'type': t, 'count': c} for t, c in by_type],
            'by_endpoint': [{'endpoint': e, 'count': c} for e, c in by_endpoint],
            'period_days': days
        }

    except Exception as e:
        logger.exception(f"Failed to get error stats: {e}")
        return {'error': str(e)}


def cleanup_old_errors(days: int = 30) -> int:
    """
    Count old resolved errors (NO DELETION).

    Error logs are preserved for historical analysis.
    This function only returns a count, it does NOT delete anything.
    """
    from app.models.errors import ErrorLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # Count only - no deletion (data preservation policy)
        old_count = ErrorLog.query.filter(
            ErrorLog.status.in_(['resolved', 'ignored']),
            ErrorLog.created_at < cutoff
        ).count()

        total_count = ErrorLog.query.count()

        logger.info(f"Error log stats: {old_count} old resolved/ignored, {total_count} total (preserved, no deletion)")
        return 0  # Return 0 as nothing is deleted

    except Exception as e:
        logger.exception(f"Failed to count errors: {e}")
        return 0
