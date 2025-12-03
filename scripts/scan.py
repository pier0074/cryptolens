#!/usr/bin/env python
"""
Pattern Scan Script
Fetches latest candles, aggregates, detects patterns, and sends notifications.
Run via cron: */5 * * * * (every 5 minutes)

This replaces APScheduler for better CPU efficiency.
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


def fetch_latest_candles(verbose=False):
    """Fetch latest 1m candles for all active symbols."""
    from app import create_app, db
    from app.models import Symbol
    from app.services.data_fetcher import fetch_candles

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        total_fetched = 0
        symbols_updated = []

        for symbol in symbols:
            try:
                new_count, _ = fetch_candles(symbol.symbol, '1m', limit=5)
                total_fetched += new_count
                if new_count > 0:
                    symbols_updated.append(symbol.symbol)
                    if verbose:
                        print(f"  {symbol.symbol}: {new_count} new candles")
            except Exception as e:
                if verbose:
                    print(f"  {symbol.symbol}: ERROR - {e}")

        return total_fetched, symbols_updated


def aggregate_timeframes(symbols_updated, verbose=False):
    """Aggregate 1m candles to higher timeframes."""
    from app import create_app
    from app.services.aggregator import aggregate_candles

    if not symbols_updated:
        return 0

    timeframes_to_aggregate = get_timeframes_to_check()
    target_timeframes = [tf for tf in timeframes_to_aggregate if tf != '1m']

    if not target_timeframes:
        return 0

    total_aggregated = 0
    app = create_app()
    with app.app_context():
        for symbol in symbols_updated:
            for tf in target_timeframes:
                try:
                    count = aggregate_candles(symbol, '1m', tf)
                    total_aggregated += count
                    if verbose and count > 0:
                        print(f"  {symbol} → {tf}: {count} candles")
                except Exception as e:
                    if verbose:
                        print(f"  {symbol} → {tf}: ERROR - {e}")

    return total_aggregated


def scan_patterns(verbose=False):
    """Scan for new patterns on relevant timeframes."""
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import get_all_detectors

    timeframes_to_scan = get_timeframes_to_check()
    total_patterns = 0

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
                            total_patterns += len(patterns)
                            if verbose:
                                print(f"  {symbol.symbol} {tf}: {len(patterns)} {detector.pattern_type} patterns")
                    except Exception:
                        pass  # Silent fail for individual patterns

    return total_patterns


def update_pattern_status(verbose=False):
    """Update status of existing patterns (check if filled)."""
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import get_all_detectors
    from app.services.data_fetcher import get_latest_candles

    timeframes_to_check = get_timeframes_to_check()
    updated_count = 0

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()

        for symbol in symbols:
            try:
                candles = get_latest_candles(symbol.symbol, '1m', limit=1)
                if candles:
                    current_price = candles[-1]['close']
                    for tf in timeframes_to_check:
                        for detector in detectors:
                            if hasattr(detector, 'update_pattern_status'):
                                updated = detector.update_pattern_status(symbol.symbol, tf, current_price)
                                updated_count += updated
            except Exception:
                pass

    return updated_count


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
                print(f"  Signal generation error: {e}")
            return {'signals_generated': 0}


def main():
    parser = argparse.ArgumentParser(description='Run CryptoLens pattern scan')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--fetch-only', action='store_true', help='Only fetch candles, skip pattern scan')
    parser.add_argument('--scan-only', action='store_true', help='Only scan patterns, skip fetch')
    args = parser.parse_args()

    start_time = time.time()

    if args.verbose:
        print("=" * 50)
        print(f"  CryptoLens Scan - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 50)
        print(f"  Timeframes: {', '.join(get_timeframes_to_check())}")

    # Step 1: Fetch latest candles
    if not args.scan_only:
        if args.verbose:
            print("\n[1/5] Fetching latest candles...")
        fetched, symbols_updated = fetch_latest_candles(args.verbose)
        if args.verbose:
            print(f"      → {fetched} new candles from {len(symbols_updated)} symbols")
    else:
        symbols_updated = []

    if args.fetch_only:
        return

    # Step 2: Aggregate to higher timeframes
    if not args.scan_only and symbols_updated:
        if args.verbose:
            print("\n[2/5] Aggregating timeframes...")
        aggregated = aggregate_timeframes(symbols_updated, args.verbose)
        if args.verbose:
            print(f"      → {aggregated} candles aggregated")

    # Step 3: Scan for patterns
    if args.verbose:
        print("\n[3/5] Scanning for patterns...")
    patterns_found = scan_patterns(args.verbose)
    if args.verbose:
        print(f"      → {patterns_found} new patterns detected")

    # Step 4: Update pattern status
    if args.verbose:
        print("\n[4/5] Updating pattern status...")
    updated = update_pattern_status(args.verbose)
    if args.verbose:
        print(f"      → {updated} patterns updated")

    # Step 5: Generate signals
    if args.verbose:
        print("\n[5/5] Generating signals...")
    signal_result = generate_signals(args.verbose)

    elapsed = time.time() - start_time

    if args.verbose:
        print("\n" + "=" * 50)
        print(f"  Completed in {elapsed:.1f}s")
        print("=" * 50)
    else:
        # Minimal output for cron logs
        if patterns_found > 0 or signal_result.get('signals_generated', 0) > 0:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M')}] "
                  f"patterns={patterns_found} signals={signal_result.get('signals_generated', 0)} "
                  f"time={elapsed:.1f}s")


if __name__ == '__main__':
    main()
