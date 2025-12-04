"""
Tests for Database Health Check Script (Incremental Verification)

Tests the candle verification functions and incremental verification logic.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol, Candle
from scripts.db_health import (
    check_candle_ohlcv,
    check_candle_alignment,
    check_gap,
    check_continuity,
    verify_candles_incremental,
    get_verification_stats,
    reset_verification
)


@pytest.fixture
def app():
    """Create test app with in-memory database."""
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        yield app
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


class TestContinuityCheck:
    """Test continuity checks (open == prev close)."""

    def test_continuous(self, app, test_symbol):
        """Open equals previous close - no issue."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100.5, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000060000,
                open=100.5, high=101, low=99, close=101, volume=1000
            )
            diff = check_continuity(prev, curr, threshold=0.001)
            assert diff is None

    def test_small_diff_within_threshold(self, app, test_symbol):
        """Small diff within threshold passes."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000060000,
                open=100.05,  # 0.05% diff
                high=101, low=99, close=101, volume=1000
            )
            diff = check_continuity(prev, curr, threshold=0.001)  # 0.1%
            assert diff is None

    def test_discontinuity_above_threshold(self, app, test_symbol):
        """Diff above threshold returns percentage."""
        with app.app_context():
            prev = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100, volume=1000
            )
            curr = Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=1700000060000,
                open=105,  # 5% diff
                high=106, low=104, close=105, volume=1000
            )
            diff = check_continuity(prev, curr, threshold=0.001)
            assert diff is not None
            assert diff == pytest.approx(0.05, rel=0.01)


class TestIncrementalVerification:
    """Test the incremental verification process."""

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

            result = verify_candles_incremental(test_symbol, '1m', fix=False)
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

            result = verify_candles_incremental(test_symbol, '1m', fix=False)
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

            result = verify_candles_incremental(test_symbol, '1m', fix=False)
            assert result['verified'] == 5
            assert result['error'] is not None
            assert result['error']['type'] == 'gap'
            assert result['error']['missing_candles'] == 5

    def test_stop_on_misaligned(self, app, test_symbol):
        """Verification should stop on misaligned candle."""
        with app.app_context():
            # 5m aligned timestamp
            aligned_ts = 1699999800000  # Aligned to 5m
            # 3 aligned candles
            for i in range(3):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='5m',
                    timestamp=aligned_ts + i * 300000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            # 1 misaligned candle
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='5m',
                timestamp=aligned_ts + 3 * 300000 + 60000,  # +1 minute off
                open=100, high=101, low=99, close=100, volume=1000
            ))
            db.session.commit()

            result = verify_candles_incremental(test_symbol, '5m', fix=False)
            assert result['verified'] == 3
            assert result['error'] is not None
            assert result['error']['type'] == 'misaligned'

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

            result = verify_candles_incremental(test_symbol, '1m', fix=True)
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

            # First run with batch_size=5
            result1 = verify_candles_incremental(
                test_symbol, '1m', fix=False, batch_size=5
            )
            assert result1['verified'] == 5

            # Second run should verify remaining 5
            result2 = verify_candles_incremental(
                test_symbol, '1m', fix=False, batch_size=5
            )
            assert result2['verified'] == 5

            # Third run - all verified
            result3 = verify_candles_incremental(
                test_symbol, '1m', fix=False, batch_size=5
            )
            assert result3['verified'] == 0


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


class TestIntegration:
    """Integration tests with multiple error scenarios."""

    def test_error_stops_further_verification(self, app, test_symbol):
        """Error in middle should leave subsequent candles unverified."""
        with app.app_context():
            base_ts = 1700000000000
            # 3 valid
            for i in range(3):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            # 1 invalid
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=base_ts + 3 * 60000,
                open=100, high=95, low=105, close=100, volume=1000
            ))
            # 3 more valid
            for i in range(4, 7):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            result = verify_candles_incremental(test_symbol, '1m', fix=False)
            assert result['verified'] == 3
            assert result['error']['type'] == 'ohlcv_invalid'

            # Check stats - 4 should be unverified (invalid + 3 after)
            stats = get_verification_stats(test_symbol, '1m')
            assert stats['verified'] == 3
            assert stats['unverified'] == 4

    def test_fix_and_continue(self, app, test_symbol):
        """After fixing error, should be able to continue verification."""
        with app.app_context():
            base_ts = 1700000000000
            # 3 valid
            for i in range(3):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            # 1 invalid
            db.session.add(Candle(
                symbol_id=test_symbol, timeframe='1m',
                timestamp=base_ts + 3 * 60000,
                open=100, high=95, low=105, close=100, volume=1000
            ))
            # 3 more valid (but now minute 4 is missing after deletion!)
            for i in range(4, 7):
                db.session.add(Candle(
                    symbol_id=test_symbol, timeframe='1m',
                    timestamp=base_ts + i * 60000,
                    open=100, high=101, low=99, close=100, volume=1000
                ))
            db.session.commit()

            # First run with fix - deletes invalid, verifies first 3
            result1 = verify_candles_incremental(test_symbol, '1m', fix=True)
            assert result1['verified'] == 3
            assert result1['error']['action'] == 'deleted'

            # Second run - now there's a gap!
            result2 = verify_candles_incremental(test_symbol, '1m', fix=False)
            assert result2['error']['type'] == 'gap'
