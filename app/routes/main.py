"""
Main Routes
Public-facing pages including landing page
"""
from flask import Blueprint, render_template, redirect, url_for, session
from app import db
from app.models import User, Pattern, Signal, Symbol, SUBSCRIPTION_PLANS

main_bp = Blueprint('main', __name__)


def get_current_user():
    """Get the current logged-in user"""
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None


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
