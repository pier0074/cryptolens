#!/usr/bin/env python
"""
Database Health Check for Candle Data (Hierarchical Verification)

VERIFICATION ORDER (Critical):
1. First, verify ALL 1m candles - these are the source of truth
2. Only after 1m candles are verified, verify aggregated timeframes
3. Aggregated candles are recalculated from 1m and compared

Checks:
1. Gap detection - missing candles in sequence
2. Timestamp alignment - higher TFs at correct boundaries
3. OHLCV sanity - high >= low, high >= open/close, etc.
4. Aggregation accuracy - recalculate from 1m and compare

Usage:
  python scripts/db_health.py                    # Report only (one batch)
  python scripts/db_health.py --fix              # Fix issues in one batch
  python scripts/db_health.py --until-done       # Run until all verified or error
  python scripts/db_health.py --until-done --fix # Run continuously with fixes
  python scripts/db_health.py --symbol BTC/USDT  # Check specific symbol
  python scripts/db_health.py --reset            # Reset all verification flags
  python scripts/db_health.py --batch-size week  # Use week-sized batches (default)
  python scripts/db_health.py --batch-size day   # Use day-sized batches

Options:
  --fix              Auto-fix issues (delete bad candles, fetch missing, re-aggregate)
  --until-done       Run continuously until all candles verified or unfixable error
  --max-iterations N Maximum iterations in until-done mode (default: unlimited)
  --batch-size SIZE  Batch size: 'day' (1440) or 'week' (10080, default)
  --symbol, -s SYM   Check specific symbol only (e.g., BTC/USDT)
  --reset            Reset all verification flags
  --accept-gaps      Mark current gaps as accepted
  --show-gaps        Show all known/accepted gaps
  --clear-gaps       Clear all known gaps
  --quiet, -q        Only show summary

Batch Sizes:
  day  = 1440 candles  (60 min * 24 hours)
  week = 10080 candles (1440 * 7 days)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
from datetime import datetime, timezone
from collections import defaultdict

import ccxt.async_support as ccxt_async

from app import create_app, db
from app.models import Symbol, Candle, KnownGap

# Import shared retry utilities
from scripts.utils.retry import async_retry_call

# Meaningful batch sizes
BATCH_SIZES = {
    'day': 1440,    # 60 minutes * 24 hours
    'week': 10080,  # 1440 * 7 days
}

# Timeframe intervals in milliseconds
TF_MS = {
    '1m': 60000,
    '5m': 300000,
    '15m': 900000,
    '30m': 1800000,
    '1h': 3600000,
    '2h': 7200000,
    '4h': 14400000,
    '1d': 86400000,
}

# Alignment modulo values (in minutes)
TF_ALIGNMENT_MOD = {
    '5m': 5,
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '4h': 240,
    '1d': 1440,
}

# Number of 1m candles per aggregated candle
TF_1M_COUNT = {
    '5m': 5,
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '4h': 240,
    '1d': 1440,
}

# Aggregated timeframes in order
AGGREGATED_TFS = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']


def check_candle_ohlcv(candle):
    """Check OHLCV sanity for a single candle. Returns list of problems."""
    problems = []
    if candle.high < candle.low:
        problems.append('high < low')
    if candle.high < candle.open:
        problems.append('high < open')
    if candle.high < candle.close:
        problems.append('high < close')
    if candle.low > candle.open:
        problems.append('low > open')
    if candle.low > candle.close:
        problems.append('low > close')
    if candle.volume < 0:
        problems.append('volume < 0')
    if candle.open <= 0 or candle.close <= 0 or candle.high <= 0 or candle.low <= 0:
        problems.append('price <= 0')
    return problems


def check_candle_alignment(candle):
    """Check if candle timestamp is properly aligned. Returns True if aligned."""
    if candle.timeframe == '1m':
        return True  # 1m is always aligned

    mod = TF_ALIGNMENT_MOD.get(candle.timeframe)
    if not mod:
        return True

    # Timestamp in minutes should be divisible by mod
    minutes = candle.timestamp // 60000
    return minutes % mod == 0


def check_gap(prev_candle, curr_candle, interval_ms):
    """Check if there's a gap between two candles. Returns number of missing candles."""
    expected = prev_candle.timestamp + interval_ms
    if curr_candle.timestamp > expected:
        return (curr_candle.timestamp - expected) // interval_ms
    return 0


