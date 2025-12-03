#!/usr/bin/env python
"""
Pattern Detection Script
Aggregates candles, detects patterns, updates status, generates signals.
Run via cron: */5 * * * * (every 5 minutes)

This script assumes data has been fetched by fetch.py.
Separation allows fetch.py to run more frequently (every minute).
"""
import sys
import os
import time
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone


def get_timeframes_to_check():
    """Determine which timeframes need checking based on current time."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    hour = now.hour

    timeframes = ['1m']  # Always check 1m

    if minute % 5 == 0:
        timeframes.append('5m')
    if minute % 15 == 0:
        timeframes.append('15m')
    if minute % 30 == 0:
        timeframes.append('30m')
    if minute == 0:
        timeframes.append('1h')
        if hour % 2 == 0:
            timeframes.append('2h')
        if hour % 4 == 0:
            timeframes.append('4h')
    if hour == 0 and minute == 0:
        timeframes.append('1d')

    return timeframes


def aggregate_timeframes(verbose=False):
    """Aggregate 1m candles to higher timeframes."""
    from app import create_app
    from app.models import Symbol
    from app.services.aggregator import aggregate_candles

    timeframes_to_check = get_timeframes_to_check()
    target_timeframes = [tf for tf in timeframes_to_check if tf != '1m']

    if not target_timeframes:
        return 0

    total = 0
    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        for symbol in symbols:
            for tf in target_timeframes:
                try:
                    count = aggregate_candles(symbol.symbol, '1m', tf)
                    total += count
                    if verbose and count > 0:
                        print(f"  {symbol.symbol} -> {tf}: {count} candles")
                except Exception as e:
                    if verbose:
                        print(f"  {symbol.symbol} -> {tf}: ERROR - {e}")

    return total


def scan_patterns(verbose=False):
    """Scan for new patterns on relevant timeframes."""
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import get_all_detectors

    timeframes_to_scan = get_timeframes_to_check()
    total = 0

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()

        for symbol in symbols:
            for tf in timeframes_to_scan:
                for detector in detectors:
                    try:
                        patterns = detector.detect(symbol.symbol, tf)
                        if patterns:
                            total += len(patterns)
                            if verbose:
                                print(f"  {symbol.symbol} {tf}: {len(patterns)} {detector.pattern_type}")
                    except Exception:
                        pass

    return total


def update_pattern_status(verbose=False):
    """Update status of existing patterns (check if filled)."""
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import get_all_detectors
    from app.services.data_fetcher import get_latest_candles

    timeframes = get_timeframes_to_check()
    updated = 0

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()

        for symbol in symbols:
            try:
                candles = get_latest_candles(symbol.symbol, '1m', limit=1)
                if candles:
                    price = candles[-1]['close']
                    for tf in timeframes:
                        for detector in detectors:
                            if hasattr(detector, 'update_pattern_status'):
                                updated += detector.update_pattern_status(
                                    symbol.symbol, tf, price
                                )
            except Exception:
                pass

    return updated


def generate_signals(verbose=False):
    """Generate signals for high-confluence patterns."""
    from app import create_app
    from app.services.signals import scan_and_generate_signals

    app = create_app()
    with app.app_context():
        try:
            result = scan_and_generate_signals()
            if verbose and result['signals_generated'] > 0:
                print(f"  Generated {result['signals_generated']} signals")
            return result
        except Exception as e:
            if verbose:
                print(f"  Signal error: {e}")
            return {'signals_generated': 0}


def main():
    parser = argparse.ArgumentParser(description='Pattern detection script')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--aggregate-only', action='store_true', help='Only aggregate')
    parser.add_argument('--detect-only', action='store_true', help='Only detect patterns')
    args = parser.parse_args()

    start_time = time.time()
    timeframes = get_timeframes_to_check()

    if args.verbose:
        print("=" * 50)
        print(f"  Pattern Detection - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 50)
        print(f"  Timeframes: {', '.join(timeframes)}")

    # Step 1: Aggregate
    if not args.detect_only:
        if args.verbose:
            print("\n[1/4] Aggregating timeframes...")
        agg_count = aggregate_timeframes(args.verbose)
        if args.verbose:
            print(f"      -> {agg_count} candles aggregated")

    if args.aggregate_only:
        return

    # Step 2: Detect patterns
    if args.verbose:
        print("\n[2/4] Scanning for patterns...")
    patterns_found = scan_patterns(args.verbose)
    if args.verbose:
        print(f"      -> {patterns_found} new patterns")

    # Step 3: Update pattern status
    if args.verbose:
        print("\n[3/4] Updating pattern status...")
    updated = update_pattern_status(args.verbose)
    if args.verbose:
        print(f"      -> {updated} patterns updated")

    # Step 4: Generate signals
    if args.verbose:
        print("\n[4/4] Generating signals...")
    signal_result = generate_signals(args.verbose)

    elapsed = time.time() - start_time

    if args.verbose:
        print("\n" + "=" * 50)
        print(f"  Completed in {elapsed:.1f}s")
        print("=" * 50)
    else:
        # Minimal output for cron logs
        signals = signal_result.get('signals_generated', 0)
        if patterns_found > 0 or signals > 0:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M')}] "
                  f"patterns={patterns_found} signals={signals} time={elapsed:.1f}s")


if __name__ == '__main__':
    main()
