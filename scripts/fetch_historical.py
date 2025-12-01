#!/usr/bin/env python3
"""
Historical Data Fetcher Script
Downloads historical candle data for all symbols
Supports resume from interruption
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
from app.services.data_fetcher import fetch_historical
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


def get_existing_candle_count(app, symbol_name):
    """Get count of existing candles for a symbol"""
    with app.app_context():
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if sym:
            return Candle.query.filter_by(symbol_id=sym.id, timeframe='1m').count()
    return 0


def main():
    """Fetch historical data for all symbols"""
    app = create_app()

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

        print(f"\nFetching historical data for {len(remaining)} symbols...")
        print("=" * 60)

        days = 7  # 7 days is faster, increase to 30 for more history
        start_time = time.time()

        for i, symbol in enumerate(remaining, 1):
            symbol_start = time.time()
            total_symbols = len(remaining)

            # Check existing data
            existing = get_existing_candle_count(app, symbol.symbol)

            print(f"\n[{i}/{total_symbols}] {symbol.symbol}")
            if existing > 0:
                print(f"  Already have {existing} candles, fetching new...")

            # Progress callback for detailed logging
            def progress_callback(batch, total, count):
                pct = (batch / total) * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                print(f"\r  Fetching: [{bar}] {pct:5.1f}% | Batch {batch}/{total} | {count} candles", end="", flush=True)

            # Fetch 1m candles
            try:
                count = fetch_historical(symbol.symbol, '1m', days=days, progress_callback=progress_callback)
                print(f"\n  ✓ Fetched {count} new 1m candles")
            except Exception as e:
                print(f"\n  ✗ Error fetching: {e}")
                continue

            # Aggregate to higher timeframes
            print(f"  Aggregating to higher timeframes...")
            try:
                agg_results = aggregate_all_timeframes(symbol.symbol)
                agg_summary = ", ".join([f"{tf}:{cnt}" for tf, cnt in agg_results.items() if cnt > 0])
                if agg_summary:
                    print(f"    ✓ {agg_summary}")
            except Exception as e:
                print(f"    ✗ Aggregation error: {e}")

            # Mark as completed and save progress
            progress['completed'].append(symbol.symbol)
            save_progress(progress)

            # Stats
            symbol_time = time.time() - symbol_start
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            remaining_time = avg_time * (total_symbols - i)

            print(f"  ⏱  {symbol_time:.1f}s | ETA: {remaining_time/60:.1f} min remaining")

            # Rate limiting between symbols
            time.sleep(0.5)

        # Done!
        total_time = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"✓ Historical data fetch complete!")
        print(f"  Total time: {total_time/60:.1f} minutes")
        print(f"  Symbols fetched: {len(remaining)}")

        # Clear progress file on successful completion
        clear_progress()


if __name__ == '__main__':
    # Check for --force flag
    if '--force' in sys.argv:
        clear_progress()
        print("Progress cleared. Starting fresh...")

    if '--clear' in sys.argv:
        clear_progress()
        print("Progress file cleared.")
        sys.exit(0)

    main()
