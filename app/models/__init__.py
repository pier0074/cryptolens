"""
Models package - exports all models and constants for backward compatibility

Usage:
    from app.models import User, Subscription, Pattern, Signal, ...
    from app.models import SUBSCRIPTION_PLANS, SUBSCRIPTION_TIERS, ...
"""

# Base utilities and constants
from app.models.base import (
    _ensure_utc_naive,
    _utc_now_naive,
    LOG_CATEGORIES,
    LOG_LEVELS,
    TRADE_MOODS,
    TRADE_STATUSES,
    PAYMENT_STATUSES,
    PAYMENT_PROVIDERS,
    SUBSCRIPTION_STATUSES,
    SUBSCRIPTION_PLANS,
    SUBSCRIPTION_TIERS,
    CRON_JOB_TYPES,
    CRON_CATEGORIES,
)

# System models
from app.models.system import (
    Log,
    Setting,
    StatsCache,
    Backtest,
    Payment,
    CronJob,
    CronRun,
    NotificationTemplate,
    BroadcastNotification,
    ScheduledNotification,
    NOTIFICATION_TEMPLATE_TYPES,
    NOTIFICATION_TARGETS,
)

# Trading models
from app.models.trading import (
    Symbol,
    Candle,
    Pattern,
    Signal,
    Notification,
    UserSymbolPreference,
)

# Portfolio models
from app.models.portfolio import (
    trade_tags,
    Portfolio,
    TradeTag,
    Trade,
    JournalEntry,
)

# User models
from app.models.user import (
    User,
    Subscription,
    UserNotification,
)

# Error tracking models
from app.models.errors import (
    ErrorLog,
    ErrorStats,
)

# Export all for 'from app.models import *'
__all__ = [
    # Utilities
    '_ensure_utc_naive',
    '_utc_now_naive',
    # Constants
    'LOG_CATEGORIES',
    'LOG_LEVELS',
    'TRADE_MOODS',
    'TRADE_STATUSES',
    'PAYMENT_STATUSES',
    'PAYMENT_PROVIDERS',
    'SUBSCRIPTION_STATUSES',
    'SUBSCRIPTION_PLANS',
    'SUBSCRIPTION_TIERS',
    'CRON_JOB_TYPES',
    'CRON_CATEGORIES',
    # System models
    'Log',
    'Setting',
    'StatsCache',
    'Backtest',
    'Payment',
    'CronJob',
    'CronRun',
    'NotificationTemplate',
    'BroadcastNotification',
    'ScheduledNotification',
    'NOTIFICATION_TEMPLATE_TYPES',
    'NOTIFICATION_TARGETS',
    # Trading models
    'Symbol',
    'Candle',
    'Pattern',
    'Signal',
    'Notification',
    'UserSymbolPreference',
    # Portfolio models
    'trade_tags',
    'Portfolio',
    'TradeTag',
    'Trade',
    'JournalEntry',
    # User models
    'User',
    'Subscription',
    'UserNotification',
    # Error tracking models
    'ErrorLog',
    'ErrorStats',
]