def is_known_gap(symbol_id, timeframe, gap_start, gap_end):
    """Check if a gap is already known/accepted."""
    return KnownGap.query.filter(
        KnownGap.symbol_id == symbol_id,
        KnownGap.timeframe == timeframe,
        KnownGap.gap_start <= gap_start,
        KnownGap.gap_end >= gap_end
    ).first() is not None


def get_1m_candles_for_aggregation(symbol_id, timeframe, agg_timestamp):
    """
    Get the 1m candles that should aggregate into a specific aggregated candle.

    Returns: list of Candle objects, or None if not all 1m candles are verified
    """
    interval_ms = TF_MS[timeframe]
    count = TF_1M_COUNT[timeframe]

    # The aggregated candle timestamp marks the START of the period
    start_ts = agg_timestamp
    end_ts = agg_timestamp + interval_ms - 60000  # Last 1m candle in the period

    # Get all 1m candles in this range
    candles_1m = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m',
        Candle.timestamp >= start_ts,
        Candle.timestamp <= end_ts
    ).order_by(Candle.timestamp).all()

    # Check if all are verified
    if len(candles_1m) != count:
        return None  # Missing 1m candles

    for c in candles_1m:
        if c.verified_at is None:
            return None  # Unverified 1m candle

    return candles_1m


def calculate_aggregated_ohlcv(candles_1m):
    """
    Calculate what the aggregated OHLCV should be from 1m candles.

    Returns: dict with open, high, low, close, volume
    """
    if not candles_1m:
        return None

    return {
        'open': candles_1m[0].open,
        'high': max(c.high for c in candles_1m),
        'low': min(c.low for c in candles_1m),
        'close': candles_1m[-1].close,
        'volume': sum(c.volume for c in candles_1m),
    }


def validate_aggregated_candle(candle, candles_1m, tolerance=0.0001):
    """
    Validate an aggregated candle by recalculating from 1m data.

    Returns: list of problems, empty if valid
    """
    expected = calculate_aggregated_ohlcv(candles_1m)
    if not expected:
        return ['cannot_calculate']

    problems = []

    # Compare with tolerance for floating point
    if abs(candle.open - expected['open']) / max(expected['open'], 0.0001) > tolerance:
        problems.append(f"open mismatch: {candle.open} vs {expected['open']}")

    if abs(candle.high - expected['high']) / max(expected['high'], 0.0001) > tolerance:
        problems.append(f"high mismatch: {candle.high} vs {expected['high']}")

    if abs(candle.low - expected['low']) / max(expected['low'], 0.0001) > tolerance:
        problems.append(f"low mismatch: {candle.low} vs {expected['low']}")

    if abs(candle.close - expected['close']) / max(expected['close'], 0.0001) > tolerance:
        problems.append(f"close mismatch: {candle.close} vs {expected['close']}")

    # Volume can have larger variance
    if expected['volume'] > 0:
        vol_diff = abs(candle.volume - expected['volume']) / expected['volume']
        if vol_diff > 0.01:  # 1% tolerance for volume
            problems.append(f"volume mismatch: {candle.volume} vs {expected['volume']}")

    return problems


