"""
Tests for Database Health Check Script (Hierarchical Verification)

Tests the candle verification functions including:
- OHLCV sanity checks
- Timestamp alignment checks
- Gap detection
- Aggregation validation (recalculation from 1m)
- Hierarchical verification (1m first, then aggregated)
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol, Candle, KnownGap
from scripts.db_health import (
    check_candle_ohlcv,
    check_candle_alignment,
    check_gap,
    get_1m_candles_for_aggregation,
    calculate_aggregated_ohlcv,
    validate_aggregated_candle,
    verify_1m_candles,
    verify_aggregated_candles,
    get_verification_stats,
    reset_verification,
    BATCH_SIZES,
    TF_MS,
    TF_1M_COUNT
)


@pytest.fixture
def app():
    """Create test app with MySQL test database."""
    app = create_app('testing')
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def test_symbol(app):
    """Create a test symbol."""
    with app.app_context():
        symbol = Symbol(symbol='TEST/USDT', is_active=True)
        db.session.add(symbol)
        db.session.commit()
        return symbol.id


class TestCandleOHLCVCheck:
    """Test OHLCV sanity checks for individual candles."""

    def test_valid_candle(self, app, test_symbol):
        """Valid OHLCV should return no problems."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=105, low=95, close=102, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert problems == []

    def test_high_less_than_low(self, app, test_symbol):
        """high < low should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=95, low=105, close=100, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'high < low' in problems

    def test_high_less_than_open(self, app, test_symbol):
        """high < open should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=110, high=105, low=95, close=100, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'high < open' in problems

    def test_high_less_than_close(self, app, test_symbol):
        """high < close should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=105, low=95, close=110, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'high < close' in problems

    def test_low_greater_than_open(self, app, test_symbol):
        """low > open should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=90, high=105, low=95, close=100, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'low > open' in problems

    def test_low_greater_than_close(self, app, test_symbol):
        """low > close should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=105, low=95, close=90, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'low > close' in problems

    def test_negative_volume(self, app, test_symbol):
        """Negative volume should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=105, low=95, close=102, volume=-500
            )
            problems = check_candle_ohlcv(candle)
            assert 'volume < 0' in problems

    def test_zero_price(self, app, test_symbol):
        """Zero prices should be detected."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=0, high=105, low=95, close=102, volume=1000
            )
            problems = check_candle_ohlcv(candle)
            assert 'price <= 0' in problems

    def test_multiple_errors(self, app, test_symbol):
        """Multiple errors should all be reported."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=110, high=95, low=105, close=120, volume=-100
            )
            problems = check_candle_ohlcv(candle)
            assert len(problems) >= 3


