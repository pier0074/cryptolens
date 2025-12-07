"""
Authentication Routes
Handles user registration, login, logout, and profile
"""
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.auth import (
    register_user, authenticate_user, change_password,
    get_user_by_id, AuthError, validate_password
)
from app.services.lockout import record_failed_attempt, is_locked, clear_lockout
from app.services.subscription import check_subscription_status
from app.services.email import (
    send_verification_email, send_password_reset_email,
    send_welcome_email, send_password_changed_email, is_email_configured
)
from app.models import User, SUBSCRIPTION_PLANS
from app.decorators import login_required, admin_required, get_current_user
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

            # Generate verification token and send email
            if is_email_configured():
                token = user.generate_email_verification_token()
                db.session.commit()
                send_verification_email(user, token)
                flash('Registration successful! Please check your email to verify your account.', 'success')
            else:
                # Auto-verify if email not configured (development mode)
                user.is_verified = True
                db.session.commit()
                flash('Registration successful! Please log in.', 'success')

            return redirect(url_for('auth.login'))
        except AuthError as e:
            flash(str(e), 'error')
            return render_template('auth/register.html', email=email, username=username)

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def login():
    """User login page"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    # Check if this is a 2FA verification step
    pending_2fa_user_id = session.get('pending_2fa_user_id')

    if request.method == 'POST':
        totp_code = request.form.get('totp_code', '').strip()

        # Handle 2FA verification
        if pending_2fa_user_id and totp_code:
            user = db.session.get(User, pending_2fa_user_id)
            if user and user.verify_totp(totp_code):
                # Clear pending 2FA state
                session.pop('pending_2fa_user_id', None)

                # Complete login
                session['user_id'] = user.id
                session.permanent = True

                flash(f'Welcome back, {user.username}!', 'success')

                next_page = request.args.get('next')
                if next_page and is_safe_url(next_page):
                    return redirect(next_page)
                return redirect(url_for('auth.profile'))
            else:
                flash('Invalid authentication code.', 'error')
                return render_template('auth/login.html', requires_2fa=True)

        # Handle initial login
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Check if account is locked
        locked, minutes_remaining = is_locked(email)
        if locked:
            flash(f'Account temporarily locked. Try again in {minutes_remaining} minutes.', 'error')
            return render_template('auth/login.html')

        user = authenticate_user(email, password)
        if user:
            # Clear any failed attempt counters on successful login
            clear_lockout(user)
            # Check if 2FA is enabled
            if user.totp_enabled:
                # Store pending 2FA state in session
                session['pending_2fa_user_id'] = user.id
                return render_template('auth/login.html', requires_2fa=True)

            session['user_id'] = user.id
            session.permanent = True

            flash(f'Welcome back, {user.username}!', 'success')

            # Redirect to next page or profile (with open redirect protection)
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for('auth.profile'))
        else:
            # Record failed attempt for lockout tracking
            record_failed_attempt(email)
            flash('Invalid email or password.', 'error')

    # Clear any stale pending 2FA state on GET request
    if request.method == 'GET':
        session.pop('pending_2fa_user_id', None)

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
    """User profile and subscription status (unified with settings)"""
    from app.models import Symbol, Setting
    from app.config import Config

    user = get_current_user()
    sub_status = check_subscription_status(user.id)

    # Settings data (for Trading and System tabs)
    symbols = Symbol.query.all()
    settings = {
        'ntfy_topic': Setting.get('ntfy_topic', Config.NTFY_TOPIC),
        'ntfy_priority': Setting.get('ntfy_priority', str(Config.NTFY_PRIORITY)),
        'scan_interval': Setting.get('scan_interval', str(Config.SCAN_INTERVAL_MINUTES)),
        'risk_per_trade': Setting.get('risk_per_trade', '1.0'),
        'default_rr': Setting.get('default_rr', '3.0'),
        'min_confluence': Setting.get('min_confluence', '2'),
        'notifications_enabled': Setting.get('notifications_enabled', 'true'),
        'api_key': Setting.get('api_key', ''),
        'log_level': Setting.get('log_level', 'INFO'),
    }
    available_symbols = sorted(Config.SYMBOLS)

    return render_template('auth/profile.html',
                           user=user,
                           subscription=sub_status,
                           plans=SUBSCRIPTION_PLANS,
                           symbols=symbols,
                           settings=settings,
                           available_symbols=available_symbols)


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


@auth_bp.route('/change-subscription', methods=['POST'])
@login_required
@admin_required
def change_subscription():
    """Change subscription plan (admin only for testing)"""
    from app.models import Subscription
    from datetime import datetime, timezone, timedelta

    user = get_current_user()
    new_plan = request.form.get('plan', '').strip()

    if new_plan not in SUBSCRIPTION_PLANS:
        flash('Invalid plan selected.', 'error')
        return redirect(url_for('auth.subscription'))

    # Get or create subscription
    sub = user.subscription
    if not sub:
        sub = Subscription(user_id=user.id)
        db.session.add(sub)

    # Update plan
    sub.plan = new_plan
    sub.status = 'active'
    sub.starts_at = datetime.now(timezone.utc)

    # Set expiry based on plan
    plan_config = SUBSCRIPTION_PLANS[new_plan]
    if plan_config.get('days'):
        sub.expires_at = datetime.now(timezone.utc) + timedelta(days=plan_config['days'])
    else:
        sub.expires_at = None  # No expiry for free tier

    db.session.commit()
    flash(f'Subscription changed to {plan_config["name"]}!', 'success')
    return redirect(url_for('auth.subscription'))


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


# =============================================================================
# EMAIL VERIFICATION ROUTES
# =============================================================================

@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    """Verify email with token"""
    # Find user with this token
    user = User.query.filter_by(email_verification_token=token).first()

    if not user:
        flash('Invalid verification link.', 'error')
        return redirect(url_for('auth.login'))

    if not user.verify_email_token(token):
        flash('Verification link has expired. Please request a new one.', 'error')
        return redirect(url_for('auth.login'))

    # Verify the user
    user.is_verified = True
    user.clear_email_verification_token()
    db.session.commit()

    # Send welcome email
    if is_email_configured():
        send_welcome_email(user)

    flash('Email verified successfully! You can now log in.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def resend_verification():
    """Resend verification email"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        user = User.query.filter_by(email=email).first()

        if user and not user.is_verified:
            if is_email_configured():
                token = user.generate_email_verification_token()
                db.session.commit()
                send_verification_email(user, token)

        # Always show same message to prevent email enumeration
        flash('If an account with that email exists and is not verified, a verification link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/resend_verification.html')


