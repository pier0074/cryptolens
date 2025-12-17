#!/usr/bin/env python
"""
Real-time Candle Fetcher with Pattern Detection

Optimized async flow:
1. Batch query all symbols' last timestamps (single DB query)
2. Align fetch start time across all symbols
3. True parallel fetch using ccxt rate limiting (no semaphore)
4. Batch save candles
5. Aggregate higher timeframes
6. Detect patterns
7. Update pattern status
8. Generate signals
9. Expire old patterns
10. Log run to database

Usage:
  python scripts/fetch.py              # Normal fetch (silent)
  python scripts/fetch.py --verbose    # Verbose output with details
  python scripts/fetch.py --gaps       # Use 'gaps' job name for cron tracking

Options:
  --verbose, -v   Show detailed output (symbols, candle counts, timing)
  --gaps          Log this run as 'gaps' job instead of 'fetch' job

Cron setup:
  * * * * * cd /path && venv/bin/python scripts/fetch.py
"""
import sys
import os
import asyncio
import time
import traceback
import fcntl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lock file path for preventing concurrent execution
LOCK_FILE = '/tmp/cryptolens_fetch.lock'

from datetime import datetime, timezone

# Import shared fetch utilities
from scripts.utils.fetch_utils import (
    get_all_last_timestamps,
    get_aligned_fetch_start,
    fetch_symbol_batches,
    create_exchange,
    logger
)

# All timeframes to aggregate (always, regardless of current time)
ALL_TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']