class TestCandleAlignmentCheck:
    """Test timestamp alignment checks for candles."""

    def test_1m_always_aligned(self, app, test_symbol):
        """1m candles are always aligned."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000012345,
                open=100, high=101, low=99, close=100, volume=1000
            )
            assert check_candle_alignment(candle) is True

    def test_5m_aligned(self, app, test_symbol):
        """5m candles at :00, :05, etc. are aligned."""
        with app.app_context():
            # 1699999800000 / 60000 = 28333330 minutes, 28333330 % 5 = 0
            candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=1699999800000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            assert check_candle_alignment(candle) is True

    def test_5m_misaligned(self, app, test_symbol):
        """5m candles at :01, :02, etc. are misaligned."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=1700000060000,  # minute 1
                open=100, high=101, low=99, close=100, volume=1000
            )
            assert check_candle_alignment(candle) is False

    def test_1h_aligned(self, app, test_symbol):
        """1h candles at :00 are aligned."""
        with app.app_context():
            # 1700002800000 / 60000 = 28333380, 28333380 % 60 = 0
            candle = Candle(
                symbol_id=test_symbol, timeframe='1h',
                timestamp=1700002800000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            assert check_candle_alignment(candle) is True

    def test_1h_misaligned(self, app, test_symbol):
        """1h candles at :22 are misaligned."""
        with app.app_context():
            candle = Candle(
                symbol_id=test_symbol, timeframe='1h',
                timestamp=1700002800000 + 22 * 60000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            assert check_candle_alignment(candle) is False


class TestGapCheck:
    """Test gap detection between candles."""

    def test_no_gap(self, app, test_symbol):
        """Consecutive candles have no gap."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000060000,  # +1 minute
                open=100, high=101, low=99, close=100, volume=1000
            )
            missing = check_gap(prev, curr, 60000)
            assert missing == 0

    def test_single_gap(self, app, test_symbol):
        """One missing candle detected."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000120000,  # +2 minutes (1 missing)
                open=100, high=101, low=99, close=100, volume=1000
            )
            missing = check_gap(prev, curr, 60000)
            assert missing == 1

    def test_large_gap(self, app, test_symbol):
        """Multiple missing candles detected."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000600000,  # +10 minutes (9 missing)
                open=100, high=101, low=99, close=100, volume=1000
            )
            missing = check_gap(prev, curr, 60000)
            assert missing == 9


class TestBatchSizes:
    """Test batch size constants."""

    def test_day_batch_size(self):
        """Day batch size is correct."""
        assert BATCH_SIZES['day'] == 1440  # 60 * 24

    def test_week_batch_size(self):
        """Week batch size is correct."""
        assert BATCH_SIZES['week'] == 10080  # 1440 * 7


class TestAggregationCalculation:
    """Test aggregation calculation from 1m candles."""

    def test_calculate_ohlcv_from_1m(self, app, test_symbol):
        """Calculate OHLCV from 1m candles correctly."""
        with app.app_context():
            # Create 5 1m candles for a 5m aggregation
            candles_1m = []
            for i in range(5):
                candle = Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=1700000000000 + i * 60000,
                    open=100 + i,    # 100, 101, 102, 103, 104
                    high=105 + i,    # 105, 106, 107, 108, 109
                    low=95 + i,      # 95, 96, 97, 98, 99
                    close=101 + i,   # 101, 102, 103, 104, 105
                    volume=1000 + i * 100  # 1000, 1100, 1200, 1300, 1400
                )
                candles_1m.append(candle)

            result = calculate_aggregated_ohlcv(candles_1m)

            assert result['open'] == 100       # First candle open
            assert result['high'] == 109       # Max high
            assert result['low'] == 95         # Min low
            assert result['close'] == 105      # Last candle close
            assert result['volume'] == 6000    # Sum of volumes

    def test_calculate_empty_returns_none(self):
        """Empty candle list returns None."""
        result = calculate_aggregated_ohlcv([])
        assert result is None


class TestAggregationValidation:
    """Test aggregation validation (recalculation check)."""

    def test_valid_aggregation(self, app, test_symbol):
        """Valid aggregated candle passes validation."""
        with app.app_context():
            # Create 5 1m candles
            candles_1m = []
            base_ts = 1700000000000
            for i in range(5):
                candle = Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                )
                candles_1m.append(candle)

            # Create matching aggregated candle
            agg_candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100, high=105, low=95, close=100, volume=5000
            )

            problems = validate_aggregated_candle(agg_candle, candles_1m)
            assert problems == []

    def test_mismatched_open(self, app, test_symbol):
        """Aggregated candle with wrong open is detected."""
        with app.app_context():
            candles_1m = []
            base_ts = 1700000000000
            for i in range(5):
                candle = Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                )
                candles_1m.append(candle)

            # Wrong open
            agg_candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=110,  # Wrong!
                high=105, low=95, close=100, volume=5000
            )

            problems = validate_aggregated_candle(agg_candle, candles_1m)
            assert len(problems) > 0
            assert any('open mismatch' in p for p in problems)

    def test_mismatched_high(self, app, test_symbol):
        """Aggregated candle with wrong high is detected."""
        with app.app_context():
            candles_1m = []
            base_ts = 1700000000000
            for i in range(5):
                candle = Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                )
                candles_1m.append(candle)

            # Wrong high
            agg_candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100,
                high=110,  # Wrong!
                low=95, close=100, volume=5000
            )

            problems = validate_aggregated_candle(agg_candle, candles_1m)
            assert len(problems) > 0
            assert any('high mismatch' in p for p in problems)

    def test_mismatched_volume(self, app, test_symbol):
        """Aggregated candle with wrong volume is detected."""
        with app.app_context():
            candles_1m = []
            base_ts = 1700000000000
            for i in range(5):
                candle = Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                )
                candles_1m.append(candle)

            # Wrong volume (>1% off)
            agg_candle = Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100, high=105, low=95, close=100,
                volume=6000  # Wrong! Should be 5000
            )

            problems = validate_aggregated_candle(agg_candle, candles_1m)
            assert len(problems) > 0
            assert any('volume mismatch' in p for p in problems)


class TestVerify1mCandles:
    """Test 1m candle verification."""

    def test_verify_valid_candles(self, app, test_symbol):
        """Valid candles should be verified."""
        with app.app_context():
            base_ts = 1700000000000
            for i in range(10):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)
            result = verify_1m_candles(test_symbol, symbol, fix=False)
            assert result['verified'] == 10
            assert result['error'] is None

    def test_stop_on_ohlcv_error(self, app, test_symbol):
        """Verification should stop on OHLCV error."""
        with app.app_context():
            base_ts = 1700000000000
            # 5 valid candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            # 1 invalid candle
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=base_ts + 5 * 60000,
                open=100, high=95, low=105, close=100, volume=1000  # Invalid!
            ))
            # 4 more valid candles
            for i in range(6, 10):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)
            result = verify_1m_candles(test_symbol, symbol, fix=False)
            assert result['verified'] == 5
            assert result['error'] is not None
            assert result['error']['type'] == 'ohlcv_invalid'

    def test_stop_on_gap(self, app, test_symbol):
        """Verification should stop on gap."""
        with app.app_context():
            base_ts = 1700000000000
            # 5 valid candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            # Gap: skip minute 5, add minute 10
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=base_ts + 10 * 60000,
                open=100, high=101, low=99, close=100, volume=1000
            ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)
            result = verify_1m_candles(test_symbol, symbol, fix=False)
            assert result['verified'] == 5
            assert result['error'] is not None
            assert result['error']['type'] == 'gap'
            assert result['error']['missing_candles'] == 5

    def test_fix_deletes_invalid(self, app, test_symbol):
        """Fix mode should delete invalid candle."""
        with app.app_context():
            base_ts = 1700000000000
            # 2 valid, 1 invalid
            for i in range(2):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=base_ts + 2 * 60000,
                open=100, high=95, low=105, close=100, volume=1000  # Invalid
            ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)
            result = verify_1m_candles(test_symbol, symbol, fix=True)
            assert result['verified'] == 2
            assert result['error']['action'] == 'deleted'

            # Verify the invalid candle was deleted
            count = Candle.query.filter_by(
                symbol_id=test_symbol, timeframe='1m'
            ).count()
            assert count == 2

    def test_incremental_continues_from_last(self, app, test_symbol):
        """Second run should continue from where first stopped."""
        with app.app_context():
            base_ts = 1700000000000
            # 10 valid candles
            for i in range(10):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)

            # First run with batch_size=5
            result1 = verify_1m_candles(
                test_symbol, symbol, fix=False, batch_size=5
            )
            assert result1['verified'] == 5

            # Second run should verify remaining 5
            result2 = verify_1m_candles(
                test_symbol, symbol, fix=False, batch_size=5
            )
            assert result2['verified'] == 5

            # Third run - all verified
            result3 = verify_1m_candles(
                test_symbol, symbol, fix=False, batch_size=5
            )
            assert result3['verified'] == 0
            assert result3['all_done'] is True


class TestVerifyAggregatedCandles:
    """Test aggregated candle verification."""

    def test_verify_with_all_1m_verified(self, app, test_symbol):
        """Aggregated candles verify when 1m are verified."""
        with app.app_context():
            # Use 5m-aligned timestamp: 28333330 * 60000 = 1699999800000
            # 28333330 % 5 = 0, so this is properly 5m-aligned
            base_ts = 1699999800000
            now_ms = base_ts + 10 * 60000

            # Create 5 verified 1m candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=now_ms
                ))

            # Create matching 5m candle
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100, high=105, low=95, close=100, volume=5000
            ))
            db.session.commit()

            result = verify_aggregated_candles(
                test_symbol, 'TEST/USDT', '5m', fix=False
            )
            assert result['verified'] == 1
            assert result['error'] is None

    def test_skip_when_1m_not_verified(self, app, test_symbol):
        """Aggregated candles skip when 1m are not verified."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000

            # Create 5 UNVERIFIED 1m candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=None  # Not verified
                ))

            # Create 5m candle
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100, high=105, low=95, close=100, volume=5000
            ))
            db.session.commit()

            result = verify_aggregated_candles(
                test_symbol, 'TEST/USDT', '5m', fix=False
            )
            assert result['verified'] == 0
            assert result['skipped'] == 1  # Skipped due to unverified 1m

    def test_detect_aggregation_mismatch(self, app, test_symbol):
        """Detect mismatch between aggregated and 1m data."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000
            now_ms = base_ts + 10 * 60000

            # Create 5 verified 1m candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=now_ms
                ))

            # Create MISMATCHED 5m candle
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=base_ts,
                open=100, high=110, low=95, close=100, volume=5000  # Wrong high!
            ))
            db.session.commit()

            result = verify_aggregated_candles(
                test_symbol, 'TEST/USDT', '5m', fix=False
            )
            assert result['error'] is not None
            assert result['error']['type'] == 'aggregation_mismatch'


class TestGet1mCandlesForAggregation:
    """Test getting 1m candles for aggregation validation."""

    def test_returns_candles_when_all_verified(self, app, test_symbol):
        """Returns 1m candles when all are verified."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000
            now_ms = base_ts + 10 * 60000

            # Create 5 verified 1m candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=now_ms
                ))
            db.session.commit()

            candles = get_1m_candles_for_aggregation(test_symbol, '5m', base_ts)
            assert candles is not None
            assert len(candles) == 5

    def test_returns_none_when_unverified(self, app, test_symbol):
        """Returns None when 1m candles are not verified."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000

            # Create 5 UNVERIFIED 1m candles
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=None
                ))
            db.session.commit()

            candles = get_1m_candles_for_aggregation(test_symbol, '5m', base_ts)
            assert candles is None

    def test_returns_none_when_missing_candles(self, app, test_symbol):
        """Returns None when some 1m candles are missing."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000
            now_ms = base_ts + 10 * 60000

            # Create only 3 of the required 5 candles
            for i in [0, 1, 2]:  # Missing 3 and 4
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000,
                    verified_at=now_ms
                ))
            db.session.commit()

            candles = get_1m_candles_for_aggregation(test_symbol, '5m', base_ts)
            assert candles is None


