#!/usr/bin/env python3
"""
Historical Data Fetcher with Gap Detection

Features:
- Async parallel fetching for speed
- Gap detection and filling
- Progress tracking via database
- Hourly cron for gap filling, manual for initial load

Usage:
  python fetch_historical.py                       # Initial load (from fetch_start_date)
  python fetch_historical.py --days 30             # Fetch last 30 days
  python fetch_historical.py --gaps                # Find and fill gaps only (last 7 days)
  python fetch_historical.py --gaps --full         # Find and fill gaps (entire database)
  python fetch_historical.py --status              # Show DB status
  python fetch_historical.py --delete              # Delete all data
  python fetch_historical.py --symbol BTC/USDT     # Fetch specific symbol only
  python fetch_historical.py --verbose             # Show detailed output
  python fetch_historical.py --no-aggregate        # Skip aggregation step

Options:
  --days N            Days of history to fetch (overrides fetch_start_date)
  --gaps              Find and fill gaps only (for hourly cron)
  --full              With --gaps: scan entire database instead of last 7 days
  --status            Show database status (candle counts, date ranges)
  --delete            Delete all candle data
  --symbol, -s SYM    Fetch specific symbol only (e.g., BTC/USDT)
  --verbose, -v       Show detailed progress output
  --no-aggregate      Skip higher timeframe aggregation

Cron (hourly gap check):
  0 * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch_historical.py --gaps
"""
import sys
import os
import time
import asyncio
import fcntl
import tempfile
from datetime import datetime, timezone, timedelta
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lock file path for preventing concurrent execution (use system temp directory)
LOCK_FILE = os.path.join(tempfile.gettempdir(), 'cryptolens_historical.lock')


def acquire_lock():
    """Acquire file lock to prevent concurrent execution."""
    try:
        lock_file = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except IOError:
        return None


def release_lock(lock_file):
    """Release file lock."""
    if lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
        except Exception:
            pass


from sqlalchemy import func

# Import shared fetch utilities
from scripts.utils.fetch_utils import (
    create_exchange,
    logger
)

# Import retry utilities for error handling
from scripts.utils.retry import (
    is_rate_limit_error,
    is_timeout_error,
    extract_rate_limit_wait_time,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    TIMEOUT_RETRY_DELAY_SECONDS,
)


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    return f"{seconds/3600:.1f}h"


def progress_bar(current, total, width=30):
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct*100:5.1f}%"


def find_gaps(symbol_id: int, start_ts: int, end_ts: int, max_gap_minutes: int = 5) -> List[Tuple[int, int]]:
    """
    Find gaps in 1m candle data for a symbol.

    Returns list of (gap_start_ts, gap_end_ts) tuples.
    Only returns gaps larger than max_gap_minutes.
    """
    from app import db
    from app.models import Candle

    # Get all timestamps in range, ordered
    timestamps = db.session.query(Candle.timestamp).filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m',
        Candle.timestamp >= start_ts,
        Candle.timestamp <= end_ts
    ).order_by(Candle.timestamp).all()

    timestamps = [t[0] for t in timestamps]

    if len(timestamps) < 2:
        return [(start_ts, end_ts)] if len(timestamps) == 0 else []

    gaps = []
    expected_interval = 60 * 1000  # 1 minute in ms
    max_gap_ms = max_gap_minutes * 60 * 1000

    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i-1]
        if gap > max_gap_ms:
            gaps.append((timestamps[i-1] + expected_interval, timestamps[i] - expected_interval))

    # Check gap at start
    if timestamps[0] - start_ts > max_gap_ms:
        gaps.insert(0, (start_ts, timestamps[0] - expected_interval))

    # Check gap at end (but not beyond current time - fetch.py handles that)
    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000) - (5 * 60 * 1000)  # 5 min buffer
    if now_ts - timestamps[-1] > max_gap_ms and timestamps[-1] < end_ts:
        gaps.append((timestamps[-1] + expected_interval, min(end_ts, now_ts)))

    logger.debug(f"Found {len(gaps)} gaps for symbol_id={symbol_id}")
    return gaps


