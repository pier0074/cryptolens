#!/usr/bin/env python
"""
Database Health Check for Candle Data (Incremental Verification)

Checks candles sequentially from first unverified, marks them verified on success.
When an error is found, stops - all subsequent candles remain unverified.

Checks:
1. Gap detection - missing candles in sequence
2. Timestamp alignment - higher TFs at correct boundaries
3. OHLCV sanity - high >= low, high >= open/close, etc.
4. Continuity - open should equal previous candle's close

Usage:
  python scripts/db_health.py              # Report only (incremental)
  python scripts/db_health.py --fix        # Auto-fix: delete bad candles, fetch missing, re-aggregate
  python scripts/db_health.py --symbol BTC/USDT  # Check specific symbol
  python scripts/db_health.py --reset      # Reset all verification flags
  python scripts/db_health.py --accept-gaps  # Mark current gaps as OK (exchange had no data)
  python scripts/db_health.py --show-gaps  # Show all known gaps

Gap Handling:
  --fix will attempt to fetch missing 1m candles from the exchange.
  If the exchange returns no data, the gap is marked as "known" (legitimate).
  Higher timeframes are re-aggregated after filling gaps.

Cron (optional, daily):
  0 3 * * * cd /path && venv/bin/python scripts/db_health.py --fix
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


def check_continuity(prev_candle, curr_candle, threshold=0.001):
    """Check if current open equals previous close. Returns diff % if exceeded."""
    if prev_candle.close > 0:
        diff_pct = abs(curr_candle.open - prev_candle.close) / prev_candle.close
        if diff_pct > threshold:
            return diff_pct
    return None


def is_known_gap(symbol_id, timeframe, gap_start, gap_end):
    """Check if a gap is already known/accepted."""
    return KnownGap.query.filter(
        KnownGap.symbol_id == symbol_id,
        KnownGap.timeframe == timeframe,
        KnownGap.gap_start <= gap_start,
        KnownGap.gap_end >= gap_end
    ).first() is not None


async def fetch_missing_candles(symbol_name, gap_start_ms, gap_end_ms, verbose=False):
    """
    Fetch missing 1m candles from exchange for a gap.

    Returns:
        list: OHLCV data if found, empty list if exchange has no data
    """
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

            # Filter to only include candles within our gap range
            for candle in batch:
                if gap_start_ms <= candle[0] <= gap_end_ms:
                    all_ohlcv.append(candle)

            # Move to next batch
            if batch:
                since = batch[-1][0] + 60000
            else:
                break

            # Small delay between batches
            if len(batch) == 1000:
                await asyncio.sleep(0.2)

        return all_ohlcv

    finally:
        await exchange.close()


def save_fetched_candles(symbol_id, ohlcv, verbose=False):
    """
    Save fetched candles to database.

    Returns:
        int: Number of new candles saved
    """
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
        # Update existing
        existing.gap_end = gap_end
        existing.missing_candles = missing_candles
        existing.reason = reason
        existing.verified_empty = verified_empty
    else:
        # Create new
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


def reaggregate_timeframes(symbol_name, verbose=False):
    """Re-aggregate all higher timeframes for a symbol."""
    from app.services.aggregator import aggregate_candles

    timeframes = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
    for tf in timeframes:
        try:
            aggregate_candles(symbol_name, '1m', tf)
            if verbose:
                print(f"    Re-aggregated {tf}")
        except Exception as e:
            if verbose:
                print(f"    Failed to aggregate {tf}: {e}")


async def fix_gap(symbol, gap_start, gap_end, missing_candles, verbose=False):
    """
    Attempt to fix a gap by fetching from exchange.

    Returns:
        dict with 'action' ('filled', 'marked_empty', 'error') and details
    """
    if verbose:
        print(f"    Attempting to fetch {missing_candles} missing candles...")

    try:
        # Fetch missing data
        ohlcv = await fetch_missing_candles(symbol.symbol, gap_start, gap_end, verbose)

        if ohlcv:
            # Save fetched candles
            saved = save_fetched_candles(symbol.id, ohlcv, verbose)

            if saved > 0:
                # Re-aggregate higher timeframes
                if verbose:
                    print(f"    Re-aggregating higher timeframes...")
                reaggregate_timeframes(symbol.symbol, verbose)

                return {
                    'action': 'filled',
                    'candles_fetched': len(ohlcv),
                    'candles_saved': saved
                }
            else:
                # All fetched candles already existed
                return {
                    'action': 'already_exists',
                    'candles_fetched': len(ohlcv)
                }
        else:
            # Exchange has no data - mark as known gap
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


def verify_candles_incremental(symbol_id, timeframe, fix=False, batch_size=10000, verbose=True, symbol=None):
    """
    Verify candles incrementally for a symbol/timeframe.

    Returns dict with:
        - verified: number of newly verified candles
        - error: dict describing first error found (or None)
        - stopped_at: timestamp where verification stopped (or None)
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = TF_MS.get(timeframe, 60000)

    # Get the last verified candle timestamp to find where to start
    last_verified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == timeframe,
        Candle.verified_at.isnot(None)
    ).order_by(Candle.timestamp.desc()).first()

    # Start from after last verified, or from the beginning
    start_ts = last_verified.timestamp if last_verified else 0

    # Get unverified candles in order
    unverified = Candle.query.filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == timeframe,
        Candle.timestamp > start_ts,
        Candle.verified_at.is_(None)
    ).order_by(Candle.timestamp).limit(batch_size).all()

    if not unverified:
        return {'verified': 0, 'error': None, 'stopped_at': None}

    # Need previous candle for gap/continuity checks
    prev_candle = last_verified
    if not prev_candle and start_ts == 0:
        # First candle - can't check gap/continuity, but can check OHLCV/alignment
        pass

    verified_count = 0
    error_found = None
    candles_to_verify = []

    for i, candle in enumerate(unverified):
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

        # 2. Check alignment (for non-1m timeframes)
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

        # 3. Check gap (if we have a previous candle)
        if prev_candle:
            missing = check_gap(prev_candle, candle, interval_ms)
            if missing > 0:
                gap_start = prev_candle.timestamp + interval_ms
                gap_end = candle.timestamp - interval_ms

                # Check if this is a known gap
                if is_known_gap(symbol_id, timeframe, gap_start, gap_end):
                    # Known gap - skip and continue verification
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

                # For 1m gaps with fix=True, try to fetch from exchange
                if fix and timeframe == '1m' and symbol:
                    fix_result = asyncio.run(fix_gap(symbol, gap_start, gap_end, missing, verbose))
                    error_found['fix_result'] = fix_result

                    if fix_result['action'] == 'filled':
                        # Gap was filled - continue verification from this point
                        # (need to re-run to pick up new candles)
                        error_found['action'] = 'filled'
                    elif fix_result['action'] == 'marked_empty':
                        # Gap is legitimate - skip and continue
                        candles_to_verify.append(candle)
                        prev_candle = candle
                        error_found = None  # Clear error since we handled it
                        continue
                    elif fix_result['action'] == 'already_exists':
                        # Candles exist but weren't found in our query - re-run needed
                        error_found['action'] = 'needs_rerun'

                break

        # 4. Check continuity (if we have a previous consecutive candle)
        if prev_candle and candle.timestamp - prev_candle.timestamp == interval_ms:
            diff_pct = check_continuity(prev_candle, candle)
            if diff_pct is not None:
                # Continuity errors are informational (crypto can gap)
                # We don't stop for these, just note them
                pass  # Could log if verbose

        # Candle passed all checks - mark for verification
        candles_to_verify.append(candle)
        prev_candle = candle

    # Mark verified candles
    if candles_to_verify:
        for candle in candles_to_verify:
            candle.verified_at = now_ms
        db.session.commit()
        verified_count = len(candles_to_verify)

    return {
        'verified': verified_count,
        'error': error_found,
        'stopped_at': error_found['timestamp'] if error_found and 'timestamp' in error_found else None,
        'remaining': len(unverified) - verified_count - (1 if error_found else 0)
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


def run_health_check(symbol_filter=None, fix=False, verbose=True, reset=False, app=None):
    """
    Run incremental health checks.

    Args:
        symbol_filter: Check only this symbol (e.g., 'BTC/USDT')
        fix: Auto-fix issues (delete bad candles)
        verbose: Print detailed output
        reset: Reset all verification flags
        app: Optional Flask app instance. If None, creates a new app.
             Pass existing app when calling from within app context.
    """
    # Create app only if not provided (avoids nested contexts)
    if app is None:
        app = create_app()
        context_manager = app.app_context()
    else:
        # Use a null context manager when app is provided
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

        # Handle reset flag
        if reset:
            print("Resetting all verification flags...")
            total_reset = reset_verification()
            print(f"Reset {total_reset} candles.")
            return

        print(f"\n{'='*60}")
        print(f"  DATABASE HEALTH CHECK - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  Mode: {'FIX' if fix else 'REPORT ONLY'} (Incremental)")
        print(f"{'='*60}\n")

        total_verified = 0
        total_errors = defaultdict(int)
        symbols_with_errors = []

        for symbol in symbols:
            symbol_output = []
            symbol_has_error = False

            for tf in ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']:
                stats = get_verification_stats(symbol.id, tf)

                if stats['total'] == 0:
                    continue

                # Run incremental verification (pass symbol for gap fixing)
                result = verify_candles_incremental(symbol.id, tf, fix=fix, verbose=verbose, symbol=symbol)

                total_verified += result['verified']

                # Build output line
                line_parts = []

                if result['verified'] > 0:
                    line_parts.append(f"verified: {result['verified']}")

                if result['error']:
                    symbol_has_error = True
                    err = result['error']
                    err_type = err['type']
                    total_errors[err_type] += 1

                    if err_type == 'gap':
                        gap_msg = f"GAP: {err['missing_candles']} missing after {err['after_timestamp']}"
                        if 'action' in err:
                            gap_msg += f" ({err['action']})"
                        elif 'fix_result' in err:
                            gap_msg += f" ({err['fix_result'].get('action', 'unknown')})"
                        line_parts.append(gap_msg)
                    elif err_type == 'ohlcv_invalid':
                        action = f" ({err.get('action', 'found')})" if fix else ""
                        line_parts.append(f"OHLCV: {', '.join(err['problems'])}{action}")
                    elif err_type == 'misaligned':
                        action = f" ({err.get('action', 'found')})" if fix else ""
                        line_parts.append(f"MISALIGNED: ts={err['timestamp']}{action}")

                # Show remaining unverified
                new_stats = get_verification_stats(symbol.id, tf)
                if new_stats['unverified'] > 0:
                    line_parts.append(f"remaining: {new_stats['unverified']}")

                if line_parts:
                    symbol_output.append(f"  {tf}: {', '.join(line_parts)}")

            if symbol_output and verbose:
                print(f"{symbol.symbol}:")
                for line in symbol_output:
                    print(line)
                print()

            if symbol_has_error:
                symbols_with_errors.append(symbol.symbol)

        # Summary
        print(f"{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}")

        if total_verified > 0:
            print(f"  Newly verified: {total_verified} candles")

        if total_errors:
            print(f"  Errors found:")
            for err_type, count in total_errors.items():
                print(f"    - {err_type}: {count}")
            print(f"  Symbols with errors: {', '.join(symbols_with_errors)}")
        elif total_verified == 0:
            # Check if everything is already verified
            total_unverified = 0
            for symbol in symbols:
                for tf in ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']:
                    stats = get_verification_stats(symbol.id, tf)
                    total_unverified += stats['unverified']

            if total_unverified == 0:
                print("  All candles verified - no issues found!")
            else:
                print(f"  {total_unverified} candles still unverified (run with --fix to continue)")
        else:
            print("  No errors found in this batch!")

        print()
        return {'verified': total_verified, 'errors': dict(total_errors)}


def accept_current_gaps(symbol_filter=None, verbose=True):
    """
    Mark all currently detected gaps as accepted/known.
    Use this when you've verified the exchange has no data for those periods.
    """
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
            for tf in ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d']:
                interval_ms = TF_MS.get(tf, 60000)

                # Get all candles in order
                candles = Candle.query.filter_by(
                    symbol_id=symbol.id,
                    timeframe=tf
                ).order_by(Candle.timestamp).all()

                if len(candles) < 2:
                    continue

                # Find gaps
                for i in range(1, len(candles)):
                    prev = candles[i - 1]
                    curr = candles[i]
                    missing = check_gap(prev, curr, interval_ms)

                    if missing > 0:
                        gap_start = prev.timestamp + interval_ms
                        gap_end = curr.timestamp - interval_ms

                        # Check if already known
                        if not is_known_gap(symbol.id, tf, gap_start, gap_end):
                            record_known_gap(
                                symbol.id, tf, gap_start, gap_end, missing,
                                reason='accepted', verified_empty=False
                            )
                            total_gaps += 1
                            if verbose:
                                print(f"  {symbol.symbol} {tf}: Accepted gap of {missing} candles "
                                      f"({datetime.fromtimestamp(gap_start/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})")

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
    parser = argparse.ArgumentParser(description='Database health check for candle data')
    parser.add_argument('--fix', action='store_true',
                        help='Auto-fix: delete bad candles, fetch missing 1m data, re-aggregate')
    parser.add_argument('--symbol', '-s', type=str, help='Check specific symbol (e.g., BTC/USDT)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Only show summary')
    parser.add_argument('--reset', action='store_true', help='Reset all verification flags')
    parser.add_argument('--accept-gaps', action='store_true',
                        help='Mark current gaps as accepted (exchange has no data)')
    parser.add_argument('--show-gaps', action='store_true', help='Show all known/accepted gaps')
    parser.add_argument('--clear-gaps', action='store_true', help='Clear all known gaps')
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
            reset=args.reset
        )


if __name__ == '__main__':
    main()
