import os
import secrets
from dotenv import load_dotenv

load_dotenv()


def get_secret_key():
    """Get or generate SECRET_KEY"""
    key = os.getenv('SECRET_KEY')
    if key:
        return key
    # In development, generate a random key (will change on restart)
    # In production, SECRET_KEY env var should be set
    return secrets.token_hex(32)


class Config:
    """Base configuration"""
    SECRET_KEY = get_secret_key()
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///data/cryptolens.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Database engine options
    # For SQLite: timeout prevents "database is locked" errors
    # For PostgreSQL/MySQL: add pool_size, pool_recycle for connection pooling
    @staticmethod
    def get_engine_options():
        """Get database engine options based on database type."""
        db_url = os.getenv('DATABASE_URL', 'sqlite:///data/cryptolens.db')

        if db_url.startswith('sqlite'):
            # SQLite uses NullPool by default, no connection pooling needed
            return {
                'connect_args': {'timeout': 30},  # Wait up to 30s for locks
                'pool_pre_ping': True,  # Verify connections before use
            }
        else:
            # PostgreSQL/MySQL connection pooling
            return {
                'pool_size': 10,        # Number of connections to keep
                'pool_recycle': 300,    # Recycle connections after 5 min
                'pool_pre_ping': True,  # Verify connections before use
                'max_overflow': 20,     # Allow 20 additional connections
            }

    SQLALCHEMY_ENGINE_OPTIONS = get_engine_options.__func__()

    # NTFY.sh Notifications
    NTFY_TOPIC = os.getenv('NTFY_TOPIC', 'cryptolens-signals')
    NTFY_PRIORITY = int(os.getenv('NTFY_PRIORITY', 4))
    NTFY_URL = 'https://ntfy.sh'

    # Scanner Settings
    SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', 5))

    # Default Symbols
    SYMBOLS = [
        'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT',
        'DOGE/USDT', 'SOL/USDT', 'DOT/USDT', 'POL/USDT', 'LTC/USDT',
        'SHIB/USDT', 'TRX/USDT', 'AVAX/USDT', 'LINK/USDT', 'ATOM/USDT',
        'UNI/USDT', 'XMR/USDT', 'ETC/USDT', 'XLM/USDT', 'BCH/USDT',
        'APT/USDT', 'FIL/USDT', 'LDO/USDT', 'ARB/USDT', 'OP/USDT',
        'NEAR/USDT', 'INJ/USDT', 'RUNE/USDT', 'AAVE/USDT', 'GRT/USDT'
    ]

    # Timeframes
    TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']  # All timeframes (for UI)
    PATTERN_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d']  # For pattern detection (1m too noisy)

    # Exchange (binance has better rate limits and 1000 candles/request)
    EXCHANGE = 'binance'

    # Data fetching
    BATCH_SIZE = 1000  # Binance allows 1000 candles per request
    RATE_LIMIT_DELAY = 0.1  # Minimum delay between API calls (seconds)

    # Pattern detection
    MIN_ZONE_PERCENT = 0.15  # Minimum zone size as % of price
    ORDER_BLOCK_STRENGTH_MULTIPLIER = 1.5  # Body must be this much larger than avg

    # Timeframe overlap thresholds (for pattern deduplication)
    OVERLAP_THRESHOLDS = {
        '1m': 0.50, '5m': 0.55, '15m': 0.60, '30m': 0.65,
        '1h': 0.70, '2h': 0.75, '4h': 0.80, '1d': 0.85,
    }
    DEFAULT_OVERLAP_THRESHOLD = 0.70

    # Timeframe to milliseconds mapping (for historical fetch calculations)
    TIMEFRAME_MS = {
        '1m': 60 * 1000,
        '5m': 5 * 60 * 1000,
        '15m': 15 * 60 * 1000,
        '30m': 30 * 60 * 1000,
        '1h': 60 * 60 * 1000,
        '2h': 2 * 60 * 60 * 1000,
        '4h': 4 * 60 * 60 * 1000,
        '1d': 24 * 60 * 60 * 1000
    }

    # Pattern expiry: How long patterns stay valid before auto-expiring (in hours)
    # Lower timeframes expire faster as they're less significant
    PATTERN_EXPIRY_HOURS = {
        '1m': 4,       # 4 hours
        '5m': 12,      # 12 hours
        '15m': 24,     # 1 day
        '30m': 48,     # 2 days
        '1h': 72,      # 3 days
        '2h': 120,     # 5 days
        '4h': 168,     # 7 days
        '1d': 336,     # 14 days
    }
    DEFAULT_PATTERN_EXPIRY_HOURS = 72  # 3 days default


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False

    def __init__(self):
        if not os.getenv('SECRET_KEY'):
            raise ValueError("SECRET_KEY environment variable is required in production")


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
