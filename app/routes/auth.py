"""
Authentication Routes
Handles user registration, login, logout, and profile
"""
from functools import wraps
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.auth import (
    register_user, authenticate_user, change_password,
    get_user_by_id, AuthError
)
from app.services.subscription import check_subscription_status
from app.models import User, SUBSCRIPTION_PLANS
from app import db, limiter


def is_safe_url(target):
    """
    Check if the redirect target is safe (same host).
    Prevents open redirect attacks.
    """
    if not target:
        return False
    # Parse the target URL
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    # Only allow redirects to same scheme/host or relative paths
    return (
        test_url.scheme in ('', 'http', 'https') and
        (test_url.netloc == '' or test_url.netloc == ref_url.netloc)
    )

auth_bp = Blueprint('auth', __name__)


def login_required(f):
    """Decorator to require login for a route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        user = get_user_by_id(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get the current logged-in user"""
    if 'user_id' in session:
        return get_user_by_id(session['user_id'])
    return None


@auth_bp.before_app_request
def load_user():
    """Load current user into g for templates"""
    g.user = get_current_user()


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def register():
    """User registration page"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        # Validate password confirmation
        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/register.html', email=email, username=username)

        try:
            user = register_user(email, username, password)
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except AuthError as e:
            flash(str(e), 'error')
            return render_template('auth/register.html', email=email, username=username)

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """User login page"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        user = authenticate_user(email, password)
        if user:
            session['user_id'] = user.id
            session.permanent = True

            flash(f'Welcome back, {user.username}!', 'success')

            # Redirect to next page or profile (with open redirect protection)
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('auth.profile'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    """Log out current user"""
    session.pop('user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile')
@login_required
def profile():
    """User profile and subscription status"""
    user = get_current_user()
    sub_status = check_subscription_status(user.id)

    return render_template('auth/profile.html',
                           user=user,
                           subscription=sub_status,
                           plans=SUBSCRIPTION_PLANS)


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password_route():
    """Change user password"""
    user = get_current_user()
    old_password = request.form.get('old_password', '')
    new_password = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')

    if new_password != confirm:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('auth.profile'))

    try:
        change_password(user.id, old_password, new_password)
        flash('Password changed successfully.', 'success')
    except AuthError as e:
        flash(str(e), 'error')

    return redirect(url_for('auth.profile'))


@auth_bp.route('/subscription')
@login_required
def subscription():
    """View subscription details"""
    user = get_current_user()
    sub_status = check_subscription_status(user.id)

    return render_template('auth/subscription.html',
                           user=user,
                           subscription=sub_status,
                           plans=SUBSCRIPTION_PLANS)


# API endpoints for AJAX
@auth_bp.route('/api/status')
def api_status():
    """Get current user status (for AJAX)"""
    user = get_current_user()
    if not user:
        return jsonify({'logged_in': False})

    sub_status = check_subscription_status(user.id)
    return jsonify({
        'logged_in': True,
        'user': user.to_dict(include_subscription=False),
        'subscription': sub_status,
    })


@auth_bp.route('/api/topic')
@login_required
def api_topic():
    """Get user's NTFY topic"""
    user = get_current_user()
    return jsonify({
        'topic': user.ntfy_topic,
        'url': f"https://ntfy.sh/{user.ntfy_topic}",
    })
