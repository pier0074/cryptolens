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
from app.models import User, Subscription, SUBSCRIPTION_PLANS, CronJob, CronRun, CRON_JOB_TYPES
from app import db
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
        query = query.filter(User.is_active == True)
    elif status == 'inactive':
        query = query.filter(User.is_active == False)
    elif status == 'verified':
        query = query.filter(User.is_verified == True)
    elif status == 'unverified':
        query = query.filter(User.is_verified == False)
    elif status == 'admin':
        query = query.filter(User.is_admin == True)
    elif status == 'locked':
        # Use naive UTC for SQLite comparison
        query = query.filter(User.locked_until > datetime.now(timezone.utc).replace(tzinfo=None))

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Use naive UTC for SQLite datetime comparison in templates
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

    # Use naive UTC for SQLite datetime comparison in templates
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

    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/make-admin', methods=['POST'])
@admin_required
def make_admin_route(user_id):
    """Grant admin privileges"""
    if make_admin(user_id):
        flash('Admin privileges granted.', 'success')
    else:
        flash('Failed to grant admin privileges.', 'error')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/revoke-admin', methods=['POST'])
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
@admin_required
def modify_subscription(user_id):
    """Modify user subscription"""
    action = request.form.get('action')
    plan = request.form.get('plan', 'monthly')
    custom_days = request.form.get('custom_days')

    try:
        if action == 'create':
            # Create new subscription (cancel existing first)
            cancel_subscription(user_id)
            extend_subscription(user_id, plan, custom_days=int(custom_days) if custom_days else None)
            flash(f'New {plan} subscription created.', 'success')
        elif action == 'extend':
            extend_subscription(user_id, plan, custom_days=int(custom_days) if custom_days else None)
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
        flash(str(e), 'error')
    except ValueError as e:
        flash(f'Invalid custom days value: {e}', 'error')

    return redirect(url_for('admin.user_detail', user_id=user_id))


@admin_bp.route('/users/create', methods=['GET', 'POST'])
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
    """Ensure all cron jobs exist in database"""
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

    # Get recent runs for history
    recent_runs = CronRun.query.order_by(CronRun.started_at.desc()).limit(50).all()

    # Calculate overall stats
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    total_runs_24h = CronRun.query.filter(CronRun.started_at >= since_24h).count()
    failed_runs_24h = CronRun.query.filter(
        CronRun.started_at >= since_24h,
        CronRun.success == False
    ).count()

    return render_template('admin/crons.html',
                           jobs=jobs,
                           recent_runs=recent_runs,
                           total_runs_24h=total_runs_24h,
                           failed_runs_24h=failed_runs_24h,
                           cron_types=CRON_JOB_TYPES)


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
    error.resolved_by = session.get('user_id')
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
        current = get_current_user()
        template = NotificationTemplate(
            name=request.form.get('name'),
            template_type=request.form.get('template_type'),
            title=request.form.get('title'),
            message=request.form.get('message'),
            priority=int(request.form.get('priority', 3)),
            tags=request.form.get('tags'),
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
        template.name = request.form.get('name')
        template.template_type = request.form.get('template_type')
        template.title = request.form.get('title')
        template.message = request.form.get('message')
        template.priority = int(request.form.get('priority', 3))
        template.tags = request.form.get('tags')
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
@admin_required
def broadcast():
    """Send a broadcast notification"""
    from app.models import (
        NotificationTemplate, BroadcastNotification,
        NOTIFICATION_TEMPLATE_TYPES, NOTIFICATION_TARGETS
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

    query = User.query.filter(User.is_active == True, User.is_verified == True)

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
