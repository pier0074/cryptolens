"""
Email Service
Handles sending emails via SMTP for verification, password reset, etc.
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from flask import current_app

from app.models import User


class EmailError(Exception):
    """Email-related error"""
    pass


def get_smtp_connection():
    """
    Create and return an SMTP connection based on configuration.

    Returns:
        smtplib.SMTP or smtplib.SMTP_SSL connection
    """
    config = current_app.config

    server = config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = config.get('MAIL_PORT', 587)
    use_tls = config.get('MAIL_USE_TLS', True)
    use_ssl = config.get('MAIL_USE_SSL', False)
    username = config.get('MAIL_USERNAME')
    password = config.get('MAIL_PASSWORD')

    if not username or not password:
        raise EmailError("Email credentials not configured")

    context = ssl.create_default_context()
    timeout = 30  # 30 second timeout to prevent indefinite hangs

    if use_ssl:
        smtp = smtplib.SMTP_SSL(server, port, context=context, timeout=timeout)
    else:
        smtp = smtplib.SMTP(server, port, timeout=timeout)
        if use_tls:
            smtp.starttls(context=context)

    smtp.login(username, password)
    return smtp


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None
) -> bool:
    """
    Send an email.

    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML content of the email
        text_body: Plain text content (optional, will be generated from HTML if not provided)

    Returns:
        True if sent successfully, False otherwise
    """
    config = current_app.config

    sender_email = config.get('MAIL_DEFAULT_SENDER', 'noreply@cryptolens.app')
    sender_name = config.get('MAIL_SENDER_NAME', 'CryptoLens')

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{sender_email}>"
    msg['To'] = to

    # Add plain text part
    if not text_body:
        # Strip HTML tags for plain text version
        import re
        text_body = re.sub('<[^<]+?>', '', html_body)

    part1 = MIMEText(text_body, 'plain')
    part2 = MIMEText(html_body, 'html')

    msg.attach(part1)
    msg.attach(part2)

    try:
        with get_smtp_connection() as smtp:
            smtp.sendmail(sender_email, to, msg.as_string())
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {to}: {str(e)}")
        return False


def send_verification_email(user: User, token: str) -> bool:
    """
    Send email verification email to user.

    Args:
        user: User object
        token: Verification token

    Returns:
        True if sent successfully
    """
    config = current_app.config
    app_url = config.get('APP_URL', 'http://localhost:5000')
    verification_url = f"{app_url}/auth/verify-email/{token}"

    subject = "Verify Your CryptoLens Account"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .button:hover {{ background: #4f46e5; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to CryptoLens!</h1>
            </div>
            <div class="content">
                <p>Hi {user.username},</p>
                <p>Thank you for registering with CryptoLens. Please verify your email address by clicking the button below:</p>
                <p style="text-align: center;">
                    <a href="{verification_url}" class="button">Verify Email Address</a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #6366f1;">{verification_url}</p>
                <p>This link will expire in 24 hours.</p>
                <p>If you didn't create an account with CryptoLens, you can safely ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; CryptoLens - Crypto Trading Pattern Detection</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Welcome to CryptoLens!

    Hi {user.username},

    Thank you for registering with CryptoLens. Please verify your email address by clicking the link below:

    {verification_url}

    This link will expire in 24 hours.

    If you didn't create an account with CryptoLens, you can safely ignore this email.

    CryptoLens - Crypto Trading Pattern Detection
    """

    return send_email(user.email, subject, html_body, text_body)


