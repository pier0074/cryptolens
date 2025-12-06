#!/usr/bin/env python3
"""
Run all migrations for upgrading existing databases.

For NEW installations, this is NOT needed - db.create_all() includes everything.

Usage:
    python scripts/migrate_all.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def get_table_columns(table_name):
    """Get list of column names for a table."""
    result = db.session.execute(text(f"PRAGMA table_info({table_name})"))
    return [row[1] for row in result.fetchall()]


def get_table_indexes(table_name):
    """Get list of index names for a table."""
    result = db.session.execute(text(f"PRAGMA index_list({table_name})"))
    return [row[1] for row in result.fetchall()]


def table_exists(table_name):
    """Check if a table exists."""
    result = db.session.execute(text(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
    ))
    return result.fetchone() is not None


def migrate():
    app = create_app()
    with app.app_context():
        changes = []

        # 1. Symbol.notify_enabled
        cols = get_table_columns('symbols')
        if 'notify_enabled' not in cols:
            db.session.execute(text(
                "ALTER TABLE symbols ADD COLUMN notify_enabled BOOLEAN DEFAULT 1"
            ))
            changes.append("Added symbols.notify_enabled")

        # 2. Candle.verified_at
        cols = get_table_columns('candles')
        if 'verified_at' not in cols:
            db.session.execute(text(
                "ALTER TABLE candles ADD COLUMN verified_at INTEGER"
            ))
            changes.append("Added candles.verified_at")

        # 3. Pattern trading levels
        cols = get_table_columns('patterns')
        pattern_cols = ['entry', 'stop_loss', 'take_profit_1', 'take_profit_2',
                       'take_profit_3', 'risk', 'risk_reward_1', 'risk_reward_2', 'risk_reward_3']
        for col in pattern_cols:
            if col not in cols:
                db.session.execute(text(
                    f"ALTER TABLE patterns ADD COLUMN {col} FLOAT"
                ))
                changes.append(f"Added patterns.{col}")

        # 4. StatsCache table
        if not table_exists('stats_cache'):
            db.session.execute(text("""
                CREATE TABLE stats_cache (
                    id INTEGER PRIMARY KEY,
                    key VARCHAR(50) UNIQUE NOT NULL,
                    data TEXT NOT NULL,
                    computed_at INTEGER NOT NULL
                )
            """))
            changes.append("Created stats_cache table")

        # 5. Pattern list index
        indexes = get_table_indexes('patterns')
        if 'idx_pattern_list' not in indexes:
            db.session.execute(text(
                "CREATE INDEX idx_pattern_list ON patterns (status, detected_at)"
            ))
            changes.append("Added idx_pattern_list index")

        # 6. Candle unverified index
        indexes = get_table_indexes('candles')
        if 'idx_candle_unverified' not in indexes:
            db.session.execute(text(
                "CREATE INDEX idx_candle_unverified ON candles (symbol_id, timeframe, verified_at)"
            ))
            changes.append("Added idx_candle_unverified index")

        if 'idx_candle_timeframe' not in indexes:
            db.session.execute(text(
                "CREATE INDEX idx_candle_timeframe ON candles (timeframe)"
            ))
            changes.append("Added idx_candle_timeframe index")

        db.session.commit()

        if changes:
            print("Migrations applied:")
            for c in changes:
                print(f"  - {c}")
        else:
            print("Database is up to date. No migrations needed.")


if __name__ == '__main__':
    migrate()
