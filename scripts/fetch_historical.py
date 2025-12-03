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
                           verbose: bool = False) -> List:
    """Fetch candles for a time range using async."""
    all_candles = []
    current_ts = start_ts
    batch_size = 1000

    while current_ts < end_ts:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, '1m', since=current_ts, limit=batch_size)
            if not ohlcv:
                break

            all_candles.extend(ohlcv)

            # Move to next batch
            last_ts = ohlcv[-1][0]
            if last_ts <= current_ts:
                break
            current_ts = last_ts + 60000

            if verbose and len(all_candles) % 10000 == 0:
                print(f"    Fetched {len(all_candles):,} candles...", end='\r')

        except Exception as e:
            if verbose:
                print(f"    Error at {current_ts}: {e}")
            await asyncio.sleep(1)
            current_ts += batch_size * 60000

    return all_candles


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
                               days: int, verbose: bool = False) -> dict:
    """Find and fill gaps for a single symbol."""
    from app import create_app

    now = datetime.now(timezone.utc)
    start_ts = int((now - timedelta(days=days)).timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000) - (5 * 60 * 1000)  # 5 min buffer

    app = create_app()
    with app.app_context():
        gaps = find_gaps(symbol_id, start_ts, end_ts)

    if not gaps:
        return {'symbol': symbol_name, 'gaps': 0, 'filled': 0}

    total_filled = 0
    for gap_start, gap_end in gaps:
        if verbose:
            gap_duration = (gap_end - gap_start) / (60 * 1000)
            print(f"    Gap: {gap_duration:.0f} minutes")

        candles = await fetch_range_async(exchange, symbol_name, gap_start, gap_end, verbose)

        if candles:
            with app.app_context():
                filled = save_candles_batch(symbol_id, candles, verbose)
                total_filled += filled

    return {'symbol': symbol_name, 'gaps': len(gaps), 'filled': total_filled}


async def fetch_symbol_full(exchange, symbol_name: str, symbol_id: int,
                           days: int, verbose: bool = False) -> dict:
    """Fetch full history for a symbol."""
    from app import create_app

    now = datetime.now(timezone.utc)
    start_ts = int((now - timedelta(days=days)).timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)

    if verbose:
        print(f"\n  {symbol_name}:")
        print(f"    Range: {days} days ({(end_ts - start_ts) // (60*60*1000*24)} days)")

    candles = await fetch_range_async(exchange, symbol_name, start_ts, end_ts, verbose)

    if verbose:
        print(f"    Fetched {len(candles):,} candles")

    app = create_app()
    with app.app_context():
        new_count = save_candles_batch(symbol_id, candles, verbose)

    if verbose:
        print(f"    Saved {new_count:,} new candles")

    return {'symbol': symbol_name, 'fetched': len(candles), 'new': new_count}


async def run_gap_fill(symbols: List[Tuple[str, int]], days: int, verbose: bool = False):
    """Fill gaps for all symbols in parallel."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        tasks = [fill_gaps_for_symbol(exchange, name, sid, days, verbose)
                 for name, sid in symbols]
        results = await asyncio.gather(*tasks)
        return results
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
        for i, (name, sid) in enumerate(symbols):
            if verbose:
                print(f"\n[{i+1}/{len(symbols)}] {name}")

            result = await fetch_symbol_full(exchange, name, sid, days, verbose)
            results.append(result)

        return results
    finally:
        await exchange.close()


def aggregate_all_symbols(verbose: bool = False):
    """Aggregate 1m candles to all higher timeframes."""
    from app import create_app
    from app.models import Symbol
    from app.services.aggregator import aggregate_all_timeframes

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        if verbose:
            print("\nAggregating to higher timeframes...")

        for sym in symbols:
            if verbose:
                print(f"  {sym.symbol}...", end=' ')
            try:
                results = aggregate_all_timeframes(sym.symbol)
                if verbose:
                    totals = sum(results.values())
                    print(f"{totals:,} candles")
            except Exception as e:
                if verbose:
                    print(f"ERROR: {e}")


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
    parser.add_argument('--days', type=int, default=365, help='Days of history (default: 365)')
    parser.add_argument('--gaps', action='store_true', help='Only fill gaps (for hourly cron)')
    parser.add_argument('--status', action='store_true', help='Show database status')
    parser.add_argument('--delete', action='store_true', help='Delete all data')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--no-aggregate', action='store_true', help='Skip aggregation')
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.delete:
        if delete_all():
            # Continue with fetch after delete
            pass
        else:
            return

    # Get symbols
    from app import create_app
    from app.models import Symbol
    from app.config import Config

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("Initializing default symbols...")
            for name in Config.SYMBOLS:
                db.session.add(Symbol(symbol=name, exchange='binance'))
            db.session.commit()
            symbols = Symbol.query.filter_by(is_active=True).all()

        symbol_list = [(s.symbol, s.id) for s in symbols]

    start_time = time.time()

    print(f"\n{'═'*60}")
    print(f"  CryptoLens Historical Data Fetcher")
    print(f"{'═'*60}")
    print(f"  Mode: {'Gap fill' if args.gaps else 'Full fetch'}")
    print(f"  Symbols: {len(symbol_list)}")
    print(f"  Days: {args.days}")
    print(f"{'═'*60}")

    if args.gaps:
        # Gap fill mode (for hourly cron)
        results = asyncio.run(run_gap_fill(symbol_list, args.days, args.verbose))

        total_gaps = sum(r['gaps'] for r in results)
        total_filled = sum(r['filled'] for r in results)

        print(f"\n  Gaps found: {total_gaps}")
        print(f"  Candles filled: {total_filled:,}")
    else:
        # Full fetch mode
        results = asyncio.run(run_full_fetch(symbol_list, args.days, args.verbose))

        total_new = sum(r['new'] for r in results)
        print(f"\n  New candles: {total_new:,}")

    # Aggregate
    if not args.no_aggregate:
        aggregate_all_symbols(args.verbose)

    elapsed = time.time() - start_time
    print(f"\n  Time: {format_time(elapsed)}")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()
