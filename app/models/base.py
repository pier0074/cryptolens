"""
Base utilities and constants for models
"""
from datetime import datetime, timezone, timedelta
from app import db


def _ensure_utc_naive(dt):
    """
    Ensure datetime is naive UTC for consistent comparisons.
    SQLite stores datetimes without timezone info, so we normalize all
    datetimes to naive UTC for comparison.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC and strip timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_now_naive():
    """Get current UTC time as a naive datetime (for SQLite compatibility)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Log categories
LOG_CATEGORIES = {
    'fetch': 'Data Fetching',
    'aggregate': 'Aggregation',
    'scan': 'Pattern Scanning',
    'signal': 'Signal Generation',
    'notify': 'Notifications',
    'system': 'System',
    'error': 'Errors'
}

# Log levels
LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

# Trade mood options for journal entries
TRADE_MOODS = ['confident', 'neutral', 'fearful', 'greedy', 'fomo', 'revenge']

# Trade status options
TRADE_STATUSES = ['pending', 'open', 'closed', 'cancelled']

# Payment status options
PAYMENT_STATUSES = ['pending', 'completed', 'failed', 'refunded', 'expired']
PAYMENT_PROVIDERS = ['lemonsqueezy', 'nowpayments']

# Subscription status options
SUBSCRIPTION_STATUSES = ['active', 'expired', 'cancelled', 'suspended']

# Subscription plan definitions (3-tier system)
SUBSCRIPTION_PLANS = {
    'free': {
        'name': 'Free',
        'price': 0,
        'price_yearly': 0,
        'days': None,  # Unlimited duration with limited features
        'tier': 'free',
    },
    'pro': {
        'name': 'Pro',
        'price': 19,  # Monthly
        'price_yearly': 190,  # ~$15.83/mo
        'days': 30,
        'tier': 'pro',
    },
    'premium': {
        'name': 'Premium',
        'price': 49,  # Monthly
        'price_yearly': 490,  # ~$40.83/mo
        'days': 30,
        'tier': 'premium',
    },
}

# Subscription tier feature limits
SUBSCRIPTION_TIERS = {
    'free': {
        'name': 'Free',
        'symbols': ['BTC/USDT'],  # Only BTC
        'max_symbols': 1,
        'daily_notifications': 3,
        'dashboard': 'limited',  # BTC only
        'patterns_page': False,
        'patterns_limit': 0,
        'signals_page': False,
        'signals_limit': 0,
        'analytics_page': False,
        'portfolio': False,
        'portfolio_limit': 0,
        'transactions_limit': 0,
        'backtest': False,
        'stats_page': 'limited',  # BTC only
        'api_access': False,
        'priority_support': False,
        'settings': ['ntfy'],  # Only NTFY settings
        'risk_parameters': False,
    },
    'pro': {
        'name': 'Pro',
        'symbols': None,  # Any symbol
        'max_symbols': 10,
        'daily_notifications': 100,
        'dashboard': 'full',
        'patterns_page': True,
        'patterns_limit': 100,  # Last 100 entries
        'signals_page': True,
        'signals_limit': 100,  # Last 100 entries
        'analytics_page': True,  # No recent backtest
        'portfolio': True,
        'portfolio_limit': 1,
        'transactions_limit': 10,
        'backtest': False,
        'stats_page': 'full',
        'api_access': False,
        'priority_support': False,
        'settings': ['ntfy', 'risk'],  # NTFY + Risk Parameters
        'risk_parameters': True,
    },
    'premium': {
        'name': 'Premium',
        'symbols': None,  # Any symbol
        'max_symbols': None,  # Unlimited
        'daily_notifications': None,  # Unlimited
        'dashboard': 'full',
        'patterns_page': True,
        'patterns_limit': None,  # Full history
        'signals_page': True,
        'signals_limit': None,  # Full history
        'analytics_page': True,  # Full with backtest
        'portfolio': True,
        'portfolio_limit': None,  # Unlimited
        'transactions_limit': None,  # Unlimited
        'backtest': True,
        'stats_page': 'full',
        'api_access': True,
        'priority_support': True,
        'settings': ['ntfy', 'risk'],  # NTFY + Risk Parameters
        'risk_parameters': True,
    },
}

# Cron job types
CRON_JOB_TYPES = {
    'fetch': {
        'name': 'Data Fetch',
        'description': 'Fetch 1-minute candles from exchange',
        'schedule': '* * * * *',  # Every minute
    },
    'gaps': {
        'name': 'Gap Fill',
        'description': 'Fill gaps in historical data',
        'schedule': '0 * * * *',  # Every hour
    },
    'cleanup': {
        'name': 'Cleanup',
        'description': 'Clean up old logs and expired data',
        'schedule': '0 0 * * *',  # Daily at midnight
    },
}
