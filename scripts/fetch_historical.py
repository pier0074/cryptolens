#!/usr/bin/env python3
"""
Historical Data Fetcher with Gap Detection

Features:
- Async parallel fetching for speed
- Gap detection and filling
- Progress tracking via database
- Hourly cron for gap filling, manual for initial load

Usage:
  python fetch_historical.py                    # Initial load (1 year)
  python fetch_historical.py --days=30          # Fetch 30 days
  python fetch_historical.py --gaps             # Find and fill gaps only
  python fetch_historical.py --status           # Show DB status
  python fetch_historical.py --delete           # Delete all data

Cron (hourly gap check):
  0 * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch_historical.py --gaps
"""
import sys
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt_async
from sqlalchemy import func

# Import shared retry utilities
from scripts.utils.retry import (
    async_retry_call, is_rate_limit_error, is_timeout_error,
    extract_rate_limit_wait_time, logger,
    MAX_RETRIES, RETRY_DELAY_SECONDS, TIMEOUT_RETRY_DELAY_SECONDS,
    DEFAULT_RATE_LIMIT_COOLOFF_SECONDS
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

    return gaps


async def fetch_range_async(exchange, symbol: str, start_ts: int, end_ts: int,
                           verbose: bool = False, save_callback=None,
                           save_every: int = 10000) -> List:
    """Fetch candles for a time range using async with retry and rate limit handling.

    Args:
        save_callback: Optional function(candles) to save candles incrementally.
                       If provided, saves every `save_every` candles for crash resilience.
        save_every: Save to DB every N candles (default 10,000 = ~1 week of 1m data)

    Returns:
        List of candles (empty if save_callback was used, since they're already saved)
    """
    all_candles = []
    pending_candles = []  # Buffer for incremental saves
    current_ts = start_ts
    batch_size = 1000
    total_range = end_ts - start_ts
    last_progress = -1
    total_saved = 0
    consecutive_errors = 0

    while current_ts < end_ts:
        retries = 0
        success = False

        while retries < MAX_RETRIES and not success:
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, '1m', since=current_ts, limit=batch_size)
                if not ohlcv:
                    success = True  # No more data, but not an error
                    break

                if save_callback:
                    pending_candles.extend(ohlcv)
                    # Save every N candles for crash resilience
                    if len(pending_candles) >= save_every:
                        saved = save_callback(pending_candles)
                        total_saved += saved
                        pending_candles = []
                else:
                    all_candles.extend(ohlcv)

                # Move to next batch
                last_ts = ohlcv[-1][0]
                if last_ts <= current_ts:
                    success = True
                    break
                current_ts = last_ts + 60000
                success = True
                consecutive_errors = 0  # Reset on success

                # Show progress every 10%
                if not verbose:
                    progress = int((current_ts - start_ts) / total_range * 10)
                    if progress > last_progress:
                        print(".", end='', flush=True)
                        last_progress = progress
                else:
                    count = total_saved + len(pending_candles) if save_callback else len(all_candles)
                    if count % 10000 < batch_size:
                        print(f"    Fetched {count:,} candles...", end='\r')

            except Exception as e:
                retries += 1
                consecutive_errors += 1

                if is_rate_limit_error(e):
                    # Rate limit: extract wait time and cool off
                    wait_time = extract_rate_limit_wait_time(e)
                    logger.warning(f"Rate limit hit for {symbol} at {current_ts}, cooling off {wait_time}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Rate limit hit, cooling off {wait_time}s...")
                    await asyncio.sleep(wait_time)

                elif is_timeout_error(e):
                    # Timeout: retry with shorter delay
                    logger.warning(f"Timeout for {symbol} at {current_ts}, retrying in {TIMEOUT_RETRY_DELAY_SECONDS}s (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Timeout, retrying in {TIMEOUT_RETRY_DELAY_SECONDS}s...")
                    await asyncio.sleep(TIMEOUT_RETRY_DELAY_SECONDS)

                else:
                    # Other error: log and retry with standard delay
                    logger.error(f"Error fetching {symbol} at {current_ts}: {e} (attempt {retries}/{MAX_RETRIES})")
                    if verbose:
                        print(f"\n    Error at {current_ts}: {e}, retrying...")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

        # If all retries failed, skip this batch and move forward
        if not success:
            logger.error(f"Failed to fetch {symbol} at {current_ts} after {MAX_RETRIES} retries, skipping batch")
            if verbose:
                print(f"\n    Failed after {MAX_RETRIES} retries, skipping batch")
            current_ts += batch_size * 60000

            # If too many consecutive errors, bail out
            if consecutive_errors >= MAX_RETRIES * 3:
                logger.error(f"Too many consecutive errors for {symbol}, aborting fetch")
                if verbose:
                    print(f"\n    Too many consecutive errors, aborting")
                break

        # Break if no more data
        if success and not ohlcv:
            break

    # Save remaining pending candles
    if save_callback and pending_candles:
        saved = save_callback(pending_candles)
        total_saved += saved

    return all_candles if not save_callback else []


def save_candles_batch(symbol_id: int, candles: List, verbose: bool = False) -> int:
    """Save candles to database, skipping duplicates."""
    from app import db
    from app.models import Candle

    if not candles:
        return 0

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


