"""
Shared fetch utilities for real-time and historical data fetching.

This module provides common functions used by both fetch.py (real-time) and
fetch_historical.py (historical/gap-fill) scripts.

Features:
- Batch timestamp queries (single DB query for all symbols)
- Aligned fetch start time calculation
- True parallel async fetching with ccxt rate limiting
- Proper logging and error handling

Usage:
    from scripts.utils.fetch_utils import (
        get_all_last_timestamps,
        get_aligned_fetch_start,
        fetch_symbol_batches,
        create_exchange,
        logger
    )
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import ccxt.async_support as ccxt_async

from scripts.utils.retry import (
    is_rate_limit_error,
    is_timeout_error,
    extract_rate_limit_wait_time,
    get_error_summary,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    TIMEOUT_RETRY_DELAY_SECONDS,
)

# Configure module logger
logger = logging.getLogger('fetch')


def get_all_last_timestamps(app, symbols: List[str], timeframe: str = '1m') -> Dict[str, int]:
    """
    Batch query: Get last candle timestamp for all symbols in ONE query.

    This is significantly faster than querying each symbol individually,
    especially when dealing with many symbols.

    Args:
        app: Flask application instance
        symbols: List of symbol names (e.g., ['BTC/USDT', 'ETH/USDT'])
        timeframe: Timeframe to query (default '1m')

    Returns:
        Dict mapping symbol name to last timestamp in milliseconds.
        Symbols with no data are not included in the result.

    Example:
        >>> timestamps = get_all_last_timestamps(app, ['BTC/USDT', 'ETH/USDT'])
        >>> timestamps
        {'BTC/USDT': 1702500000000, 'ETH/USDT': 1702499940000}
    """
    from app.models import Symbol, Candle
    from sqlalchemy import func

    with app.app_context():
        # Get symbol name -> id mapping
        symbol_records = Symbol.query.filter(Symbol.symbol.in_(symbols)).all()
        symbol_map = {s.symbol: s.id for s in symbol_records}
        id_to_symbol = {s.id: s.symbol for s in symbol_records}

        if not symbol_map:
            logger.warning("No symbols found in database for timestamp query")
            return {}

        # Single query for all symbols' max timestamps
        results = Candle.query.filter(
            Candle.symbol_id.in_(symbol_map.values()),
            Candle.timeframe == timeframe
        ).with_entities(
            Candle.symbol_id,
            func.max(Candle.timestamp).label('max_ts')
        ).group_by(Candle.symbol_id).all()

        timestamps = {id_to_symbol[r.symbol_id]: r.max_ts for r in results}

        logger.debug(f"Loaded timestamps for {len(timestamps)}/{len(symbols)} symbols")
        return timestamps


def get_aligned_fetch_start(
    timestamps: Dict[str, int],
    now_ms: int,
    default_gap_minutes: int = 500
) -> int:
    """
    Calculate aligned fetch start time across all symbols.

    Uses the minimum (oldest) timestamp to ensure all symbols sync up.
    This ensures consistency when fetching data for multiple symbols.

    Args:
        timestamps: Dict of symbol -> last timestamp (from get_all_last_timestamps)
        now_ms: Current time in milliseconds
        default_gap_minutes: Gap to use if no timestamps exist (default 500 minutes)

    Returns:
        Fetch start timestamp in milliseconds, aligned to minute boundary.

    Example:
        >>> timestamps = {'BTC/USDT': 1702500000000, 'ETH/USDT': 1702499940000}
        >>> start = get_aligned_fetch_start(timestamps, 1702503600000)
        >>> # Returns 1702500000000 (aligned to oldest + 1 minute)
    """
    if not timestamps:
        # No data - fetch default gap
        start = now_ms - (default_gap_minutes * 60 * 1000)
        logger.info(f"No existing data, fetching last {default_gap_minutes} minutes")
        return start

    # Find the oldest last timestamp (minimum)
    min_ts = min(timestamps.values())

    # Start from next minute after the oldest
    fetch_start = min_ts + 60000

    # Align to minute boundary
    fetch_start = (fetch_start // 60000) * 60000

    gap_minutes = (now_ms - fetch_start) // 60000
    logger.debug(f"Aligned fetch start: {gap_minutes} minutes gap from oldest timestamp")

    return fetch_start


def create_exchange(exchange_id: str = 'binance', **options) -> ccxt_async.Exchange:
    """
    Create an async exchange instance with rate limiting enabled.

    Args:
        exchange_id: Exchange identifier (default 'binance')
        **options: Additional options to pass to exchange constructor

    Returns:
        Configured async exchange instance

    Example:
        >>> exchange = create_exchange('binance')
        >>> # ... use exchange ...
        >>> await exchange.close()
    """
    exchange_class = getattr(ccxt_async, exchange_id)

    default_options = {
        'enableRateLimit': True,  # Let ccxt handle rate limiting
        'options': {'defaultType': 'spot'},
    }

    # Merge with provided options
    config = {**default_options, **options}

    exchange = exchange_class(config)
    logger.debug(f"Created {exchange_id} exchange with rate limiting enabled")

    return exchange


async def fetch_symbol_batches(
    exchange,
    symbol: str,
    since: int,
    until: int,
    timeframe: str = '1m',
    batch_size: int = 1000,
    verbose: bool = False
) -> List[List]:
    """
    Fetch all candle batches for a single symbol within a time range.

    This function handles pagination automatically, fetching multiple batches
    until all data in the range is retrieved. ccxt handles rate limiting internally.

    Args:
        exchange: ccxt async exchange instance
        symbol: Symbol to fetch (e.g., 'BTC/USDT')
        since: Start timestamp in milliseconds
        until: End timestamp in milliseconds
        timeframe: Candle timeframe (default '1m')
        batch_size: Maximum candles per request (default 1000, Binance max)
        verbose: Print progress messages

    Returns:
        List of OHLCV candles: [[timestamp, open, high, low, close, volume], ...]

    Raises:
        Exception: If fetch fails after all retries

    Example:
        >>> candles = await fetch_symbol_batches(exchange, 'BTC/USDT', since, until)
        >>> print(f"Fetched {len(candles)} candles")
    """
    all_ohlcv = []
    current_since = since
    consecutive_errors = 0

    while current_since < until:
        retries = 0
        success = False
        batch = None

        while retries < MAX_RETRIES and not success:
            try:
                batch = await exchange.fetch_ohlcv(
                    symbol, timeframe,
                    since=current_since,
                    limit=batch_size
                )

                if not batch:
                    success = True
                    break

                all_ohlcv.extend(batch)
                consecutive_errors = 0

                # Move to next batch
                last_ts = batch[-1][0]
                if last_ts <= current_since:
                    # No progress, we've reached the end
                    success = True
                    break

                current_since = last_ts + 60000  # Next minute
                success = True

                # Stop if we got less than full batch (reached end)
                if len(batch) < batch_size:
                    break

            except Exception as e:
                retries += 1
                consecutive_errors += 1
                error_summary = get_error_summary(e)

                if is_rate_limit_error(e):
                    wait_time = extract_rate_limit_wait_time(e)
                    logger.warning(f"{symbol}: Rate limit hit, cooling off {wait_time}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"    {symbol}: Rate limit, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)

                elif is_timeout_error(e):
                    logger.warning(f"{symbol}: Timeout, retrying in {TIMEOUT_RETRY_DELAY_SECONDS}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"    {symbol}: Timeout, retrying...")
                    await asyncio.sleep(TIMEOUT_RETRY_DELAY_SECONDS)

                else:
                    logger.error(f"{symbol}: {error_summary} (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"    {symbol}: {error_summary}, retrying...")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

        # If all retries failed
        if not success:
            logger.error(f"{symbol}: Failed to fetch at {current_since} after {MAX_RETRIES} retries")
            if verbose:
                print(f"    {symbol}: Failed after {MAX_RETRIES} retries, skipping batch")

            # Skip this batch and continue
            current_since += batch_size * 60000

            # If too many consecutive errors, abort
            if consecutive_errors >= MAX_RETRIES * 3:
                logger.error(f"{symbol}: Too many consecutive errors, aborting fetch")
                if verbose:
                    print(f"    {symbol}: Too many errors, aborting")
                break

        # Break if no more data
        if success and not batch:
            break

    return all_ohlcv


async def fetch_symbols_parallel(
    symbols: List[str],
    since: int,
    until: int,
    exchange=None,
    timeframe: str = '1m',
    verbose: bool = False
) -> Tuple[Dict[str, List], Dict[str, str]]:
    """
    Fetch candles for multiple symbols in true parallel.

    Creates tasks for all symbols and waits for them to complete.
    ccxt handles rate limiting internally, queueing requests as needed.

    Args:
        symbols: List of symbols to fetch
        since: Start timestamp in milliseconds
        until: End timestamp in milliseconds
        exchange: Optional exchange instance (creates one if not provided)
        timeframe: Candle timeframe (default '1m')
        verbose: Print progress messages

    Returns:
        Tuple of (results, errors):
        - results: Dict mapping symbol -> list of OHLCV candles
        - errors: Dict mapping symbol -> error message (for failed fetches)

    Example:
        >>> results, errors = await fetch_symbols_parallel(
        ...     ['BTC/USDT', 'ETH/USDT'], since, until
        ... )
        >>> for symbol, candles in results.items():
        ...     print(f"{symbol}: {len(candles)} candles")
    """
    close_exchange = False
    if exchange is None:
        exchange = create_exchange()
        close_exchange = True

    try:
        # Create ALL fetch tasks at once (true parallel)
        fetch_tasks = {
            symbol: asyncio.create_task(
                fetch_symbol_batches(exchange, symbol, since, until, timeframe, verbose=verbose)
            )
            for symbol in symbols
        }

        logger.info(f"Created {len(fetch_tasks)} parallel fetch tasks")

        # Wait for ALL fetches to complete
        results = {}
        errors = {}

        for symbol, task in fetch_tasks.items():
            try:
                results[symbol] = await task
                logger.debug(f"{symbol}: Fetched {len(results[symbol])} candles")
            except Exception as e:
                error_msg = get_error_summary(e)
                errors[symbol] = error_msg
                results[symbol] = []
                logger.error(f"{symbol}: Fetch failed - {error_msg}")

        total_candles = sum(len(v) for v in results.values())
        logger.info(f"Parallel fetch complete: {total_candles:,} candles from {len(symbols)} symbols")

        return results, errors

    finally:
        if close_exchange:
            await exchange.close()


def save_candles_to_db(
    app,
    symbol_name: str,
    candles: List[List],
    timeframe: str = '1m'
) -> int:
    """
    Save candles to database, skipping duplicates.

    Args:
        app: Flask application instance
        symbol_name: Symbol name (e.g., 'BTC/USDT')
        candles: List of OHLCV candles
        timeframe: Candle timeframe (default '1m')

    Returns:
        Number of new candles saved

    Example:
        >>> new_count = save_candles_to_db(app, 'BTC/USDT', candles)
        >>> print(f"Saved {new_count} new candles")
    """
    from app.models import Symbol, Candle
    from app import db

    if not candles:
        return 0

    with app.app_context():
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            logger.warning(f"{symbol_name}: Symbol not found in database")
            return 0

        # Get existing timestamps
        timestamps = [c[0] for c in candles]
        existing = set(
            c.timestamp for c in Candle.query.filter(
                Candle.symbol_id == sym.id,
                Candle.timeframe == timeframe,
                Candle.timestamp.in_(timestamps)
            ).all()
        )

        new_count = 0
        for candle in candles:
            ts, o, h, l, c, v = candle
            if ts in existing:
                continue

            # Validate candle data
            if any(x is None or x <= 0 for x in [o, h, l, c]):
                continue

            db.session.add(Candle(
                symbol_id=sym.id,
                timeframe=timeframe,
                timestamp=ts,
                open=o, high=h, low=l, close=c,
                volume=v or 0
            ))
            new_count += 1

        if new_count > 0:
            db.session.commit()
            logger.debug(f"{symbol_name}: Saved {new_count} new candles")

        return new_count
