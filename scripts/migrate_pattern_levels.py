#!/usr/bin/env python
"""
Migration: Add trading level columns to patterns table and backfill existing patterns.

This migration:
1. Adds new columns for pre-computed trading levels (entry, stop_loss, take_profits, etc.)
2. Backfills existing patterns with calculated trading levels

Run: python scripts/migrate_pattern_levels.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Pattern, Candle
from app.services.trading import calculate_trading_levels, calculate_atr, find_swing_high, find_swing_low
from sqlalchemy import text
import pandas as pd


def add_columns():
    """Add trading level columns to patterns table if they don't exist."""
    columns_to_add = [
        ('entry', 'FLOAT'),
        ('stop_loss', 'FLOAT'),
        ('take_profit_1', 'FLOAT'),
        ('take_profit_2', 'FLOAT'),
        ('take_profit_3', 'FLOAT'),
        ('risk', 'FLOAT'),
        ('risk_reward_1', 'FLOAT'),
        ('risk_reward_2', 'FLOAT'),
        ('risk_reward_3', 'FLOAT'),
    ]

    for col_name, col_type in columns_to_add:
        try:
            db.session.execute(text(f"ALTER TABLE patterns ADD COLUMN {col_name} {col_type}"))
            print(f"  Added column: {col_name}")
        except Exception as e:
            if 'duplicate column' in str(e).lower():
                print(f"  Column already exists: {col_name}")
            else:
                print(f"  Error adding {col_name}: {e}")

    db.session.commit()


def get_candles_df(symbol_id: int, timeframe: str, limit: int = 100) -> pd.DataFrame:
    """Get candles as DataFrame for trading calculations."""
    candles = Candle.query.filter_by(
        symbol_id=symbol_id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    if not candles:
        return pd.DataFrame()

    data = [{
        'timestamp': c.timestamp,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'volume': c.volume
    } for c in reversed(candles)]

    return pd.DataFrame(data)


def backfill_patterns():
    """Calculate and store trading levels for all existing patterns."""
    patterns = Pattern.query.filter(Pattern.entry.is_(None)).all()

    if not patterns:
        print("  No patterns need backfilling")
        return 0

    print(f"  Backfilling {len(patterns)} patterns...")

    # Cache DataFrames by (symbol_id, timeframe)
    df_cache = {}
    levels_cache = {}

    updated = 0
    for i, pattern in enumerate(patterns):
        cache_key = (pattern.symbol_id, pattern.timeframe)

        # Get DataFrame (cached)
        if cache_key not in df_cache:
            df_cache[cache_key] = get_candles_df(pattern.symbol_id, pattern.timeframe)

        df = df_cache[cache_key]

        # Get ATR/swing levels (cached per symbol/tf)
        if cache_key not in levels_cache:
            if df is not None and not df.empty:
                levels_cache[cache_key] = {
                    'atr': calculate_atr(df),
                    'swing_high': find_swing_high(df, len(df) - 1),
                    'swing_low': find_swing_low(df, len(df) - 1),
                }
            else:
                levels_cache[cache_key] = {'atr': 0, 'swing_high': None, 'swing_low': None}

        cached = levels_cache[cache_key]

        # Calculate trading levels
        levels = calculate_trading_levels(
            pattern_type=pattern.pattern_type,
            zone_low=pattern.zone_low,
            zone_high=pattern.zone_high,
            direction=pattern.direction,
            atr=cached['atr'],
            swing_high=cached['swing_high'],
            swing_low=cached['swing_low']
        )

        # Update pattern with trading levels
        pattern.entry = levels.entry
        pattern.stop_loss = levels.stop_loss
        pattern.take_profit_1 = levels.take_profit_1
        pattern.take_profit_2 = levels.take_profit_2
        pattern.take_profit_3 = levels.take_profit_3
        pattern.risk = levels.risk
        pattern.risk_reward_1 = round(levels.risk_reward_1, 2)
        pattern.risk_reward_2 = round(levels.risk_reward_2, 2)
        pattern.risk_reward_3 = round(levels.risk_reward_3, 2)

        updated += 1

        # Progress update every 100 patterns
        if (i + 1) % 100 == 0:
            print(f"    Processed {i + 1}/{len(patterns)} patterns...")
            db.session.commit()

    db.session.commit()
    return updated


def migrate():
    """Run the full migration."""
    app = create_app()

    with app.app_context():
        print("Migration: Adding trading level columns to patterns table")
        print()

        print("Step 1: Adding new columns...")
        add_columns()
        print()

        print("Step 2: Backfilling existing patterns...")
        updated = backfill_patterns()
        print()

        print(f"Migration complete! Updated {updated} patterns.")


if __name__ == '__main__':
    migrate()