async def fill_gaps_for_symbol(exchange, symbol_name: str, symbol_id: int,
                               days: int, verbose: bool = False,
                               full_scan: bool = False, app=None, print_lock=None) -> dict:
    """Find and fill gaps for a single symbol.

    Args:
        full_scan: If True, scan from beginning of database to now (ignores days parameter)
        app: Flask app context to reuse (avoids creating multiple apps)
        print_lock: asyncio.Lock for serializing output
    """
    from app import db
    from app.models import Candle
    from sqlalchemy import func

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
        return {'symbol': symbol_name, 'gaps': 0, 'filled': 0}

    # Collect results, then print at end to avoid interleaving
    total_filled = 0
    gap_results = []

    # Create save callback that uses app context
    def make_save_callback():
        saved_count = [0]  # Use list to allow mutation in closure

        def save_cb(candles):
            with app.app_context():
                saved = save_candles_batch(symbol_id, candles, False)
                saved_count[0] += saved
                return saved
        return save_cb, saved_count

    for i, (gap_start, gap_end) in enumerate(gaps):
        gap_duration = (gap_end - gap_start) / (60 * 1000)
        gap_start_dt = datetime.fromtimestamp(gap_start / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        gap_end_dt = datetime.fromtimestamp(gap_end / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')

        # Use incremental saves for large gaps (>10k candles = ~1 week)
        save_cb, saved_count = make_save_callback()
        await fetch_range_async(exchange, symbol_name, gap_start, gap_end, False,
                                save_callback=save_cb, save_every=10000)

        filled = saved_count[0]
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

    return {'symbol': symbol_name, 'gaps': len(gaps), 'filled': total_filled}


async def fetch_symbol_full(exchange, symbol_name: str, symbol_id: int,
                           days: int, verbose: bool = False, index: int = 0,
                           total: int = 1) -> dict:
    """Fetch full history for a symbol with incremental saves."""
    from app import create_app

    now = datetime.now(timezone.utc)
    start_ts = int((now - timedelta(days=days)).timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)

    # Always show progress (symbol name with index)
    print(f"  [{index+1}/{total}] {symbol_name} ", end='', flush=True)

    if verbose:
        print(f"\n    Range: {days} days")

    app = create_app()
    total_saved = [0]
    total_fetched = [0]

    # Create save callback for incremental saves
    def save_cb(candles):
        with app.app_context():
            saved = save_candles_batch(symbol_id, candles, False)
            total_saved[0] += saved
            total_fetched[0] += len(candles)
            return saved

    # Use incremental saves every 10k candles
    await fetch_range_async(exchange, symbol_name, start_ts, end_ts, verbose,
                            save_callback=save_cb, save_every=10000)

    new_count = total_saved[0]
    fetched_count = total_fetched[0]

    # Show result on same line (after dots)
    if not verbose:
        print(f" {fetched_count:,} candles, {new_count:,} new", flush=True)
    else:
        print(f"    Saved {new_count:,} new candles")

    return {'symbol': symbol_name, 'fetched': fetched_count, 'new': new_count}


async def run_gap_fill(symbols: List[Tuple[str, int]], days: int, verbose: bool = False,
                       full_scan: bool = False):
    """Fill gaps for all symbols with rate-limited parallel fetching.

    Args:
        full_scan: If True, scan from beginning of database (not just last X days)
    """
    from app import create_app
    from app.config import Config

    # Create app once to avoid repeated "Logging system active" messages
    app = create_app()

    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

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

    try:
        tasks = [limited_fill(name, sid) for name, sid in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out exceptions and log them
        clean_results = []
        for r in results:
            if isinstance(r, Exception):
                if verbose:
                    print(f"  Gap fill error: {r}")
                clean_results.append({'symbol': 'unknown', 'gaps': 0, 'filled': 0, 'error': str(r)})
            else:
                clean_results.append(r)
        return clean_results
    finally:
        await exchange.close()


async def run_full_fetch(symbols: List[Tuple[str, int]], days: int, verbose: bool = False):
    """Fetch full history for all symbols (sequential for progress display)."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        results = []
        total = len(symbols)
        for i, (name, sid) in enumerate(symbols):
            result = await fetch_symbol_full(exchange, name, sid, days, verbose,
                                            index=i, total=total)
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
    from app import create_app, db
    from app.models import Symbol, Setting
    from app.config import Config

    app = create_app()
    with app.app_context():
        # Filter by specific symbol if provided
        if args.symbol:
            symbols = Symbol.query.filter_by(symbol=args.symbol).all()
            if not symbols:
                print(f"  Symbol '{args.symbol}' not found in database.", flush=True)
                return
        else:
            symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("  No active symbols found. Add symbols in Admin > Symbols.", flush=True)
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

    if args.gaps:
        # Gap fill mode
        results = asyncio.run(run_gap_fill(symbol_list, days, args.verbose, args.full))

        total_gaps = sum(r['gaps'] for r in results)
        total_filled = sum(r['filled'] for r in results)

        print(f"\n  Gaps found: {total_gaps}")
        print(f"  Candles filled: {total_filled:,}")
    else:
        # Full fetch mode
        results = asyncio.run(run_full_fetch(symbol_list, days, args.verbose))

        total_new = sum(r['new'] for r in results)
        print(f"\n  New candles: {total_new:,}")

    # Aggregate (reuse app from initial symbol fetch)
    if not args.no_aggregate:
        aggregate_all_symbols(args.verbose, app, symbol_filter=args.symbol)

    elapsed = time.time() - start_time
    print(f"\n  Time: {format_time(elapsed)}")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()
