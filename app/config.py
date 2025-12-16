import os
import secrets
from dotenv import load_dotenv

load_dotenv()


def is_production() -> bool:
    """
    Detect if running in production environment.

    Returns True if:
    - FLASK_ENV=production, or
    - ENV=production, or
    - Running on common PaaS (detected via env vars)
    """
    flask_env = os.getenv('FLASK_ENV', '').lower()
    env = os.getenv('ENV', '').lower()

    # Explicit production flag
    if flask_env == 'production' or env == 'production':
        return True

    # Common PaaS detection
    paas_indicators = [
        'DYNO',           # Heroku
        'RAILWAY_ENVIRONMENT',  # Railway
        'RENDER',         # Render
        'VERCEL',         # Vercel
        'FLY_APP_NAME',   # Fly.io
    ]
    for indicator in paas_indicators:
        if os.getenv(indicator):
            return True

    return False


def get_database_url() -> str:
    """
    Build MySQL database URL from environment variables.

    Supports two modes:
    1. Direct URL: DATABASE_URL env var (takes precedence)
    2. Split config: DB_HOST, DB_USER, DB_PASS, DB_NAME, DB_PORT

    In production, uses PROD_DB_* variables if available.
    In development, uses DB_* variables.
    """
    # Check for direct DATABASE_URL first (backwards compatible)
    direct_url = os.getenv('DATABASE_URL')
    if direct_url:
        return direct_url

    # Determine prefix based on environment
    prefix = 'PROD_DB' if is_production() else 'DB'

    # Get database configuration
    db_host = os.getenv(f'{prefix}_HOST', os.getenv('DB_HOST', 'localhost'))
    db_user = os.getenv(f'{prefix}_USER', os.getenv('DB_USER', 'root'))
    db_pass = os.getenv(f'{prefix}_PASS', os.getenv('DB_PASS', ''))
    db_name = os.getenv(f'{prefix}_NAME', os.getenv('DB_NAME', 'cryptolens'))
    db_port = os.getenv(f'{prefix}_PORT', os.getenv('DB_PORT', '3306'))

    # Build MySQL connection URL
    # Format: mysql+pymysql://user:pass@host:port/database
    if db_pass:
        return f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    else:
        return f"mysql+pymysql://{db_user}@{db_host}:{db_port}/{db_name}"


