"""
Application Constants
Centralized configuration values for the application
"""

# =============================================================================
# SECURITY CONSTANTS
# =============================================================================

# Account lockout settings
LOCKOUT_MAX_ATTEMPTS = 5  # Failed login attempts before lockout
LOCKOUT_DURATION_MINUTES = 15  # Lockout duration in minutes

# Circuit breaker settings
CIRCUIT_BREAKER_FAIL_MAX = 5  # Failures before circuit opens
CIRCUIT_BREAKER_RESET_TIMEOUT = 30  # Seconds before circuit resets

# =============================================================================
# HTTP/API CONSTANTS
# =============================================================================

# Request timeouts (seconds)
HTTP_TIMEOUT_DEFAULT = 10
HTTP_TIMEOUT_LONG = 30
HTTP_TIMEOUT_CRON = 120

# Retry settings
HTTP_MAX_RETRIES = 3

# =============================================================================
# NOTIFICATION CONSTANTS
# =============================================================================

# NTFY priority levels
PRIORITY_MIN = 1
PRIORITY_LOW = 2
PRIORITY_DEFAULT = 3
PRIORITY_HIGH = 4
PRIORITY_URGENT = 5

# =============================================================================
# DATA FETCHING CONSTANTS
# =============================================================================

# Candle limits for different operations
CANDLES_LIMIT_DEFAULT = 200  # Default for pattern detection
CANDLES_LIMIT_BACKTEST = 5000  # For backtesting
CANDLES_LIMIT_SIGNAL = 1  # For current price lookup

# Historical data defaults
HISTORICAL_DAYS_DEFAULT = 30

# =============================================================================
# PATTERN DETECTION CONSTANTS
# =============================================================================

# Swing point detection
SWING_LOOKBACK_DEFAULT = 5

# Pattern overlap threshold for deduplication
PATTERN_OVERLAP_THRESHOLD = 0.70
