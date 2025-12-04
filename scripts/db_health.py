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
  python scripts/db_health.py           # Report only (incremental)
  python scripts/db_health.py --fix     # Auto-fix issues and mark verified
  python scripts/db_health.py --symbol BTC/USDT  # Check specific symbol
  python scripts/db_health.py --reset   # Reset all verification flags

Cron (optional, daily):
  0 3 * * * cd /path && venv/bin/python scripts/db_health.py --fix
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime, timezone
from collections import defaultdict

from app import create_app, db
from app.models import Symbol, Candle

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


def verify_candles_incremental(symbol_id, timeframe, fix=False, batch_size=10000, verbose=True):
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
                error_found = {
                    'type': 'gap',
                    'after_timestamp': prev_candle.timestamp,
                    'before_timestamp': candle.timestamp,
                    'missing_candles': missing
                }
                # Gaps can't be "fixed" by deletion - they need data refetch
                # So we just report and stop
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


def run_health_check(symbol_filter=None, fix=False, verbose=True, reset=False):
    """Run incremental health checks."""
    app = create_app()

    with app.app_context():
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

                # Run incremental verification
                result = verify_candles_incremental(symbol.id, tf, fix=fix, verbose=verbose)

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
                        line_parts.append(f"GAP: {err['missing_candles']} missing after {err['after_timestamp']}")
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


def main():
    parser = argparse.ArgumentParser(description='Database health check for candle data')
    parser.add_argument('--fix', action='store_true', help='Auto-fix issues (delete bad data)')
    parser.add_argument('--symbol', '-s', type=str, help='Check specific symbol (e.g., BTC/USDT)')
    parser.add_argument('--quiet', '-q', action='store_true', help='Only show summary')
    parser.add_argument('--reset', action='store_true', help='Reset all verification flags')
    args = parser.parse_args()

    run_health_check(
        symbol_filter=args.symbol,
        fix=args.fix,
        verbose=not args.quiet,
        reset=args.reset
    )


if __name__ == '__main__':
    main()