def process_symbol(symbol_name, ohlcv, app, verbose=False):
    """
    Process a single symbol after fetch:
    1. Save candles to DB
    2. Aggregate ALL higher timeframes
    3. Detect patterns on all fetched candles
    4. Update pattern status
    """
    import time as _time
    from app.models import Symbol, Candle
    from app.services.aggregator import aggregate_new_candles
    from app.services.patterns import get_all_detectors
    from app import db

    _t0 = _time.time()
    _timings = {}  # Track where time is spent
    with app.app_context():
        # Get symbol
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            logger.warning(f"{symbol_name}: Symbol not found in database")
            return {'symbol': symbol_name, 'new': 0, 'patterns': 0}

        # 1. Save new candles with IntegrityError handling
        from sqlalchemy.exc import IntegrityError

        timestamps = [c[0] for c in ohlcv]
        existing = set(
            c.timestamp for c in Candle.query.filter(
                Candle.symbol_id == sym.id,
                Candle.timeframe == '1m',
                Candle.timestamp.in_(timestamps)
            ).all()
        )

        new_count = 0
        for candle in ohlcv:
            ts, o, h, l, c, v = candle
            if ts in existing:
                continue
            db.session.add(Candle(
                symbol_id=sym.id,
                timeframe='1m',
                timestamp=ts,
                open=o, high=h, low=l, close=c,
                volume=v or 0
            ))
            new_count += 1

        if new_count > 0:
            try:
                db.session.commit()
                logger.debug(f"{symbol_name}: Saved {new_count} new 1m candles")
            except IntegrityError:
                db.session.rollback()
                logger.warning(f"{symbol_name}: Some candles already existed (race condition)")
                new_count = 0

        # 2. Aggregate ALL higher timeframes (smart aggregation)
        # aggregate_new_candles() automatically:
        # - Finds last aggregated timestamp
        # - Loads only source candles after that point
        # - Creates all possible complete target candles
        # - Skips current incomplete period
        _t_agg = _time.time()
        for tf in ALL_TIMEFRAMES:
            try:
                aggregate_new_candles(symbol_name, '1m', tf)
            except Exception as e:
                db.session.rollback()
                logger.error(f"{symbol_name}: Aggregation failed for {tf}: {e}")
                if verbose:
                    print(f"  Warning: Aggregation failed for {tf}: {e}")
        _timings['aggregation'] = _time.time() - _t_agg

        # 3. Detect patterns on all timeframes
        # OPTIMIZED: Load DataFrame once per timeframe, share across all detectors
        # Pre-compute ATR/swings once per timeframe, batch commits
        patterns_found = 0
        if new_count > 0:
            from app.services.aggregator import get_candles_as_dataframe
            from app.services.trading import calculate_atr, find_swing_high, find_swing_low

            detectors = get_all_detectors()
            scan_limit = len(ohlcv) + 50  # Fetched candles + context

            for tf in ['1m'] + ALL_TIMEFRAMES:
                # Scale limit for higher timeframes
                tf_multiplier = {
                    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
                    '1h': 60, '2h': 120, '4h': 240, '1d': 1440
                }.get(tf, 1)
                tf_limit = max(50, scan_limit // tf_multiplier + 10)

                # Load DataFrame ONCE per timeframe (not 3x per detector)
                try:
                    df = get_candles_as_dataframe(symbol_name, tf, tf_limit)
                except Exception as e:
                    logger.error(f"{symbol_name}: Failed to load candles for {tf}: {e}")
                    continue

                # Pre-compute ATR and swings ONCE per timeframe (not per pattern)
                precomputed = None
                if df is not None and not df.empty:
                    precomputed = {
                        'atr': calculate_atr(df),
                        'swing_high': find_swing_high(df, len(df) - 1),
                        'swing_low': find_swing_low(df, len(df) - 1)
                    }

                # Prefetch existing patterns ONCE for all detectors
                for detector in detectors:
                    try:
                        detector.prefetch_existing_patterns(sym.id, tf)
                    except Exception:
                        pass  # Will fall back to DB queries

                for detector in detectors:
                    try:
                        # Pass pre-loaded DataFrame and precomputed values
                        patterns = detector.detect(symbol_name, tf, limit=tf_limit, df=df, precomputed=precomputed)
                        if patterns:
                            patterns_found += len(patterns)
                    except Exception as e:
                        # Ensure session is clean before continuing
                        db.session.rollback()
                        logger.error(f"{symbol_name}: Pattern detection failed for {detector.__class__.__name__} on {tf}: {e}")
                        if verbose:
                            print(f"  Warning: Pattern detection failed for {detector.__class__.__name__} on {tf}: {e}")
                    finally:
                        # Clear cache after detection
                        detector.clear_pattern_cache()

            # Single commit after all pattern detection (not per detector/timeframe)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"{symbol_name}: Pattern commit failed: {e}")

        # 4. Update pattern status with current price (BATCHED - single commit)
        if ohlcv:
            current_price = ohlcv[-1][4]  # close price
            detectors = get_all_detectors()
            for detector in detectors:
                if hasattr(detector, 'update_pattern_status'):
                    for tf in ['1m'] + ALL_TIMEFRAMES:
                        try:
                            # Don't commit each call - batch them
                            detector.update_pattern_status(symbol_name, tf, current_price, commit=False)
                        except Exception as e:
                            db.session.rollback()
                            logger.error(f"{symbol_name}: Pattern status update failed for {detector.__class__.__name__} on {tf}: {e}")
                            if verbose:
                                print(f"  Warning: Pattern status update failed for {detector.__class__.__name__} on {tf}: {e}")

            # Single commit for all status updates
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"{symbol_name}: Pattern status commit failed: {e}")

        _elapsed = _time.time() - _t0
        if verbose and (new_count > 0 or patterns_found > 0):
            print(f"  {symbol_name}: {new_count} candles, {patterns_found} patterns ({_elapsed:.1f}s)")

        logger.info(f"{symbol_name}: Processed {new_count} candles, {patterns_found} patterns in {_elapsed:.1f}s")

        return {
            'symbol': symbol_name,
            'new': new_count,
            'patterns': patterns_found,
            'time': _elapsed
        }


