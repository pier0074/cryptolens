#!/usr/bin/env python3
"""
Historical Data Fetcher Script
Downloads historical candle data for all symbols (sequential to avoid SQLite locks)
"""
import sys
import os
import time
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol, Candle
from app.services.aggregator import aggregate_all_timeframes
from app.config import Config

# Progress file to track completed symbols
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fetch_progress.json')


def load_progress():
    """Load progress from file"""
    try:
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {'completed': [], 'started_at': None}


def save_progress(progress):
    """Save progress to file"""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def clear_progress():
    """Clear progress file"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


def format_time(seconds):
    """Format seconds into human readable time"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def fetch_symbol_with_logging(app, symbol_name, days):
    """
    Fetch historical data for a single symbol with detailed logging
    """
    import ccxt
    from datetime import timedelta

    with app.app_context():
        exchange = ccxt.kucoin({'enableRateLimit': True})

        # Get or create symbol
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            sym = Symbol(symbol=symbol_name, exchange='kucoin')
            db.session.add(sym)
            db.session.commit()

        # Calculate time range
        now = datetime.utcnow()
        start_time = now - timedelta(days=days)
        since = int(start_time.timestamp() * 1000)
        now_ts = int(now.timestamp() * 1000)

        # Timeframe settings
        timeframe = '1m'
        candle_duration = 60 * 1000  # 1 minute in ms
        batch_size = 500

        # Calculate totals
        total_candles_needed = (now_ts - since) // candle_duration
        total_batches = max(1, (total_candles_needed // batch_size) + 1)

        print(f"\n{'─'*50}")
        print(f"📊 {symbol_name}")
        print(f"   Target: ~{total_candles_needed:,} candles ({total_batches} batches)")
        print(f"   Range: {start_time.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}")
        sys.stdout.flush()

        total_new = 0
        total_existing = 0
        current_since = since
        batch_num = 0
        last_log_pct = -10
        batch_start = time.time()

        while current_since < now_ts:
            batch_num += 1

            try:
                # Fetch from exchange
                ohlcv = exchange.fetch_ohlcv(symbol_name, timeframe, since=current_since, limit=batch_size)

                if not ohlcv:
                    # No more data
                    break

                # Save candles
                new_in_batch = 0
                for candle in ohlcv:
                    timestamp, open_price, high, low, close, volume = candle

                    # Check if exists
                    existing = Candle.query.filter_by(
                        symbol_id=sym.id,
                        timeframe=timeframe,
                        timestamp=timestamp
                    ).first()

                    if not existing:
                        new_candle = Candle(
                            symbol_id=sym.id,
                            timeframe=timeframe,
                            timestamp=timestamp,
                            open=open_price,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume
                        )
                        db.session.add(new_candle)
                        new_in_batch += 1
                    else:
                        total_existing += 1

                # Commit this batch
                db.session.commit()
                total_new += new_in_batch

                # Progress logging (every 10% or every 100 batches)
                pct = int((batch_num / total_batches) * 100)
                if pct >= last_log_pct + 10 or batch_num % 100 == 0:
                    last_log_pct = pct
                    elapsed = time.time() - batch_start
                    rate = batch_num / elapsed if elapsed > 0 else 0
                    eta = (total_batches - batch_num) / rate if rate > 0 else 0

                    # Show date being fetched
                    current_date = datetime.utcfromtimestamp(current_since / 1000).strftime('%Y-%m-%d')

                    print(f"   [{pct:3d}%] Batch {batch_num}/{total_batches} | "
                          f"Date: {current_date} | "
                          f"New: {total_new:,} | "
                          f"ETA: {format_time(eta)}")
                    sys.stdout.flush()

                # Move to next batch
                current_since += batch_size * candle_duration

                # Rate limiting
                time.sleep(exchange.rateLimit / 1000)

            except Exception as e:
                print(f"   ⚠️  Batch {batch_num} error: {e}")
                sys.stdout.flush()
                time.sleep(2)
                continue

        # Aggregate to higher timeframes
        print(f"   Aggregating to higher timeframes...")
        sys.stdout.flush()
        agg_results = aggregate_all_timeframes(symbol_name)
        agg_count = sum(agg_results.values())

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
            'time': elapsed
        }


def main():
    """Fetch historical data for all symbols"""
    app = create_app()

    # Parse arguments
    days = 365  # Default 1 year

    for arg in sys.argv:
        if arg.startswith('--days='):
            days = int(arg.split('=')[1])

    # Load progress
    progress = load_progress()

    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("No symbols found. Initializing default symbols...")
            for symbol_name in Config.SYMBOLS:
                symbol = Symbol(symbol=symbol_name, exchange='kucoin')
                db.session.add(symbol)
            db.session.commit()
            symbols = Symbol.query.filter_by(is_active=True).all()

        # Check which symbols need fetching
        completed = set(progress.get('completed', []))
        remaining = [s for s in symbols if s.symbol not in completed]

        if not remaining:
            print("All symbols already fetched! Use --force to re-fetch.")
            print("Clearing progress file...")
            clear_progress()
            return

        if completed:
            print(f"\n🔄 Resuming... {len(completed)} done, {len(remaining)} remaining")
        else:
            progress['started_at'] = datetime.now().isoformat()

        print(f"\n{'═'*60}")
        print(f"  CryptoLens Historical Data Fetcher")
        print(f"{'═'*60}")
        print(f"  📈 Symbols to fetch: {len(remaining)}")
        print(f"  📅 Days of history: {days} ({days/365:.1f} years)")
        print(f"  📊 Est. candles/symbol: ~{days * 24 * 60:,}")
        print(f"  ⏱️  Mode: Sequential (SQLite safe)")
        print(f"{'═'*60}")

        start_time = time.time()
        completed_count = 0
        total_new_candles = 0
        total_agg_candles = 0

        # Process symbols sequentially
        for i, symbol in enumerate(remaining):
            completed_count += 1
            print(f"\n[{completed_count}/{len(remaining)}] Processing {symbol.symbol}...")

            try:
                result = fetch_symbol_with_logging(app, symbol.symbol, days)

                if result['success']:
                    total_new_candles += result['new_candles']
                    total_agg_candles += result['aggregated']

                    # Mark as completed
                    progress['completed'].append(symbol.symbol)
                    save_progress(progress)

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
        print(f"  📈 Symbols fetched: {completed_count}")
        print(f"  📊 New candles: {total_new_candles:,}")
        print(f"  📊 Aggregated: {total_agg_candles:,}")
        print(f"{'═'*60}\n")

        # Clear progress file on successful completion
        clear_progress()


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
  --force       Clear progress and start fresh
  --clear       Just clear progress file
  --help        Show this help

Examples:
  python fetch_historical.py              # Fetch 1 year of data
  python fetch_historical.py --days=30    # Fetch 30 days
  python fetch_historical.py --force      # Start fresh
        """)
        sys.exit(0)

    if '--force' in sys.argv:
        clear_progress()
        print("Progress cleared. Starting fresh...")

    if '--clear' in sys.argv:
        clear_progress()
        print("Progress file cleared.")
        sys.exit(0)

    main()