class TestVerificationStats:
    """Test verification statistics functions."""

    def test_all_unverified(self, app, test_symbol):
        """New candles should all be unverified."""
        with app.app_context():
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=1700000000000 + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            stats = get_verification_stats(test_symbol, '1m')
            assert stats['total'] == 5
            assert stats['verified'] == 0
            assert stats['unverified'] == 5

    def test_partial_verified(self, app, test_symbol):
        """Partial verification should show correct counts."""
        with app.app_context():
            now_ms = 1700000000000
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=now_ms + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000,
                    verified_at=now_ms if i < 3 else None  # First 3 verified
                ))
            db.session.commit()

            stats = get_verification_stats(test_symbol, '1m')
            assert stats['total'] == 5
            assert stats['verified'] == 3
            assert stats['unverified'] == 2

    def test_reset_verification(self, app, test_symbol):
        """Reset should clear all verification flags."""
        with app.app_context():
            now_ms = 1700000000000
            for i in range(5):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=now_ms + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000,
                    verified_at=now_ms  # All verified
                ))
            db.session.commit()

            reset_count = reset_verification(test_symbol, '1m')
            assert reset_count == 5

            stats = get_verification_stats(test_symbol, '1m')
            assert stats['unverified'] == 5


class TestHierarchicalVerification:
    """Test that aggregated candles are only verified after 1m."""

    def test_1m_must_complete_before_aggregated(self, app, test_symbol):
        """1m verification must complete before aggregated starts."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000

            # Create 10 1m candles (unverified)
            for i in range(10):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                ))

            # Create 2 5m candles (unverified)
            for i in range(2):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='5m',
                    timestamp=base_ts + i * 300000,
                    open=100, high=105, low=95, close=100, volume=5000
                ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)

            # Verify 1m first - should work
            result_1m = verify_1m_candles(test_symbol, symbol, fix=False)
            assert result_1m['verified'] == 10
            assert result_1m['all_done'] is True

            # Now 5m should verify
            result_5m = verify_aggregated_candles(
                test_symbol, 'TEST/USDT', '5m', fix=False
            )
            assert result_5m['verified'] == 2
            assert result_5m['skipped'] == 0


class TestIntegration:
    """Integration tests with multiple scenarios."""

    def test_full_verification_workflow(self, app, test_symbol):
        """Test complete verification from start to finish."""
        with app.app_context():
            # Use 5m-aligned timestamp
            base_ts = 1699999800000

            # Create 10 1m candles
            for i in range(10):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=105, low=95, close=100, volume=1000
                ))

            # Create 2 matching 5m candles
            for i in range(2):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='5m',
                    timestamp=base_ts + i * 300000,
                    open=100, high=105, low=95, close=100, volume=5000
                ))
            db.session.commit()

            symbol = Symbol.query.get(test_symbol)

            # Step 1: Verify 1m
            result_1m = verify_1m_candles(test_symbol, symbol, fix=False)
            assert result_1m['all_done'] is True

            # Step 2: Verify 5m
            result_5m = verify_aggregated_candles(
                test_symbol, 'TEST/USDT', '5m', fix=False
            )
            assert result_5m['all_done'] is True

            # Check final stats
            stats_1m = get_verification_stats(test_symbol, '1m')
            assert stats_1m['verified'] == 10

            stats_5m = get_verification_stats(test_symbol, '5m')
            assert stats_5m['verified'] == 2
