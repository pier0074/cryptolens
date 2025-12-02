"""
Test Configuration and Fixtures
"""
import pytest
import os
import tempfile
from datetime import datetime, timezone

# Set test environment before importing app
os.environ['FLASK_ENV'] = 'testing'

from app import create_app, db
from app.models import Symbol, Candle, Pattern, Signal


@pytest.fixture(scope='function')
def app():
    """Create application for testing"""
    # Create a temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix='.db')

    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
        'SECRET_KEY': 'test-secret-key'
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture(scope='function')
def client(app):
    """Test client for making requests"""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Database session for tests"""
    with app.app_context():
        yield db.session


@pytest.fixture
def sample_symbol(app):
    """Create a sample symbol for testing"""
    with app.app_context():
        symbol = Symbol(symbol='BTC/USDT', exchange='binance', is_active=True)
        db.session.add(symbol)
        db.session.commit()
        return symbol.id


@pytest.fixture
def sample_candles_bullish_fvg(app, sample_symbol):
    """
    Create candles that form a bullish Fair Value Gap (imbalance)

    Bullish FVG: Candle 1 high < Candle 3 low (gap up)

    Candle 0: Base candle
    Candle 1: Low candle (sets the high boundary)
    Candle 2: Strong bullish move (creates the gap)
    Candle 3: Continuation (low is above candle 1 high)
    """
    with app.app_context():
        base_time = 1700000000000  # Base timestamp in ms
        candles_data = [
            # timestamp, open, high, low, close, volume
            (base_time, 100.0, 101.0, 99.0, 100.5, 1000),      # Candle 0
            (base_time + 60000, 100.5, 101.5, 100.0, 101.0, 1000),  # Candle 1 (high=101.5)
            (base_time + 120000, 102.0, 105.0, 101.8, 104.5, 2000), # Candle 2 (strong move)
            (base_time + 180000, 104.5, 106.0, 103.5, 105.5, 1500), # Candle 3 (low=103.5 > 101.5)
            (base_time + 240000, 105.5, 106.5, 105.0, 106.0, 1000), # Candle 4
        ]

        for ts, o, h, l, c, v in candles_data:
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=ts,
                open=o, high=h, low=l, close=c, volume=v
            )
            db.session.add(candle)

        db.session.commit()
        return sample_symbol


@pytest.fixture
def sample_candles_bearish_fvg(app, sample_symbol):
    """
    Create candles that form a bearish Fair Value Gap (imbalance)

    Bearish FVG: Candle 1 low > Candle 3 high (gap down)
    """
    with app.app_context():
        base_time = 1700000000000
        candles_data = [
            (base_time, 100.0, 101.0, 99.0, 100.5, 1000),
            (base_time + 60000, 100.5, 101.0, 99.5, 99.8, 1000),    # Candle 1 (low=99.5)
            (base_time + 120000, 99.0, 99.2, 95.0, 95.5, 2000),     # Candle 2 (strong down)
            (base_time + 180000, 95.5, 97.0, 94.5, 96.0, 1500),     # Candle 3 (high=97.0 < 99.5)
            (base_time + 240000, 96.0, 96.5, 95.0, 95.5, 1000),
        ]

        for ts, o, h, l, c, v in candles_data:
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=ts,
                open=o, high=h, low=l, close=c, volume=v
            )
            db.session.add(candle)

        db.session.commit()
        return sample_symbol


@pytest.fixture
def sample_candles_no_fvg(app, sample_symbol):
    """Create candles with no Fair Value Gap (overlapping wicks)"""
    with app.app_context():
        base_time = 1700000000000
        candles_data = [
            (base_time, 100.0, 101.0, 99.0, 100.5, 1000),
            (base_time + 60000, 100.5, 102.0, 100.0, 101.5, 1000),
            (base_time + 120000, 101.5, 103.0, 101.0, 102.5, 1000),  # Overlaps with candle 1
            (base_time + 180000, 102.5, 104.0, 102.0, 103.5, 1000),
            (base_time + 240000, 103.5, 105.0, 103.0, 104.5, 1000),
        ]

        for ts, o, h, l, c, v in candles_data:
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=ts,
                open=o, high=h, low=l, close=c, volume=v
            )
            db.session.add(candle)

        db.session.commit()
        return sample_symbol


@pytest.fixture
def sample_candles_small_fvg(app, sample_symbol):
    """Create candles with FVG smaller than minimum zone size (0.15%)"""
    with app.app_context():
        base_time = 1700000000000
        # Create a tiny FVG that's below 0.15% threshold
        # Gap between candle 1 high (100.05) and candle 3 low (100.10) = 0.05%
        # All other candles overlap to prevent other FVGs
        candles_data = [
            (base_time, 100.0, 100.2, 99.8, 100.1, 1000),       # 0: high=100.2
            (base_time + 60000, 100.0, 100.05, 99.9, 100.0, 1000),  # 1: high=100.05
            (base_time + 120000, 100.0, 100.15, 99.95, 100.1, 1000), # 2: overlaps with both
            (base_time + 180000, 100.1, 100.2, 100.10, 100.15, 1000), # 3: low=100.10 (gap=0.05%)
            (base_time + 240000, 100.1, 100.25, 100.05, 100.2, 1000), # 4: overlaps
        ]

        for ts, o, h, l, c, v in candles_data:
            candle = Candle(
                symbol_id=sample_symbol,
                timeframe='1h',
                timestamp=ts,
                open=o, high=h, low=l, close=c, volume=v
            )
            db.session.add(candle)

        db.session.commit()
        return sample_symbol


@pytest.fixture
def sample_pattern(app, sample_symbol):
    """Create a sample pattern for testing"""
    with app.app_context():
        pattern = Pattern(
            symbol_id=sample_symbol,
            timeframe='1h',
            pattern_type='imbalance',
            direction='bullish',
            zone_high=103.5,
            zone_low=101.5,
            detected_at=1700000180000,
            status='active'
        )
        db.session.add(pattern)
        db.session.commit()
        return pattern.id


@pytest.fixture
def sample_signal(app, sample_symbol, sample_pattern):
    """Create a sample signal for testing"""
    with app.app_context():
        signal = Signal(
            symbol_id=sample_symbol,
            direction='long',
            entry_price=103.5,
            stop_loss=100.0,
            take_profit_1=107.0,
            take_profit_2=110.5,
            take_profit_3=114.0,
            risk_reward=3.0,
            confluence_score=3,
            pattern_id=sample_pattern,
            status='pending'
        )
        db.session.add(signal)
        db.session.commit()
        return signal.id
