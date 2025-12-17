"""
Admin Routes
User and subscription management for administrators
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from app.routes.auth import admin_required, get_current_user
from app.services.auth import (
    verify_user, deactivate_user, activate_user,
    make_admin, revoke_admin, get_user_by_id, register_user, AuthError
)
from app.services.subscription import (
    extend_subscription, cancel_subscription, suspend_subscription,
    reactivate_subscription, get_subscription_stats, get_expiring_soon,
    SubscriptionError
)
from app.models import User, Subscription, SUBSCRIPTION_PLANS, CronJob, CronRun, CRON_JOB_TYPES, CRON_CATEGORIES
from app import db, limiter
from datetime import datetime, timezone, timedelta

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@admin_required
def index():
    """Admin dashboard"""
    stats = get_subscription_stats()
    return render_template('admin/index.html', stats=stats)


@admin_bp.route('/users')
@admin_required
def users():
    """List all users"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Filters
    status = request.args.get('status', 'all')
    search = request.args.get('search', '')

    query = User.query

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                User.email.ilike(search_term),
                User.username.ilike(search_term)
            )
        )

    if status == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status == 'inactive':
        query = query.filter(User.is_active.is_(False))
    elif status == 'verified':
        query = query.filter(User.is_verified.is_(True))
    elif status == 'unverified':
        query = query.filter(User.is_verified.is_(False))
    elif status == 'admin':
        query = query.filter(User.is_admin.is_(True))
    elif status == 'locked':
        query = query.filter(User.locked_until > datetime.now(timezone.utc).replace(tzinfo=None))

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template('admin/users.html',
                           users=pagination.items,
                           pagination=pagination,
                           status=status,
                           search=search,
                           now=now)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """User detail page"""
    from app.models import UserNotification

    user = get_user_by_id(user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))

    # Get user's subscription
    subscription = user.subscription

    # Get recent notifications for this user
    notifications = UserNotification.query.filter_by(user_id=user_id).order_by(
        UserNotification.sent_at.desc()
    ).limit(10).all()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template('admin/user_detail.html',
                           user=user,
                           subscription=subscription,
                           notifications=notifications,
                           plans=SUBSCRIPTION_PLANS,
                           now=now)


@admin_bp.route('/users/<int:user_id>/verify', methods=['POST'])
@admin_required
def verify_user_route(user_id):
    """Verify a user's email"""
    if verify_user(user_id):
        flash('User verified successfully.', 'success')
    else:
        flash('Failed to verify user.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/activate', methods=['POST'])
