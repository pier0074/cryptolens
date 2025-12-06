"""
Admin Routes
User and subscription management for administrators
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
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
from app.models import User, Subscription, SUBSCRIPTION_PLANS
from app import db

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
