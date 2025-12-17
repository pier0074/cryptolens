"""
Tests for the shared fetch utilities module.

Tests the core fetch functions used by both fetch.py and fetch_historical.py:
- get_all_last_timestamps: Batch timestamp query
- get_aligned_fetch_start: Aligned timestamp calculation
- fetch_symbol_batches: Async OHLCV fetching
- save_candles_to_db: Database saving with deduplication
"""
import pytest
from unittest.mock import AsyncMock, patch

from scripts.utils.fetch_utils import (
    get_all_last_timestamps,
    get_aligned_fetch_start,
    fetch_symbol_batches,
    fetch_symbols_parallel,
    save_candles_to_db,
    create_exchange,
)


class TestGetAlignedFetchStart:
    """Tests for get_aligned_fetch_start function."""

    def test_empty_timestamps_returns_default_gap(self):
        """When no timestamps exist, should return default gap from now."""
        now_ms = 1700000000000  # Example timestamp
        default_gap = 500

        result = get_aligned_fetch_start({}, now_ms, default_gap_minutes=default_gap)

        expected = now_ms - (default_gap * 60 * 1000)
        assert result == expected

    def test_uses_minimum_timestamp(self):
        """Should use the oldest (minimum) timestamp across all symbols."""
        now_ms = 1700000000000
        timestamps = {
            'BTC/USDT': 1699999000000,  # Newest
            'ETH/USDT': 1699998000000,  # Oldest
            'SOL/USDT': 1699998500000,  # Middle
        }

        result = get_aligned_fetch_start(timestamps, now_ms)

        # Should start from oldest + 1 minute, aligned to minute boundary
        expected_start = 1699998000000 + 60000  # ETH (oldest) + 1 minute
        expected_aligned = (expected_start // 60000) * 60000
        assert result == expected_aligned

    def test_aligns_to_minute_boundary(self):
        """Result should always be aligned to minute boundary."""
        now_ms = 1700000000000
        timestamps = {
            'BTC/USDT': 1699999012345,  # Not aligned to minute
        }

        result = get_aligned_fetch_start(timestamps, now_ms)

        # Check it's aligned to minute boundary
        assert result % 60000 == 0

    def test_single_symbol(self):
        """Should work with a single symbol."""
        now_ms = 1700000000000
        timestamps = {'BTC/USDT': 1699999000000}

        result = get_aligned_fetch_start(timestamps, now_ms)

        # Start from the only timestamp + 1 minute
        expected = ((1699999000000 + 60000) // 60000) * 60000
        assert result == expected


class TestGetAllLastTimestamps:
    """Tests for get_all_last_timestamps function."""

    def test_returns_timestamps_for_existing_symbols(self, app):
        """Should return timestamps for symbols with data."""
        from app.models import Symbol, Candle
        from app import db

        with app.app_context():
            # Create test symbols
            sym1 = Symbol(symbol='TEST1/USDT', is_active=True)
            sym2 = Symbol(symbol='TEST2/USDT', is_active=True)
            db.session.add_all([sym1, sym2])
            db.session.commit()

            # Add candles
            db.session.add(Candle(
                symbol_id=sym1.id, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100.5, volume=1000
            ))
            db.session.add(Candle(
                symbol_id=sym2.id, timeframe='1m',
                timestamp=1700001000000,
                open=50, high=51, low=49, close=50.5, volume=500
            ))
            db.session.commit()

            # Test
            result = get_all_last_timestamps(app, ['TEST1/USDT', 'TEST2/USDT'])

            assert 'TEST1/USDT' in result
            assert 'TEST2/USDT' in result
            assert result['TEST1/USDT'] == 1700000000000
            assert result['TEST2/USDT'] == 1700001000000

    def test_returns_empty_for_nonexistent_symbols(self, app):
        """Should return empty dict for symbols not in database."""
        result = get_all_last_timestamps(app, ['NONEXISTENT/USDT'])
        assert result == {}

    def test_returns_max_timestamp_for_symbol(self, app):
        """Should return the maximum (most recent) timestamp for each symbol."""
        from app.models import Symbol, Candle
        from app import db

        with app.app_context():
            sym = Symbol(symbol='MULTI/USDT', is_active=True)
            db.session.add(sym)
            db.session.commit()

            # Add multiple candles
            for i, ts in enumerate([1700000000000, 1700001000000, 1700002000000]):
                db.session.add(Candle(
                    symbol_id=sym.id, timeframe='1m',
                    timestamp=ts,
                    open=100+i, high=101+i, low=99+i, close=100.5+i, volume=1000
                ))
            db.session.commit()

            result = get_all_last_timestamps(app, ['MULTI/USDT'])

            # Should return the maximum timestamp
            assert result['MULTI/USDT'] == 1700002000000


class TestFetchSymbolBatches:
    """Tests for fetch_symbol_batches async function."""

    @pytest.mark.asyncio
    async def test_fetches_single_batch(self):
        """Should fetch a single batch when data fits in one request."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_ohlcv.return_value = [
            [1700000000000, 100, 101, 99, 100.5, 1000],
            [1700000060000, 100.5, 102, 100, 101, 1100],
        ]

        result = await fetch_symbol_batches(
            mock_exchange, 'BTC/USDT',
            since=1700000000000,
            until=1700000120000,
            batch_size=1000
        )

        assert len(result) == 2
        assert mock_exchange.fetch_ohlcv.called

    @pytest.mark.asyncio
    async def test_fetches_multiple_batches(self):
        """Should fetch multiple batches for large time ranges."""
        mock_exchange = AsyncMock()

        # Use a function to generate responses - returns full batch then empty
        call_count = [0]

        async def mock_fetch(*args, **kwargs):
            call_count[0] += 1
            since = kwargs.get('since', args[2] if len(args) > 2 else 0)
            batch_size = kwargs.get('limit', 100)

            if call_count[0] == 1:
                # First batch: full batch
                return [[since + i * 60000, 100, 101, 99, 100.5, 1000] for i in range(batch_size)]
            elif call_count[0] == 2:
                # Second batch: partial (less than batch_size, triggers stop)
                return [[since + i * 60000, 100, 101, 99, 100.5, 1000] for i in range(50)]
            # After that, return empty to stop
            return []

        mock_exchange.fetch_ohlcv.side_effect = mock_fetch

        result = await fetch_symbol_batches(
            mock_exchange, 'BTC/USDT',
            since=1700000000000,
            until=1700020000000,
            batch_size=100
        )

        # Should have called at least twice: full batch + partial
        assert call_count[0] >= 2
        # Should have fetched the 100 from first + 50 from second
        assert len(result) == 150

    @pytest.mark.asyncio
    async def test_handles_empty_response(self):
        """Should handle empty response gracefully."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_ohlcv.return_value = []

        result = await fetch_symbol_batches(
            mock_exchange, 'BTC/USDT',
            since=1700000000000,
            until=1700000120000
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_stops_on_no_progress(self):
        """Should stop fetching when no progress is made (same timestamp)."""
        mock_exchange = AsyncMock()

        # Return same data repeatedly (no progress)
        mock_exchange.fetch_ohlcv.return_value = [
            [1700000000000, 100, 101, 99, 100.5, 1000],
        ]

        result = await fetch_symbol_batches(
            mock_exchange, 'BTC/USDT',
            since=1700000000000,
            until=1700100000000
        )

        # Should stop after first batch since timestamp doesn't advance
        assert len(result) == 1


class TestFetchSymbolsParallel:
    """Tests for fetch_symbols_parallel function."""

    @pytest.mark.asyncio
    async def test_fetches_multiple_symbols(self):
        """Should fetch data for multiple symbols in parallel."""
        with patch('scripts.utils.fetch_utils.create_exchange') as mock_create:
            mock_exchange = AsyncMock()
            mock_exchange.fetch_ohlcv.return_value = [
                [1700000000000, 100, 101, 99, 100.5, 1000],
            ]
            mock_create.return_value = mock_exchange

            results, errors = await fetch_symbols_parallel(
                ['BTC/USDT', 'ETH/USDT'],
                since=1700000000000,
                until=1700000120000
            )

            assert 'BTC/USDT' in results
            assert 'ETH/USDT' in results
            assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_handles_partial_failures(self):
        """Should continue fetching other symbols when one fails."""
        with patch('scripts.utils.fetch_utils.create_exchange') as mock_create:
            mock_exchange = AsyncMock()

            # BTC succeeds, ETH fails
            async def mock_fetch(symbol, *args, **kwargs):
                if 'BTC' in symbol:
                    return [[1700000000000, 100, 101, 99, 100.5, 1000]]
                raise Exception("Network error")

            mock_exchange.fetch_ohlcv.side_effect = mock_fetch
            mock_create.return_value = mock_exchange

            results, errors = await fetch_symbols_parallel(
                ['BTC/USDT', 'ETH/USDT'],
                since=1700000000000,
                until=1700000120000
            )

            assert len(results['BTC/USDT']) == 1
            assert len(results['ETH/USDT']) == 0
            assert 'ETH/USDT' in errors


class TestSaveCandlesToDb:
    """Tests for save_candles_to_db function."""

    def test_saves_new_candles(self, app):
        """Should save new candles to database."""
        from app.models import Symbol, Candle
        from app import db

        with app.app_context():
            sym = Symbol(symbol='SAVE/USDT', is_active=True)
            db.session.add(sym)
            db.session.commit()

            candles = [
                [1700000000000, 100, 101, 99, 100.5, 1000],
                [1700000060000, 100.5, 102, 100, 101, 1100],
            ]

            count = save_candles_to_db(app, 'SAVE/USDT', candles)

            assert count == 2

            # Verify in database
            saved = Candle.query.filter_by(symbol_id=sym.id).all()
            assert len(saved) == 2

    def test_skips_duplicate_candles(self, app):
        """Should skip candles that already exist."""
        from app.models import Symbol, Candle
        from app import db

        with app.app_context():
            sym = Symbol(symbol='DUP/USDT', is_active=True)
            db.session.add(sym)
            db.session.commit()

            # Add existing candle
            db.session.add(Candle(
                symbol_id=sym.id, timeframe='1m',
                timestamp=1700000000000,
                open=100, high=101, low=99, close=100.5, volume=1000
            ))
            db.session.commit()

            # Try to save same timestamp
            candles = [
                [1700000000000, 100, 101, 99, 100.5, 1000],  # Duplicate
                [1700000060000, 100.5, 102, 100, 101, 1100],  # New
            ]

            count = save_candles_to_db(app, 'DUP/USDT', candles)

            assert count == 1  # Only the new one

    def test_returns_zero_for_empty_list(self, app):
        """Should return 0 for empty candle list."""
        count = save_candles_to_db(app, 'ANY/USDT', [])
        assert count == 0

    def test_returns_zero_for_nonexistent_symbol(self, app):
        """Should return 0 for symbol not in database."""
        candles = [[1700000000000, 100, 101, 99, 100.5, 1000]]
        count = save_candles_to_db(app, 'NONEXISTENT/USDT', candles)
        assert count == 0


class TestCreateExchange:
    """Tests for create_exchange function."""

    def test_creates_binance_exchange(self):
        """Should create a Binance exchange instance."""
        exchange = create_exchange('binance')

        assert exchange is not None
        assert exchange.id == 'binance'
        assert exchange.enableRateLimit is True

    def test_enables_rate_limiting_by_default(self):
        """Should enable rate limiting by default."""
        exchange = create_exchange('binance')
        assert exchange.enableRateLimit is True

    def test_accepts_custom_options(self):
        """Should accept custom options."""
        exchange = create_exchange('binance', timeout=30000)
        assert exchange.timeout == 30000


class TestIntegration:
    """Integration tests for fetch utilities."""

    def test_full_fetch_workflow(self, app):
        """Test the complete fetch workflow with mocked exchange."""
        from app.models import Symbol
        from app import db

        with app.app_context():
            # Setup
            sym = Symbol(symbol='INTG/USDT', is_active=True)
            db.session.add(sym)
            db.session.commit()

            # 1. Get timestamps (should be empty initially)
            timestamps = get_all_last_timestamps(app, ['INTG/USDT'])
            assert timestamps == {}

            # 2. Calculate aligned start (should use default)
            now_ms = 1700100000000
            start = get_aligned_fetch_start(timestamps, now_ms, default_gap_minutes=10)
            expected = now_ms - (10 * 60 * 1000)
            assert start == expected

            # 3. Save candles
            candles = [
                [1700099400000, 100, 101, 99, 100.5, 1000],
                [1700099460000, 100.5, 102, 100, 101, 1100],
            ]
            count = save_candles_to_db(app, 'INTG/USDT', candles)
            assert count == 2

            # 4. Get timestamps again (should return max)
            timestamps = get_all_last_timestamps(app, ['INTG/USDT'])
            assert timestamps['INTG/USDT'] == 1700099460000

            # 5. Calculate new aligned start
            start = get_aligned_fetch_start(timestamps, now_ms)
            # Should be the last timestamp + 1 minute, aligned
            expected = ((1700099460000 + 60000) // 60000) * 60000
            assert start == expected
