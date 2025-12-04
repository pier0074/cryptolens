#!/usr/bin/env python
"""
Migration: Add stats_cache table for pre-computed statistics.

Run: python scripts/migrate_add_stats_cache.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def migrate():
    """Create stats_cache table if it doesn't exist."""
    app = create_app()

    with app.app_context():
        # Check if table already exists
        result = db.session.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stats_cache'"
        ))
        if result.fetchone():
            print("Table 'stats_cache' already exists. Migration skipped.")
            return

        # Create the table
        print("Creating 'stats_cache' table...")
        db.session.execute(text("""
            CREATE TABLE stats_cache (
                id INTEGER PRIMARY KEY,
                key VARCHAR(50) NOT NULL UNIQUE,
                data TEXT NOT NULL,
                computed_at INTEGER NOT NULL
            )
        """))
        db.session.commit()
        print("Table created successfully.")

        # Note: Run compute_stats.py to populate
        print("\nTo populate the cache, run:")
        print("  python scripts/compute_stats.py")


if __name__ == '__main__':
    migrate()