async def fetch_range_with_save(
    exchange,
    symbol: str,
    symbol_id: int,
    start_ts: int,
    end_ts: int,
    app,
    verbose: bool = False,
    save_every: int = 10000
) -> Tuple[int, int]:
    """
    Fetch candles for a time range with incremental saves.

    Uses the shared fetch_symbol_batches function but saves incrementally
    for crash resilience during large historical fetches.

    Args:
        exchange: ccxt async exchange instance
        symbol: Symbol name
        symbol_id: Symbol database ID
        start_ts: Start timestamp in milliseconds
        end_ts: End timestamp in milliseconds
        app: Flask application instance
        verbose: Print progress messages
        save_every: Save to DB every N candles (default 10,000)

    Returns:
        Tuple of (fetched_count, saved_count)
    """

    all_candles = []
    total_fetched = 0
    total_saved = 0
    current_ts = start_ts
    batch_size = 1000
    total_range = end_ts - start_ts
    last_progress = -1
    consecutive_errors = 0

    while current_ts < end_ts:
        retries = 0
        success = False
        batch = None

        while retries < MAX_RETRIES and not success:
            try:
                batch = await exchange.fetch_ohlcv(symbol, '1m', since=current_ts, limit=batch_size)

                if not batch:
                    success = True
                    break

                all_candles.extend(batch)
                total_fetched += len(batch)
                consecutive_errors = 0

                # Save every N candles for crash resilience
                if len(all_candles) >= save_every:
                    saved = _save_candles_batch(app, symbol_id, all_candles)
                    total_saved += saved
                    all_candles = []

                # Move to next batch
                last_ts = batch[-1][0]
                if last_ts <= current_ts:
                    success = True
                    break
                current_ts = last_ts + 60000
                success = True

                # Show progress
                if not verbose:
                    progress = int((current_ts - start_ts) / total_range * 10)
                    if progress > last_progress:
                        print(".", end='', flush=True)
                        last_progress = progress
                else:
                    if total_fetched % 10000 < batch_size:
                        print(f"    Fetched {total_fetched:,} candles...", end='\r')

            except Exception as e:
                retries += 1
                consecutive_errors += 1

                if is_rate_limit_error(e):
                    wait_time = extract_rate_limit_wait_time(e)
                    logger.warning(f"{symbol}: Rate limit hit, cooling off {wait_time}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Rate limit hit, cooling off {wait_time}s...")
                    await asyncio.sleep(wait_time)

                elif is_timeout_error(e):
                    logger.warning(f"{symbol}: Timeout, retrying in {TIMEOUT_RETRY_DELAY_SECONDS}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Timeout, retrying in {TIMEOUT_RETRY_DELAY_SECONDS}s...")
                    await asyncio.sleep(TIMEOUT_RETRY_DELAY_SECONDS)

                else:
                    logger.error(f"{symbol}: Error at {current_ts}: {e} (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Error at {current_ts}: {e}, retrying...")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

        # If all retries failed, skip this batch and move forward
        if not success:
            logger.error(f"{symbol}: Failed at {current_ts} after {MAX_RETRIES} retries, skipping batch")
            if verbose:
                print(f"\n    Failed after {MAX_RETRIES} retries, skipping batch")
            current_ts += batch_size * 60000

            # If too many consecutive errors, bail out
            if consecutive_errors >= MAX_RETRIES * 3:
                logger.error(f"{symbol}: Too many consecutive errors, aborting fetch")
                if verbose:
                    print(f"\n    Too many consecutive errors, aborting")
                break

        # Break if no more data
        if success and not batch:
            break

    # Save remaining candles
    if all_candles:
        saved = _save_candles_batch(app, symbol_id, all_candles)
        total_saved += saved

    return total_fetched, total_saved


