#!/usr/bin/env python
"""
Migration: Add indexes for stats page performance

Run: python scripts/migrate_add_stats_indexes.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def migrate():
    """Add performance indexes for stats page."""
    app = create_app()

    with app.app_context():
        indexes = [
            ("idx_candle_timeframe", "CREATE INDEX IF NOT EXISTS idx_candle_timeframe ON candles (timeframe)"),
            ("idx_signal_symbol", "CREATE INDEX IF NOT EXISTS idx_signal_symbol ON signals (symbol_id)"),
        ]

        for name, sql in indexes:
            try:
                print(f"Creating index '{name}'...")
                db.session.execute(text(sql))
                db.session.commit()
                print(f"  Done.")
            except Exception as e:
                print(f"  Skipped (may already exist): {e}")

        # Run ANALYZE to update query planner statistics
        print("Running ANALYZE...")
        db.session.execute(text("ANALYZE"))
        db.session.commit()
        print("Done.")


if __name__ == '__main__':
    migrate()