# =============================================================================
# PASSWORD RESET ROUTES
# =============================================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def forgot_password():
    """Request password reset"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        user = User.query.filter_by(email=email).first()

        if user and user.is_verified:
            if is_email_configured():
                token = user.generate_password_reset_token()
                db.session.commit()
                send_password_reset_email(user, token)

        # Always show same message to prevent email enumeration
        flash('If an account with that email exists, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def reset_password(token):
    """Reset password with token"""
    if 'user_id' in session:
        return redirect(url_for('auth.profile'))

    # Find user with this token
    user = User.query.filter_by(password_reset_token=token).first()

    if not user or not user.verify_password_reset_token(token):
        flash('Invalid or expired reset link. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html', token=token)

        # Validate password strength (same rules as registration)
        valid, error = validate_password(password)
        if not valid:
            flash(error, 'error')
            return render_template('auth/reset_password.html', token=token)

        # Update password
        user.set_password(password)
        user.clear_password_reset_token()
        db.session.commit()

        # Send confirmation email
        if is_email_configured():
            send_password_changed_email(user)

        flash('Password reset successfully! Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


# =============================================================================
# TWO-FACTOR AUTHENTICATION (2FA) ROUTES
# =============================================================================

@auth_bp.route('/2fa/setup', methods=['GET', 'POST'])
@login_required
def setup_2fa():
    """Setup two-factor authentication"""
    import io
    import base64
    import qrcode

    user = get_current_user()

    if user.totp_enabled:
        flash('Two-factor authentication is already enabled.', 'info')
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        # Generate new TOTP secret
        user.generate_totp_secret()
        db.session.commit()

    # Generate QR code if secret exists
    qr_code_data = None
    if user.totp_secret:
        totp_uri = user.get_totp_uri()
        if totp_uri:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(totp_uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert to base64 for embedding in HTML
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            qr_code_data = base64.b64encode(buffer.getvalue()).decode()

    return render_template('auth/2fa_setup.html',
                           user=user,
                           qr_code_data=qr_code_data)


@auth_bp.route('/2fa/verify', methods=['POST'])
@login_required
def verify_2fa():
    """Verify TOTP code and enable 2FA"""
    user = get_current_user()

    if user.totp_enabled:
        flash('Two-factor authentication is already enabled.', 'info')
        return redirect(url_for('auth.profile'))

    if not user.totp_secret:
        flash('Please generate a 2FA secret first.', 'error')
        return redirect(url_for('auth.setup_2fa'))

    totp_code = request.form.get('totp_code', '').strip()

    if not totp_code:
        flash('Please enter the authentication code.', 'error')
        return redirect(url_for('auth.setup_2fa'))

    if user.verify_totp(totp_code):
        user.totp_enabled = True
        db.session.commit()
        flash('Two-factor authentication has been enabled!', 'success')
        return redirect(url_for('auth.profile'))
    else:
        flash('Invalid authentication code. Please try again.', 'error')
        return redirect(url_for('auth.setup_2fa'))


@auth_bp.route('/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    """Disable two-factor authentication"""
    user = get_current_user()

    if not user.totp_enabled:
        flash('Two-factor authentication is not enabled.', 'info')
        return redirect(url_for('auth.profile'))

    # Require password confirmation
    password = request.form.get('password', '')
    if not user.check_password(password):
        flash('Invalid password.', 'error')
        return redirect(url_for('auth.profile'))

    # Disable 2FA
    user.totp_enabled = False
    user.totp_secret = None
    db.session.commit()

    flash('Two-factor authentication has been disabled.', 'success')
    return redirect(url_for('auth.profile'))


# =============================================================================
# NOTIFICATION PREFERENCES ROUTES
# =============================================================================

@auth_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notification_preferences():
    """Manage notification preferences"""
    user = get_current_user()

    if request.method == 'POST':
        # Update notification preferences
        user.notify_enabled = 'notify_enabled' in request.form
        user.notify_signals = 'notify_signals' in request.form
        user.notify_patterns = 'notify_patterns' in request.form
        user.notify_priority = int(request.form.get('notify_priority', 3))
        user.notify_min_confluence = int(request.form.get('notify_min_confluence', 2))
        user.notify_directions = request.form.get('notify_directions', 'both')
        user.quiet_hours_enabled = 'quiet_hours_enabled' in request.form
        user.quiet_hours_start = int(request.form.get('quiet_hours_start', 22))
        user.quiet_hours_end = int(request.form.get('quiet_hours_end', 7))

        db.session.commit()
        flash('Notification preferences saved!', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/notifications.html', user=user)


@auth_bp.route('/notifications/test', methods=['POST'])
@login_required
def test_user_notification():
    """Send a test notification to the user"""
    from app.services.notifier import send_notification
    from datetime import datetime, timezone

    user = get_current_user()

    if not user.can_receive_notifications:
        return jsonify({
            'success': False,
            'error': 'Notifications are disabled or subscription inactive'
        }), 400

    # Send test notification
    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%d/%m/%Y %H:%M UTC")

    title = "CryptoLens Test Notification"
    message = f"{timestamp_str}\n\nThis is a test notification from CryptoLens.\n\nYour notification preferences are working correctly!"

    success = send_notification(
        topic=user.ntfy_topic,
        title=title,
        message=message,
        priority=user.notify_priority,
        tags="test,check"
    )

    return jsonify({'success': success})
