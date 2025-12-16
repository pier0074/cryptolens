"""
Tests for Email Service

Tests the email sending functionality with mocked SMTP.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.services.email import (
    send_email,
    send_verification_email,
    send_password_reset_email,
    send_welcome_email,
    send_password_changed_email,
    is_email_configured,
    EmailError
)


class TestIsEmailConfigured:
    """Test email configuration checking"""

    def test_email_not_configured_without_credentials(self, app):
        """Email reports not configured when no credentials"""
        with app.app_context():
            app.config['MAIL_USERNAME'] = None
            app.config['MAIL_PASSWORD'] = None
            assert is_email_configured() is False

    def test_email_configured_with_credentials(self, app):
        """Email reports configured when credentials present"""
        with app.app_context():
            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'
            assert is_email_configured() is True


class TestSendEmail:
    """Test core email sending functionality"""

    def test_send_email_success(self, app):
        """Send email succeeds with valid SMTP connection"""
        with app.app_context():
            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.get_smtp_connection') as mock_smtp:
                mock_connection = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_connection)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

                result = send_email(
                    to='recipient@example.com',
                    subject='Test Subject',
                    html_body='<p>Test body</p>'
                )
                assert result is True
                mock_connection.sendmail.assert_called_once()

    def test_send_email_failure(self, app):
        """Send email returns False on SMTP error"""
        with app.app_context():
            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.get_smtp_connection') as mock_smtp:
                mock_smtp.side_effect = Exception('SMTP error')

                result = send_email(
                    to='recipient@example.com',
                    subject='Test Subject',
                    html_body='<p>Test body</p>'
                )
                assert result is False

    def test_send_email_with_text_body(self, app):
        """Send email accepts custom text body"""
        with app.app_context():
            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.get_smtp_connection') as mock_smtp:
                mock_connection = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_connection)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

                result = send_email(
                    to='recipient@example.com',
                    subject='Test Subject',
                    html_body='<p>HTML body</p>',
                    text_body='Plain text body'
                )
                assert result is True


class TestSendVerificationEmail:
    """Test verification email functionality"""

    def test_send_verification_email(self, app, sample_user):
        """Verification email sends with correct content"""
        with app.app_context():
            from app.models import User
            user = User.query.filter_by(email='test@example.com').first()

            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.send_email') as mock_send:
                mock_send.return_value = True

                result = send_verification_email(user, 'test-token-123')
                assert result is True
                mock_send.assert_called_once()

                # Verify email parameters (positional args: to, subject, html_body)
                call_args = mock_send.call_args[0]
                assert call_args[0] == user.email
                assert 'Verify' in call_args[1]
                assert 'test-token-123' in call_args[2]


class TestSendPasswordResetEmail:
    """Test password reset email functionality"""

    def test_send_password_reset_email(self, app, sample_user):
        """Password reset email sends with correct content"""
        with app.app_context():
            from app.models import User
            user = User.query.filter_by(email='test@example.com').first()

            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.send_email') as mock_send:
                mock_send.return_value = True

                result = send_password_reset_email(user, 'reset-token-456')
                assert result is True
                mock_send.assert_called_once()

                # Verify email parameters (positional args: to, subject, html_body)
                call_args = mock_send.call_args[0]
                assert call_args[0] == user.email
                assert 'Reset' in call_args[1]
                assert 'reset-token-456' in call_args[2]


class TestSendWelcomeEmail:
    """Test welcome email functionality"""

    def test_send_welcome_email(self, app, sample_user):
        """Welcome email sends with correct content"""
        with app.app_context():
            from app.models import User
            user = User.query.filter_by(email='test@example.com').first()

            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.send_email') as mock_send:
                mock_send.return_value = True

                result = send_welcome_email(user)
                assert result is True
                mock_send.assert_called_once()

                # Verify email parameters (positional args: to, subject, html_body)
                call_args = mock_send.call_args[0]
                assert call_args[0] == user.email
                assert 'Welcome' in call_args[1]


class TestSendPasswordChangedEmail:
    """Test password changed notification email"""

    def test_send_password_changed_email(self, app, sample_user):
        """Password changed email sends with correct content"""
        with app.app_context():
            from app.models import User
            user = User.query.filter_by(email='test@example.com').first()

            app.config['MAIL_USERNAME'] = 'test@example.com'
            app.config['MAIL_PASSWORD'] = 'secret'

            with patch('app.services.email.send_email') as mock_send:
                mock_send.return_value = True

                result = send_password_changed_email(user)
                assert result is True
                mock_send.assert_called_once()

                # Verify email parameters (positional args: to, subject, html_body)
                call_args = mock_send.call_args[0]
                assert call_args[0] == user.email
                assert 'Changed' in call_args[1]