async def run_fetch_cycle(symbols, app, verbose=False):
    """
    True parallel fetch cycle - ccxt handles rate limiting.

    Phase 1: Batch query all timestamps (1 DB query)
    Phase 2: Parallel fetch all symbols (ccxt queues internally)
    Phase 3: Sequential processing (after all fetches complete)
    """
    import time as _time

    # Create exchange - let ccxt handle rate limiting
    exchange = create_exchange('binance')

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    target_time = datetime.now(timezone.utc).strftime('%H:%M')

    try:
        # Phase 1: Get all timestamps in ONE query
        _t0 = _time.time()
        last_timestamps = get_all_last_timestamps(app, symbols)

        # Calculate aligned fetch start (oldest timestamp across all symbols)
        fetch_start = get_aligned_fetch_start(last_timestamps, now_ms)
        gap_minutes = (now_ms - fetch_start) // 60000

        if verbose:
            print(f"  Target: {target_time} UTC")
            print(f"  Phase 1: Fetching {len(symbols)} symbols in parallel...")
            for symbol in symbols:
                print(f"  {symbol}: Fetching {gap_minutes} min gap...")

        logger.info(f"Fetch cycle: {len(symbols)} symbols, {gap_minutes} minutes gap")

        # Phase 2: Create ALL fetch tasks at once (true parallel)
        _t2 = _time.time()
        fetch_tasks = {
            symbol: asyncio.create_task(
                fetch_symbol_batches(exchange, symbol, fetch_start, now_ms, verbose=False)
            )
            for symbol in symbols
        }

        # Wait for ALL fetches to complete (ccxt queues internally)
        fetch_results = {}
        fetch_errors = {}

        for symbol, task in fetch_tasks.items():
            try:
                fetch_results[symbol] = await task
            except Exception as e:
                fetch_errors[symbol] = str(e)
                fetch_results[symbol] = []
                logger.error(f"{symbol}: Fetch failed - {e}")

        _t3 = _time.time()
        total_candles = sum(len(v) for v in fetch_results.values())

        if verbose:
            print(f"  Phase 1 complete: {total_candles:,} candles in {(_t3-_t2):.1f}s")

        logger.info(f"Fetch phase complete: {total_candles:,} candles in {_t3-_t2:.1f}s")

        # Phase 3: Process results sequentially (CPU-bound, doesn't block network)
        if verbose:
            print(f"  Phase 2: Processing {len(symbols)} symbols...")

        _t4 = _time.time()
        results = []
        for symbol in symbols:
            ohlcv = fetch_results.get(symbol, [])
            if symbol in fetch_errors:
                results.append({
                    'symbol': symbol,
                    'new': 0,
                    'patterns': 0,
                    'error': fetch_errors[symbol]
                })
            elif ohlcv:
                result = process_symbol(symbol, ohlcv, app, verbose)
                results.append(result)
            else:
                results.append({'symbol': symbol, 'new': 0, 'patterns': 0})

        if verbose:
            _t5 = _time.time()
            print(f"  Phase 2 complete: processed in {(_t5-_t4):.1f}s")

        return results

    finally:
        await exchange.close()


def generate_signals_batch(app, verbose=False):
    """Generate signals for all symbols (runs once after all fetches)."""
    import time as _time
    from app.services.signals import scan_and_generate_signals

    with app.app_context():
        try:
            _t0 = _time.time()
            result = scan_and_generate_signals()
            elapsed = _time.time() - _t0
            if verbose:
                print(f"  Generated {result['signals_generated']} signals ({elapsed:.1f}s)")
            logger.info(f"Generated {result['signals_generated']} signals in {elapsed:.1f}s")
            result['time'] = elapsed
            return result
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            if verbose:
                print(f"  Signal error: {e}")
            return {'signals_generated': 0, 'time': 0}


def expire_old_patterns(app, verbose=False):
    """Mark expired patterns based on timeframe-specific expiry."""
    import time as _time
    from app.models import Pattern
    from app.config import Config
    from app import db

    with app.app_context():
        _t0 = _time.time()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        active_patterns = Pattern.query.filter_by(status='active').all()

        expired_count = 0
        for pattern in active_patterns:
            expiry_hours = Config.PATTERN_EXPIRY_HOURS.get(
                pattern.timeframe,
                Config.DEFAULT_PATTERN_EXPIRY_HOURS
            )
            expiry_ms = expiry_hours * 60 * 60 * 1000
            expires_at = pattern.detected_at + expiry_ms

            if now_ms > expires_at:
                pattern.status = 'expired'
                expired_count += 1

        if expired_count > 0:
            db.session.commit()

        elapsed = _time.time() - _t0
        logger.info(f"Expired {expired_count} patterns in {elapsed:.1f}s")
        if verbose:
            print(f"  Expired {expired_count} patterns ({elapsed:.1f}s)")

        return {'expired': expired_count, 'time': elapsed}


def start_cron_run(app, job_name='fetch'):
    """Start tracking a cron run."""
    from app.models import CronJob, CronRun
    from app import db

    with app.app_context():
        # Get or create the job
        job = CronJob.query.filter_by(name=job_name).first()
        if not job:
            from app.models import CRON_JOB_TYPES
            config = CRON_JOB_TYPES.get(job_name, {})
            job = CronJob(
                name=job_name,
                description=config.get('description', ''),
                schedule=config.get('schedule', '* * * * *'),
                is_enabled=True
            )
            db.session.add(job)
            db.session.commit()

        # Check if job is enabled
        if not job.is_enabled:
            logger.info(f"Job '{job_name}' is disabled, skipping")
            return None

        # Create a new run record
        run = CronRun(job_id=job.id)
        db.session.add(run)
        db.session.commit()
        return run.id


