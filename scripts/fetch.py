#!/usr/bin/env python
"""
Fast Candle Fetcher - Async Parallel Fetching
Fetches latest 1m candles for all symbols using async/await for speed.
Run via cron: */1 * * * * (every minute)

This script only fetches data - no pattern detection.
Use detect.py for pattern detection.
"""
import sys
import os
import asyncio
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt_async
from datetime import datetime, timezone


async def fetch_symbol(exchange, symbol, limit=5):
    """Fetch latest candles for a single symbol."""
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, '1m', limit=limit)
        return symbol, ohlcv, None
    except Exception as e:
        return symbol, None, str(e)


async def fetch_all_parallel(symbols, limit=5):
    """Fetch all symbols in parallel with rate limiting."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        # Create tasks for all symbols
        tasks = [fetch_symbol(exchange, s, limit) for s in symbols]

        # Run all in parallel (ccxt handles rate limiting internally)
        results = await asyncio.gather(*tasks)

        return results
    finally:
        await exchange.close()


def save_candles(results, verbose=False):
    """Save fetched candles to database (sequential for SQLite safety)."""
    from app import create_app, db
    from app.models import Symbol, Candle

    app = create_app()
    with app.app_context():
        total_new = 0
        symbols_updated = []

        for symbol_name, ohlcv, error in results:
            if error:
                if verbose:
                    print(f"  {symbol_name}: ERROR - {error}")
                continue

            if not ohlcv:
                continue

            # Get symbol ID
            sym = Symbol.query.filter_by(symbol=symbol_name).first()
            if not sym:
                continue

            # Get existing timestamps for this batch
            timestamps = [c[0] for c in ohlcv]
            existing = set(
                c.timestamp for c in Candle.query.filter(
                    Candle.symbol_id == sym.id,
                    Candle.timeframe == '1m',
                    Candle.timestamp.in_(timestamps)
                ).all()
            )

            # Save new candles
            new_count = 0
            for candle in ohlcv:
                ts, o, h, l, c, v = candle
                if ts in existing:
                    continue

                db.session.add(Candle(
                    symbol_id=sym.id,
                    timeframe='1m',
                    timestamp=ts,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v or 0
                ))
                new_count += 1

            if new_count > 0:
                total_new += new_count
                symbols_updated.append(symbol_name)
                if verbose:
                    print(f"  {symbol_name}: {new_count} new candles")

        if total_new > 0:
            db.session.commit()

        return total_new, symbols_updated


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fast parallel candle fetcher')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--limit', type=int, default=5, help='Candles per symbol (default: 5)')
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
        print(f"Fetching {len(symbols)} symbols (limit={args.limit})...")

    # Async fetch all symbols in parallel
    results = asyncio.run(fetch_all_parallel(symbols, args.limit))

    fetch_time = time.time() - start_time

    # Save to database (sequential)
    total_new, symbols_updated = save_candles(results, args.verbose)

    total_time = time.time() - start_time

    if args.verbose or total_new > 0:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
              f"fetched={len(symbols)} new={total_new} "
              f"fetch={fetch_time:.1f}s total={total_time:.1f}s")


if __name__ == '__main__':
    main()
