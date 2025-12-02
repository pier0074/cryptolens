#!/usr/bin/env python3
"""
Historical Data Fetcher Script
Downloads historical candle data for all symbols (sequential to avoid SQLite locks)
Progress is tracked via database - no external files needed.
"""
import sys
import os
import time
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol, Candle
from app.services.aggregator import aggregate_all_timeframes
from app.config import Config
from sqlalchemy import func


def format_time(seconds):
    """Format seconds into human readable time"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def progress_bar(current, total, width=30, prefix=''):
    """Generate a progress bar string"""
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = '█' * filled + '░' * (width - filled)
    return f"{prefix}[{bar}] {pct*100:5.1f}%"


def get_symbol_progress(symbol_id, target_start_ts):
    """
    Get fetch progress for a symbol from database

    Returns:
        dict with 'candle_count', 'oldest_ts', 'newest_ts', 'needs_fetch', 'resume_from_ts'
    """
    # Get candle stats for 1m timeframe
    stats = db.session.query(
        func.count(Candle.id),
        func.min(Candle.timestamp),
        func.max(Candle.timestamp)
    ).filter(
        Candle.symbol_id == symbol_id,
        Candle.timeframe == '1m'
    ).first()

    candle_count = stats[0] or 0
    oldest_ts = stats[1]
    newest_ts = stats[2]

    # Determine if we need to fetch and where to resume from
    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    if candle_count == 0:
        # No candles at all - start from target_start
        return {
            'candle_count': 0,
            'oldest_ts': None,
            'newest_ts': None,
            'needs_fetch': True,
            'resume_from_ts': target_start_ts,
            'status': 'new'
        }

    # Check if we have recent data (within last hour = considered up-to-date)
    one_hour_ago = now_ts - (60 * 60 * 1000)
    has_recent = newest_ts >= one_hour_ago

    # Check if we have old enough data
    has_full_history = oldest_ts <= target_start_ts + (60 * 60 * 1000)  # Within 1 hour of target

    if has_recent and has_full_history:
        return {
            'candle_count': candle_count,
            'oldest_ts': oldest_ts,
            'newest_ts': newest_ts,
            'needs_fetch': False,
            'resume_from_ts': None,
            'status': 'complete'
        }

    # Need to fetch - resume from newest timestamp
    return {
        'candle_count': candle_count,
        'oldest_ts': oldest_ts,
        'newest_ts': newest_ts,
        'needs_fetch': True,
        'resume_from_ts': newest_ts + 60000 if newest_ts else target_start_ts,  # +1 minute
        'status': 'partial'
    }


def fetch_symbol_with_logging(app, symbol_name, days, force_refetch=False):
    """
    Fetch historical data for a single symbol with detailed logging
    Uses Binance (1000 candles/batch) with batch DB checking for speed
    """
    import ccxt

    with app.app_context():
        # Use Binance for faster fetching (1000 candles vs 500)
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })

        # Get or create symbol
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            sym = Symbol(symbol=symbol_name, exchange='binance')
            db.session.add(sym)
            db.session.commit()

        # Calculate time range
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(days=days)
        target_start_ts = int(start_time.timestamp() * 1000)
        now_ts = int(now.timestamp() * 1000)

        # Check existing progress from DB
        progress = get_symbol_progress(sym.id, target_start_ts)

        if not progress['needs_fetch'] and not force_refetch:
            print(f"\n{'─'*50}")
            print(f"📊 {symbol_name}")
            print(f"   ✅ Already complete: {progress['candle_count']:,} candles in DB")
            return {
                'symbol': symbol_name,
                'success': True,
                'new_candles': 0,
                'existing_candles': progress['candle_count'],
                'aggregated': 0,
                'time': 0,
                'skipped': True
            }

        # Determine starting point
        since = progress['resume_from_ts']

        # Timeframe settings - Binance allows 1000 candles per request
        timeframe = '1m'
        candle_duration = 60 * 1000  # 1 minute in ms
        batch_size = 1000  # Binance limit

        # Calculate totals
        total_candles_needed = (now_ts - since) // candle_duration
        total_batches = max(1, (total_candles_needed // batch_size) + 1)

        print(f"\n{'─'*50}")
        print(f"📊 {symbol_name}")

        if progress['status'] == 'partial':
            existing_date = datetime.fromtimestamp(progress['newest_ts'] / 1000, tz=timezone.utc)
            print(f"   ⏩ Resuming from {existing_date.strftime('%Y-%m-%d %H:%M')} ({progress['candle_count']:,} candles in DB)")

        print(f"   Target: ~{total_candles_needed:,} candles ({total_batches} batches)")
        print(f"   Range: {datetime.fromtimestamp(since/1000, tz=timezone.utc).strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}")
        sys.stdout.flush()

        total_new = 0
        total_existing = 0
        current_since = since
        batch_num = 0
        batch_start = time.time()

        while current_since < now_ts:
            batch_num += 1

            try:
                # Fetch from exchange
                ohlcv = exchange.fetch_ohlcv(symbol_name, timeframe, since=current_since, limit=batch_size)

                if not ohlcv:
                    break

                # Batch check existing timestamps (much faster than individual queries)
                timestamps = [c[0] for c in ohlcv]
                existing_timestamps = set(
                    c.timestamp for c in Candle.query.filter(
                        Candle.symbol_id == sym.id,
                        Candle.timeframe == timeframe,
                        Candle.timestamp.in_(timestamps)
                    ).all()
                )

                # Save only new candles
                new_in_batch = 0
                for candle in ohlcv:
                    timestamp, open_price, high, low, close, volume = candle

                    if timestamp in existing_timestamps:
                        total_existing += 1
                        continue

                    # Validate OHLC data
                    if any(v is None or v <= 0 for v in [open_price, high, low, close]):
                        continue

                    new_candle = Candle(
                        symbol_id=sym.id,
                        timeframe=timeframe,
                        timestamp=timestamp,
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume or 0
                    )
                    db.session.add(new_candle)
                    new_in_batch += 1

                # Commit this batch
                db.session.commit()
                total_new += new_in_batch

                # Progress bar update (every batch for smooth animation)
                elapsed = time.time() - batch_start
                rate = batch_num / elapsed if elapsed > 0 else 0
                eta = (total_batches - batch_num) / rate if rate > 0 else 0
                current_date = datetime.fromtimestamp(current_since / 1000, tz=timezone.utc).strftime('%Y-%m-%d')

                # In-place progress bar
                bar = progress_bar(batch_num, total_batches)
                status = f"\r   {bar} | {current_date} | {total_new:,} candles | ETA: {format_time(eta)}    "
                print(status, end='', flush=True)

                # Move to next batch - use last timestamp to avoid gaps
                if ohlcv:
                    current_since = ohlcv[-1][0] + candle_duration
                else:
                    current_since += batch_size * candle_duration

                # Binance rate limit is generous, minimal delay needed
                time.sleep(0.1)

            except Exception as e:
                print(f"   ⚠️  Batch {batch_num} error: {e}")
                sys.stdout.flush()
                time.sleep(2)
                continue

        # Show 100% complete
        bar = progress_bar(total_batches, total_batches)
        print(f"\r   {bar} | Complete | {total_new:,} candles                    ")

        # Aggregate to higher timeframes
        print(f"   📊 Aggregating 1m candles → 5m, 15m, 1h, 4h, 1d...")
        sys.stdout.flush()
        agg_results = aggregate_all_timeframes(symbol_name)
        agg_count = sum(agg_results.values())
        print(f"   📊 Created: 5m={agg_results.get('5m', 0):,} | 15m={agg_results.get('15m', 0):,} | "
              f"1h={agg_results.get('1h', 0):,} | 4h={agg_results.get('4h', 0):,} | 1d={agg_results.get('1d', 0):,}")

        elapsed = time.time() - batch_start
        print(f"   ✅ Done! {total_new:,} new + {total_existing:,} existing | "
              f"Aggregated: {agg_count:,} | Time: {format_time(elapsed)}")
        sys.stdout.flush()

        return {
            'symbol': symbol_name,
            'success': True,
            'new_candles': total_new,
            'existing_candles': total_existing,
            'aggregated': agg_count,
            'time': elapsed,
            'skipped': False
        }


def show_db_status(app):
    """Show current database status for all symbols"""
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        print(f"\n{'═'*60}")
        print(f"  Database Status")
        print(f"{'═'*60}")

        total_candles = 0
        for sym in symbols:
            count = Candle.query.filter_by(symbol_id=sym.id, timeframe='1m').count()
            total_candles += count

            # Get date range
            oldest = db.session.query(func.min(Candle.timestamp)).filter(
                Candle.symbol_id == sym.id, Candle.timeframe == '1m'
            ).scalar()
            newest = db.session.query(func.max(Candle.timestamp)).filter(
                Candle.symbol_id == sym.id, Candle.timeframe == '1m'
            ).scalar()

            if oldest and newest:
                oldest_date = datetime.fromtimestamp(oldest / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                newest_date = datetime.fromtimestamp(newest / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                print(f"  {sym.symbol:12} | {count:>10,} candles | {oldest_date} → {newest_date}")
            else:
                print(f"  {sym.symbol:12} | {count:>10,} candles | No data")

        print(f"{'─'*60}")
        print(f"  Total: {total_candles:,} candles (1m timeframe)")
        print(f"{'═'*60}\n")


def main():
    """Fetch historical data for all symbols"""
    app = create_app()

    # Parse arguments
    days = 365  # Default 1 year
    force = '--force' in sys.argv

    for arg in sys.argv:
        if arg.startswith('--days='):
            days = int(arg.split('=')[1])

    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("No symbols found. Initializing default symbols...")
            for symbol_name in Config.SYMBOLS:
                symbol = Symbol(symbol=symbol_name, exchange='binance')
                db.session.add(symbol)
            db.session.commit()
            symbols = Symbol.query.filter_by(is_active=True).all()

        # Calculate target start timestamp
        now = datetime.now(timezone.utc)
        target_start_ts = int((now - timedelta(days=days)).timestamp() * 1000)

        # Check which symbols need fetching
        symbols_status = []
        for sym in symbols:
            progress = get_symbol_progress(sym.id, target_start_ts)
            symbols_status.append({
                'symbol': sym,
                'progress': progress,
                'needs_fetch': progress['needs_fetch'] or force
            })

        remaining = [s for s in symbols_status if s['needs_fetch']]
        complete = [s for s in symbols_status if not s['needs_fetch']]

        print(f"\n{'═'*60}")
        print(f"  CryptoLens Historical Data Fetcher")
        print(f"{'═'*60}")
        print(f"  📈 Total symbols: {len(symbols)}")
        print(f"  ✅ Already complete: {len(complete)}")
        print(f"  📥 Need fetching: {len(remaining)}")
        print(f"  📅 Days of history: {days} ({days/365:.1f} years)")
        print(f"  📊 Est. candles/symbol: ~{days * 24 * 60:,}")
        print(f"  ⏱️  Mode: Sequential (SQLite safe)")
        print(f"{'═'*60}")

        if not remaining:
            print("\n✅ All symbols already have complete data!")
            print("   Use --force to re-fetch anyway.")
            show_db_status(app)
            return

        start_time = time.time()
        completed_count = 0
        total_new_candles = 0
        total_agg_candles = 0
        skipped_count = 0

        # Process symbols sequentially
        for i, item in enumerate(remaining):
            symbol = item['symbol']
            completed_count += 1
            print(f"\n[{completed_count}/{len(remaining)}] Processing {symbol.symbol}...")

            try:
                result = fetch_symbol_with_logging(app, symbol.symbol, days, force_refetch=force)

                if result['success']:
                    if result.get('skipped'):
                        skipped_count += 1
                    else:
                        total_new_candles += result['new_candles']
                        total_agg_candles += result['aggregated']

            except Exception as e:
                print(f"   ❌ Failed: {e}")

            # Overall progress
            elapsed = time.time() - start_time
            if completed_count > 0:
                avg_time = elapsed / completed_count
                remaining_time = avg_time * (len(remaining) - completed_count)
                print(f"\n   📊 Overall: {completed_count}/{len(remaining)} symbols | "
                      f"Elapsed: {format_time(elapsed)} | "
                      f"ETA: {format_time(remaining_time)}")

        # Done!
        total_time = time.time() - start_time
        print(f"\n{'═'*60}")
        print(f"  ✅ Historical data fetch complete!")
        print(f"{'═'*60}")
        print(f"  ⏱️  Total time: {format_time(total_time)}")
        print(f"  📈 Symbols processed: {completed_count}")
        print(f"  ⏭️  Skipped (complete): {skipped_count}")
        print(f"  📊 New candles: {total_new_candles:,}")
        print(f"  📊 Aggregated: {total_agg_candles:,}")
        print(f"{'═'*60}\n")


if __name__ == '__main__':
    print("\n" + "═"*60)
    print("  CryptoLens Data Fetcher")
    print("═"*60)

    # Check for flags
    if '--help' in sys.argv:
        print("""
Usage: python fetch_historical.py [options]

Options:
  --days=N      Days of history to fetch (default: 365)
  --force       Force re-fetch even if data exists
  --status      Show database status only
  --help        Show this help

Progress Tracking:
  Progress is tracked automatically via the database.
  If the script crashes, it will resume from where it left off
  based on the most recent candles stored in the DB.

Examples:
  python fetch_historical.py              # Fetch 1 year of data
  python fetch_historical.py --days=30    # Fetch 30 days
  python fetch_historical.py --status     # Check current DB status
  python fetch_historical.py --force      # Re-fetch all data
        """)
        sys.exit(0)

    if '--status' in sys.argv:
        app = create_app()
        show_db_status(app)
        sys.exit(0)

    main()