def _save_candles_batch(app, symbol_id: int, candles: List) -> int:
    """Save candles to database, skipping duplicates."""
    from app import db
    from app.models import Candle

    if not candles:
        return 0

    with app.app_context():
        # Get existing timestamps
        timestamps = [c[0] for c in candles]
        existing = set(
            c.timestamp for c in Candle.query.filter(
                Candle.symbol_id == symbol_id,
                Candle.timeframe == '1m',
                Candle.timestamp.in_(timestamps)
            ).all()
        )

        new_count = 0
        for candle in candles:
            ts, o, h, l, c, v = candle
            if ts in existing:
                continue
            if any(x is None or x <= 0 for x in [o, h, l, c]):
                continue

            db.session.add(Candle(
                symbol_id=symbol_id,
                timeframe='1m',
                timestamp=ts,
                open=o, high=h, low=l, close=c,
                volume=v or 0
            ))
            new_count += 1

        if new_count > 0:
            db.session.commit()

        return new_count


async def fill_gaps_for_symbol(
    exchange,
    symbol_name: str,
    symbol_id: int,
    days: int,
    verbose: bool = False,
    full_scan: bool = False,
    app=None,
    print_lock=None
) -> dict:
    """
    Find and fill gaps for a single symbol.

    Args:
        exchange: ccxt async exchange instance
        symbol_name: Symbol name (e.g., 'BTC/USDT')
        symbol_id: Symbol database ID
        days: Days to scan for gaps
        verbose: Show detailed output
        full_scan: If True, scan from beginning of database to now
        app: Flask app context to reuse
        print_lock: asyncio.Lock for serializing output
    """
    from app import db
    from app.models import Candle

    now = datetime.now(timezone.utc)
    end_ts = int(now.timestamp() * 1000) - (5 * 60 * 1000)  # 5 min buffer

    with app.app_context():
        if full_scan:
            # Get earliest candle timestamp from database
            earliest = db.session.query(func.min(Candle.timestamp)).filter(
                Candle.symbol_id == symbol_id,
                Candle.timeframe == '1m'
            ).scalar()

            if earliest:
                start_ts = earliest
            else:
                # No data, use days parameter
                start_ts = int((now - timedelta(days=days)).timestamp() * 1000)
        else:
            start_ts = int((now - timedelta(days=days)).timestamp() * 1000)

        gaps = find_gaps(symbol_id, start_ts, end_ts)

    if not gaps:
        if verbose and print_lock:
            async with print_lock:
                print(f"  {symbol_name}: No gaps found")
        logger.debug(f"{symbol_name}: No gaps found")
        return {'symbol': symbol_name, 'gaps': 0, 'filled': 0}

    # Collect results, then print at end to avoid interleaving
    total_filled = 0
    gap_results = []

    for i, (gap_start, gap_end) in enumerate(gaps):
        gap_duration = (gap_end - gap_start) / (60 * 1000)
        gap_start_dt = datetime.fromtimestamp(gap_start / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        gap_end_dt = datetime.fromtimestamp(gap_end / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')

        # Fetch and save with incremental saves for large gaps
        fetched, filled = await fetch_range_with_save(
            exchange, symbol_name, symbol_id, gap_start, gap_end, app, False
        )

        total_filled += filled
        if filled > 0:
            gap_results.append(f"    [{i+1}/{len(gaps)}] {gap_start_dt} → {gap_end_dt} ({gap_duration:.0f}m) = {filled:,} saved")
        else:
            gap_results.append(f"    [{i+1}/{len(gaps)}] {gap_start_dt} → {gap_end_dt} ({gap_duration:.0f}m) = no data")

    # Print all output for this symbol at once (with lock)
    if print_lock:
        async with print_lock:
            print(f"  {symbol_name}: {len(gaps)} gap(s), {total_filled:,} candles filled")
            if verbose:
                for line in gap_results:
                    print(line)
    else:
        print(f"  {symbol_name}: {len(gaps)} gap(s), {total_filled:,} candles filled")
        if verbose:
            for line in gap_results:
                print(line)

    logger.info(f"{symbol_name}: Filled {len(gaps)} gaps with {total_filled:,} candles")
    return {'symbol': symbol_name, 'gaps': len(gaps), 'filled': total_filled}


async def fetch_symbol_full(
    exchange,
    symbol_name: str,
    symbol_id: int,
    days: int,
    verbose: bool = False,
    index: int = 0,
    total: int = 1,
    app=None
) -> dict:
    """Fetch full history for a symbol with incremental saves."""
    from app import create_app

    now = datetime.now(timezone.utc)
    start_ts = int((now - timedelta(days=days)).timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)

    # Always show progress (symbol name with index)
    print(f"  [{index+1}/{total}] {symbol_name} ", end='', flush=True)

    if verbose:
        print(f"\n    Range: {days} days")

    if app is None:
        app = create_app()

    # Fetch with incremental saves
    fetched_count, new_count = await fetch_range_with_save(
        exchange, symbol_name, symbol_id, start_ts, end_ts, app, verbose
    )

    # Show result on same line (after dots)
    if not verbose:
        print(f" {fetched_count:,} candles, {new_count:,} new", flush=True)
    else:
        print(f"    Saved {new_count:,} new candles")

    logger.info(f"{symbol_name}: Fetched {fetched_count:,} candles, {new_count:,} new")
    return {'symbol': symbol_name, 'fetched': fetched_count, 'new': new_count}


async def run_gap_fill(
    symbols: List[Tuple[str, int]],
    days: int,
    verbose: bool = False,
    full_scan: bool = False
):
    """
    Fill gaps for all symbols with rate-limited parallel fetching.

    Args:
        symbols: List of (symbol_name, symbol_id) tuples
        days: Days to scan for gaps
        verbose: Show detailed output
        full_scan: If True, scan from beginning of database
    """
    from app import create_app
    from app.config import Config

    # Create app once to avoid repeated "Logging system active" messages
    app = create_app()

    exchange = create_exchange('binance')

    # Semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_REQUESTS)

    # Lock for serializing output
    print_lock = asyncio.Lock()

    async def limited_fill(name, sid):
        async with semaphore:
            return await fill_gaps_for_symbol(exchange, name, sid, days, verbose, full_scan, app, print_lock)

    scan_type = "entire database" if full_scan else f"last {days} days"
    if verbose:
        print(f"  Filling gaps for {len(symbols)} symbols ({scan_type}, max {Config.MAX_CONCURRENT_REQUESTS} concurrent)...")

    logger.info(f"Starting gap fill for {len(symbols)} symbols ({scan_type})")

    try:
        tasks = [limited_fill(name, sid) for name, sid in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and log them
        clean_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Gap fill error: {r}")
                if verbose:
                    print(f"  Gap fill error: {r}")
                clean_results.append({'symbol': 'unknown', 'gaps': 0, 'filled': 0, 'error': str(r)})
            else:
                clean_results.append(r)
        return clean_results
    finally:
        await exchange.close()


async def run_full_fetch(
    symbols: List[Tuple[str, int]],
    days: int,
    verbose: bool = False
):
    """Fetch full history for all symbols (sequential for progress display)."""
    from app import create_app

    app = create_app()
    exchange = create_exchange('binance')

    logger.info(f"Starting full fetch for {len(symbols)} symbols, {days} days")

    try:
        results = []
        total = len(symbols)
        for i, (name, sid) in enumerate(symbols):
            result = await fetch_symbol_full(exchange, name, sid, days, verbose, index=i, total=total, app=app)
            results.append(result)

        return results
    finally:
        await exchange.close()


def aggregate_all_symbols(verbose: bool = False, app=None, symbol_filter: str = None):
    """Aggregate 1m candles to all higher timeframes."""
    from app import create_app
    from app.models import Symbol
    from app.services.aggregator import aggregate_all_timeframes

    if app is None:
        app = create_app()
    with app.app_context():
        if symbol_filter:
            symbols = Symbol.query.filter_by(symbol=symbol_filter).all()
        else:
            symbols = Symbol.query.filter_by(is_active=True).all()

        print("\nAggregating to higher timeframes...", flush=True)

        total_candles = 0
        errors = 0
        for i, sym in enumerate(symbols):
            if verbose:
                print(f"  [{i+1}/{len(symbols)}] {sym.symbol}...", end=' ', flush=True)
            try:
                results = aggregate_all_timeframes(sym.symbol)
                totals = sum(results.values())
                total_candles += totals
                if verbose:
                    print(f"{totals:,} candles")
            except Exception as e:
                errors += 1
                logger.error(f"Aggregation error for {sym.symbol}: {e}")
                if verbose:
                    print(f"ERROR: {e}")

        if not verbose:
            print(f"  {total_candles:,} candles aggregated", flush=True)

        if errors > 0:
            logger.warning(f"Aggregation completed with {errors} error(s)")


def show_status():
    """Show database status."""
    from app import create_app, db
    from app.models import Symbol, Candle

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        print(f"\n{'═'*60}")
        print(f"  Database Status")
        print(f"{'═'*60}")

        total = 0
        for sym in symbols:
            count = Candle.query.filter_by(symbol_id=sym.id, timeframe='1m').count()
            total += count

            oldest = db.session.query(func.min(Candle.timestamp)).filter(
                Candle.symbol_id == sym.id, Candle.timeframe == '1m'
            ).scalar()
            newest = db.session.query(func.max(Candle.timestamp)).filter(
                Candle.symbol_id == sym.id, Candle.timeframe == '1m'
            ).scalar()

            if oldest and newest:
                oldest_date = datetime.fromtimestamp(oldest / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                newest_date = datetime.fromtimestamp(newest / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                print(f"  {sym.symbol:12} | {count:>10,} | {oldest_date} → {newest_date}")
            else:
                print(f"  {sym.symbol:12} | {count:>10,} | No data")

        print(f"{'─'*60}")
        print(f"  Total: {total:,} candles (1m)")
        print(f"{'═'*60}\n")


def delete_all():
    """Delete all data."""
    from app import create_app, db
    from app.models import Candle, Pattern, Signal, Notification, Log

    app = create_app()
    with app.app_context():
        print("\n⚠️  This will delete ALL data!")
        confirm = input("Type 'DELETE' to confirm: ")

        if confirm != 'DELETE':
            print("Aborted.")
            return False

        print("\nDeleting...")
        Notification.query.delete()
        Signal.query.delete()
        Pattern.query.delete()
        Log.query.delete()
        Candle.query.delete()
        db.session.commit()
        logger.info("All data deleted")
        print("Done.")
        return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Historical data fetcher')
    parser.add_argument('--days', type=int, default=None, help='Days of history (overrides fetch_start_date setting)')
    parser.add_argument('--gaps', action='store_true', help='Only fill gaps (for hourly cron)')
    parser.add_argument('--full', action='store_true', help='With --gaps: scan entire database, not just last X days')
    parser.add_argument('--status', action='store_true', help='Show database status')
    parser.add_argument('--delete', action='store_true', help='Delete all data')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--no-aggregate', action='store_true', help='Skip aggregation')
    parser.add_argument('--symbol', '-s', type=str, help='Fetch specific symbol only (e.g., BTC/USDT)')
    args = parser.parse_args()

    # Acquire lock to prevent concurrent execution (except for --status which is read-only)
    lock_file = None
    if not args.status:
        lock_file = acquire_lock()
        if lock_file is None:
            print("Another instance is already running, skipping")
            logger.warning("Historical fetch skipped: another instance is running")
            return

    try:
        # Immediate feedback
        print(f"\n{'═'*60}")
        print(f"  CryptoLens Historical Data Fetcher")
        print(f"{'═'*60}")
        print(f"  Loading...", flush=True)

        if args.status:
            show_status()
            return

        if args.delete:
            if delete_all():
                # Continue with fetch after delete
                pass
            else:
                return

        # Get symbols and fetch_start_date setting
        from app import create_app
        from app.models import Symbol, Setting

        app = create_app()
        with app.app_context():
            # Filter by specific symbol if provided
            if args.symbol:
                symbols = Symbol.query.filter_by(symbol=args.symbol).all()
                if not symbols:
                    print(f"  Symbol '{args.symbol}' not found in database.", flush=True)
                    logger.warning(f"Symbol '{args.symbol}' not found")
                    return
            else:
                symbols = Symbol.query.filter_by(is_active=True).all()

            if not symbols:
                print("  No active symbols found. Add symbols in Admin > Symbols.", flush=True)
                logger.warning("No active symbols found")
                return

            symbol_list = [(s.symbol, s.id) for s in symbols]

            # Get fetch_start_date from database setting (default: 2024-01-01)
            fetch_start_setting = Setting.query.filter_by(key='fetch_start_date').first()
            fetch_start_date = fetch_start_setting.value if fetch_start_setting else '2024-01-01'

            # Calculate days from start date to now
            if args.days is not None:
                days = args.days
                date_info = f"{days} days (--days override)"
            else:
                try:
                    start_dt = datetime.strptime(fetch_start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    days = (datetime.now(timezone.utc) - start_dt).days
                    date_info = f"from {fetch_start_date} ({days} days)"
                except ValueError:
                    days = 365
                    date_info = f"365 days (invalid fetch_start_date: {fetch_start_date})"

        start_time = time.time()

        mode_desc = 'Gap fill (full DB)' if args.gaps and args.full else 'Gap fill' if args.gaps else 'Full fetch'
        print(f"  Mode: {mode_desc}")
        print(f"  Symbols: {len(symbol_list)}")
        for sym_name, _ in symbol_list:
            print(f"    • {sym_name}")
        if args.gaps and args.full:
            print(f"  Period: Entire database to now")
        else:
            print(f"  Target: {date_info}")
        print(f"{'═'*60}", flush=True)

        logger.info(f"Starting historical fetch: mode={mode_desc}, symbols={len(symbol_list)}, days={days}")

        if args.gaps:
            # Gap fill mode
            results = asyncio.run(run_gap_fill(symbol_list, days, args.verbose, args.full))

            total_gaps = sum(r['gaps'] for r in results)
            total_filled = sum(r['filled'] for r in results)

            print(f"\n  Gaps found: {total_gaps}")
            print(f"  Candles filled: {total_filled:,}")
            logger.info(f"Gap fill complete: {total_gaps} gaps, {total_filled:,} candles filled")
        else:
            # Full fetch mode
            results = asyncio.run(run_full_fetch(symbol_list, days, args.verbose))

            total_new = sum(r['new'] for r in results)
            print(f"\n  New candles: {total_new:,}")
            logger.info(f"Full fetch complete: {total_new:,} new candles")

        # Aggregate (reuse app from initial symbol fetch)
        if not args.no_aggregate:
            aggregate_all_symbols(args.verbose, app, symbol_filter=args.symbol)

        # Refresh stats cache
        print("\nRefreshing statistics...", flush=True)
        from scripts.compute_stats import compute_stats
        with app.app_context():
            compute_stats()

        elapsed = time.time() - start_time
        print(f"\n  Time: {format_time(elapsed)}")
        print(f"{'═'*60}\n")

        logger.info(f"Historical fetch complete in {format_time(elapsed)}")

    except Exception as e:
        logger.error(f"Historical fetch failed: {e}", exc_info=True)
        print(f"\nERROR: {e}")
        raise

    finally:
        # Always release the lock
        release_lock(lock_file)


if __name__ == '__main__':
    main()
