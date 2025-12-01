#!/usr/bin/env python3
"""
Historical Data Fetcher Script
Downloads historical candle data for all symbols
"""
import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Symbol
from app.services.data_fetcher import fetch_historical
from app.services.aggregator import aggregate_all_timeframes
from app.config import Config


def main():
    """Fetch historical data for all symbols"""
    app = create_app()

    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            print("No symbols found. Initializing default symbols...")
            for symbol_name in Config.SYMBOLS:
                symbol = Symbol(symbol=symbol_name, exchange='kucoin')
                db.session.add(symbol)
            db.session.commit()
            symbols = Symbol.query.filter_by(is_active=True).all()

        print(f"Fetching historical data for {len(symbols)} symbols...")
        print("=" * 50)

        days = 30  # Default 30 days of history

        for i, symbol in enumerate(symbols, 1):
            print(f"\n[{i}/{len(symbols)}] {symbol.symbol}")

            # Fetch 1m candles
            print(f"  Fetching 1m candles ({days} days)...")
            count = fetch_historical(symbol.symbol, '1m', days=days)
            print(f"  ✓ Fetched {count} 1m candles")

            # Aggregate to higher timeframes
            print(f"  Aggregating to higher timeframes...")
            agg_results = aggregate_all_timeframes(symbol.symbol)
            for tf, cnt in agg_results.items():
                if cnt > 0:
                    print(f"    ✓ {tf}: {cnt} candles")

            # Rate limiting
            time.sleep(1)

        print("\n" + "=" * 50)
        print("Historical data fetch complete!")


if __name__ == '__main__':
    main()