async def fetch_missing_candles(symbol_name, gap_start_ms, gap_end_ms, verbose=False):
    """Fetch missing 1m candles from exchange for a gap."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        all_ohlcv = []
        since = gap_start_ms

        while since <= gap_end_ms:
            batch = await async_retry_call(
                exchange.fetch_ohlcv,
                symbol_name, '1m',
                since=since, limit=1000,
                context=f"{symbol_name} gap-fill",
                verbose=verbose
            )

            if not batch:
                break

            for candle in batch:
                if gap_start_ms <= candle[0] <= gap_end_ms:
                    all_ohlcv.append(candle)

            if batch:
                since = batch[-1][0] + 60000
            else:
                break

            if len(batch) == 1000:
                await asyncio.sleep(0.2)

        return all_ohlcv

    finally:
        await exchange.close()


def save_fetched_candles(symbol_id, ohlcv, verbose=False):
    """Save fetched candles to database."""
    if not ohlcv:
        return 0

    timestamps = [c[0] for c in ohlcv]
    existing = set(
        c.timestamp for c in Candle.query.filter(
            Candle.symbol_id == symbol_id,
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
            symbol_id=symbol_id,
            timeframe='1m',
            timestamp=ts,
            open=o, high=h, low=l, close=c,
            volume=v or 0
        ))
        new_count += 1

    if new_count > 0:
        db.session.commit()
        if verbose:
            print(f"    Saved {new_count} candles")

    return new_count


def record_known_gap(symbol_id, timeframe, gap_start, gap_end, missing_candles,
                     reason='no_exchange_data', verified_empty=True):
    """Record a gap as known/accepted."""
    existing = KnownGap.query.filter_by(
        symbol_id=symbol_id,
        timeframe=timeframe,
        gap_start=gap_start
    ).first()

    if existing:
        existing.gap_end = gap_end
        existing.missing_candles = missing_candles
        existing.reason = reason
        existing.verified_empty = verified_empty
    else:
        db.session.add(KnownGap(
            symbol_id=symbol_id,
            timeframe=timeframe,
            gap_start=gap_start,
            gap_end=gap_end,
            missing_candles=missing_candles,
            reason=reason,
            verified_empty=verified_empty
        ))

    db.session.commit()


def reaggregate_candle(symbol_id, symbol_name, timeframe, timestamp, candles_1m):
    """Re-aggregate a single candle from 1m data."""
    expected = calculate_aggregated_ohlcv(candles_1m)
    if not expected:
        return False

    # Find and update or create the aggregated candle
    candle = Candle.query.filter_by(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=timestamp
    ).first()

    if candle:
        candle.open = expected['open']
        candle.high = expected['high']
        candle.low = expected['low']
        candle.close = expected['close']
        candle.volume = expected['volume']
        candle.verified_at = None  # Will be re-verified
    else:
        db.session.add(Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=timestamp,
            open=expected['open'],
            high=expected['high'],
            low=expected['low'],
            close=expected['close'],
            volume=expected['volume']
        ))

    db.session.commit()
    return True


async def fix_gap(symbol, gap_start, gap_end, missing_candles, verbose=False):
    """Attempt to fix a gap by fetching from exchange."""
    if verbose:
        print(f"    Attempting to fetch {missing_candles} missing candles...")

    try:
        ohlcv = await fetch_missing_candles(symbol.symbol, gap_start, gap_end, verbose)

        if ohlcv:
            saved = save_fetched_candles(symbol.id, ohlcv, verbose)

            if saved > 0:
                return {
                    'action': 'filled',
                    'candles_fetched': len(ohlcv),
                    'candles_saved': saved
                }
            else:
                return {
                    'action': 'already_exists',
                    'candles_fetched': len(ohlcv)
                }
        else:
            record_known_gap(
                symbol.id, '1m', gap_start, gap_end, missing_candles,
                reason='no_exchange_data', verified_empty=True
            )
            if verbose:
                print(f"    Exchange has no data - marked as known gap")
            return {
                'action': 'marked_empty',
                'reason': 'no_exchange_data'
            }

    except Exception as e:
        return {
            'action': 'error',
            'error': str(e)
        }


def verify_1m_candles(symbol_id, symbol, fix=False, batch_size=10080, verbose=True):
    """
    Verify 1m candles only.

    Returns dict with:
        - verified: number of newly verified candles
        - error: dict describing first error found (or None)
        - remaining: number of unverified candles remaining
        - all_done: True if all 1m candles are verified
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = TF_MS['1m']

    # Get the last verified 1m candle
    last_verified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m',
        Candle.verified_at.isnot(None)
    ).order_by(Candle.timestamp.desc()).first()

    start_ts = last_verified.timestamp if last_verified else 0

    # Get unverified 1m candles
    unverified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m',
        Candle.timestamp > start_ts,
        Candle.verified_at.is_(None)
    ).order_by(Candle.timestamp).limit(batch_size).all()

    if not unverified:
        # Check total remaining
        total_remaining = Candle.query.filter(
            Candle.symbol_id == symbol_id,
            Candle.timeframe == '1m',
            Candle.verified_at.is_(None)
        ).count()
        return {
            'verified': 0,
            'error': None,
            'remaining': total_remaining,
            'all_done': total_remaining == 0
        }

    prev_candle = last_verified
    verified_count = 0
    error_found = None
    candles_to_verify = []

    for candle in unverified:
        # 1. Check OHLCV sanity
        ohlcv_problems = check_candle_ohlcv(candle)
        if ohlcv_problems:
            error_found = {
                'type': 'ohlcv_invalid',
                'timestamp': candle.timestamp,
                'problems': ohlcv_problems,
                'candle_id': candle.id
            }
            if fix:
                db.session.delete(candle)
                db.session.commit()
                error_found['action'] = 'deleted'
            break

        # 2. Check gap (if we have a previous candle)
        if prev_candle:
            missing = check_gap(prev_candle, candle, interval_ms)
            if missing > 0:
                gap_start = prev_candle.timestamp + interval_ms
                gap_end = candle.timestamp - interval_ms

                # Check if known gap
                if is_known_gap(symbol_id, '1m', gap_start, gap_end):
                    candles_to_verify.append(candle)
                    prev_candle = candle
                    continue

                error_found = {
                    'type': 'gap',
                    'after_timestamp': prev_candle.timestamp,
                    'before_timestamp': candle.timestamp,
                    'gap_start': gap_start,
                    'gap_end': gap_end,
                    'missing_candles': missing
                }

                if fix and symbol:
                    fix_result = asyncio.run(fix_gap(symbol, gap_start, gap_end, missing, verbose))
                    error_found['fix_result'] = fix_result

                    if fix_result['action'] == 'filled':
                        error_found['action'] = 'filled'
                    elif fix_result['action'] == 'marked_empty':
                        candles_to_verify.append(candle)
                        prev_candle = candle
                        error_found = None
                        continue
                    elif fix_result['action'] == 'already_exists':
                        error_found['action'] = 'needs_rerun'

                break

        candles_to_verify.append(candle)
        prev_candle = candle

    # Mark verified candles
    if candles_to_verify:
        for candle in candles_to_verify:
            candle.verified_at = now_ms
        db.session.commit()
        verified_count = len(candles_to_verify)

    # Get remaining count
    remaining = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m',
        Candle.verified_at.is_(None)
    ).count()

    return {
        'verified': verified_count,
        'error': error_found,
        'remaining': remaining,
        'all_done': remaining == 0 and error_found is None
    }


