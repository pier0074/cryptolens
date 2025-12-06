"""
Access Control Decorators
Decorators for enforcing subscription-based feature access.
"""
from functools import wraps
from flask import session, redirect, url_for, flash, request, abort, jsonify, g
from app.services.auth import get_user_by_id

# Tier hierarchy for comparison
TIER_HIERARCHY = {
    'free': 0,
    'pro': 1,
    'premium': 2,
}


def get_effective_tier(user):
    """
    Get the effective tier for a user, respecting admin 'view_as' mode.

    When an admin uses 'View as' to simulate a tier, this returns that tier
    instead of bypassing restrictions. Returns None if admin should have
    full access (no view_as or view_as='admin').
    """
    if user.is_admin:
        view_as = session.get('view_as')
        if view_as and view_as != 'admin':
            return view_as
        return None  # Full admin access
    return user.subscription_tier


def get_current_user():
    """Get the current logged-in user"""
    if 'user_id' in session:
        return get_user_by_id(session['user_id'])
    return None


def login_required(f):
    """Decorator to require login for a route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        user = get_user_by_id(session['user_id'])
        if not user or not user.is_admin:
            if request.is_json:
                return jsonify({'error': 'Admin access required'}), 403
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)
    return decorated_function


def subscription_required(f):
    """
    Decorator to require any valid subscription.
    User must be logged in and have an active/valid subscription.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        user = get_user_by_id(session['user_id'])
        if not user:
            session.pop('user_id', None)
            if request.is_json:
                return jsonify({'error': 'User not found'}), 401
            return redirect(url_for('auth.login'))

        if not user.has_valid_subscription:
            if request.is_json:
                return jsonify({'error': 'Valid subscription required'}), 403
            flash('An active subscription is required to access this feature.', 'warning')
            return redirect(url_for('auth.subscription'))

        return f(*args, **kwargs)
    return decorated_function


def tier_required(min_tier):
    """
    Decorator factory to require a minimum subscription tier.

    Args:
        min_tier: Minimum tier required ('free', 'pro', or 'premium')

    Usage:
        @tier_required('pro')
        def pro_feature():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login', next=request.url))

            user = get_user_by_id(session['user_id'])
            if not user:
                session.pop('user_id', None)
                if request.is_json:
                    return jsonify({'error': 'User not found'}), 401
                return redirect(url_for('auth.login'))

            # Get effective tier (respects admin 'view_as' mode)
            effective_tier = get_effective_tier(user)
            if effective_tier is None:
                # Admin with full access
                return f(*args, **kwargs)

            user_tier_level = TIER_HIERARCHY.get(effective_tier, 0)
            required_tier_level = TIER_HIERARCHY.get(min_tier, 0)

            if user_tier_level < required_tier_level:
                tier_names = {'free': 'Free', 'pro': 'Pro', 'premium': 'Premium'}
                required_name = tier_names.get(min_tier, min_tier.title())

                if request.is_json:
                    return jsonify({
                        'error': f'{required_name} subscription required',
                        'current_tier': effective_tier,
                        'required_tier': min_tier,
                    }), 403

                flash(f'This feature requires a {required_name} subscription or higher.', 'warning')
                return redirect(url_for('auth.subscription'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def feature_required(feature_name, redirect_on_fail='auth.subscription'):
    """
    Decorator factory to require access to a specific feature.

    Args:
        feature_name: The feature to check (from SUBSCRIPTION_TIERS)
        redirect_on_fail: Where to redirect if access denied (default: subscription page)

    Usage:
        @feature_required('backtest')
        def backtest_page():
            ...

        @feature_required('patterns_page')
        def patterns_list():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                if request.is_json:
                    return jsonify({'error': 'Authentication required'}), 401
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login', next=request.url))

            user = get_user_by_id(session['user_id'])
            if not user:
                session.pop('user_id', None)
                if request.is_json:
                    return jsonify({'error': 'User not found'}), 401
                return redirect(url_for('auth.login'))

            # Get effective tier (respects admin 'view_as' mode)
            effective_tier = get_effective_tier(user)
            if effective_tier is None:
                # Admin with full access
                return f(*args, **kwargs)

            # Check feature access for effective tier
            from app.models import SUBSCRIPTION_TIERS
            tier_features = SUBSCRIPTION_TIERS.get(effective_tier, SUBSCRIPTION_TIERS['free'])
            feature_value = tier_features.get(feature_name)

            # Check if feature is accessible
            has_access = False
            if isinstance(feature_value, bool):
                has_access = feature_value
            elif feature_value is not None:
                has_access = True

            if not has_access:
                feature_display = feature_name.replace('_', ' ').title()

                if request.is_json:
                    return jsonify({
                        'error': f'Access to {feature_display} not available in your plan',
                        'feature': feature_name,
                        'current_tier': effective_tier,
                    }), 403

                flash(f'Upgrade your subscription to access {feature_display}.', 'warning')
                return redirect(url_for(redirect_on_fail))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def check_feature_limit(feature_name, current_count=None):
    """
    Check if user has reached their feature limit.

    Args:
        feature_name: The feature limit to check (e.g., 'portfolio_limit')
        current_count: Current usage count (if None, just returns the limit)

    Returns:
        tuple: (has_remaining, limit, remaining)
            - has_remaining: True if user can use more
            - limit: The limit value (None = unlimited)
            - remaining: How many remaining (None = unlimited)
    """
    user = get_current_user()
    if not user:
        return False, 0, 0

    limit = user.get_feature_limit(feature_name)

    # Unlimited
    if limit is None:
        return True, None, None

    # No current count provided, just return limit info
    if current_count is None:
        return True, limit, limit

    remaining = max(0, limit - current_count)
    has_remaining = remaining > 0

    return has_remaining, limit, remaining


def limit_query_results(query, feature_name):
    """
    Apply limit to a query based on user's feature limits.

    Args:
        query: SQLAlchemy query object
        feature_name: The limit feature (e.g., 'patterns_limit', 'signals_limit')

    Returns:
        Limited query or original query if no limit
    """
    user = get_current_user()
    if not user:
        return query.limit(10)  # Default safety limit for anonymous

    limit = user.get_feature_limit(feature_name)

    if limit is None:
        return query  # No limit

    return query.limit(limit)


def get_allowed_symbols(user=None):
    """
    Get the list of symbols a user is allowed to access.

    Args:
        user: User object (if None, fetches current user)

    Returns:
        list or None: List of allowed symbols, or None for unlimited
    """
    if user is None:
        user = get_current_user()

    if not user:
        return ['BTC/USDT']  # Default for anonymous

    features = user.tier_features
    allowed = features.get('symbols')

    # None means any symbol allowed
    if allowed is None:
        return None

    return allowed


def filter_symbols_by_tier(symbols, user=None):
    """
    Filter a list of symbols based on user's tier access.

    Args:
        symbols: List of symbol strings or Symbol objects
        user: User object (if None, fetches current user)

    Returns:
        Filtered list of symbols
    """
    allowed = get_allowed_symbols(user)

    # No restriction
    if allowed is None:
        return symbols

    # Filter to allowed symbols
    result = []
    for sym in symbols:
        # Handle both strings and Symbol objects
        sym_str = sym if isinstance(sym, str) else sym.symbol
        if sym_str in allowed:
            result.append(sym)

    return result
