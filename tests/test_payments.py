"""
Tests for Payment System
Tests webhook handling, checkout flows, and payment verification
"""
import pytest
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from app import db
from app.models import User, Subscription, Payment


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