def complete_cron_run(app, run_id, success=True, error_message=None,
                      symbols_processed=0, candles_fetched=0, patterns_found=0,
                      signals_generated=0, notifications_sent=0):
    """Complete a cron run with results."""
    from app.models import CronRun
    from app import db

    if not run_id:
        return

    with app.app_context():
        run = db.session.get(CronRun, run_id)
        if run:
            run.ended_at = datetime.now(timezone.utc)
            # Handle timezone-naive started_at from database
            started_at = run.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            run.duration_ms = int((run.ended_at - started_at).total_seconds() * 1000)
            run.success = success
            run.error_message = error_message
            run.symbols_processed = symbols_processed
            run.candles_fetched = candles_fetched
            run.patterns_found = patterns_found
            run.signals_generated = signals_generated
            run.notifications_sent = notifications_sent
            db.session.commit()

            logger.info(f"Cron run completed: success={success}, symbols={symbols_processed}, candles={candles_fetched}")


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


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Candle fetcher with pattern detection')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--gaps', action='store_true', help='Fill data gaps (hourly job)')
    args = parser.parse_args()

    # Acquire lock to prevent concurrent execution
    lock_file = acquire_lock()
    if lock_file is None:
        print("Another instance is already running, skipping")
        logger.warning("Fetch skipped: another instance is running")
        return

    job_name = 'gaps' if args.gaps else 'fetch'

    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f"[{ts}] {'Filling gaps' if args.gaps else 'Fetching'}...", end=' ', flush=True)

    start_time = time.time()
    run_id = None
    error_msg = None

    from app import create_app
    from app.models import Symbol

    app = create_app()

    try:
        # Start tracking the run
        run_id = start_cron_run(app, job_name)
        if run_id is None:
            print("Job disabled, skipping")
            return

        with app.app_context():
            symbols = [s.symbol for s in Symbol.query.filter_by(is_active=True).all()]

        if not symbols:
            print("No active symbols found")
            logger.warning("No active symbols found")
            complete_cron_run(app, run_id, success=True, symbols_processed=0)
            return

        if args.verbose:
            print(f"\n  {len(symbols)} symbols")

        logger.info(f"Starting fetch cycle for {len(symbols)} symbols")

        # 1. Fetch and process all symbols (parallel)
        results = asyncio.run(run_fetch_cycle(symbols, app, args.verbose))

        # 2. Generate signals
        signal_result = generate_signals_batch(app, args.verbose)

        # 3. Expire old patterns
        expire_result = expire_old_patterns(app, args.verbose)

        # Summary
        total_new = sum(r.get('new', 0) for r in results)
        total_patterns = sum(r.get('patterns', 0) for r in results)
        total_signals = signal_result.get('signals_generated', 0)
        errors = [r.get('error') for r in results if r.get('error')]

        # Log success (or partial success with errors)
        complete_cron_run(
            app, run_id,
            success=len(errors) == 0,
            error_message='; '.join(errors[:3]) if errors else None,
            symbols_processed=len(symbols),
            candles_fetched=total_new,
            patterns_found=total_patterns,
            signals_generated=total_signals,
            notifications_sent=0  # Updated by notification service if used
        )

        # Refresh stats cache
        from scripts.compute_stats import compute_stats
        _t_stats = time.time()
        with app.app_context():
            compute_stats()
        stats_time = time.time() - _t_stats
        if args.verbose:
            print(f"  Stats cache refreshed ({stats_time:.1f}s)")

        elapsed = time.time() - start_time

        logger.info(f"Fetch cycle complete: {total_new} candles, {total_patterns} patterns, {total_signals} signals in {elapsed:.1f}s")

        if args.verbose:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                  f"Total: {total_new} candles, {total_patterns} patterns, {total_signals} signals "
                  f"({elapsed:.1f}s)")
        else:
            print(f"done. {total_new} candles, {total_patterns} patterns, {total_signals} signals ({elapsed:.1f}s)")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"ERROR: {error_msg}")
        logger.error(f"Fetch cycle failed: {error_msg}", exc_info=True)
        if args.verbose:
            traceback.print_exc()

        # Log failure
        complete_cron_run(
            app, run_id,
            success=False,
            error_message=error_msg
        )

    finally:
        # Always release the lock
        release_lock(lock_file)


if __name__ == '__main__':
    main()