def verify_aggregated_candles(symbol_id, symbol_name, timeframe, fix=False, batch_size=1000, verbose=True):
    """
    Verify aggregated candles by recalculating from 1m data.

    Only verifies candles where ALL underlying 1m candles are verified.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Get unverified aggregated candles
    unverified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == timeframe,
        Candle.verified_at.is_(None)
    ).order_by(Candle.timestamp).limit(batch_size).all()

    if not unverified:
        remaining = Candle.query.filter(
            Candle.symbol_id == symbol_id,
            Candle.timeframe == timeframe,
            Candle.verified_at.is_(None)
        ).count()
        return {
            'verified': 0,
            'skipped': 0,
            'error': None,
            'remaining': remaining,
            'all_done': remaining == 0
        }

    verified_count = 0
    skipped_count = 0
    error_found = None
    candles_to_verify = []

    for candle in unverified:
        # Get underlying 1m candles
        candles_1m = get_1m_candles_for_aggregation(symbol_id, timeframe, candle.timestamp)

        if candles_1m is None:
            # 1m candles not ready yet - skip
            skipped_count += 1
            continue

        # Validate OHLCV sanity first
        ohlcv_problems = check_candle_ohlcv(candle)
        if ohlcv_problems:
            error_found = {
                'type': 'ohlcv_invalid',
                'timestamp': candle.timestamp,
                'problems': ohlcv_problems,
                'candle_id': candle.id
            }
            if fix:
                # Re-aggregate from 1m
                if reaggregate_candle(symbol_id, symbol_name, timeframe, candle.timestamp, candles_1m):
                    error_found['action'] = 'reaggregated'
                else:
                    db.session.delete(candle)
                    db.session.commit()
                    error_found['action'] = 'deleted'
            break

        # Validate aggregation accuracy
        agg_problems = validate_aggregated_candle(candle, candles_1m)
        if agg_problems:
            error_found = {
                'type': 'aggregation_mismatch',
                'timestamp': candle.timestamp,
                'problems': agg_problems,
                'candle_id': candle.id
            }
            if fix:
                # Re-aggregate from 1m
                if reaggregate_candle(symbol_id, symbol_name, timeframe, candle.timestamp, candles_1m):
                    error_found['action'] = 'reaggregated'
                    error_found = None  # Fixed, continue
                    continue
            break

        # Check alignment
        if not check_candle_alignment(candle):
            error_found = {
                'type': 'misaligned',
                'timestamp': candle.timestamp,
                'expected_mod': TF_ALIGNMENT_MOD.get(timeframe),
                'candle_id': candle.id
            }
            if fix:
                db.session.delete(candle)
                db.session.commit()
                error_found['action'] = 'deleted'
            break

        candles_to_verify.append(candle)

    # Mark verified
    if candles_to_verify:
        for candle in candles_to_verify:
            candle.verified_at = now_ms
        db.session.commit()
        verified_count = len(candles_to_verify)

    remaining = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == timeframe,
        Candle.verified_at.is_(None)
    ).count()

    return {
        'verified': verified_count,
        'skipped': skipped_count,
        'error': error_found,
        'remaining': remaining,
        'all_done': remaining == 0 and error_found is None
    }


def get_verification_stats(symbol_id, timeframe):
    """Get verification statistics for a symbol/timeframe."""
    total = Candle.query.filter_by(
        symbol_id=symbol_id,
        timeframe=timeframe
    ).count()

    verified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == timeframe,
        Candle.verified_at.isnot(None)
    ).count()

    return {'total': total, 'verified': verified, 'unverified': total - verified}


def reset_verification(symbol_id=None, timeframe=None):
    """Reset verification flags for candles."""
    query = Candle.query
    if symbol_id:
        query = query.filter(Candle.symbol_id == symbol_id)
    if timeframe:
        query = query.filter(Candle.timeframe == timeframe)

    count = query.update({Candle.verified_at: None})
    db.session.commit()
    return count


def run_health_check(symbol_filter=None, fix=False, verbose=True, reset=False,
                     until_done=False, max_iterations=None, batch_size='week', app=None):
    """
    Run hierarchical health checks.

    Order:
    1. Verify all 1m candles first
    2. Only then verify aggregated timeframes

    Exit conditions:
    - All candles verified
    - No progress made for 3 consecutive iterations (stuck)
    - Max iterations reached
    """
    batch_count = BATCH_SIZES.get(batch_size, 10080)

    if app is None:
        app = create_app()
        context_manager = app.app_context()
    else:
        from contextlib import nullcontext
        context_manager = nullcontext()

    with context_manager:
        if symbol_filter:
            symbols = Symbol.query.filter_by(symbol=symbol_filter).all()
        else:
            symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print(f"No symbols found{' matching ' + symbol_filter if symbol_filter else ''}")
            return

        if reset:
            print("Resetting all verification flags...")
            total_reset = reset_verification()
            print(f"Reset {total_reset} candles.")
            if not fix and not until_done:
                return
            print()

        iteration = 0
        total_verified = 0
        no_progress_count = 0  # Track consecutive iterations with no progress
        MAX_NO_PROGRESS = 3    # Exit after this many iterations with no progress

        while True:
            iteration += 1

            if max_iterations and iteration > max_iterations:
                print(f"\nMax iterations ({max_iterations}) reached.")
                break

            print(f"\n{'='*60}")
            print(f"  DATABASE HEALTH CHECK - Iteration {iteration}")
            print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            print(f"  Mode: {'FIX' if fix else 'REPORT'} | Batch: {batch_size} ({batch_count})")
            print(f"{'='*60}\n")

            iteration_verified = 0
            iteration_skipped = 0  # Track skipped candles
            all_symbols_done = True
            total_errors = defaultdict(int)

            for symbol in symbols:
                symbol_output = []

                # STEP 1: Verify 1m candles first
                stats_1m = get_verification_stats(symbol.id, '1m')
                if stats_1m['total'] > 0:
                    result_1m = verify_1m_candles(
                        symbol.id, symbol, fix=fix,
                        batch_size=batch_count, verbose=verbose
                    )

                    iteration_verified += result_1m['verified']

                    if result_1m['verified'] > 0 or result_1m['error'] or result_1m['remaining'] > 0:
                        line = f"  1m: verified {result_1m['verified']}"
                        if result_1m['remaining'] > 0:
                            line += f", remaining {result_1m['remaining']}"
                            all_symbols_done = False
                        if result_1m['error']:
                            err = result_1m['error']
                            total_errors[err['type']] += 1
                            line += f" | ERROR: {err['type']}"
                            if 'action' in err:
                                line += f" ({err['action']})"
                            all_symbols_done = False
                        symbol_output.append(line)

                    # Only proceed to aggregated TFs if 1m is fully verified
                    if not result_1m['all_done']:
                        if verbose and symbol_output:
                            print(f"{symbol.symbol}:")
                            for line in symbol_output:
                                print(line)
                            print()
                        continue

                # STEP 2: Verify aggregated timeframes (only if 1m is done)
                for tf in AGGREGATED_TFS:
                    stats = get_verification_stats(symbol.id, tf)
                    if stats['total'] == 0:
                        continue

                    result = verify_aggregated_candles(
                        symbol.id, symbol.symbol, tf, fix=fix,
                        batch_size=1000, verbose=verbose
                    )

                    iteration_verified += result['verified']
                    iteration_skipped += result.get('skipped', 0)

                    if result['verified'] > 0 or result['skipped'] > 0 or result['error'] or result['remaining'] > 0:
                        line = f"  {tf}: verified {result['verified']}"
                        if result['skipped'] > 0:
                            line += f", skipped {result['skipped']} (1m pending)"
                        if result['remaining'] > 0:
                            line += f", remaining {result['remaining']}"
                            all_symbols_done = False
                        if result['error']:
                            err = result['error']
                            total_errors[err['type']] += 1
                            line += f" | ERROR: {err['type']}"
                            if 'action' in err:
                                line += f" ({err['action']})"
                        symbol_output.append(line)

                if verbose and symbol_output:
                    print(f"{symbol.symbol}:")
                    for line in symbol_output:
                        print(line)
                    print()

            total_verified += iteration_verified

            # Summary for this iteration
            print(f"{'='*60}")
            print(f"  ITERATION {iteration} SUMMARY")
            print(f"{'='*60}")
            print(f"  Verified this iteration: {iteration_verified}")
            print(f"  Skipped this iteration: {iteration_skipped}")
            print(f"  Total verified: {total_verified}")

            if total_errors:
                print(f"  Errors: {dict(total_errors)}")

            if all_symbols_done:
                print("\n  ALL CANDLES VERIFIED!")
                break

            # Check for stuck state (no progress made)
            if iteration_verified == 0:
                no_progress_count += 1
                if no_progress_count >= MAX_NO_PROGRESS:
                    print(f"\n  NO PROGRESS for {MAX_NO_PROGRESS} consecutive iterations.")
                    print(f"  This usually means remaining candles depend on 1m data")
                    print(f"  that hasn't been fetched yet (near current time).")
                    print(f"  Run the fetch script to get latest 1m data, then try again.")
                    print(f"\n  EXITING - no more work possible at this time.")
                    break
                else:
                    print(f"\n  WARNING: No progress this iteration ({no_progress_count}/{MAX_NO_PROGRESS})")
            else:
                no_progress_count = 0  # Reset counter on progress

            if not until_done:
                remaining_1m = sum(
                    get_verification_stats(s.id, '1m')['unverified']
                    for s in symbols
                )
                print(f"\n  Remaining 1m candles: {remaining_1m}")
                print(f"  Run with --until-done to continue automatically")
                break

            print(f"\n  Continuing to next iteration...")

        print()
        return {'verified': total_verified, 'iterations': iteration}


def accept_current_gaps(symbol_filter=None, verbose=True):
    """Mark all currently detected gaps as accepted/known."""
    app = create_app()

    with app.app_context():
        if symbol_filter:
            symbols = Symbol.query.filter_by(symbol=symbol_filter).all()
        else:
            symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("No symbols found")
            return

        print(f"\n{'='*60}")
        print("  ACCEPTING CURRENT GAPS")
        print(f"{'='*60}\n")

        total_gaps = 0

        for symbol in symbols:
            for tf in ['1m'] + AGGREGATED_TFS:
                interval_ms = TF_MS.get(tf, 60000)

                candles = Candle.query.filter_by(
                    symbol_id=symbol.id,
                    timeframe=tf
                ).order_by(Candle.timestamp).all()

                if len(candles) < 2:
                    continue

                for i in range(1, len(candles)):
                    prev = candles[i - 1]
                    curr = candles[i]
                    missing = check_gap(prev, curr, interval_ms)

                    if missing > 0:
                        gap_start = prev.timestamp + interval_ms
                        gap_end = curr.timestamp - interval_ms

                        if not is_known_gap(symbol.id, tf, gap_start, gap_end):
                            record_known_gap(
                                symbol.id, tf, gap_start, gap_end, missing,
                                reason='accepted', verified_empty=False
                            )
                            total_gaps += 1
                            if verbose:
                                print(f"  {symbol.symbol} {tf}: Accepted gap of {missing} candles")

        print(f"\n{'='*60}")
        print(f"  Accepted {total_gaps} new gaps")
        print(f"{'='*60}\n")


def show_known_gaps(symbol_filter=None):
    """Show all known/accepted gaps."""
    app = create_app()

    with app.app_context():
        query = KnownGap.query

        if symbol_filter:
            symbol = Symbol.query.filter_by(symbol=symbol_filter).first()
            if symbol:
                query = query.filter_by(symbol_id=symbol.id)

        gaps = query.order_by(KnownGap.symbol_id, KnownGap.timeframe, KnownGap.gap_start).all()

        if not gaps:
            print("No known gaps recorded.")
            return

        print(f"\n{'='*60}")
        print("  KNOWN GAPS")
        print(f"{'='*60}\n")

        current_symbol = None
        for gap in gaps:
            symbol = Symbol.query.get(gap.symbol_id)
            if symbol.symbol != current_symbol:
                if current_symbol:
                    print()
                current_symbol = symbol.symbol
                print(f"{current_symbol}:")

            start_dt = datetime.fromtimestamp(gap.gap_start / 1000, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(gap.gap_end / 1000, tz=timezone.utc)
            print(f"  {gap.timeframe}: {start_dt.strftime('%Y-%m-%d %H:%M')} - "
                  f"{end_dt.strftime('%Y-%m-%d %H:%M')} ({gap.missing_candles} candles, {gap.reason})")

        print(f"\n{'='*60}")
        print(f"  Total: {len(gaps)} known gaps")
        print(f"{'='*60}\n")


def clear_known_gaps(symbol_filter=None):
    """Clear all known gaps (to re-check them)."""
    app = create_app()

    with app.app_context():
        query = KnownGap.query

        if symbol_filter:
            symbol = Symbol.query.filter_by(symbol=symbol_filter).first()
            if symbol:
                query = query.filter_by(symbol_id=symbol.id)

        count = query.delete()
        db.session.commit()
        print(f"Cleared {count} known gaps.")


def main():
    parser = argparse.ArgumentParser(
        description='Database health check for candle data (hierarchical verification)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/db_health.py                        # Report one batch
  python scripts/db_health.py --fix                  # Fix one batch
  python scripts/db_health.py --until-done --fix     # Fix everything
  python scripts/db_health.py --reset --until-done --fix  # Full re-verify
        """
    )
    parser.add_argument('--fix', action='store_true',
                        help='Auto-fix: delete bad candles, fetch missing, re-aggregate')
    parser.add_argument('--until-done', action='store_true',
                        help='Run continuously until all verified or unfixable error')
    parser.add_argument('--max-iterations', type=int, default=None,
                        help='Max iterations in until-done mode')
    parser.add_argument('--batch-size', choices=['day', 'week'], default='week',
                        help='Batch size: day (1440) or week (10080, default)')
    parser.add_argument('--symbol', '-s', type=str,
                        help='Check specific symbol (e.g., BTC/USDT)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Only show summary')
    parser.add_argument('--reset', action='store_true',
                        help='Reset all verification flags')
    parser.add_argument('--accept-gaps', action='store_true',
                        help='Mark current gaps as accepted')
    parser.add_argument('--show-gaps', action='store_true',
                        help='Show all known/accepted gaps')
    parser.add_argument('--clear-gaps', action='store_true',
                        help='Clear all known gaps')
    args = parser.parse_args()

    if args.show_gaps:
        show_known_gaps(symbol_filter=args.symbol)
    elif args.accept_gaps:
        accept_current_gaps(symbol_filter=args.symbol, verbose=not args.quiet)
    elif args.clear_gaps:
        clear_known_gaps(symbol_filter=args.symbol)
    else:
        run_health_check(
            symbol_filter=args.symbol,
            fix=args.fix,
            verbose=not args.quiet,
            reset=args.reset,
            until_done=args.until_done,
            max_iterations=args.max_iterations,
            batch_size=args.batch_size
        )


if __name__ == '__main__':
    main()
