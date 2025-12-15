"""
Payment Service
Handles payment processing for LemonSqueezy (fiat) and NOWPayments (crypto)
"""
import os
import hmac
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from app import db
from app.models import User, Subscription, Payment, SUBSCRIPTION_PLANS
from app.services.logger import log_payment


# API Configuration
LEMONSQUEEZY_API_KEY = os.environ.get('LEMONSQUEEZY_API_KEY', '')
LEMONSQUEEZY_WEBHOOK_SECRET = os.environ.get('LEMONSQUEEZY_WEBHOOK_SECRET', '')
LEMONSQUEEZY_STORE_ID = os.environ.get('LEMONSQUEEZY_STORE_ID', '')

NOWPAYMENTS_API_KEY = os.environ.get('NOWPAYMENTS_API_KEY', '')
NOWPAYMENTS_IPN_SECRET = os.environ.get('NOWPAYMENTS_IPN_SECRET', '')

# Plan to LemonSqueezy variant ID mapping (configure in .env)
LEMONSQUEEZY_VARIANTS = {
    'pro_monthly': os.environ.get('LEMONSQUEEZY_PRO_MONTHLY_VARIANT', ''),
    'pro_yearly': os.environ.get('LEMONSQUEEZY_PRO_YEARLY_VARIANT', ''),
    'premium_monthly': os.environ.get('LEMONSQUEEZY_PREMIUM_MONTHLY_VARIANT', ''),
    'premium_yearly': os.environ.get('LEMONSQUEEZY_PREMIUM_YEARLY_VARIANT', ''),
    'lifetime': os.environ.get('LEMONSQUEEZY_LIFETIME_VARIANT', ''),
}


def is_lemonsqueezy_configured():
    """Check if LemonSqueezy is configured"""
    return bool(LEMONSQUEEZY_API_KEY and LEMONSQUEEZY_STORE_ID)


def is_nowpayments_configured():
    """Check if NOWPayments is configured"""
    return bool(NOWPAYMENTS_API_KEY)


# =============================================================================
# LEMONSQUEEZY (Fiat Payments)
# =============================================================================

def create_lemonsqueezy_checkout(user, plan, billing_cycle='monthly'):
    """
    Create a LemonSqueezy checkout URL for the user.

    Args:
        user: User object
        plan: 'pro' or 'premium'
        billing_cycle: 'monthly' or 'yearly'

    Returns:
        dict with checkout_url or error
    """
    if not is_lemonsqueezy_configured():
        return {'success': False, 'error': 'LemonSqueezy not configured'}

    variant_key = f"{plan}_{billing_cycle}"
    variant_id = LEMONSQUEEZY_VARIANTS.get(variant_key)

    if not variant_id:
        return {'success': False, 'error': f'Invalid plan: {plan}_{billing_cycle}'}

    # Get plan price
    plan_config = SUBSCRIPTION_PLANS.get(plan, {})
    if billing_cycle == 'yearly':
        price = plan_config.get('price_yearly', 0)
    else:
        price = plan_config.get('price', 0)

    try:
        # Create checkout via LemonSqueezy API
        response = requests.post(
            'https://api.lemonsqueezy.com/v1/checkouts',
            headers={
                'Authorization': f'Bearer {LEMONSQUEEZY_API_KEY}',
                'Content-Type': 'application/vnd.api+json',
                'Accept': 'application/vnd.api+json',
            },
            json={
                'data': {
                    'type': 'checkouts',
                    'attributes': {
                        'checkout_data': {
                            'email': user.email,
                            'custom': {
                                'user_id': str(user.id),
                                'plan': plan,
                                'billing_cycle': billing_cycle,
                            }
                        }
                    },
                    'relationships': {
                        'store': {
                            'data': {
                                'type': 'stores',
                                'id': LEMONSQUEEZY_STORE_ID
                            }
                        },
                        'variant': {
                            'data': {
                                'type': 'variants',
                                'id': variant_id
                            }
                        }
                    }
                }
            },
            timeout=30
        )

        if response.status_code == 201:
            data = response.json()
            checkout_url = data['data']['attributes']['url']

            # Create pending payment record
            payment = Payment(
                user_id=user.id,
                provider='lemonsqueezy',
                plan=plan,
                billing_cycle=billing_cycle,
                amount=price,
                currency='USD',
                status='pending'
            )
            db.session.add(payment)
            db.session.commit()

            log_payment(
                f"Checkout created: {plan} ({billing_cycle}) for {user.username}",
                details={'user_id': user.id, 'payment_id': payment.id, 'provider': 'lemonsqueezy', 'amount': price}
            )

            return {'success': True, 'checkout_url': checkout_url, 'payment_id': payment.id}
        else:
            log_payment(
                f"Checkout creation failed for {user.username}",
                level='ERROR',
                details={'user_id': user.id, 'provider': 'lemonsqueezy', 'error': response.text[:200]}
            )
            return {'success': False, 'error': response.text}

    except Exception as e:
        log_payment(
            f"Checkout exception for {user.username}: {str(e)}",
            level='ERROR',
            details={'user_id': user.id, 'provider': 'lemonsqueezy'}
        )
        return {'success': False, 'error': str(e)}


