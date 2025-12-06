"""
Payment Routes
Handles checkout, webhooks, and payment status for LemonSqueezy and NOWPayments
"""
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session
from app import db
from app.models import User, Payment, SUBSCRIPTION_PLANS
from app.services.payment import (
    is_lemonsqueezy_configured,
    is_nowpayments_configured,
    create_lemonsqueezy_checkout,
    verify_lemonsqueezy_webhook,
    process_lemonsqueezy_webhook,
    create_nowpayments_invoice,
    verify_nowpayments_webhook,
    process_nowpayments_webhook,
    get_available_cryptos
)
from functools import wraps

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')


def login_required(f):
    """Require user to be logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get the current logged-in user"""
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None


# =============================================================================
# UPGRADE/CHECKOUT PAGES
# =============================================================================

@payments_bp.route('/upgrade')
@login_required
def upgrade():
    """Show upgrade/pricing page"""
    user = get_current_user()

    return render_template('payments/upgrade.html',
        user=user,
        plans=SUBSCRIPTION_PLANS,
        current_plan=user.subscription.plan if user.subscription else 'free',
        lemonsqueezy_enabled=is_lemonsqueezy_configured(),
        nowpayments_enabled=is_nowpayments_configured(),
        available_cryptos=get_available_cryptos() if is_nowpayments_configured() else []
    )


@payments_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """Create checkout session"""
    user = get_current_user()

    plan = request.form.get('plan', 'pro')
    billing_cycle = request.form.get('billing_cycle', 'monthly')
    payment_method = request.form.get('payment_method', 'card')
    crypto_currency = request.form.get('crypto_currency', 'USDT')

    # Validate plan
    if plan not in ['pro', 'premium', 'lifetime']:
        flash('Invalid plan selected', 'error')
        return redirect(url_for('payments.upgrade'))

    # Validate billing cycle
    if billing_cycle not in ['monthly', 'yearly'] and plan != 'lifetime':
        flash('Invalid billing cycle', 'error')
        return redirect(url_for('payments.upgrade'))

    if payment_method == 'card':
        # LemonSqueezy checkout
        if not is_lemonsqueezy_configured():
            flash('Card payments are not available at this time', 'error')
            return redirect(url_for('payments.upgrade'))

        result = create_lemonsqueezy_checkout(user, plan, billing_cycle)

        if result['success']:
            return redirect(result['checkout_url'])
        else:
            flash(f'Checkout failed: {result["error"]}', 'error')
            return redirect(url_for('payments.upgrade'))

    elif payment_method == 'crypto':
        # NOWPayments checkout
        if not is_nowpayments_configured():
            flash('Crypto payments are not available at this time', 'error')
            return redirect(url_for('payments.upgrade'))

        result = create_nowpayments_invoice(user, plan, billing_cycle, crypto_currency)

        if result['success']:
            # Show crypto payment page
            return render_template('payments/crypto_payment.html',
                user=user,
                payment=result,
                plan=plan,
                billing_cycle=billing_cycle
            )
        else:
            flash(f'Payment creation failed: {result["error"]}', 'error')
            return redirect(url_for('payments.upgrade'))

    else:
        flash('Invalid payment method', 'error')
        return redirect(url_for('payments.upgrade'))


@payments_bp.route('/status/<int:payment_id>')
@login_required
def payment_status(payment_id):
    """Check payment status"""
    user = get_current_user()
    payment = Payment.query.filter_by(id=payment_id, user_id=user.id).first()

    if not payment:
        flash('Payment not found', 'error')
        return redirect(url_for('payments.upgrade'))

    return render_template('payments/status.html',
        user=user,
        payment=payment
    )


@payments_bp.route('/status/<int:payment_id>/check')
@login_required
def check_payment_status(payment_id):
    """API endpoint to check payment status (for polling)"""
    user = get_current_user()
    payment = Payment.query.filter_by(id=payment_id, user_id=user.id).first()

    if not payment:
        return jsonify({'error': 'Payment not found'}), 404

    return jsonify({
        'status': payment.status,
        'completed': payment.status == 'completed'
    })


@payments_bp.route('/success')
@login_required
def payment_success():
    """Payment success page"""
    user = get_current_user()
    return render_template('payments/success.html', user=user)


@payments_bp.route('/cancel')
@login_required
def payment_cancel():
    """Payment cancelled page"""
    user = get_current_user()
    return render_template('payments/cancel.html', user=user)


# =============================================================================
# WEBHOOKS
# =============================================================================

@payments_bp.route('/lemonsqueezy/webhook', methods=['POST'])
def lemonsqueezy_webhook():
    """Handle LemonSqueezy webhooks"""
    signature = request.headers.get('X-Signature', '')

    if not verify_lemonsqueezy_webhook(request.data, signature):
        return jsonify({'error': 'Invalid signature'}), 401

    data = request.get_json()
    event_name = data.get('meta', {}).get('event_name', '')

    result = process_lemonsqueezy_webhook(event_name, data.get('data', {}))

    if result['success']:
        return jsonify({'status': 'ok'}), 200
    else:
        return jsonify({'error': result.get('error', 'Unknown error')}), 400


@payments_bp.route('/nowpayments/webhook', methods=['POST'])
def nowpayments_webhook():
    """Handle NOWPayments IPN callbacks"""
    signature = request.headers.get('x-nowpayments-sig', '')
    data = request.get_json()

    if not verify_nowpayments_webhook(data, signature):
        return jsonify({'error': 'Invalid signature'}), 401

    result = process_nowpayments_webhook(data)

    if result['success']:
        return jsonify({'status': 'ok'}), 200
    else:
        return jsonify({'error': result.get('error', 'Unknown error')}), 400


# =============================================================================
# PAYMENT HISTORY
# =============================================================================

@payments_bp.route('/history')
@login_required
def payment_history():
    """Show payment history"""
    user = get_current_user()
    payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()

    return render_template('payments/history.html',
        user=user,
        payments=payments
    )