def get_secret_key() -> str:
    """
    Get or generate SECRET_KEY.

    Security: In production, SECRET_KEY MUST be set.
    In development, generates a random key but warns that sessions won't persist.
    """
    key = os.getenv('SECRET_KEY')
    if key:
        return key

    if is_production():
        raise ValueError(
            "CRITICAL: SECRET_KEY environment variable is required in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # Development mode - generate random key with warning
    import warnings
    warnings.warn(
        "SECRET_KEY not set - using random key. Sessions will be invalidated on restart. "
        "Set SECRET_KEY environment variable for persistent sessions.",
        UserWarning
    )
    return secrets.token_hex(32)


def get_engine_options() -> dict:
    """Get MySQL database engine options."""
    return {
        'pool_size': 10,
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'max_overflow': 20,
    }


class Config:
    """Base configuration"""
    SECRET_KEY = get_secret_key()
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = get_engine_options()

    # Environment detection (available to templates/code)
    IS_PRODUCTION = is_production()

    # NTFY.sh Notifications
    NTFY_TOPIC = os.getenv('NTFY_TOPIC', 'cryptolens-signals')
    NTFY_PRIORITY = int(os.getenv('NTFY_PRIORITY', 4))
    NTFY_URL = os.getenv('NTFY_URL', 'https://ntfy.sh')

    # Scanner Settings
    SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL_MINUTES', 5))

    # Available Symbols (for quick-add dropdown in Settings)
    # Top 100+ cryptocurrencies by market cap, sorted alphabetically
    SYMBOLS = [
        # Top 10
        'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'SOL/USDT',
        'ADA/USDT', 'DOGE/USDT', 'TRX/USDT', 'AVAX/USDT', 'LINK/USDT',
        # 11-30
        'TON/USDT', 'SHIB/USDT', 'DOT/USDT', 'BCH/USDT', 'LTC/USDT',
        'NEAR/USDT', 'UNI/USDT', 'PEPE/USDT', 'APT/USDT', 'ICP/USDT',
        'POL/USDT', 'ETC/USDT', 'RENDER/USDT', 'FET/USDT', 'STX/USDT',
        'TAO/USDT', 'ATOM/USDT', 'XMR/USDT', 'IMX/USDT', 'FIL/USDT',
        # 31-60
        'ARB/USDT', 'OP/USDT', 'INJ/USDT', 'HBAR/USDT', 'VET/USDT',
        'MKR/USDT', 'GRT/USDT', 'AAVE/USDT', 'RUNE/USDT', 'THETA/USDT',
        'WIF/USDT', 'BONK/USDT', 'FLOKI/USDT', 'SEI/USDT', 'SUI/USDT',
        'TIA/USDT', 'JUP/USDT', 'PYTH/USDT', 'STRK/USDT', 'WLD/USDT',
        'LDO/USDT', 'XLM/USDT', 'ALGO/USDT', 'FTM/USDT', 'SAND/USDT',
        'MANA/USDT', 'AXS/USDT', 'GALA/USDT', 'ENJ/USDT', 'CHZ/USDT',
        # 61-90
        'FLOW/USDT', 'NEO/USDT', 'EOS/USDT', 'XTZ/USDT', 'IOTA/USDT',
        'KAVA/USDT', 'ZEC/USDT', 'QTUM/USDT', 'DASH/USDT', 'WAVES/USDT',
        'SNX/USDT', 'CRV/USDT', 'COMP/USDT', 'YFI/USDT', 'SUSHI/USDT',
        '1INCH/USDT', 'BAL/USDT', 'ZRX/USDT', 'ENS/USDT', 'KSM/USDT',
        'ROSE/USDT', 'CELO/USDT', 'ONE/USDT', 'ANKR/USDT', 'SKL/USDT',
        'STORJ/USDT', 'ICX/USDT', 'ZIL/USDT', 'ONT/USDT', 'IOST/USDT',
        # 91-120 (DeFi, Gaming, Layer 2)
        'CAKE/USDT', 'DYDX/USDT', 'GMX/USDT', 'BLUR/USDT', 'MAGIC/USDT',
        'MEME/USDT', 'ORDI/USDT', 'SATS/USDT', 'RATS/USDT', 'PIXEL/USDT',
        'PORTAL/USDT', 'AEVO/USDT', 'BOME/USDT', 'SLERF/USDT', 'ONDO/USDT',
        'ENA/USDT', 'ETHFI/USDT', 'W/USDT', 'OMNI/USDT', 'REZ/USDT',
        'BB/USDT', 'NOT/USDT', 'IO/USDT', 'ZK/USDT', 'LISTA/USDT',
        'ZRO/USDT', 'BLAST/USDT', 'DOGS/USDT', 'NEIRO/USDT', 'TURBO/USDT'
    ]

    # Timeframes for pattern detection and UI display
    # Note: 1m excluded - too noisy for reliable pattern detection
    TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
    # PATTERN_TIMEFRAMES kept for backwards compatibility (same as TIMEFRAMES)
    PATTERN_TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']

    # Exchange (binance has better rate limits and 1000 candles/request)
    EXCHANGE = 'binance'

    # Data fetching
    BATCH_SIZE = 1000  # Binance allows 1000 candles per request
    RATE_LIMIT_DELAY = 0.5  # Minimum delay between API calls (seconds)
    MAX_CONCURRENT_REQUESTS = 5  # Max parallel API requests (Binance limit: 1200/min = 20/sec, this is conservative)
    RATE_LIMIT_RETRY_DELAY = 2.0  # Delay before retrying after rate limit error (seconds)
    MAX_RETRIES = 3  # Max retries for rate-limited requests
    INTER_SYMBOL_DELAY = 0.1  # Delay between starting each symbol fetch (seconds)

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

    # Email Configuration (SMTP)
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@cryptolens.app')
    MAIL_SENDER_NAME = os.getenv('MAIL_SENDER_NAME', 'CryptoLens')

    # Token expiry times
    EMAIL_VERIFICATION_EXPIRY_HOURS = 24
    PASSWORD_RESET_EXPIRY_HOURS = 1

    # Cache Configuration
    # Uses Redis if REDIS_URL is set, otherwise falls back to simple in-memory cache
    CACHE_TYPE = 'RedisCache' if os.getenv('REDIS_URL') else 'SimpleCache'
    CACHE_REDIS_URL = os.getenv('REDIS_URL')
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes default

    # Cache TTLs for specific data types
    CACHE_TTL_PATTERN_MATRIX = 60      # 1 minute - changes frequently
    CACHE_TTL_STATS = 300              # 5 minutes - moderate update frequency
    CACHE_TTL_USER_TIER = 3600         # 1 hour - rarely changes

    # Application URL (for email links)
    APP_URL = os.getenv('APP_URL', 'http://localhost:5000')

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


class TestingConfig(Config):
    """Testing configuration - uses MySQL test database"""
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    # Test database: uses TEST_DB_* env vars or defaults to cryptolens_test on localhost
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'TEST_DATABASE_URL',
        f"mysql+pymysql://{os.getenv('TEST_DB_USER', 'root')}:{os.getenv('TEST_DB_PASS', '')}@{os.getenv('TEST_DB_HOST', 'localhost')}:{os.getenv('TEST_DB_PORT', '3306')}/{os.getenv('TEST_DB_NAME', 'cryptolens_test')}"
    )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