def verify_lemonsqueezy_webhook(payload, signature):
    """
    Verify LemonSqueezy webhook signature.

    Security: If webhook secret is not configured, logs a critical warning
    and rejects all webhooks in production for safety.
    """
    if not LEMONSQUEEZY_WEBHOOK_SECRET:
        log_payment(
            "SECURITY WARNING: LemonSqueezy webhook secret not configured - rejecting webhook",
            level='ERROR',
            details={'signature_provided': bool(signature)}
        )
        return False

    if not signature:
        log_payment("LemonSqueezy webhook missing signature", level='WARNING')
        return False

    expected = hmac.new(
        LEMONSQUEEZY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def process_lemonsqueezy_webhook(event_name, data):
    """
    Process LemonSqueezy webhook events.

    Events handled:
    - order_created: New order
    - subscription_created: New subscription
    - subscription_updated: Subscription changed
    - subscription_cancelled: Subscription cancelled
    """
    log_payment(
        f"LemonSqueezy webhook received: {event_name}",
        details={'event': event_name, 'data_id': data.get('id')}
    )

    custom_data = data.get('meta', {}).get('custom_data', {})
    user_id = custom_data.get('user_id')

    if not user_id:
        log_payment("LemonSqueezy webhook missing user_id", level='WARNING')
        return {'success': False, 'error': 'Missing user_id'}

    user = db.session.get(User, int(user_id))
    if not user:
        log_payment(f"LemonSqueezy webhook user not found: {user_id}", level='WARNING')
        return {'success': False, 'error': 'User not found'}

    if event_name in ['order_created', 'subscription_created']:
        plan = custom_data.get('plan', 'pro')
        billing_cycle = custom_data.get('billing_cycle', 'monthly')

        log_payment(
            f"Processing payment for {user.username}: {plan} ({billing_cycle})",
            details={'user_id': user.id, 'event': event_name}
        )

        # Activate subscription
        return activate_subscription(
            user=user,
            plan=plan,
            billing_cycle=billing_cycle,
            provider='lemonsqueezy',
            external_id=str(data.get('id'))
        )

    elif event_name == 'subscription_cancelled':
        # Mark subscription as cancelled
        if user.subscription:
            user.subscription.status = 'cancelled'
            user.subscription.cancelled_at = datetime.now(timezone.utc)
            db.session.commit()
            log_payment(
                f"Subscription cancelled for {user.username}",
                details={'user_id': user.id}
            )
        return {'success': True}

    return {'success': True}


# =============================================================================
# NOWPAYMENTS (Crypto Payments)
# =============================================================================

def create_nowpayments_invoice(user, plan, billing_cycle='monthly', crypto_currency='USDT'):
    """
    Create a NOWPayments invoice for crypto payment.

    Args:
        user: User object
        plan: 'pro' or 'premium'
        billing_cycle: 'monthly' or 'yearly'
        crypto_currency: BTC, ETH, USDT, etc.

    Returns:
        dict with payment details or error
    """
    if not is_nowpayments_configured():
        return {'success': False, 'error': 'NOWPayments not configured'}

    # Get plan price
    plan_config = SUBSCRIPTION_PLANS.get(plan, {})
    if billing_cycle == 'yearly':
        price = plan_config.get('price_yearly', 0)
    else:
        price = plan_config.get('price', 0)

    if price <= 0:
        return {'success': False, 'error': 'Invalid plan price'}

    try:
        # Create invoice via NOWPayments API
        response = requests.post(
            'https://api.nowpayments.io/v1/invoice',
            headers={
                'x-api-key': NOWPAYMENTS_API_KEY,
                'Content-Type': 'application/json',
            },
            json={
                'price_amount': price,
                'price_currency': 'USD',
                'pay_currency': crypto_currency,
                'order_id': f'cryptolens_{user.id}_{plan}_{int(datetime.now().timestamp())}',
                'order_description': f'CryptoLens {plan.title()} ({billing_cycle})',
                'ipn_callback_url': os.environ.get('APP_URL', '') + '/payments/nowpayments/webhook',
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()

            # Create pending payment record
            payment = Payment(
                user_id=user.id,
                provider='nowpayments',
                external_id=data.get('id'),
                plan=plan,
                billing_cycle=billing_cycle,
                amount=price,
                currency='USD',
                crypto_currency=crypto_currency,
                status='pending',
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)  # 1 hour to pay
            )
            db.session.add(payment)
            db.session.commit()

            log_payment(
                f"Crypto invoice created: {plan} ({billing_cycle}) for {user.username}",
                details={'user_id': user.id, 'payment_id': payment.id, 'provider': 'nowpayments', 'currency': crypto_currency, 'amount': price}
            )

            return {
                'success': True,
                'payment_id': payment.id,
                'invoice_url': data.get('invoice_url'),
                'pay_address': data.get('pay_address'),
                'pay_amount': data.get('pay_amount'),
                'pay_currency': crypto_currency,
                'expires_at': payment.expires_at.isoformat()
            }
        else:
            log_payment(
                f"Crypto invoice creation failed for {user.username}",
                level='ERROR',
                details={'user_id': user.id, 'provider': 'nowpayments', 'error': response.text[:200]}
            )
            return {'success': False, 'error': response.text}

    except Exception as e:
        log_payment(
            f"Crypto invoice exception for {user.username}: {str(e)}",
            level='ERROR',
            details={'user_id': user.id, 'provider': 'nowpayments'}
        )
        return {'success': False, 'error': str(e)}


def verify_nowpayments_webhook(payload, signature):
    """
    Verify NOWPayments IPN signature.

    Security: If IPN secret is not configured, logs a critical warning
    and rejects all webhooks in production for safety.
    """
    if not NOWPAYMENTS_IPN_SECRET:
        log_payment(
            "SECURITY WARNING: NOWPayments IPN secret not configured - rejecting webhook",
            level='ERROR',
            details={'signature_provided': bool(signature)}
        )
        return False

    if not signature:
        log_payment("NOWPayments webhook missing signature", level='WARNING')
        return False

    import json
    sorted_payload = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    expected = hmac.new(
        NOWPAYMENTS_IPN_SECRET.encode(),
        sorted_payload.encode(),
        hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def process_nowpayments_webhook(data):
    """
    Process NOWPayments IPN callback.

    Status values:
    - waiting: Waiting for payment
    - confirming: Payment detected, confirming
    - confirmed: Payment confirmed
    - finished: Payment completed
    - failed: Payment failed
    - expired: Payment expired
    """
    payment_id = data.get('invoice_id') or data.get('payment_id')
    status = data.get('payment_status')

    log_payment(
        f"NOWPayments webhook received: {status}",
        details={'payment_id': payment_id, 'status': status}
    )

    # Find payment record
    payment = Payment.query.filter_by(
        provider='nowpayments',
        external_id=str(payment_id)
    ).first()

    if not payment:
        log_payment(f"NOWPayments payment not found: {payment_id}", level='WARNING')
        return {'success': False, 'error': 'Payment not found'}

    # Update payment status
    if status == 'finished':
        payment.status = 'completed'
        payment.completed_at = datetime.now(timezone.utc)
        payment.crypto_amount = data.get('actually_paid')

        # Activate subscription
        user = db.session.get(User, payment.user_id)
        if user:
            log_payment(
                f"Crypto payment completed for {user.username}: {payment.plan}",
                details={'user_id': user.id, 'amount': payment.crypto_amount, 'plan': payment.plan}
            )
            activate_subscription(
                user=user,
                plan=payment.plan,
                billing_cycle=payment.billing_cycle,
                provider='nowpayments',
                external_id=str(payment_id)
            )

    elif status in ['failed', 'expired']:
        payment.status = status
        log_payment(
            f"Crypto payment {status}: {payment_id}",
            level='WARNING',
            details={'payment_id': payment_id, 'user_id': payment.user_id}
        )

    elif status == 'confirming':
        payment.crypto_amount = data.get('actually_paid')
        log_payment(f"Crypto payment confirming: {payment_id}", details={'amount': payment.crypto_amount})

    db.session.commit()
    return {'success': True}


# =============================================================================
# SHARED FUNCTIONS
# =============================================================================

def activate_subscription(user, plan, billing_cycle, provider, external_id=None):
    """
    Activate or extend a user's subscription.

    Idempotent: If external_id was already processed, returns success without
    double-crediting the subscription.

    Args:
        user: User object
        plan: 'pro', 'premium', or 'lifetime'
        billing_cycle: 'monthly' or 'yearly'
        provider: 'lemonsqueezy' or 'nowpayments'
        external_id: Provider's transaction ID (used for idempotency)

    Returns:
        dict with success status and subscription info
    """
    # IDEMPOTENCY CHECK: If we've already processed this external_id, don't double-credit
    if external_id:
        existing_payment = Payment.query.filter_by(
            provider=provider,
            external_id=str(external_id),
            status='completed'
        ).first()

        if existing_payment:
            log_payment(
                f"Idempotency: Webhook already processed for {external_id}",
                details={'provider': provider, 'external_id': external_id, 'user_id': user.id}
            )
            return {
                'success': True,
                'idempotent': True,
                'plan': plan,
                'message': 'Already processed'
            }

    now = datetime.now(timezone.utc)

    # Calculate expiry
    if plan == 'lifetime':
        expires_at = None
    elif billing_cycle == 'yearly':
        expires_at = now + timedelta(days=365)
    else:
        expires_at = now + timedelta(days=30)

    if user.subscription:
        # Extend existing subscription
        subscription = user.subscription
        subscription.plan = plan
        subscription.status = 'active'

        # Extend from current expiry if still active
        if subscription.expires_at and subscription.is_valid:
            subscription.expires_at = subscription.expires_at + timedelta(days=30 if billing_cycle == 'monthly' else 365)
        else:
            subscription.starts_at = now
            subscription.expires_at = expires_at
    else:
        # Create new subscription
        subscription = Subscription(
            user_id=user.id,
            plan=plan,
            starts_at=now,
            expires_at=expires_at,
            status='active'
        )
        db.session.add(subscription)

    # Update payment record
    payment = Payment.query.filter_by(
        provider=provider,
        external_id=external_id
    ).first()

    if payment:
        payment.status = 'completed'
        payment.completed_at = now

    db.session.commit()

    log_payment(
        f"Subscription activated: {user.username} -> {plan}",
        details={
            'user_id': user.id,
            'plan': plan,
            'billing_cycle': billing_cycle,
            'provider': provider,
            'expires_at': expires_at.isoformat() if expires_at else 'lifetime'
        }
    )

    return {
        'success': True,
        'plan': plan,
        'expires_at': expires_at.isoformat() if expires_at else None
    }


def get_available_cryptos():
    """Get list of available cryptocurrencies from NOWPayments"""
    if not is_nowpayments_configured():
        # Return default list
        return ['BTC', 'ETH', 'USDT', 'LTC', 'DOGE']

    try:
        response = requests.get(
            'https://api.nowpayments.io/v1/currencies',
            headers={'x-api-key': NOWPAYMENTS_API_KEY},
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            # Return popular ones first
            popular = ['btc', 'eth', 'usdttrc20', 'usdt', 'ltc', 'doge', 'sol', 'bnb']
            currencies = data.get('currencies', [])
            return [c.upper() for c in popular if c in currencies]
        return ['BTC', 'ETH', 'USDT', 'LTC', 'DOGE']
    except (requests.RequestException, ValueError, KeyError):
        return ['BTC', 'ETH', 'USDT', 'LTC', 'DOGE']
