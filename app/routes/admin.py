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

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin/users.html',
                           users=pagination.items,
                           pagination=pagination,
                           status=status,
                           search=search)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """User detail page"""
    user = get_user_by_id(user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_detail.html',
                           user=user,
                           plans=SUBSCRIPTION_PLANS)


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

    try:
        if action == 'extend':
            extend_subscription(user_id, plan)
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

    return render_template('admin/subscriptions.html',
                           subscriptions=pagination.items,
                           pagination=pagination,
                           status=status,
                           plan=plan,
                           plans=SUBSCRIPTION_PLANS)


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
