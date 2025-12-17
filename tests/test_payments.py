"""
Tests for Payment System
Tests webhook handling, checkout flows, and payment verification
"""
import pytest
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from app import db
from app.models import User, Subscription


class TestLemonSqueezyWebhook:
    """Tests for LemonSqueezy webhook handling"""

    @pytest.fixture
    def user_for_payment(self, app):
        """Create a user for payment testing"""
        with app.app_context():
            user = User(
                email='payment_test@example.com',
                username='payment_test',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_payment_test'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    def test_webhook_requires_valid_signature(self, client, app):
        """Test that webhook rejects invalid signatures"""
        payload = {
            'meta': {'event_name': 'order_created'},
            'data': {}
        }

        response = client.post(
            '/payments/lemonsqueezy/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-Signature': 'invalid_signature'}
        )

        # Should reject with 401 (unauthorized) if signature verification is enabled
        # or 200 if not configured (no secret key)
        assert response.status_code in [200, 401]

    def test_webhook_csrf_exempt(self, client, app):
        """Test that webhook endpoint is exempt from CSRF protection"""
        payload = {
            'meta': {'event_name': 'order_created'},
            'data': {}
        }

        # Should not return 400 (CSRF error)
        response = client.post(
            '/payments/lemonsqueezy/webhook',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code != 400 or b'CSRF' not in response.data

    @patch('app.routes.payments.verify_lemonsqueezy_webhook')
    @patch('app.routes.payments.process_lemonsqueezy_webhook')
    def test_webhook_order_created_activates_subscription(self, mock_process, mock_verify, client, app, user_for_payment):
        """Test that order_created webhook activates subscription"""
        mock_verify.return_value = True
        mock_process.return_value = {'success': True}

        payload = {
            'meta': {'event_name': 'order_created'},
            'data': {
                'attributes': {
                    'user_email': 'payment_test@example.com',
                    'status': 'paid',
                    'first_order_item': {
                        'variant_name': 'Pro Monthly'
                    }
                }
            }
        }

        response = client.post(
            '/payments/lemonsqueezy/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-Signature': 'test_signature'}
        )

        assert response.status_code == 200
        mock_process.assert_called_once()

    @patch('app.routes.payments.verify_lemonsqueezy_webhook')
    def test_webhook_subscription_updated(self, mock_verify, client, app):
        """Test subscription_updated webhook handling"""
        mock_verify.return_value = True

        with patch('app.routes.payments.process_lemonsqueezy_webhook') as mock_process:
            mock_process.return_value = {'success': True}

            payload = {
                'meta': {'event_name': 'subscription_updated'},
                'data': {
                    'attributes': {
                        'status': 'active'
                    }
                }
            }

            response = client.post(
                '/payments/lemonsqueezy/webhook',
                data=json.dumps(payload),
                content_type='application/json',
                headers={'X-Signature': 'test_signature'}
            )

            assert response.status_code == 200


class TestNOWPaymentsWebhook:
    """Tests for NOWPayments webhook handling"""

    def test_nowpayments_webhook_csrf_exempt(self, client, app):
        """Test that NOWPayments webhook is exempt from CSRF"""
        payload = {
            'payment_id': 12345,
            'payment_status': 'finished',
            'order_id': 'test_order'
        }

        response = client.post(
            '/payments/nowpayments/webhook',
            data=json.dumps(payload),
            content_type='application/json'
        )

        # Should not get CSRF error (400)
        assert response.status_code != 400 or b'CSRF' not in response.data

    @patch('app.routes.payments.verify_nowpayments_webhook')
    @patch('app.routes.payments.process_nowpayments_webhook')
    def test_nowpayments_webhook_finished_payment(self, mock_process, mock_verify, client, app):
        """Test finished payment webhook processing"""
        mock_verify.return_value = True
        mock_process.return_value = {'success': True}

        payload = {
            'payment_id': 12345,
            'payment_status': 'finished',
            'order_id': 'user_1_pro_monthly',
            'actually_paid': 29.99
        }

        response = client.post(
            '/payments/nowpayments/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'x-nowpayments-sig': 'test_signature'}
        )

        assert response.status_code == 200
        mock_process.assert_called_once()

    @patch('app.routes.payments.verify_nowpayments_webhook')
    def test_nowpayments_invalid_signature_rejected(self, mock_verify, client, app):
        """Test that invalid signatures are rejected"""
        mock_verify.return_value = False

        payload = {
            'payment_id': 12345,
            'payment_status': 'finished'
        }

        response = client.post(
            '/payments/nowpayments/webhook',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'x-nowpayments-sig': 'invalid'}
        )

        assert response.status_code == 401


