#!/usr/bin/env python3
"""
Run all migrations for upgrading existing MySQL databases.

For NEW installations, this is NOT needed - db.create_all() includes everything.

Usage:
    python scripts/migrate_all.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect


def get_table_columns(table_name):
    """Get list of column names for a table (MySQL)."""
    inspector = inspect(db.engine)
    columns = inspector.get_columns(table_name)
    return [col['name'] for col in columns]


def get_table_indexes(table_name):
    """Get list of index names for a table (MySQL)."""
    inspector = inspect(db.engine)
    indexes = inspector.get_indexes(table_name)
    return [idx['name'] for idx in indexes]


def table_exists(table_name):
    """Check if a table exists (MySQL)."""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def add_column_if_not_exists(table, column, column_def, changes):
    """Add column if it doesn't exist."""
    cols = get_table_columns(table)
    if column not in cols:
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
        changes.append(f"Added {table}.{column}")


def add_index_if_not_exists(table, index_name, index_def, changes):
    """Add index if it doesn't exist."""
    indexes = get_table_indexes(table)
    if index_name not in indexes:
        db.session.execute(text(f"CREATE INDEX {index_name} ON {table} {index_def}"))
        changes.append(f"Added {index_name} index")


def migrate():
    app = create_app()
    with app.app_context():
        changes = []

        # symbols table
        if table_exists('symbols'):
            add_column_if_not_exists('symbols', 'notify_enabled', 'BOOLEAN DEFAULT 1', changes)

        # candles table
        if table_exists('candles'):
            add_column_if_not_exists('candles', 'verified_at', 'BIGINT', changes)
            add_index_if_not_exists('candles', 'idx_candle_unverified', '(symbol_id, timeframe, verified_at)', changes)
            add_index_if_not_exists('candles', 'idx_candle_timeframe', '(timeframe)', changes)

        # patterns table
        if table_exists('patterns'):
            pattern_cols = {
                'entry': 'FLOAT', 'stop_loss': 'FLOAT',
                'take_profit_1': 'FLOAT', 'take_profit_2': 'FLOAT', 'take_profit_3': 'FLOAT',
                'risk': 'FLOAT', 'risk_reward_1': 'FLOAT', 'risk_reward_2': 'FLOAT', 'risk_reward_3': 'FLOAT'
            }
            for col, col_type in pattern_cols.items():
                add_column_if_not_exists('patterns', col, col_type, changes)
            add_index_if_not_exists('patterns', 'idx_pattern_list', '(status, detected_at)', changes)

        # users table
        if table_exists('users'):
            user_cols = {
                'email_verification_token': 'VARCHAR(64)',
                'email_verification_expires': 'DATETIME',
                'password_reset_token': 'VARCHAR(64)',
                'password_reset_expires': 'DATETIME',
                'failed_login_attempts': 'INTEGER DEFAULT 0',
                'locked_until': 'DATETIME',
                'telegram_chat_id': 'VARCHAR(50)',
                'telegram_username': 'VARCHAR(100)',
                'telegram_verified': 'BOOLEAN DEFAULT 0',
                'telegram_verified_at': 'DATETIME',
            }
            for col, col_type in user_cols.items():
                add_column_if_not_exists('users', col, col_type, changes)

        # subscriptions table
        if table_exists('subscriptions'):
            add_column_if_not_exists('subscriptions', 'auto_renew', 'BOOLEAN DEFAULT 0', changes)
            add_column_if_not_exists('subscriptions', 'payment_method', 'VARCHAR(50)', changes)

        # user_symbol_preferences table
        if table_exists('user_symbol_preferences'):
            pref_cols = {
                'custom_rr': 'FLOAT',
                'custom_sl_buffer_pct': 'FLOAT',
                'custom_min_zone_pct': 'FLOAT',
                'pattern_params': 'TEXT',
                'params_source': 'VARCHAR(50)',
                'optimization_run_id': 'INTEGER',
            }
            for col, col_type in pref_cols.items():
                add_column_if_not_exists('user_symbol_preferences', col, col_type, changes)

        # optimization_runs table
        if table_exists('optimization_runs'):
            opt_cols = {
                'last_candle_timestamp': 'BIGINT',
                'open_trades_json': 'TEXT',
                'is_incremental': 'BOOLEAN DEFAULT 0',
                'base_run_id': 'INTEGER',
                'updated_at': 'DATETIME',
            }
            for col, col_type in opt_cols.items():
                add_column_if_not_exists('optimization_runs', col, col_type, changes)
            add_index_if_not_exists(
                'optimization_runs', 'idx_opt_run_incremental',
                '(symbol, timeframe, pattern_type, rr_target, sl_buffer_pct)', changes
            )

        db.session.commit()

        if changes:
            print("Migrations applied:")
            for c in changes:
                print(f"  - {c}")
        else:
            print("Database is up to date. No migrations needed.")


if __name__ == '__main__':
    migrate()
