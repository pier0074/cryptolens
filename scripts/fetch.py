#!/usr/bin/env python
"""
Real-time Candle Fetcher with Immediate Pattern Detection

Event-driven architecture:
1. Fetch all symbols in parallel (async)
2. As each symbol completes → immediately aggregate → detect patterns → notify
3. First symbol to complete gets scanned first (no waiting for others)

Run via cron: * * * * * (every minute)
"""
import sys
import os
import asyncio
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt_async
from datetime import datetime, timezone


def get_timeframes_to_aggregate():
    """Determine which timeframes need aggregation based on current time."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    hour = now.hour

    timeframes = []  # 1m doesn't need aggregation

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


def process_symbol(symbol_name, ohlcv, app, verbose=False):
    """
    Process a single symbol after fetch:
    1. Save candles to DB
    2. Aggregate to higher timeframes
    3. Detect patterns
    4. Generate signals if needed

    This runs synchronously per symbol for SQLite safety.
    """
    from app.models import Symbol, Candle
    from app.services.aggregator import aggregate_candles
    from app.services.patterns import get_all_detectors
    from app import db

    with app.app_context():
        # Get symbol
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            return {'symbol': symbol_name, 'new': 0, 'patterns': 0}

        # 1. Save new candles
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
            db.session.commit()

        # 2. Aggregate to higher timeframes
        timeframes_to_agg = get_timeframes_to_aggregate()
        for tf in timeframes_to_agg:
            try:
                aggregate_candles(symbol_name, '1m', tf)
            except Exception:
                pass

        # 3. Detect patterns (only if we have new data)
        patterns_found = 0
        if new_count > 0:
            detectors = get_all_detectors()
            timeframes_to_scan = ['1m'] + timeframes_to_agg

            for tf in timeframes_to_scan:
                for detector in detectors:
                    try:
                        patterns = detector.detect(symbol_name, tf)
                        if patterns:
                            patterns_found += len(patterns)
                    except Exception:
                        pass

        # 4. Update pattern status with current price
        if ohlcv:
            current_price = ohlcv[-1][4]  # close price
            for detector in get_all_detectors():
                if hasattr(detector, 'update_pattern_status'):
                    for tf in ['1m'] + timeframes_to_agg:
                        try:
                            detector.update_pattern_status(symbol_name, tf, current_price)
                        except Exception:
                            pass

        if verbose and (new_count > 0 or patterns_found > 0):
            print(f"  {symbol_name}: {new_count} candles, {patterns_found} patterns")

        return {
            'symbol': symbol_name,
            'new': new_count,
            'patterns': patterns_found
        }


async def fetch_and_process(exchange, symbol, app, verbose=False):
    """Fetch a symbol and immediately process it."""
    try:
        # Fetch latest candles
        ohlcv = await exchange.fetch_ohlcv(symbol, '1m', limit=5)

        if ohlcv:
            # Process immediately (sync, but per-symbol)
            result = process_symbol(symbol, ohlcv, app, verbose)
            return result
        return {'symbol': symbol, 'new': 0, 'patterns': 0}

    except Exception as e:
        if verbose:
            print(f"  {symbol}: ERROR - {e}")
        return {'symbol': symbol, 'new': 0, 'patterns': 0, 'error': str(e)}


async def run_fetch_cycle(symbols, app, verbose=False):
    """Run a complete fetch cycle with parallel fetching."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        # Create tasks for all symbols
        tasks = [fetch_and_process(exchange, s, app, verbose) for s in symbols]

        # Process as each completes (not waiting for all)
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)

        return results
    finally:
        await exchange.close()


def generate_signals_batch(app, verbose=False):
    """Generate signals for all symbols (runs once after all fetches)."""
    from app.services.signals import scan_and_generate_signals

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
    import argparse
    parser = argparse.ArgumentParser(description='Real-time candle fetcher with pattern detection')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    start_time = time.time()

    # Get active symbols
    from app import create_app
    from app.models import Symbol

    app = create_app()
    with app.app_context():
        symbols = [s.symbol for s in Symbol.query.filter_by(is_active=True).all()]

    if not symbols:
        print("No active symbols found")
        return

    if args.verbose:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Fetching {len(symbols)} symbols...")
        print(f"  Timeframes to aggregate: {get_timeframes_to_aggregate() or ['none (not on boundary)']}")

    # Run async fetch cycle
    results = asyncio.run(run_fetch_cycle(symbols, app, args.verbose))

    # Generate signals (batch, once per cycle)
    signal_result = generate_signals_batch(app, args.verbose)

    elapsed = time.time() - start_time

    # Summary
    total_new = sum(r.get('new', 0) for r in results)
    total_patterns = sum(r.get('patterns', 0) for r in results)
    total_signals = signal_result.get('signals_generated', 0)

    if args.verbose or total_new > 0 or total_patterns > 0 or total_signals > 0:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
              f"new={total_new} patterns={total_patterns} signals={total_signals} "
              f"time={elapsed:.1f}s")


if __name__ == '__main__':
    main()
