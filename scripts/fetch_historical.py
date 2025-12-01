#!/usr/bin/env python3
"""
Historical Data Fetcher Script
Downloads historical candle data for all symbols
Supports resume from interruption and parallel fetching
"""
import sys
import os
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol, Candle
from app.services.data_fetcher import fetch_historical
from app.services.aggregator import aggregate_all_timeframes
from app.config import Config

# Progress file to track completed symbols
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fetch_progress.json')

# Thread lock for progress file
progress_lock = threading.Lock()


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
    with progress_lock:
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress, f, indent=2)


def clear_progress():
    """Clear progress file"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


def fetch_symbol_data(symbol_name, days, worker_id):
    """Fetch data for a single symbol (runs in thread)"""
    app = create_app()

    with app.app_context():
        try:
            # Fetch 1m candles
            count = fetch_historical(symbol_name, '1m', days=days)

            # Aggregate to higher timeframes
            agg_results = aggregate_all_timeframes(symbol_name)
            agg_count = sum(agg_results.values())

            return {
                'symbol': symbol_name,
                'success': True,
                'candles': count,
                'aggregated': agg_count,
                'worker': worker_id
            }
        except Exception as e:
            return {
                'symbol': symbol_name,
                'success': False,
                'error': str(e),
                'worker': worker_id
            }


def main():
    """Fetch historical data for all symbols"""
    app = create_app()

    # Parse arguments
    days = 365  # Default 1 year
    workers = 3  # Parallel workers (be careful with rate limits)

    for arg in sys.argv:
        if arg.startswith('--days='):
            days = int(arg.split('=')[1])
        if arg.startswith('--workers='):
            workers = int(arg.split('=')[1])

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
            print(f"Resuming... {len(completed)} symbols already done, {len(remaining)} remaining")
        else:
            progress['started_at'] = datetime.now().isoformat()

        print(f"\n{'='*60}")
        print(f"  CryptoLens Historical Data Fetcher")
        print(f"{'='*60}")
        print(f"  Symbols: {len(remaining)}")
        print(f"  Days: {days} ({days/365:.1f} years)")
        print(f"  Workers: {workers} (parallel)")
        print(f"  Est. candles per symbol: ~{days * 24 * 60:,} (1m)")
        print(f"{'='*60}\n")

        start_time = time.time()
        completed_count = 0
        total_candles = 0

        # Use ThreadPoolExecutor for parallel fetching
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all tasks
            future_to_symbol = {
                executor.submit(fetch_symbol_data, s.symbol, days, i % workers): s.symbol
                for i, s in enumerate(remaining)
            }

            # Process results as they complete
            for future in as_completed(future_to_symbol):
                symbol_name = future_to_symbol[future]
                completed_count += 1

                try:
                    result = future.result()

                    if result['success']:
                        total_candles += result['candles']
                        print(f"✓ [{completed_count}/{len(remaining)}] {result['symbol']}: "
                              f"{result['candles']:,} candles, {result['aggregated']} aggregated")

                        # Mark as completed
                        progress['completed'].append(result['symbol'])
                        save_progress(progress)
                    else:
                        print(f"✗ [{completed_count}/{len(remaining)}] {result['symbol']}: {result['error']}")

                except Exception as e:
                    print(f"✗ [{completed_count}/{len(remaining)}] {symbol_name}: Exception {e}")

                # Show ETA
                elapsed = time.time() - start_time
                if completed_count > 0:
                    avg_time = elapsed / completed_count
                    remaining_time = avg_time * (len(remaining) - completed_count)
                    print(f"  ⏱  ETA: {remaining_time/60:.1f} min | Elapsed: {elapsed/60:.1f} min")

        # Done!
        total_time = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"✓ Historical data fetch complete!")
        print(f"  Total time: {total_time/60:.1f} minutes")
        print(f"  Symbols fetched: {completed_count}")
        print(f"  Total candles: {total_candles:,}")
        print(f"{'='*60}")

        # Clear progress file on successful completion
        clear_progress()


if __name__ == '__main__':
    print("\nCryptoLens Data Fetcher")
    print("-" * 40)

    # Check for flags
    if '--help' in sys.argv:
        print("""
Usage: python fetch_historical.py [options]

Options:
  --days=N      Days of history to fetch (default: 365)
  --workers=N   Parallel workers (default: 3)
  --force       Clear progress and start fresh
  --clear       Just clear progress file
  --help        Show this help
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