def send_password_reset_email(user: User, token: str) -> bool:
    """
    Send password reset email to user.

    Args:
        user: User object
        token: Password reset token

    Returns:
        True if sent successfully
    """
    config = current_app.config
    app_url = config.get('APP_URL', 'http://localhost:5000')
    reset_url = f"{app_url}/auth/reset-password/{token}"

    subject = "Reset Your CryptoLens Password"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .button:hover {{ background: #4f46e5; }}
            .warning {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 15px; border-radius: 6px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Password Reset Request</h1>
            </div>
            <div class="content">
                <p>Hi {user.username},</p>
                <p>We received a request to reset your CryptoLens password. Click the button below to create a new password:</p>
                <p style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset Password</a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #6366f1;">{reset_url}</p>
                <div class="warning">
                    <strong>Important:</strong> This link will expire in 1 hour for security reasons.
                </div>
                <p>If you didn't request a password reset, please ignore this email or contact support if you're concerned about your account security.</p>
            </div>
            <div class="footer">
                <p>&copy; CryptoLens - Crypto Trading Pattern Detection</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_body = f"""
    Password Reset Request

    Hi {user.username},

    We received a request to reset your CryptoLens password. Click the link below to create a new password:

    {reset_url}

    This link will expire in 1 hour for security reasons.

    If you didn't request a password reset, please ignore this email or contact support if you're concerned about your account security.

    CryptoLens - Crypto Trading Pattern Detection
    """

    return send_email(user.email, subject, html_body, text_body)


def send_welcome_email(user: User) -> bool:
    """
    Send welcome email after successful verification.

    Args:
        user: User object

    Returns:
        True if sent successfully
    """
    config = current_app.config
    app_url = config.get('APP_URL', 'http://localhost:5000')

    subject = "Welcome to CryptoLens!"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .feature {{ background: white; padding: 15px; border-radius: 6px; margin: 10px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to CryptoLens!</h1>
            </div>
            <div class="content">
                <p>Hi {user.username},</p>
                <p>Your email has been verified and your account is now active!</p>

                <h3>What's Next?</h3>

                <div class="feature">
                    <strong>Set Up Notifications</strong>
                    <p>Configure your NTFY topic in settings to receive trading signals on your phone.</p>
                </div>

                <div class="feature">
                    <strong>Choose Your Plan</strong>
                    <p>Explore our subscription plans to unlock premium features and unlimited signals.</p>
                </div>

                <div class="feature">
                    <strong>Start Trading</strong>
                    <p>View the dashboard to see detected patterns and trading opportunities.</p>
                </div>

                <p style="text-align: center;">
                    <a href="{app_url}/dashboard" class="button">Go to Dashboard</a>
                </p>

                <p>If you have any questions, feel free to reach out to our support team.</p>

                <p>Happy Trading!</p>
            </div>
            <div class="footer">
                <p>&copy; CryptoLens - Crypto Trading Pattern Detection</p>
            </div>
        </div>
    </body>
    </html>
    """

    return send_email(user.email, subject, html_body)


def send_password_changed_email(user: User) -> bool:
    """
    Send notification that password was changed.

    Args:
        user: User object

    Returns:
        True if sent successfully
    """
    config = current_app.config
    app_url = config.get('APP_URL', 'http://localhost:5000')

    subject = "Your CryptoLens Password Was Changed"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
            .warning {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 15px; border-radius: 6px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Password Changed</h1>
            </div>
            <div class="content">
                <p>Hi {user.username},</p>
                <p>Your CryptoLens password was recently changed.</p>

                <div class="warning">
                    <strong>Wasn't you?</strong>
                    <p>If you didn't change your password, please reset it immediately and contact our support team.</p>
                    <p><a href="{app_url}/auth/forgot-password">Reset Password</a></p>
                </div>

                <p>If you did change your password, you can safely ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; CryptoLens - Crypto Trading Pattern Detection</p>
            </div>
        </div>
    </body>
    </html>
    """

    return send_email(user.email, subject, html_body)


def send_subscription_expiry_warning(user: User, days_remaining: int) -> bool:
    """
    Send subscription expiry warning email.

    Args:
        user: User object
        days_remaining: Days until subscription expires

    Returns:
        True if sent successfully
    """
    config = current_app.config
    app_url = config.get('APP_URL', 'http://localhost:5000')

    subject = f"Your CryptoLens Subscription Expires in {days_remaining} Day{'s' if days_remaining != 1 else ''}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #f59e0b, #ef4444); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Subscription Expiring Soon</h1>
            </div>
            <div class="content">
                <p>Hi {user.username},</p>
                <p>Your CryptoLens subscription will expire in <strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong>.</p>

                <p>Don't miss out on:</p>
                <ul>
                    <li>Real-time trading signals</li>
                    <li>Pattern detection alerts</li>
                    <li>Advanced analytics</li>
                </ul>

                <p style="text-align: center;">
                    <a href="{app_url}/auth/subscription" class="button">Renew Subscription</a>
                </p>

                <p>Thank you for being a CryptoLens user!</p>
            </div>
            <div class="footer">
                <p>&copy; CryptoLens - Crypto Trading Pattern Detection</p>
            </div>
        </div>
    </body>
    </html>
    """

    return send_email(user.email, subject, html_body)


def is_email_configured() -> bool:
    """
    Check if email is properly configured.

    Returns:
        True if email can be sent
    """
    config = current_app.config
    return bool(
        config.get('MAIL_USERNAME') and
        config.get('MAIL_PASSWORD')
    )
