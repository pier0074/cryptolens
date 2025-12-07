"""
Main Routes
Public-facing pages including landing page
"""
from flask import Blueprint, render_template, redirect, url_for
from app.models import Pattern, Signal, Symbol, SUBSCRIPTION_PLANS
from app.decorators import get_current_user

main_bp = Blueprint('main', __name__)


@main_bp.route('/landing')
def landing():
    """Public landing page"""
    # Get some stats for social proof
    stats = {
        'patterns_detected': Pattern.query.count(),
        'signals_generated': Signal.query.count(),
        'symbols_tracked': Symbol.query.filter_by(is_active=True).count(),
    }

    return render_template('landing.html',
        plans=SUBSCRIPTION_PLANS,
        stats=stats,
        user=get_current_user()
    )


@main_bp.route('/pricing')
def pricing():
    """Public pricing page"""
    return render_template('pricing.html',
        plans=SUBSCRIPTION_PLANS,
        user=get_current_user()
    )


@main_bp.route('/features')
def features():
    """Features page"""
    return render_template('features.html',
        user=get_current_user()
    )


@main_bp.route('/privacy')
def privacy():
    """Privacy Policy page"""
    return render_template('legal/privacy.html',
        user=get_current_user()
    )


@main_bp.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('legal/terms.html',
        user=get_current_user()
    )
