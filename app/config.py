import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///data/cryptolens.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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

    # Exchange
    EXCHANGE = 'kucoin'


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