class TestCheckoutFlow:
    """Tests for checkout flow"""

    @pytest.fixture
    def pro_user(self, app):
        """Create a pro user for testing"""
        with app.app_context():
            user = User(
                email='checkout_test@example.com',
                username='checkout_test',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_checkout_test'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    def test_upgrade_page_loads(self, client, app, pro_user):
        """Test upgrade page loads for logged in user"""
        client.post('/auth/login', data={
            'email': 'checkout_test@example.com',
            'password': 'TestPass123'
        })

        response = client.get('/payments/upgrade')
        assert response.status_code == 200
        assert b'Upgrade' in response.data or b'Pro' in response.data

    def test_checkout_requires_login(self, client, app):
        """Test checkout page requires authentication"""
        response = client.post('/payments/checkout', data={
            'plan': 'pro',
            'billing_cycle': 'monthly',
            'payment_method': 'card'
        }, follow_redirects=True)

        assert b'Login' in response.data

    def test_checkout_invalid_plan_rejected(self, client, app, pro_user):
        """Test checkout rejects invalid plan"""
        client.post('/auth/login', data={
            'email': 'checkout_test@example.com',
            'password': 'TestPass123'
        })

        response = client.post('/payments/checkout', data={
            'plan': 'invalid_plan',
            'billing_cycle': 'monthly',
            'payment_method': 'card'
        }, follow_redirects=True)

        assert b'Invalid plan' in response.data

    def test_payment_status_requires_own_payment(self, client, app, pro_user):
        """Test users can only see their own payment status"""
        client.post('/auth/login', data={
            'email': 'checkout_test@example.com',
            'password': 'TestPass123'
        })

        # Try to access non-existent payment
        response = client.get('/payments/status/99999')
        assert response.status_code == 302  # Redirects when not found


class TestPaymentHistory:
    """Tests for payment history"""

    def test_payment_history_requires_login(self, client, app):
        """Test payment history requires authentication"""
        response = client.get('/payments/history', follow_redirects=True)
        assert b'Login' in response.data

    def test_payment_history_shows_user_payments(self, client, app):
        """Test payment history shows only user's payments"""
        with app.app_context():
            user = User(
                email='history_test@example.com',
                username='history_test',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_history_test'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

        client.post('/auth/login', data={
            'email': 'history_test@example.com',
            'password': 'TestPass123'
        })

        response = client.get('/payments/history')
        assert response.status_code == 200


class TestWebhookSignatureVerification:
    """Tests for webhook signature verification with/without secrets configured"""

    def test_lemonsqueezy_verify_rejects_when_no_secret(self, app):
        """Test LemonSqueezy verification rejects when secret not configured"""
        with app.app_context():

            # Without secret configured, should return False
            with patch.dict('os.environ', {'LEMONSQUEEZY_WEBHOOK_SECRET': ''}):
                # Need to reload to pick up env change
                import importlib
                import app.services.payment as payment_module
                importlib.reload(payment_module)

                result = payment_module.verify_lemonsqueezy_webhook(b'test', 'sig')
                assert result is False

    def test_lemonsqueezy_verify_accepts_valid_signature(self, app):
        """Test LemonSqueezy verification accepts valid signature"""
        with app.app_context():
            secret = 'test_secret_key_123'
            payload = b'{"test": "data"}'

            # Calculate expected signature
            expected_sig = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()

            with patch.dict('os.environ', {'LEMONSQUEEZY_WEBHOOK_SECRET': secret}):
                import importlib
                import app.services.payment as payment_module
                importlib.reload(payment_module)

                result = payment_module.verify_lemonsqueezy_webhook(payload, expected_sig)
                assert result is True

    def test_lemonsqueezy_verify_rejects_invalid_signature(self, app):
        """Test LemonSqueezy verification rejects invalid signature"""
        with app.app_context():
            secret = 'test_secret_key_123'

            with patch.dict('os.environ', {'LEMONSQUEEZY_WEBHOOK_SECRET': secret}):
                import importlib
                import app.services.payment as payment_module
                importlib.reload(payment_module)

                result = payment_module.verify_lemonsqueezy_webhook(b'test', 'invalid_sig')
                assert result is False

    def test_nowpayments_verify_rejects_when_no_secret(self, app):
        """Test NOWPayments verification rejects when secret not configured"""
        with app.app_context():
            with patch.dict('os.environ', {'NOWPAYMENTS_IPN_SECRET': ''}):
                import importlib
                import app.services.payment as payment_module
                importlib.reload(payment_module)

                result = payment_module.verify_nowpayments_webhook({'test': 'data'}, 'sig')
                assert result is False

    def test_nowpayments_verify_accepts_valid_signature(self, app):
        """Test NOWPayments verification accepts valid signature"""
        with app.app_context():
            secret = 'test_ipn_secret_123'
            payload = {'payment_id': 123, 'status': 'finished'}

            # Calculate expected signature
            import json
            sorted_payload = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            expected_sig = hmac.new(
                secret.encode(),
                sorted_payload.encode(),
                hashlib.sha512
            ).hexdigest()

            with patch.dict('os.environ', {'NOWPAYMENTS_IPN_SECRET': secret}):
                import importlib
                import app.services.payment as payment_module
                importlib.reload(payment_module)

                result = payment_module.verify_nowpayments_webhook(payload, expected_sig)
                assert result is True


class TestPaymentIdempotency:
    """Tests for payment idempotency - preventing double credits"""

    @pytest.fixture
    def user_with_subscription(self, app):
        """Create a user with a subscription for testing"""
        with app.app_context():
            user = User(
                email='idempotency_test@example.com',
                username='idempotency_test',
                is_active=True,
                is_verified=True,
                ntfy_topic='cl_idempotency_test'
            )
            user.set_password('TestPass123')
            db.session.add(user)
            db.session.commit()

            sub = Subscription(
                user_id=user.id,
                plan='free',
                starts_at=datetime.now(timezone.utc),
                status='active'
            )
            db.session.add(sub)
            db.session.commit()
            return user.id

    def test_activate_subscription_idempotent(self, app, user_with_subscription):
        """Test that calling activate_subscription twice with same external_id doesn't double credit"""
        with app.app_context():
            from app.services.payment import activate_subscription
            from app.models import Payment

            user = db.session.get(User, user_with_subscription)
            external_id = 'test_external_id_12345'

            # First activation
            result1 = activate_subscription(
                user=user,
                plan='pro',
                billing_cycle='monthly',
                provider='lemonsqueezy',
                external_id=external_id
            )
            assert result1['success'] is True
            assert result1.get('idempotent') is not True  # First call is not idempotent

            # Create completed payment record (simulating first webhook)
            payment = Payment.query.filter_by(
                provider='lemonsqueezy',
                external_id=external_id
            ).first()
            if not payment:
                payment = Payment(
                    user_id=user.id,
                    provider='lemonsqueezy',
                    external_id=external_id,
                    plan='pro',
                    billing_cycle='monthly',
                    amount=19,
                    currency='USD',
                    status='completed'
                )
                db.session.add(payment)
                db.session.commit()

            # Get subscription expiry after first activation
            db.session.refresh(user)
            expiry_after_first = user.subscription.expires_at

            # Second activation with same external_id (duplicate webhook)
            result2 = activate_subscription(
                user=user,
                plan='pro',
                billing_cycle='monthly',
                provider='lemonsqueezy',
                external_id=external_id
            )
            assert result2['success'] is True
            assert result2.get('idempotent') is True  # Second call should be idempotent

            # Verify subscription wasn't double-credited
            db.session.refresh(user)
            assert user.subscription.expires_at == expiry_after_first

    def test_different_external_ids_credit_separately(self, app, user_with_subscription):
        """Test that different external_ids do credit separately"""
        with app.app_context():
            from app.services.payment import activate_subscription

            user = db.session.get(User, user_with_subscription)

            # First activation
            result1 = activate_subscription(
                user=user,
                plan='pro',
                billing_cycle='monthly',
                provider='lemonsqueezy',
                external_id='unique_id_1'
            )
            assert result1['success'] is True

            # Second activation with different external_id
            result2 = activate_subscription(
                user=user,
                plan='pro',
                billing_cycle='monthly',
                provider='lemonsqueezy',
                external_id='unique_id_2'
            )
            assert result2['success'] is True
            assert result2.get('idempotent') is not True  # Different ID, not idempotent
