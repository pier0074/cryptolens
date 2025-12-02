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
    # SQLite timeout to prevent "database is locked" errors
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'timeout': 30}  # Wait up to 30 seconds for locks
    }

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
    TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']

    # Exchange (binance has better rate limits and 1000 candles/request)
    EXCHANGE = 'binance'


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False

    def __init__(self):
        if not os.getenv('SECRET_KEY'):
            raise ValueError("SECRET_KEY environment variable is required in production")


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
