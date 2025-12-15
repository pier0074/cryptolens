"""
Base utilities and constants for models
"""
from datetime import datetime, timezone, timedelta
from app import db


def _ensure_utc_naive(dt):
    """
    Ensure datetime is naive UTC for consistent comparisons.
    Normalizes all datetimes to naive UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC and strip timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_now_naive():
    """Get current UTC time as a naive datetime"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Log categories
LOG_CATEGORIES = {
    'fetch': 'Data Fetching',
    'aggregate': 'Aggregation',
    'scan': 'Pattern Scanning',
    'signal': 'Signal Generation',
    'notify': 'Notifications',
    'system': 'System',
    'error': 'Errors',
    'auth': 'Authentication',
    'user': 'User Actions',
    'trade': 'Trading',
    'payment': 'Payments',
    'backtest': 'Backtesting',
    'api': 'API Access',
    'admin': 'Admin Actions'
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
        'tagline': 'Perfect to get started',
        'features': [
            {'text': 'BTC/USDT trading pair', 'included': True},
            {'text': '1 notification per day', 'included': True},
            {'text': 'FVG pattern detection', 'included': True},
            {'text': '10 minute notification delay', 'included': False},
            {'text': 'No portfolio tracking', 'included': False},
        ],
    },
    'pro': {
        'name': 'Pro',
        'price': 19,  # Monthly
        'price_yearly': 190,  # ~$15.83/mo
        'days': 30,
        'tier': 'pro',
        'tagline': 'For active traders',
        'features': [
            {'text': '5 symbols (BTC, ETH, XRP, BNB, SOL)', 'included': True},
            {'text': '20 notifications per day', 'included': True},
            {'text': '3 pattern types (FVG, OB, Sweep)', 'included': True},
            {'text': '1 portfolio with 5 trades/day', 'included': True},
            {'text': 'Real-time notifications', 'included': True},
            {'text': 'Last 100 patterns & 50 signals', 'included': True},
        ],
    },
    'premium': {
        'name': 'Premium',
        'price': 49,  # Monthly
        'price_yearly': 490,  # ~$40.83/mo
        'days': 30,
        'tier': 'premium',
        'tagline': 'For professional traders',
        'features': [
            {'text': 'Unlimited symbols', 'included': True},
            {'text': 'Unlimited notifications', 'included': True},
            {'text': 'All pattern types', 'included': True},
            {'text': 'Unlimited portfolios & trades', 'included': True},
            {'text': 'Full history & backtesting', 'included': True},
            {'text': 'REST API access', 'included': True},
        ],
    },
}

# Subscription tier feature limits
SUBSCRIPTION_TIERS = {
    'free': {
        'name': 'Free',
        'symbols': ['BTC/USDT'],  # Only BTC
        'max_symbols': 1,
        'pattern_types': ['imbalance'],  # FVG only
        'daily_notifications': 1,
        'notification_delay_minutes': 10,  # 10-minute delay
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
        'max_symbols': 5,
        'pattern_types': ['imbalance', 'order_block', 'liquidity_sweep'],  # Current 3 patterns
        'daily_notifications': 20,
        'notification_delay_minutes': 0,  # No delay
        'dashboard': 'full',
        'patterns_page': True,
        'patterns_limit': 100,  # Last 100 entries
        'signals_page': True,
        'signals_limit': 50,  # Last 50 entries
        'analytics_page': True,
        'portfolio': True,
        'portfolio_limit': 1,
        'transactions_limit': 5,  # 5 tx/day
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
        'pattern_types': None,  # All pattern types
        'daily_notifications': None,  # Unlimited
        'notification_delay_minutes': 0,  # No delay
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

# Cron job categories
CRON_CATEGORIES = {
    'data': {
        'name': 'Data Collection',
        'description': 'Jobs that fetch and collect market data',
        'order': 1,
    },
    'analysis': {
        'name': 'Analysis',
        'description': 'Jobs that analyze data and detect patterns',
        'order': 2,
    },
    'maintenance': {
        'name': 'Maintenance',
        'description': 'Jobs that maintain data quality and cleanup',
        'order': 3,
    },
    'workflow': {
        'name': 'Workflows',
        'description': 'Combined jobs that run multiple operations',
        'order': 4,
    },
}

# Cron job types
CRON_JOB_TYPES = {
    'fetch': {
        'name': 'Data Fetch',
        'description': 'Fetch 1-minute candles from exchange',
        'schedule': '* * * * *',  # Every minute
        'category': 'data',
    },
    'gaps': {
        'name': 'Gap Fill',
        'description': 'Fill gaps in historical data',
        'schedule': '0 * * * *',  # Every hour
        'category': 'data',
    },
    'historical_fetch': {
        'name': 'Historical Fetch',
        'description': 'Fetch historical candle data from target date',
        'schedule': 'manual',
        'category': 'data',
    },
    'pattern_scan': {
        'name': 'Pattern Scan',
        'description': 'Scan candle data for chart patterns (FVG, Order Blocks, Liquidity)',
        'schedule': 'manual',
        'category': 'analysis',
    },
    'stats': {
        'name': 'Stats Refresh',
        'description': 'Recompute database statistics cache',
        'schedule': 'manual',
        'category': 'analysis',
    },
    'cleanup': {
        'name': 'Cleanup',
        'description': 'Clean up old logs and expired data',
        'schedule': '0 0 * * *',  # Daily at midnight
        'category': 'maintenance',
    },
    'sanitize': {
        'name': 'Sanitize',
        'description': 'Verify candle data integrity (OHLCV, gaps, alignment)',
        'schedule': '0 3 * * *',  # Daily at 3 AM
        'category': 'maintenance',
    },
    'full_cycle': {
        'name': 'Full Cycle',
        'description': 'Complete cycle: fetch → pattern scan → stats refresh',
        'schedule': 'manual',
        'category': 'workflow',
    },
    'symbol_fix': {
        'name': 'Symbol Fix',
        'description': 'Fix candle data integrity for a specific symbol',
        'schedule': 'manual',
        'category': 'maintenance',
    },
}