@admin_required
def activate_user_route(user_id):
    """Activate a user account"""
    if activate_user(user_id):
        flash('User activated successfully.', 'success')
    else:
        flash('Failed to activate user.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_user_route(user_id):
    """Deactivate a user account"""
    # Prevent self-deactivation
    current = get_current_user()
    if current.id == user_id:
        flash('Cannot deactivate your own account.', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    if deactivate_user(user_id):
        flash('User deactivated successfully.', 'success')
    else:
        flash('Failed to deactivate user.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/unlock', methods=['POST'])
@admin_required
def unlock_user_route(user_id):
    """Unlock a locked user account"""
    user = get_user_by_id(user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))

    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    flash(f'Account unlocked for {user.username}.', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/bulk-action', methods=['POST'])
@limiter.limit("100 per minute")
@admin_required
def bulk_user_action():
    """Perform bulk actions on multiple users"""
    user_ids = request.form.getlist('user_ids', type=int)
    action = request.form.get('action')
    current = get_current_user()

    if not user_ids:
        flash('No users selected.', 'error')
        return redirect(url_for('admin.users'))

    if not action:
        flash('No action selected.', 'error')
        return redirect(url_for('admin.users'))

    success_count = 0
    skip_count = 0

    try:
        for user_id in user_ids:
            # Prevent self-modification for destructive actions
            if user_id == current.id and action in ['deactivate']:
                skip_count += 1
                continue

            user = db.session.get(User, user_id)
            if not user:
                continue

            if action == 'activate':
                user.is_active = True
                success_count += 1
            elif action == 'deactivate':
                user.is_active = False
                success_count += 1
            elif action == 'verify':
                user.is_verified = True
                user.email_verification_token = None
                user.email_verification_expires = None
                success_count += 1
            elif action == 'unlock':
                user.failed_attempts = 0
                user.locked_until = None
                success_count += 1

        db.session.commit()

        if success_count > 0:
            flash(f'Successfully applied {action} to {success_count} user(s).', 'success')
        if skip_count > 0:
            flash(f'Skipped {skip_count} user(s) (cannot modify yourself).', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Bulk operation failed: {str(e)}', 'error')

    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/make-admin', methods=['POST'])
@limiter.limit("60 per minute")
@admin_required
def make_admin_route(user_id):
    """Grant admin privileges"""
    if make_admin(user_id):
        flash('Admin privileges granted.', 'success')
    else:
        flash('Failed to grant admin privileges.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/revoke-admin', methods=['POST'])
@limiter.limit("60 per minute")
@admin_required
def revoke_admin_route(user_id):
    """Revoke admin privileges"""
    # Prevent self-revocation
    current = get_current_user()
    if current.id == user_id:
        flash('Cannot revoke your own admin privileges.', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))

    if revoke_admin(user_id):
        flash('Admin privileges revoked.', 'success')
    else:
        flash('Failed to revoke admin privileges.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/subscription', methods=['POST'])
@limiter.limit("100 per minute")
@admin_required
def modify_subscription(user_id):
    """Modify user subscription"""
    action = request.form.get('action')
    plan = request.form.get('plan', 'monthly')
    custom_days = request.form.get('custom_days')

    # Handle lifetime option
    is_lifetime = custom_days == 'lifetime'
    days_value = None if is_lifetime else (int(custom_days) if custom_days else None)

    try:
        if action == 'create':
            # Create new subscription (cancel existing first)
            cancel_subscription(user_id)
            extend_subscription(user_id, plan, custom_days=days_value, lifetime=is_lifetime)
            duration_msg = 'lifetime' if is_lifetime else f'{days_value or 30} days'
            flash(f'New {plan} subscription created ({duration_msg}).', 'success')
        elif action == 'extend':
            extend_subscription(user_id, plan, custom_days=days_value, lifetime=is_lifetime)
            flash(f'Subscription extended with {plan} plan.', 'success')
        elif action == 'cancel':
            cancel_subscription(user_id)
            flash('Subscription cancelled.', 'success')
        elif action == 'suspend':
            suspend_subscription(user_id)
            flash('Subscription suspended.', 'success')
        elif action == 'reactivate':
            reactivate_subscription(user_id)
            flash('Subscription reactivated.', 'success')
        else:
            flash('Invalid action.', 'error')
    except SubscriptionError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except ValueError as e:
        db.session.rollback()
        flash(f'Invalid custom days value: {e}', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Subscription operation failed: {str(e)}', 'error')

    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@limiter.limit("60 per minute")
@admin_required
def create_user():
    """Create a new user (admin)"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_verified = 'is_verified' in request.form
        is_admin = 'is_admin' in request.form
        plan = request.form.get('plan', 'free')

        try:
            user = register_user(email, username, password, auto_verify=is_verified)

            # Set admin if requested
            if is_admin:
                make_admin(user.id)

            # Upgrade subscription if not free
            if plan != 'free':
                extend_subscription(user.id, plan)

            flash(f'User {username} created successfully.', 'success')
            return redirect(url_for('admin.user_detail', user_id=user.id))

        except (AuthError, SubscriptionError) as e:
            flash(str(e), 'error')

    return render_template('admin/create_user.html', plans=SUBSCRIPTION_PLANS)


@admin_bp.route('/subscriptions')
@admin_required
def subscriptions():
    """List all subscriptions"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Filters
    status = request.args.get('status', 'all')
    plan = request.args.get('plan', 'all')

    query = Subscription.query.join(User)

    if status != 'all':
        query = query.filter(Subscription.status == status)

    if plan != 'all':
        query = query.filter(Subscription.plan == plan)

    query = query.order_by(Subscription.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get subscription stats
    stats = get_subscription_stats()

    return render_template('admin/subscriptions.html',
                           subscriptions=pagination.items,
                           pagination=pagination,
                           status=status,
                           plan=plan,
                           plans=SUBSCRIPTION_PLANS,
                           stats=stats)


@admin_bp.route('/subscriptions/expiring')
@admin_required
def expiring_subscriptions():
    """List subscriptions expiring soon"""
    days = request.args.get('days', 7, type=int)
    expiring = get_expiring_soon(days)

    return render_template('admin/expiring.html',
                           subscriptions=expiring,
                           days=days)


# API endpoints
@admin_bp.route('/api/stats')
@admin_required
def api_stats():
    """Get admin stats as JSON"""
    stats = get_subscription_stats()
    return jsonify(stats)


@admin_bp.route('/api/users/<int:user_id>', methods=['PATCH'])
@admin_required
def api_update_user(user_id):
    """Update user via API"""
    data = request.get_json()
    user = get_user_by_id(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Prevent self-modification of critical fields
    current = get_current_user()

    if 'is_active' in data:
        if current.id == user_id and not data['is_active']:
            return jsonify({'error': 'Cannot deactivate yourself'}), 400
        user.is_active = data['is_active']

    if 'is_verified' in data:
        user.is_verified = data['is_verified']

    if 'is_admin' in data:
        if current.id == user_id and not data['is_admin']:
            return jsonify({'error': 'Cannot revoke your own admin'}), 400
        user.is_admin = data['is_admin']

    db.session.commit()

    return jsonify(user.to_dict())


@admin_bp.route('/set-view-as', methods=['POST'])
@admin_required
def set_view_as():
    """Set the 'view as' tier for testing navigation and access"""
    tier = request.form.get('tier', 'admin')

    if tier not in ['admin', 'free', 'pro', 'premium']:
        flash('Invalid tier selected.', 'error')
        return redirect(url_for('admin.index'))

    if tier == 'admin':
        session.pop('view_as', None)
        flash('Viewing as Admin (full access).', 'success')
    else:
        session['view_as'] = tier
        flash(f'Now viewing as {tier.title()} tier. Navigation restricted accordingly.', 'info')

    return redirect(url_for('admin.index'))


# =============================================================================
# CRON JOB MANAGEMENT
# =============================================================================

def ensure_cron_jobs():
    """Ensure all cron jobs exist in database and clean up old ones"""
    # Clean up old/renamed jobs
    old_jobs = ['scan']  # Old job names to remove
    for old_name in old_jobs:
        old_job = CronJob.query.filter_by(name=old_name).first()
        if old_job:
            # Delete associated runs first
            CronRun.query.filter_by(job_id=old_job.id).delete()
            db.session.delete(old_job)

    # Clean up stuck "running" entries (older than 1 hour without ended_at)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    stuck_runs = CronRun.query.filter(
        CronRun.ended_at.is_(None),
        CronRun.started_at < one_hour_ago
    ).all()
    for run in stuck_runs:
        run.ended_at = datetime.now(timezone.utc)
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        run.duration_ms = int((run.ended_at - started_at).total_seconds() * 1000)
        run.success = False
        run.error_message = 'Marked as failed: exceeded 1 hour timeout'

    # Ensure all current job types exist
    for key, config in CRON_JOB_TYPES.items():
        job = CronJob.query.filter_by(name=key).first()
        if not job:
            job = CronJob(
                name=key,
                description=config['description'],
                schedule=config['schedule'],
                is_enabled=True
            )
            db.session.add(job)
    db.session.commit()


@admin_bp.route('/crons')
@admin_required
def crons():
    """Cron jobs management page"""
    ensure_cron_jobs()
    jobs = CronJob.query.order_by(CronJob.name).all()

    # Group jobs by category
    jobs_by_category = {}
    for job in jobs:
        job_config = CRON_JOB_TYPES.get(job.name, {})
        category = job_config.get('category', 'other')
        if category not in jobs_by_category:
            jobs_by_category[category] = []
        jobs_by_category[category].append(job)

    # Sort categories by order
    sorted_categories = sorted(
        CRON_CATEGORIES.keys(),
        key=lambda c: CRON_CATEGORIES[c].get('order', 99)
    )

    # Get recent runs for history
    recent_runs = CronRun.query.order_by(CronRun.started_at.desc()).limit(50).all()

    # Calculate overall stats
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    total_runs_24h = CronRun.query.filter(CronRun.started_at >= since_24h).count()
    failed_runs_24h = CronRun.query.filter(
        CronRun.started_at >= since_24h,
        CronRun.success.is_(False)
    ).count()

    return render_template('admin/crons.html',
                           jobs=jobs,
                           jobs_by_category=jobs_by_category,
                           sorted_categories=sorted_categories,
                           recent_runs=recent_runs,
                           total_runs_24h=total_runs_24h,
                           failed_runs_24h=failed_runs_24h,
                           cron_types=CRON_JOB_TYPES,
                           cron_categories=CRON_CATEGORIES)


@admin_bp.route('/crons/<int:job_id>/toggle', methods=['POST'])
@admin_required
def toggle_cron(job_id):
    """Toggle cron job enabled status"""
    job = CronJob.query.get_or_404(job_id)
    job.is_enabled = not job.is_enabled
    db.session.commit()

    status = 'enabled' if job.is_enabled else 'disabled'
    flash(f'Cron job "{job.name}" {status}.', 'success')
    return redirect(url_for('admin.crons'))


@admin_bp.route('/crons/<int:job_id>/history')
@admin_required
def cron_history(job_id):
    """Get detailed history for a cron job"""
    job = CronJob.query.get_or_404(job_id)
    page = request.args.get('page', 1, type=int)
    per_page = 50

    runs = job.runs.order_by(CronRun.started_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/cron_history.html',
                           job=job,
                           runs=runs)


@admin_bp.route('/api/crons')
@admin_required
def api_crons():
    """Get cron jobs status as JSON"""
    ensure_cron_jobs()
    jobs = CronJob.query.all()
    return jsonify({
        'jobs': [j.to_dict() for j in jobs]
    })


@admin_bp.route('/api/crons/<int:job_id>/runs')
@admin_required
def api_cron_runs(job_id):
    """Get recent runs for a cron job"""
    job = CronJob.query.get_or_404(job_id)
    limit = request.args.get('limit', 20, type=int)
    runs = job.runs.order_by(CronRun.started_at.desc()).limit(limit).all()
    return jsonify({
        'job': job.to_dict(),
        'runs': [r.to_dict() for r in runs]
    })


# ============================================
# Error Tracking Routes
# ============================================

@admin_bp.route('/errors')
@admin_required
def errors():
    """Error tracking dashboard"""
    from app.models import ErrorLog
    from app.services.error_tracker import get_error_stats

    page = request.args.get('page', 1, type=int)
    per_page = 25
    status = request.args.get('status', 'all')
    error_type = request.args.get('type', '')

    query = ErrorLog.query

    if status == 'new':
        query = query.filter(ErrorLog.status == 'new')
    elif status == 'acknowledged':
        query = query.filter(ErrorLog.status == 'acknowledged')
    elif status == 'resolved':
        query = query.filter(ErrorLog.status == 'resolved')
    elif status == 'unresolved':
        query = query.filter(ErrorLog.status.in_(['new', 'acknowledged']))

    if error_type:
        query = query.filter(ErrorLog.error_type.ilike(f'%{error_type}%'))

    query = query.order_by(ErrorLog.last_seen.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    stats = get_error_stats(days=7)

    return render_template('admin/errors.html',
                           errors=pagination.items,
                           pagination=pagination,
                           stats=stats,
                           status=status,
                           error_type=error_type)


@admin_bp.route('/errors/<int:error_id>')
@admin_required
def error_detail(error_id):
    """Error detail page"""
    from app.models import ErrorLog

    error = ErrorLog.query.get_or_404(error_id)
    return render_template('admin/error_detail.html', error=error)


@admin_bp.route('/errors/<int:error_id>/acknowledge', methods=['POST'])
@admin_required
def acknowledge_error(error_id):
    """Mark error as acknowledged"""
    from app.models import ErrorLog

    error = ErrorLog.query.get_or_404(error_id)
    error.status = 'acknowledged'
    db.session.commit()
    flash('Error acknowledged.', 'success')
    return redirect(url_for('admin.error_detail', error_id=error_id))


@admin_bp.route('/errors/<int:error_id>/resolve', methods=['POST'])
@admin_required
def resolve_error(error_id):
    """Mark error as resolved"""
    from app.models import ErrorLog

    error = ErrorLog.query.get_or_404(error_id)
    error.status = 'resolved'
    error.resolved_at = datetime.now(timezone.utc)
    # Use the authenticated user from decorator; session.get() could theoretically be None
    current_user = get_current_user()
    error.resolved_by = current_user.id if current_user else session.get('user_id')
    error.notes = request.form.get('notes', '')
    db.session.commit()
    flash('Error resolved.', 'success')
    return redirect(url_for('admin.error_detail', error_id=error_id))


@admin_bp.route('/errors/<int:error_id>/ignore', methods=['POST'])
@admin_required
def ignore_error(error_id):
    """Mark error as ignored"""
    from app.models import ErrorLog

    error = ErrorLog.query.get_or_404(error_id)
    error.status = 'ignored'
    db.session.commit()
    flash('Error ignored.', 'info')
    return redirect(url_for('admin.errors'))


@admin_bp.route('/api/errors/stats')
@admin_required
def api_error_stats():
    """Get error statistics as JSON"""
    from app.services.error_tracker import get_error_stats

    days = request.args.get('days', 7, type=int)
    stats = get_error_stats(days=days)
    return jsonify(stats)


# =============================================================================
# NOTIFICATION MANAGEMENT
# =============================================================================

@admin_bp.route('/notifications')
@admin_required
def notifications():
    """Notification management dashboard"""
    from app.models import (
        NotificationTemplate, BroadcastNotification, ScheduledNotification,
        NOTIFICATION_TEMPLATE_TYPES, NOTIFICATION_TARGETS
    )

    # Get recent broadcasts
    recent_broadcasts = BroadcastNotification.query.order_by(
        BroadcastNotification.sent_at.desc()
    ).limit(10).all()

    # Get pending scheduled notifications
    pending_scheduled = ScheduledNotification.query.filter_by(
        status='pending'
    ).order_by(ScheduledNotification.scheduled_for.asc()).all()

    # Get active templates
    templates = NotificationTemplate.query.filter_by(is_active=True).order_by(
        NotificationTemplate.times_used.desc()
    ).all()

    # Stats
    stats = {
        'total_broadcasts': BroadcastNotification.query.count(),
        'total_sent_24h': BroadcastNotification.query.filter(
            BroadcastNotification.sent_at >= datetime.now(timezone.utc) - timedelta(days=1)
        ).count(),
        'pending_scheduled': ScheduledNotification.query.filter_by(status='pending').count(),
        'active_templates': NotificationTemplate.query.filter_by(is_active=True).count(),
    }

    return render_template('admin/notifications.html',
                           recent_broadcasts=recent_broadcasts,
                           pending_scheduled=pending_scheduled,
                           templates=templates,
                           stats=stats,
                           template_types=NOTIFICATION_TEMPLATE_TYPES,
                           targets=NOTIFICATION_TARGETS)


# ----- TEMPLATES -----

@admin_bp.route('/notifications/templates')
@admin_required
def notification_templates():
    """List all notification templates"""
    from app.models import NotificationTemplate, NOTIFICATION_TEMPLATE_TYPES

    templates = NotificationTemplate.query.order_by(
        NotificationTemplate.created_at.desc()
    ).all()

    return render_template('admin/notification_templates.html',
                           templates=templates,
                           template_types=NOTIFICATION_TEMPLATE_TYPES)


@admin_bp.route('/notifications/templates/create', methods=['GET', 'POST'])
@admin_required
def create_template():
    """Create a new notification template"""
    from app.models import NotificationTemplate, NOTIFICATION_TEMPLATE_TYPES

    if request.method == 'POST':
        name = request.form.get('name', '')
        template_type = request.form.get('template_type', '')
        title = request.form.get('title', '')
        message = request.form.get('message', '')
        tags = request.form.get('tags', '')

        # Validate input lengths
        errors = []
        if not name or len(name) > 100:
            errors.append('Name is required and must be less than 100 characters')
        if not template_type or len(template_type) > 20:
            errors.append('Template type is required and must be less than 20 characters')
        if not title or len(title) > 200:
            errors.append('Title is required and must be less than 200 characters')
        if not message or len(message) > 10000:
            errors.append('Message is required and must be less than 10000 characters')
        if tags and len(tags) > 100:
            errors.append('Tags must be less than 100 characters')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('admin/create_template.html',
                                   template_types=NOTIFICATION_TEMPLATE_TYPES)

        current = get_current_user()
        template = NotificationTemplate(
            name=name,
            template_type=template_type,
            title=title,
            message=message,
            priority=int(request.form.get('priority', 3)),
            tags=tags if tags else None,
            created_by=current.id
        )
        db.session.add(template)
        db.session.commit()
        flash(f'Template "{template.name}" created.', 'success')
        return redirect(url_for('admin.notification_templates'))

    return render_template('admin/create_template.html',
                           template_types=NOTIFICATION_TEMPLATE_TYPES)


@admin_bp.route('/notifications/templates/<int:template_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_template(template_id):
    """Edit a notification template"""
    from app.models import NotificationTemplate, NOTIFICATION_TEMPLATE_TYPES

    template = NotificationTemplate.query.get_or_404(template_id)

    if request.method == 'POST':
        name = request.form.get('name', '')
        template_type = request.form.get('template_type', '')
        title = request.form.get('title', '')
        message = request.form.get('message', '')
        tags = request.form.get('tags', '')

        # Validate input lengths
        errors = []
        if not name or len(name) > 100:
            errors.append('Name is required and must be less than 100 characters')
        if not template_type or len(template_type) > 20:
            errors.append('Template type is required and must be less than 20 characters')
        if not title or len(title) > 200:
            errors.append('Title is required and must be less than 200 characters')
        if not message or len(message) > 10000:
            errors.append('Message is required and must be less than 10000 characters')
        if tags and len(tags) > 100:
            errors.append('Tags must be less than 100 characters')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('admin/edit_template.html',
                                   template=template,
                                   template_types=NOTIFICATION_TEMPLATE_TYPES)

        template.name = name
        template.template_type = template_type
        template.title = title
        template.message = message
        template.priority = int(request.form.get('priority', 3))
        template.tags = tags if tags else None
        template.is_active = 'is_active' in request.form
        db.session.commit()
        flash(f'Template "{template.name}" updated.', 'success')
        return redirect(url_for('admin.notification_templates'))

    return render_template('admin/edit_template.html',
                           template=template,
                           template_types=NOTIFICATION_TEMPLATE_TYPES)


@admin_bp.route('/notifications/templates/<int:template_id>/delete', methods=['POST'])
@admin_required
def delete_template(template_id):
    """Delete a notification template"""
    from app.models import NotificationTemplate

    template = NotificationTemplate.query.get_or_404(template_id)
    name = template.name
    db.session.delete(template)
    db.session.commit()
    flash(f'Template "{name}" deleted.', 'success')
    return redirect(url_for('admin.notification_templates'))


# ----- BROADCAST -----

@admin_bp.route('/notifications/broadcast', methods=['GET', 'POST'])
@limiter.limit("30 per minute")
@admin_required
def broadcast():
    """Send a broadcast notification"""
    from app.models import (
        NotificationTemplate, BroadcastNotification,
        NOTIFICATION_TARGETS
    )

    templates = NotificationTemplate.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        current = get_current_user()
        title = request.form.get('title')
        message = request.form.get('message')
        priority = int(request.form.get('priority', 3))
        tags = request.form.get('tags')
        target = request.form.get('target', 'all')
        template_id = request.form.get('template_id', type=int)

        # Create broadcast record
        broadcast_notif = BroadcastNotification(
            title=title,
            message=message,
            priority=priority,
            tags=tags,
            target_audience=target,
            template_id=template_id if template_id else None,
            sent_by=current.id,
            status='sending'
        )
        db.session.add(broadcast_notif)
        db.session.commit()

        # Update template usage if used
        if template_id:
            template = db.session.get(NotificationTemplate, template_id)
            if template:
                template.times_used += 1
                template.last_used_at = datetime.now(timezone.utc)
                db.session.commit()

        # Send the notifications
        from app.services.broadcast import send_broadcast
        result = send_broadcast(broadcast_notif.id)

        flash(f'Broadcast sent to {result["successful"]} users ({result["failed"]} failed).', 'success')
        return redirect(url_for('admin.notifications'))

    return render_template('admin/broadcast.html',
                           templates=templates,
                           targets=NOTIFICATION_TARGETS)


@admin_bp.route('/notifications/broadcast/<int:broadcast_id>')
@admin_required
def broadcast_detail(broadcast_id):
    """View broadcast details"""
    from app.models import BroadcastNotification

    broadcast_notif = BroadcastNotification.query.get_or_404(broadcast_id)
    return render_template('admin/broadcast_detail.html', broadcast=broadcast_notif)


@admin_bp.route('/notifications/test-connection')
@admin_required
def test_ntfy_connection():
    """Test NTFY server connectivity"""
    from app.services.notifier import test_ntfy_connection as do_test
    from app.config import Config

    result = do_test()

    # Also check user topics
    users = User.query.filter(
        User.is_active.is_(True),
        User.is_verified.is_(True),
        User.ntfy_topic.isnot(None),
        User.notify_enabled.is_(True)
    ).all()

    user_info = []
    for u in users:
        topic_valid = u.ntfy_topic and len(u.ntfy_topic) >= 3
        user_info.append({
            'username': u.username,
            'email': u.email,
            'ntfy_topic': u.ntfy_topic,
            'topic_valid': topic_valid,
            'notify_enabled': u.notify_enabled
        })

    return jsonify({
        'ntfy_test': result,
        'ntfy_url': Config.NTFY_URL,
        'eligible_users': len(user_info),
        'users': user_info
    })


# ----- SCHEDULED -----

@admin_bp.route('/notifications/schedule', methods=['GET', 'POST'])
@admin_required
def schedule_notification():
    """Schedule a notification for future delivery"""
    from app.models import (
        NotificationTemplate, ScheduledNotification, NOTIFICATION_TARGETS
    )
    from dateutil import parser

    templates = NotificationTemplate.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        current = get_current_user()
        scheduled_for_str = request.form.get('scheduled_for')

        try:
            scheduled_for = parser.parse(scheduled_for_str)
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            flash('Invalid date/time format.', 'error')
            return redirect(url_for('admin.schedule_notification'))

        if scheduled_for <= datetime.now(timezone.utc):
            flash('Scheduled time must be in the future.', 'error')
            return redirect(url_for('admin.schedule_notification'))

        scheduled = ScheduledNotification(
            title=request.form.get('title'),
            message=request.form.get('message'),
            priority=int(request.form.get('priority', 3)),
            tags=request.form.get('tags'),
            target_audience=request.form.get('target', 'all'),
            template_id=request.form.get('template_id', type=int) or None,
            scheduled_for=scheduled_for,
            created_by=current.id
        )
        db.session.add(scheduled)
        db.session.commit()

        flash(f'Notification scheduled for {scheduled_for.strftime("%Y-%m-%d %H:%M UTC")}.', 'success')
        return redirect(url_for('admin.notifications'))

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')
    return render_template('admin/schedule_notification.html',
                           templates=templates,
                           targets=NOTIFICATION_TARGETS,
                           now_str=now_str)


@admin_bp.route('/notifications/scheduled/<int:scheduled_id>/cancel', methods=['POST'])
@admin_required
def cancel_scheduled(scheduled_id):
    """Cancel a scheduled notification"""
    from app.models import ScheduledNotification

    scheduled = ScheduledNotification.query.get_or_404(scheduled_id)
    if scheduled.status != 'pending':
        flash('Cannot cancel - notification already sent or cancelled.', 'error')
    else:
        scheduled.status = 'cancelled'
        db.session.commit()
        flash('Scheduled notification cancelled.', 'success')

    return redirect(url_for('admin.notifications'))


# ----- API -----

@admin_bp.route('/api/notifications/templates')
@admin_required
def api_templates():
    """Get templates as JSON"""
    from app.models import NotificationTemplate

    templates = NotificationTemplate.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in templates])


@admin_bp.route('/api/notifications/templates/<int:template_id>')
@admin_required
def api_template_detail(template_id):
    """Get template detail as JSON"""
    from app.models import NotificationTemplate

    template = NotificationTemplate.query.get_or_404(template_id)
    return jsonify(template.to_dict())


@admin_bp.route('/api/notifications/audience-count')
@admin_required
def api_audience_count():
    """Get count of users for a target audience"""
    target = request.args.get('target', 'all')

    query = User.query.filter(User.is_active.is_(True), User.is_verified.is_(True))

    if target == 'free':
        # Users with free tier
        query = query.join(Subscription).filter(Subscription.plan == 'free')
    elif target == 'pro':
        query = query.join(Subscription).filter(Subscription.plan == 'pro')
    elif target == 'premium':
        query = query.join(Subscription).filter(Subscription.plan == 'premium')
    # 'all', 'verified', 'active' use the base query

    count = query.count()
    return jsonify({'count': count, 'target': target})


# ----- SYMBOLS MANAGEMENT -----

# Mandatory symbols that cannot be disabled
MANDATORY_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT']


@admin_bp.route('/symbols')
@admin_required
def symbols():
    """Symbols management page"""
    from app.models import Symbol, Candle, Setting
    from sqlalchemy import func

    symbols_list = Symbol.query.order_by(Symbol.symbol).all()

    # Get candle stats for all symbols in a single query (avoids N+1)
    candle_stats = db.session.query(
        Candle.symbol_id,
        func.min(Candle.timestamp).label('earliest'),
        func.max(Candle.timestamp).label('latest'),
        func.count(Candle.id).label('count')
    ).filter(
        Candle.timeframe == '1m'
    ).group_by(Candle.symbol_id).all()

    # Build lookup dict
    symbol_stats = {stat.symbol_id: {
        'earliest': stat.earliest,
        'latest': stat.latest,
        'count': stat.count
    } for stat in candle_stats}

    # Ensure all symbols have stats (even if no candles)
    for sym in symbols_list:
        if sym.id not in symbol_stats:
            symbol_stats[sym.id] = {'earliest': None, 'latest': None, 'count': 0}

    # Get fetch start date setting
    fetch_start_setting = Setting.query.filter_by(key='fetch_start_date').first()
    fetch_start_date = fetch_start_setting.value if fetch_start_setting and fetch_start_setting.value else '2024-01-01'

    return render_template('admin/symbols.html',
                           symbols=symbols_list,
                           symbol_stats=symbol_stats,
                           mandatory_symbols=MANDATORY_SYMBOLS,
                           fetch_start_date=fetch_start_date)


@admin_bp.route('/api/symbols', methods=['GET'])
@admin_required
def api_symbols():
    """Get all symbols with stats"""
    from app.models import Symbol, Candle
    from sqlalchemy import func

    symbols_list = Symbol.query.order_by(Symbol.symbol).all()

    # Get candle stats for all symbols in a single query (avoids N+1)
    candle_stats = db.session.query(
        Candle.symbol_id,
        func.min(Candle.timestamp).label('earliest'),
        func.max(Candle.timestamp).label('latest'),
        func.count(Candle.id).label('count')
    ).filter(
        Candle.timeframe == '1m'
    ).group_by(Candle.symbol_id).all()

    # Build lookup dict
    stats_map = {stat.symbol_id: {
        'earliest': stat.earliest,
        'latest': stat.latest,
        'count': stat.count
    } for stat in candle_stats}

    result = []
    for sym in symbols_list:
        stats = stats_map.get(sym.id, {'earliest': None, 'latest': None, 'count': 0})
        result.append({
            **sym.to_dict(),
            'earliest_ts': stats['earliest'],
            'latest_ts': stats['latest'],
            'candle_count': stats['count'],
            'is_mandatory': sym.symbol in MANDATORY_SYMBOLS
        })

    return jsonify(result)


@admin_bp.route('/api/symbols/exchange', methods=['GET'])
@admin_required
def api_exchange_symbols():
    """Fetch available symbols from exchange and save to DB"""
    import ccxt
    from app.models import Symbol
    from app.services.logger import log_admin

    log_admin("Symbols: Fetching available symbols from Binance exchange...")

    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        markets = exchange.load_markets()

        # Filter USDT pairs only, sorted alphabetically
        usdt_pairs = sorted([
            symbol for symbol in markets.keys()
            if symbol.endswith('/USDT') and markets[symbol].get('active', True)
        ])

        log_admin(f"Symbols: Found {len(usdt_pairs)} USDT pairs on Binance")

        # Save all to database (inactive by default, except mandatory)
        existing = {s.symbol for s in Symbol.query.all()}
        added = 0

        for symbol_name in usdt_pairs:
            if symbol_name not in existing:
                is_mandatory = symbol_name in MANDATORY_SYMBOLS
                new_symbol = Symbol(
                    symbol=symbol_name,
                    exchange='binance',
                    is_active=is_mandatory,  # Only mandatory symbols active by default
                    notify_enabled=is_mandatory
                )
                db.session.add(new_symbol)
                added += 1

        if added > 0:
            db.session.commit()
            log_admin(f"Symbols: Added {added} new symbols to database (inactive by default)")
        else:
            log_admin("Symbols: No new symbols to add (all already in database)")

        return jsonify({
            'success': True,
            'symbols': usdt_pairs,
            'count': len(usdt_pairs),
            'added': added,
            'existing': len(existing)
        })
    except Exception as e:
        db.session.rollback()
        log_admin(f"Symbols: ERROR fetching from exchange - {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/api/symbols/toggle', methods=['POST'])
@admin_required
def api_toggle_symbol():
    """Toggle symbol active status"""
    from app.models import Symbol
    from app.services.logger import log_admin

    data = request.get_json()
    symbol_id = data.get('id')
    action = data.get('action', 'toggle')  # toggle, enable, disable

    symbol = db.session.get(Symbol, symbol_id)
    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol not found'}), 404

    # Prevent disabling mandatory symbols
    if symbol.symbol in MANDATORY_SYMBOLS and action in ['toggle', 'disable']:
        if symbol.is_active and action == 'toggle':
            log_admin(f"Symbols: Blocked attempt to disable mandatory symbol {symbol.symbol}")
            return jsonify({
                'success': False,
                'error': f'{symbol.symbol} is mandatory and cannot be disabled'
            }), 400
        if action == 'disable':
            log_admin(f"Symbols: Blocked attempt to disable mandatory symbol {symbol.symbol}")
            return jsonify({
                'success': False,
                'error': f'{symbol.symbol} is mandatory and cannot be disabled'
            }), 400

    if action == 'toggle':
        symbol.is_active = not symbol.is_active
    elif action == 'enable':
        symbol.is_active = True
    elif action == 'disable':
        symbol.is_active = False

    db.session.commit()

    new_state = "enabled" if symbol.is_active else "disabled"
    log_admin(f"Symbols: {symbol.symbol} {new_state}")

    return jsonify({
        'success': True,
        'symbol': symbol.to_dict()
    })


@admin_bp.route('/api/symbols/bulk', methods=['POST'])
@limiter.limit("60 per minute")
@admin_required
def api_bulk_symbols():
    """Bulk enable/disable symbols"""
    from app.models import Symbol
    from app.services.logger import log_admin

    data = request.get_json()
    symbol_ids = data.get('ids', [])
    action = data.get('action')  # enable, disable

    if not symbol_ids or action not in ['enable', 'disable']:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400

    log_admin(f"Symbols: Bulk {action} requested for {len(symbol_ids)} symbols")

    updated = 0
    skipped = 0

    for sid in symbol_ids:
        symbol = db.session.get(Symbol, sid)
        if not symbol:
            continue

        # Skip mandatory symbols for disable action
        if action == 'disable' and symbol.symbol in MANDATORY_SYMBOLS:
            skipped += 1
            continue

        symbol.is_active = (action == 'enable')
        updated += 1

    db.session.commit()

    log_admin(f"Symbols: Bulk {action} complete - {updated} updated, {skipped} mandatory skipped")

    return jsonify({
        'success': True,
        'updated': updated,
        'skipped': skipped
    })


@admin_bp.route('/api/symbols/add', methods=['POST'])
@admin_required
def api_add_symbol():
    """Add a new symbol"""
    from app.models import Symbol
    from app.services.logger import log_admin

    data = request.get_json()
    symbol_name = data.get('symbol', '').upper().strip()

    if not symbol_name or '/' not in symbol_name:
        log_admin(f"Symbols: Invalid symbol format attempted: {symbol_name}")
        return jsonify({
            'success': False,
            'error': 'Invalid symbol format. Use BASE/QUOTE (e.g., BTC/USDT)'
        }), 400

    # Check if exists
    existing = Symbol.query.filter_by(symbol=symbol_name).first()
    if existing:
        # Just enable it if it was disabled
        if not existing.is_active:
            existing.is_active = True
            db.session.commit()
            log_admin(f"Symbols: Re-enabled existing symbol {symbol_name}")
            return jsonify({
                'success': True,
                'symbol': existing.to_dict(),
                'message': 'Symbol re-enabled'
            })
        return jsonify({
            'success': False,
            'error': 'Symbol already exists'
        }), 400

    new_symbol = Symbol(
        symbol=symbol_name,
        exchange='binance',
        is_active=True,
        notify_enabled=True
    )
    db.session.add(new_symbol)
    db.session.commit()

    log_admin(f"Symbols: Added new symbol {symbol_name} (active)")

    return jsonify({
        'success': True,
        'symbol': new_symbol.to_dict()
    })


@admin_bp.route('/api/symbols/toggle-notify', methods=['POST'])
@admin_required
def api_toggle_notify():
    """Toggle symbol notification status"""
    from app.models import Symbol

    data = request.get_json()
    symbol_id = data.get('id')

    symbol = db.session.get(Symbol, symbol_id)
    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol not found'}), 404

    symbol.notify_enabled = not symbol.notify_enabled
    db.session.commit()

    return jsonify({
        'success': True,
        'notify_enabled': symbol.notify_enabled
    })


@admin_bp.route('/save-fetch-settings', methods=['POST'])
@admin_required
def save_fetch_settings():
    """Save fetch settings (start date)"""
    from app.models import Setting
    from app.services.logger import log_admin
    from datetime import datetime

    fetch_start_date = request.form.get('fetch_start_date', '2024-01-01')

    # Validate date format (YYYY-MM-DD)
    try:
        datetime.strptime(fetch_start_date, '%Y-%m-%d')
    except ValueError:
        flash('Invalid date format. Please use YYYY-MM-DD format.', 'danger')
        return redirect(url_for('admin.symbols'))

    # Get or create setting
    setting = Setting.query.filter_by(key='fetch_start_date').first()
    old_value = setting.value if setting else None

    if setting:
        setting.value = fetch_start_date
    else:
        setting = Setting(key='fetch_start_date', value=fetch_start_date)
        db.session.add(setting)

    db.session.commit()

    if old_value != fetch_start_date:
        log_admin(f"Settings: Fetch start date changed from {old_value or 'not set'} to {fetch_start_date}")
    else:
        log_admin(f"Settings: Fetch start date confirmed as {fetch_start_date}")

    flash(f'Fetch start date set to {fetch_start_date}', 'success')
    return redirect(url_for('admin.symbols'))


# ----- DOCUMENTATION -----

@admin_bp.route('/documentation')
@admin_required
def documentation():
    """Comprehensive admin documentation"""
    section = request.args.get('section', 'overview')
    return render_template('admin/documentation.html', active_section=section)


# ----- QUICK ACTIONS -----

def _start_cron_run(job_name):
    """Start tracking a cron run for quick actions."""
    from app.models import CronJob, CronRun

    job = CronJob.query.filter_by(name=job_name).first()
    if not job:
        from app.models import CRON_JOB_TYPES
        config = CRON_JOB_TYPES.get(job_name, {})
        job = CronJob(
            name=job_name,
            description=config.get('description', f'Quick action: {job_name}'),
            schedule='manual',
            is_enabled=True
        )
        db.session.add(job)
        db.session.commit()

    run = CronRun(job_id=job.id)
    db.session.add(run)
    db.session.commit()
    return run.id


def _complete_cron_run(run_id, success=True, error_message=None, **kwargs):
    """Complete a cron run with results."""
    from app.models import CronRun
    from datetime import datetime, timezone

    if not run_id:
        return

    run = db.session.get(CronRun, run_id)
    if run:
        run.ended_at = datetime.now(timezone.utc)
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        run.duration_ms = int((run.ended_at - started_at).total_seconds() * 1000)
        run.success = success
        run.error_message = error_message
        run.patterns_found = kwargs.get('patterns_found', 0)
        run.symbols_processed = kwargs.get('symbols_processed', 0)
        run.candles_fetched = kwargs.get('candles_fetched', 0)
        db.session.commit()


@admin_bp.route('/quick/scan', methods=['POST'])
@admin_required
def quick_scan():
    """Trigger a manual pattern scan (runs in background)"""
    import threading
    from app.services.logger import log_admin

    def run_scan_in_background():
        """Run scan in a separate thread with its own app context"""
        from app import create_app
        from app.services.patterns import scan_all_patterns
        from app.models import Symbol

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('pattern_scan')
            try:
                # Count active symbols
                symbols_count = Symbol.query.filter_by(is_active=True).count()
                log_admin(f"Pattern scan: Starting scan on {symbols_count} symbols...")

                result = scan_all_patterns()
                patterns_found = result.get('patterns_found', 0)

                log_admin(f"Pattern scan: Complete! Found {patterns_found} patterns across {symbols_count} symbols")
                _complete_cron_run(
                    run_id,
                    success=True,
                    patterns_found=patterns_found,
                    symbols_processed=symbols_count
                )
            except Exception as e:
                log_admin(f"Pattern scan: FAILED - {str(e)}")
                _complete_cron_run(run_id, success=False, error_message=str(e))

    # Start background thread
    thread = threading.Thread(target=run_scan_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: Pattern scan started in background")
    flash('Pattern scan started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/quick/refresh-stats', methods=['POST'])
@admin_required
def quick_refresh_stats():
    """Trigger stats computation (runs in background)"""
    import threading
    from app.services.logger import log_admin

    def run_stats_in_background():
        from app import create_app
        from scripts.compute_stats import compute_stats

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('stats')
            try:
                result = compute_stats()
                symbols = result.get('symbols_count', 0)
                candles = result.get('total_candles', 0)
                log_admin(f"Background stats complete: {symbols} symbols, {candles:,} candles")
                _complete_cron_run(run_id, success=True, symbols_processed=symbols)
            except Exception as e:
                log_admin(f"Background stats failed: {str(e)}")
                _complete_cron_run(run_id, success=False, error_message=str(e))

    thread = threading.Thread(target=run_stats_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: Stats refresh started in background")
    flash('Stats refresh started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/quick/cleanup', methods=['POST'])
@admin_required
def quick_cleanup():
    """Trigger database health check and cleanup (runs in background)"""
    import threading
    from app.services.logger import log_admin

    def run_cleanup_in_background():
        from app import create_app
        from scripts.db_health import run_health_check

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('cleanup')
            try:
                result = run_health_check(fix=True, verbose=False, app=app)
                verified = result.get('verified', 0) if result else 0
                errors = result.get('errors', {}) if result else {}
                error_count = sum(errors.values()) if errors else 0
                log_admin(f"Background cleanup complete: verified {verified}, fixed {error_count} issues")
                _complete_cron_run(run_id, success=True, symbols_processed=verified)
            except Exception as e:
                log_admin(f"Background cleanup failed: {str(e)}")
                _complete_cron_run(run_id, success=False, error_message=str(e))

    thread = threading.Thread(target=run_cleanup_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: DB cleanup started in background")
    flash('DB cleanup started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/quick/sanitize', methods=['POST'])
@admin_required
def quick_sanitize():
    """Verify and fix candle data integrity (runs in background)"""
    import threading
    from app.services.logger import log_admin

    def run_sanitize_in_background():
        from app import create_app
        from scripts.db_health import run_health_check

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('sanitize')
            try:
                log_admin("Sanitize: Starting candle data integrity check...")
                result = run_health_check(fix=True, verbose=False, app=app)
                verified = result.get('verified', 0) if result else 0
                errors = result.get('errors', {}) if result else {}
                error_count = sum(errors.values()) if errors else 0

                # Refresh stats cache
                log_admin("Sanitize: Refreshing statistics...")
                from scripts.compute_stats import compute_stats
                compute_stats()

                log_admin(f"Sanitize: Complete! Verified {verified:,} candles, fixed {error_count} issues")
                _complete_cron_run(run_id, success=True, symbols_processed=verified)
            except Exception as e:
                log_admin(f"Sanitize: FAILED - {str(e)}")
                _complete_cron_run(run_id, success=False, error_message=str(e))

    thread = threading.Thread(target=run_sanitize_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: Data sanitization started in background")
    flash('Data sanitization started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/quick/fetch', methods=['POST'])
@admin_required
def quick_fetch():
    """Trigger manual candle fetch for all active symbols (runs in background)"""
    import threading
    from app.services.logger import log_admin

    def run_fetch_in_background():
        """Run fetch in a separate thread with its own app context"""
        import asyncio
        from app import create_app
        from app.models import Symbol

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('fetch')
            try:
                # Import fetch functions
                from scripts.fetch import run_fetch_cycle, generate_signals_batch, expire_old_patterns
                from scripts.compute_stats import compute_stats

                symbols = [s.symbol for s in Symbol.query.filter_by(is_active=True).all()]
                symbols_count = len(symbols)

                log_admin(f"Data fetch: Starting fetch for {symbols_count} symbols...")

                # Run the async fetch cycle
                results = asyncio.run(run_fetch_cycle(symbols, app, verbose=False))

                # Generate signals
                signal_result = generate_signals_batch(app, verbose=False)

                # Expire old patterns
                expire_old_patterns(app, verbose=False)

                # Calculate totals
                total_candles = sum(r.get('new', 0) for r in results)
                total_patterns = sum(r.get('patterns', 0) for r in results)
                total_signals = signal_result.get('signals_generated', 0)

                # Refresh stats
                log_admin("Data fetch: Refreshing statistics...")
                compute_stats()

                log_admin(f"Data fetch: Complete! {total_candles:,} candles, {total_patterns} patterns, {total_signals} signals")
                _complete_cron_run(
                    run_id,
                    success=True,
                    symbols_processed=symbols_count,
                    candles_fetched=total_candles,
                    patterns_found=total_patterns
                )
            except Exception as e:
                log_admin(f"Data fetch: FAILED - {str(e)}")
                _complete_cron_run(run_id, success=False, error_message=str(e))

    # Start background thread
    thread = threading.Thread(target=run_fetch_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: Data fetch started in background")
    flash('Data fetch started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/quick/full-cycle', methods=['POST'])
@admin_required
def quick_full_cycle():
    """Run full cycle: fetch → pattern scan → stats refresh (sequential, in background)"""
    import threading
    from app.services.logger import log_admin

    def run_full_cycle_in_background():
        """Run full cycle sequentially in a separate thread"""
        import asyncio
        from app import create_app
        from app.models import Symbol

        app = create_app()
        with app.app_context():
            run_id = _start_cron_run('full_cycle')
            total_candles = 0
            total_patterns = 0
            symbols_count = 0

            try:
                # === STEP 1: FETCH ===
                log_admin("Full cycle: Step 1/3 - Fetching candle data...")
                from scripts.fetch import run_fetch_cycle, generate_signals_batch, expire_old_patterns

                symbols = [s.symbol for s in Symbol.query.filter_by(is_active=True).all()]
                symbols_count = len(symbols)

                results = asyncio.run(run_fetch_cycle(symbols, app, verbose=False))
                total_candles = sum(r.get('new', 0) for r in results)

                # Generate signals and expire patterns
                generate_signals_batch(app, verbose=False)
                expire_old_patterns(app, verbose=False)

                log_admin(f"Full cycle: Fetch complete - {total_candles:,} new candles")

                # === STEP 2: PATTERN SCAN ===
                log_admin("Full cycle: Step 2/3 - Scanning for patterns...")
                from app.services.patterns import scan_all_patterns

                scan_result = scan_all_patterns()
                total_patterns = scan_result.get('patterns_found', 0)

                log_admin(f"Full cycle: Scan complete - {total_patterns} patterns found")

                # === STEP 3: STATS REFRESH ===
                log_admin("Full cycle: Step 3/3 - Refreshing statistics...")
                from scripts.compute_stats import compute_stats

                compute_stats()

                log_admin(f"Full cycle: Complete! {symbols_count} symbols, {total_candles:,} candles, {total_patterns} patterns")
                _complete_cron_run(
                    run_id,
                    success=True,
                    symbols_processed=symbols_count,
                    candles_fetched=total_candles,
                    patterns_found=total_patterns
                )

            except Exception as e:
                log_admin(f"Full cycle: FAILED - {str(e)}")
                _complete_cron_run(
                    run_id,
                    success=False,
                    error_message=str(e),
                    symbols_processed=symbols_count,
                    candles_fetched=total_candles,
                    patterns_found=total_patterns
                )

    # Start background thread
    thread = threading.Thread(target=run_full_cycle_in_background, daemon=True)
    thread.start()

    log_admin("Quick Action: Full cycle (fetch→scan→stats) started in background")
    flash('Full cycle started in background. Check Cron Jobs for progress.', 'info')

    return redirect(url_for('admin.index'))


@admin_bp.route('/api/symbols/<int:symbol_id>/fetch-historical', methods=['POST'])
@admin_required
def api_fetch_historical(symbol_id):
    """Fetch historical data for a single symbol from target start date"""
    import threading
    from app.models import Symbol, Setting
    from app.services.logger import log_admin

    symbol = db.session.get(Symbol, symbol_id)
    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol not found'}), 404

    if not symbol.is_active:
        return jsonify({'success': False, 'error': 'Symbol is not active'}), 400

    # Get target start date
    fetch_start_setting = Setting.query.filter_by(key='fetch_start_date').first()
    fetch_start_date = fetch_start_setting.value if fetch_start_setting else '2024-01-01'

    symbol_name = symbol.symbol
    log_admin(f"Historical fetch: Starting background fetch for {symbol_name} from {fetch_start_date}")

    def run_fetch_in_background(sym_name, start_date):
        """Run historical fetch in a separate thread with its own app context"""
        import ccxt
        import time
        import traceback
        from datetime import datetime, timezone
        from app import create_app, db as app_db
        from app.models import Symbol, Candle, CronJob, CronRun
        from app.services.aggregator import aggregate_candles_realtime
        from app.services.logger import log_admin

        app = create_app()
        with app.app_context():
            # Create cron run entry directly (not using helper to avoid import issues)
            job = CronJob.query.filter_by(name='historical_fetch').first()
            if not job:
                job = CronJob(name='historical_fetch', description='Fetch historical candle data', schedule='manual', is_enabled=True)
                app_db.session.add(job)
                app_db.session.commit()
            run = CronRun(job_id=job.id)
            app_db.session.add(run)
            app_db.session.commit()
            run_id = run.id

            total_candles = 0
            success = False
            error_msg = None

            try:
                # Get symbol
                sym = Symbol.query.filter_by(symbol=sym_name).first()
                if not sym:
                    error_msg = f'Symbol {sym_name} not found'
                    log_admin(f"Historical fetch: {error_msg}")
                    return

                # Parse start date to timestamp
                start_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                start_ts = int(start_dt.timestamp() * 1000)
                now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

                log_admin(f"Historical fetch: {sym_name} - fetching from {start_date} to now...")

                # Initialize exchange
                exchange = ccxt.binance({
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'}
                })

                # Fetch in batches of 1000 candles
                since = start_ts
                batch_count = 0
                while since < now_ts:
                    try:
                        ohlcv = exchange.fetch_ohlcv(sym_name, '1m', since=since, limit=1000)
                        if not ohlcv:
                            break

                        # Get existing timestamps to avoid duplicates
                        timestamps = [c[0] for c in ohlcv]
                        existing = set(
                            c.timestamp for c in Candle.query.filter(
                                Candle.symbol_id == sym.id,
                                Candle.timeframe == '1m',
                                Candle.timestamp.in_(timestamps)
                            ).all()
                        )

                        # Insert new candles
                        new_count = 0
                        for candle in ohlcv:
                            ts, o, h, low, c, v = candle
                            if ts not in existing:
                                app_db.session.add(Candle(
                                    symbol_id=sym.id,
                                    timeframe='1m',
                                    timestamp=ts,
                                    open=o, high=h, low=low, close=c,
                                    volume=v or 0
                                ))
                                new_count += 1

                        if new_count > 0:
                            app_db.session.commit()
                            total_candles += new_count

                        # Move to next batch
                        since = ohlcv[-1][0] + 60000
                        batch_count += 1

                        # Log progress every 10 batches
                        if batch_count % 10 == 0:
                            progress_date = datetime.fromtimestamp(since / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                            log_admin(f"Historical fetch: {sym_name} - progress: {progress_date}, {total_candles:,} candles so far")

                        # Rate limit delay
                        time.sleep(0.3)

                        # Break if we got less than 1000 candles (reached end)
                        if len(ohlcv) < 1000:
                            break

                    except Exception as e:
                        error_str = str(e).lower()
                        if 'rate' in error_str or '429' in error_str:
                            log_admin(f"Historical fetch: {sym_name} - rate limited, waiting 5s...")
                            time.sleep(5)
                            continue
                        raise

                # Aggregate all higher timeframes
                log_admin(f"Historical fetch: {sym_name} - aggregating higher timeframes...")
                timeframes = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
                for tf in timeframes:
                    try:
                        aggregate_candles_realtime(sym_name, '1m', tf)
                    except Exception as e:
                        log_admin(f"Historical fetch: {sym_name} - aggregation error for {tf}: {str(e)}")

                # Refresh stats cache
                log_admin(f"Historical fetch: {sym_name} - refreshing statistics...")
                from scripts.compute_stats import compute_stats
                compute_stats()

                log_admin(f"Historical fetch: {sym_name} - complete! {total_candles:,} candles fetched and aggregated")
                success = True

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                log_admin(f"Historical fetch: {sym_name} - ERROR: {error_msg}")
                traceback.print_exc()

            finally:
                # Always mark run as complete
                try:
                    run = app_db.session.get(CronRun, run_id)
                    if run:
                        run.ended_at = datetime.now(timezone.utc)
                        started_at = run.started_at
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)
                        run.duration_ms = int((run.ended_at - started_at).total_seconds() * 1000)
                        run.success = success
                        run.error_message = error_msg
                        run.candles_fetched = total_candles
                        run.symbols_processed = 1 if success else 0
                        app_db.session.commit()
                except Exception as e:
                    log_admin(f"Historical fetch: Failed to update cron run: {str(e)}")

    # Start background thread
    thread = threading.Thread(
        target=run_fetch_in_background,
        args=(symbol_name, fetch_start_date),
        daemon=True
    )
    thread.start()

    return jsonify({
        'success': True,
        'message': f'Historical fetch started for {symbol_name} from {fetch_start_date}',
        'symbol': symbol_name,
        'start_date': fetch_start_date
    })


@admin_bp.route('/api/symbols/<int:symbol_id>/fix', methods=['POST'])
@admin_required
def api_fix_symbol(symbol_id):
    """Fix candle data integrity for a single symbol (runs in background)"""
    import threading
    from app.models import Symbol
    from app.services.logger import log_admin

    symbol = db.session.get(Symbol, symbol_id)
    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol not found'}), 404

    symbol_name = symbol.symbol
    log_admin(f"Symbol fix: Starting background fix for {symbol_name}")

    def run_fix_in_background(sym_name):
        """Run db_health fix in a separate thread with its own app context"""
        import traceback
        from datetime import datetime, timezone
        from app import create_app, db as app_db
        from app.models import CronJob, CronRun
        from app.services.logger import log_admin
        from scripts.db_health import run_health_check

        app = create_app()
        with app.app_context():
            # Create cron run entry
            job = CronJob.query.filter_by(name='symbol_fix').first()
            if not job:
                job = CronJob(name='symbol_fix', description='Fix candle data for symbol', schedule='manual', is_enabled=True)
                app_db.session.add(job)
                app_db.session.commit()

            run = CronRun(job_id=job.id)
            app_db.session.add(run)
            app_db.session.commit()
            run_id = run.id

            success = False
            error_msg = None
            verified_count = 0
            error_count = 0

            try:
                log_admin(f"Symbol fix: {sym_name} - starting candle data verification...")

                # Run health check with fix=True for this specific symbol
                # Pass app to avoid nested app context
                result = run_health_check(symbol_filter=sym_name, fix=True, verbose=False, app=app)

                if result:
                    verified_count = result.get('verified', 0)
                    errors = result.get('errors', {})
                    error_count = sum(errors.values()) if errors else 0

                log_admin(f"Symbol fix: {sym_name} - complete! Verified {verified_count:,} candles, fixed {error_count} issues")
                success = True

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                log_admin(f"Symbol fix: {sym_name} - ERROR: {error_msg}")
                traceback.print_exc()

            finally:
                # Always mark run as complete
                try:
                    run = app_db.session.get(CronRun, run_id)
                    if run:
                        run.ended_at = datetime.now(timezone.utc)
                        started_at = run.started_at
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)
                        run.duration_ms = int((run.ended_at - started_at).total_seconds() * 1000)
                        run.success = success
                        run.error_message = error_msg
                        run.candles_fetched = verified_count
                        run.symbols_processed = 1 if success else 0
                        run.patterns_found = error_count  # Reuse field for errors fixed
                        app_db.session.commit()
                except Exception as e:
                    log_admin(f"Symbol fix: Failed to update cron run: {str(e)}")

    # Start background thread
    thread = threading.Thread(
        target=run_fix_in_background,
        args=(symbol_name,),
        daemon=True
    )
    thread.start()

    return jsonify({
        'success': True,
        'message': f'Fix started for {symbol_name}. Check Cron Jobs for progress.',
        'symbol': symbol_name
    })


# ============================================================================
# OPTIMIZATION ROUTES
# ============================================================================

@admin_bp.route('/optimization')
@admin_required
def optimization_index():
    """List optimization jobs"""
    from app.models import OptimizationJob

    jobs = OptimizationJob.query.order_by(OptimizationJob.created_at.desc()).all()
    return render_template('admin/optimization.html', jobs=jobs)


@admin_bp.route('/optimization/results')
@admin_required
def optimization_results():
    """View all optimization results with filters and comparison heatmaps"""
    from app.models import OptimizationRun
    from app.services.auto_tuner import auto_tuner
    from sqlalchemy import func

    # Get filter parameters
    filter_symbol = request.args.get('symbol', '')
    filter_pattern = request.args.get('pattern_type', '')
    filter_timeframe = request.args.get('timeframe', '')
    sort_by = request.args.get('sort', 'profit')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 100)  # Cap at 100

    # Base filter conditions
    base_filters = [
        OptimizationRun.status == 'completed',
        OptimizationRun.total_trades >= 1  # At least 1 trade
    ]
    if filter_symbol:
        base_filters.append(OptimizationRun.symbol == filter_symbol)
    if filter_pattern:
        base_filters.append(OptimizationRun.pattern_type == filter_pattern)
    if filter_timeframe:
        base_filters.append(OptimizationRun.timeframe == filter_timeframe)

    # Build paginated query
    query = OptimizationRun.query.filter(*base_filters)

    # Sort
    if sort_by == 'winrate':
        query = query.order_by(OptimizationRun.win_rate.desc())
    elif sort_by == 'sharpe':
        query = query.order_by(OptimizationRun.sharpe_ratio.desc())
    elif sort_by == 'trades':
        query = query.order_by(OptimizationRun.total_trades.desc())
    else:
        query = query.order_by(OptimizationRun.total_profit_pct.desc())

    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    results = pagination.items

    # Get total count for stats (use SQL count, not len)
    total_count = OptimizationRun.query.filter(*base_filters).count()

    # Get profitable count using SQL
    profitable_count = OptimizationRun.query.filter(
        *base_filters,
        OptimizationRun.total_profit_pct > 0
    ).count()

    # Get available filter options (cached query)
    symbols = db.session.query(OptimizationRun.symbol).distinct().all()
    symbols = sorted([s[0] for s in symbols if s[0]])

    # Timeframe sort order (chronological)
    tf_order = {'1m': 1, '3m': 2, '5m': 3, '15m': 4, '30m': 5, '1h': 6, '2h': 7, '4h': 8, '6h': 9, '8h': 10, '12h': 11, '1d': 12, '3d': 13, '1w': 14, '1M': 15}
    timeframes = db.session.query(OptimizationRun.timeframe).distinct().all()
    timeframes = sorted([t[0] for t in timeframes if t[0]], key=lambda x: tf_order.get(x, 99))

    # Get best results using SQL (not Python iteration)
    best_result = OptimizationRun.query.filter(*base_filters).order_by(
        OptimizationRun.total_profit_pct.desc()
    ).first()

    best_winrate = OptimizationRun.query.filter(*base_filters).order_by(
        OptimizationRun.win_rate.desc()
    ).first()

    # Get date range using SQL aggregate
    date_range = None
    date_stats = db.session.query(
        func.min(OptimizationRun.start_date),
        func.max(OptimizationRun.end_date)
    ).filter(*base_filters).first()
    if date_stats and date_stats[0] and date_stats[1]:
        date_range = {
            'start': date_stats[0],
            'end': date_stats[1]
        }

    # Get comparison heatmap data if a symbol is selected
    comparison_data = None
    if filter_symbol:
        comparison_data = auto_tuner.get_comparison_data(
            symbol=filter_symbol,
            pattern_type=filter_pattern or 'imbalance',
            timeframe=filter_timeframe if filter_timeframe else None
        )

    return render_template(
        'admin/optimization_results.html',
        results=results,
        pagination=pagination,
        symbols=symbols,
        timeframes=timeframes,
        filter_symbol=filter_symbol,
        filter_pattern=filter_pattern,
        filter_timeframe=filter_timeframe,
        sort_by=sort_by,
        best_result=best_result,
        best_winrate=best_winrate,
        date_range=date_range,
        total_count=total_count,
        profitable_count=profitable_count,
        comparison_data=comparison_data
    )


@admin_bp.route('/optimization/<int:job_id>')
@admin_required
def optimization_detail(job_id):
    """View optimization job details"""
    from app.models import OptimizationJob, OptimizationRun

    job = OptimizationJob.query.get_or_404(job_id)

    # Get top runs by profit
    top_by_profit = OptimizationRun.query.filter(
        OptimizationRun.job_id == job_id,
        OptimizationRun.status == 'completed',
        OptimizationRun.total_trades >= 5
    ).order_by(
        OptimizationRun.total_profit_pct.desc()
    ).limit(20).all()

    # Get top runs by win rate
    top_by_winrate = OptimizationRun.query.filter(
        OptimizationRun.job_id == job_id,
        OptimizationRun.status == 'completed',
        OptimizationRun.total_trades >= 5
    ).order_by(
        OptimizationRun.win_rate.desc()
    ).limit(20).all()

    return render_template(
        'admin/optimization_detail.html',
        job=job,
        top_by_profit=top_by_profit,
        top_by_winrate=top_by_winrate
    )


@admin_bp.route('/api/optimization/jobs', methods=['GET'])
@admin_required
def api_optimization_jobs():
    """API: List optimization jobs"""
    from app.models import OptimizationJob

    jobs = OptimizationJob.query.order_by(OptimizationJob.created_at.desc()).all()
    return jsonify({
        'success': True,
        'jobs': [j.to_dict() for j in jobs]
    })


@admin_bp.route('/api/optimization/jobs', methods=['POST'])
@admin_required
def api_create_optimization_job():
    """API: Create new optimization job"""
    from app.services.optimizer import optimizer
    from app.models import QUICK_PARAMETER_GRID, DEFAULT_PARAMETER_GRID

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    try:
        name = data.get('name', f"Optimization {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")
        symbols = data.get('symbols', ['BTC/USDT', 'ETH/USDT'])
        timeframes = data.get('timeframes', ['1h', '4h'])
        pattern_types = data.get('pattern_types', ['imbalance', 'order_block'])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        use_full_grid = data.get('full_grid', False)

        if not start_date:
            start_dt = datetime.now(timezone.utc) - timedelta(days=90)
            start_date = start_dt.strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        param_grid = DEFAULT_PARAMETER_GRID if use_full_grid else QUICK_PARAMETER_GRID

        job = optimizer.create_job(
            name=name,
            symbols=symbols,
            timeframes=timeframes,
            pattern_types=pattern_types,
            start_date=start_date,
            end_date=end_date,
            parameter_grid=param_grid,
            description=data.get('description')
        )

        return jsonify({
            'success': True,
            'job': job.to_dict()
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/optimization/jobs/<int:job_id>/run', methods=['POST'])
@admin_required
def api_run_optimization_job(job_id):
    """API: Run an optimization job"""
    from app.services.optimizer import optimizer
    from app.models import OptimizationJob
    import threading

    job = OptimizationJob.query.get(job_id)
    if not job:
        return jsonify({'success': False, 'error': 'Job not found'}), 404

    if job.status not in ['pending', 'failed']:
        return jsonify({'success': False, 'error': f'Job is already {job.status}'}), 400

    # Run in background thread
    def run_job_background(jid):
        from app import create_app
        app = create_app()
        with app.app_context():
            optimizer.run_job(jid)

    thread = threading.Thread(target=run_job_background, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Job started in background'
    })


@admin_bp.route('/api/optimization/jobs/<int:job_id>', methods=['DELETE'])
@admin_required
def api_delete_optimization_job(job_id):
    """API: Delete an optimization job"""
    from app.models import OptimizationJob

    job = OptimizationJob.query.get(job_id)
    if not job:
        return jsonify({'success': False, 'error': 'Job not found'}), 404

    db.session.delete(job)
    db.session.commit()

    return jsonify({'success': True})


@admin_bp.route('/api/optimization/best-params')
@admin_required
def api_best_params():
    """API: Get best parameters"""
    from app.services.optimizer import optimizer

    symbol = request.args.get('symbol')
    pattern_type = request.args.get('pattern_type')
    timeframe = request.args.get('timeframe')
    metric = request.args.get('metric', 'total_profit_pct')

    best = optimizer.get_best_params(
        symbol=symbol,
        pattern_type=pattern_type,
        timeframe=timeframe,
        metric=metric
    )

    if best:
        return jsonify({'success': True, 'best': best})
    else:
        return jsonify({'success': True, 'best': None, 'message': 'No data available'})


@admin_bp.route('/optimization/compare')
@admin_required
def optimization_compare():
    """Redirect to results page with comparison (pages merged)"""
    # Get filter parameters and redirect to results page
    symbol = request.args.get('symbol', 'BTC/USDT')
    pattern_type = request.args.get('pattern_type', 'imbalance')
    timeframe = request.args.get('timeframe', '')

    return redirect(url_for(
        'admin.optimization_results',
        symbol=symbol,
        pattern_type=pattern_type,
        timeframe=timeframe
    ))


@admin_bp.route('/api/optimization/apply-params', methods=['POST'])
@admin_required
def api_apply_optimization_params():
    """API: Apply optimization parameters to user preferences.

    Premium/Admin feature: Copies best parameters to user's symbol preferences.
    """
    from app.models import Symbol, UserSymbolPreference
    from app.services.auto_tuner import auto_tuner

    # Get current user
    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    # Check premium or admin access
    if not current_user.is_admin and current_user.subscription_tier != 'premium':
        return jsonify({
            'success': False,
            'error': 'Premium subscription required for custom parameters'
        }), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    symbol = data.get('symbol')
    pattern_type = data.get('pattern_type')
    rr_target = data.get('rr_target')
    sl_buffer_pct = data.get('sl_buffer_pct')
    min_zone_pct = data.get('min_zone_pct')

    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol required'}), 400

    # Get symbol from DB
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return jsonify({'success': False, 'error': f'Symbol {symbol} not found'}), 404

    # If specific params provided, apply them directly
    if rr_target is not None and sl_buffer_pct is not None:
        pref = UserSymbolPreference.get_or_create(current_user.id, sym.id)
        pref.set_params_from_optimization(
            rr_target=float(rr_target),
            sl_buffer_pct=float(sl_buffer_pct),
            min_zone_pct=float(min_zone_pct) if min_zone_pct else None,
            pattern_type=pattern_type
        )
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Parameters applied for {symbol}',
            'params': {
                'rr_target': rr_target,
                'sl_buffer_pct': sl_buffer_pct,
                'min_zone_pct': min_zone_pct,
                'pattern_type': pattern_type
            }
        })

    # Otherwise, find best params from optimization
    result = auto_tuner.apply_best_params_to_user(
        user_id=current_user.id,
        symbol=symbol,
        pattern_type=pattern_type,
        metric=data.get('metric', 'total_profit_pct'),
        min_trades=data.get('min_trades', 10)
    )

    return jsonify(result)


@admin_bp.route('/api/optimization/best-by-symbol')
@admin_required
def api_best_params_by_symbol():
    """API: Get best parameters grouped by symbol"""
    from app.services.auto_tuner import auto_tuner

    symbol = request.args.get('symbol')
    pattern_type = request.args.get('pattern_type')
    metric = request.args.get('metric', 'total_profit_pct')
    min_trades = request.args.get('min_trades', 10, type=int)

    results = auto_tuner.get_best_params_by_symbol(
        symbol=symbol,
        pattern_type=pattern_type,
        metric=metric,
        min_trades=min_trades
    )

    return jsonify({
        'success': True,
        'results': results
    })


@admin_bp.route('/api/optimization/user-params')
@admin_required
def api_get_user_params():
    """API: Get current user's custom symbol parameters"""
    from app.models import UserSymbolPreference

    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    # Get all preferences with custom params
    prefs = UserSymbolPreference.query.filter(
        UserSymbolPreference.user_id == current_user.id,
        db.or_(
            UserSymbolPreference.custom_rr.isnot(None),
            UserSymbolPreference.pattern_params.isnot(None)
        )
    ).all()

    return jsonify({
        'success': True,
        'preferences': [p.to_dict() for p in prefs]
    })


@admin_bp.route('/api/optimization/clear-params', methods=['POST'])
@admin_required
def api_clear_user_params():
    """API: Clear user's custom parameters"""
    from app.services.auto_tuner import auto_tuner

    current_user = get_current_user()
    if not current_user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json() or {}
    symbol = data.get('symbol')  # Optional: clear specific symbol only

    result = auto_tuner.clear_user_custom_params(
        user_id=current_user.id,
        symbol=symbol
    )

    return jsonify(result)
