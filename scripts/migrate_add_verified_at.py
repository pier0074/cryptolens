#!/usr/bin/env python
"""
Migration: Add verified_at column to candles table

Run: python scripts/migrate_add_verified_at.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def migrate():
    """Add verified_at column to candles table if it doesn't exist."""
    app = create_app()

    with app.app_context():
        # Check if column already exists
        result = db.session.execute(text("PRAGMA table_info(candles)"))
        columns = [row[1] for row in result.fetchall()]

        if 'verified_at' in columns:
            print("Column 'verified_at' already exists. Migration skipped.")
            return

        # Add the column
        print("Adding 'verified_at' column to candles table...")
        db.session.execute(text("ALTER TABLE candles ADD COLUMN verified_at INTEGER"))
        db.session.commit()
        print("Column added successfully.")

        # Create index for faster lookups
        print("Creating index for unverified candles...")
        try:
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_candle_unverified "
                "ON candles (symbol_id, timeframe, verified_at)"
            ))
            db.session.commit()
            print("Index created successfully.")
        except Exception as e:
            print(f"Index creation skipped (may already exist): {e}")

        # Show stats
        result = db.session.execute(text("SELECT COUNT(*) FROM candles"))
        total = result.scalar()
        result = db.session.execute(text("SELECT COUNT(*) FROM candles WHERE verified_at IS NULL"))
        unverified = result.scalar()
        print(f"\nMigration complete. {total} total candles, {unverified} unverified.")


if __name__ == '__main__':
    migrate()
