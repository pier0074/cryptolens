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

        # 7. Users table
        if not table_exists('users'):
            db.session.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    is_verified BOOLEAN DEFAULT 0,
                    is_admin BOOLEAN DEFAULT 0,
                    ntfy_topic VARCHAR(64) UNIQUE NOT NULL,
                    created_at DATETIME,
                    last_login DATETIME
                )
            """))
            db.session.execute(text("CREATE INDEX idx_user_email ON users (email)"))
            db.session.execute(text("CREATE INDEX idx_user_active ON users (is_active, is_verified)"))
            changes.append("Created users table")

        # 8. Subscriptions table
        if not table_exists('subscriptions'):
            db.session.execute(text("""
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER UNIQUE NOT NULL,
                    plan VARCHAR(20) DEFAULT 'free',
                    starts_at DATETIME NOT NULL,
                    expires_at DATETIME,
                    status VARCHAR(20) DEFAULT 'active',
                    grace_period_days INTEGER DEFAULT 3,
                    created_at DATETIME,
                    updated_at DATETIME,
                    cancelled_at DATETIME,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """))
            db.session.execute(text("CREATE INDEX idx_subscription_status ON subscriptions (status)"))
            db.session.execute(text("CREATE INDEX idx_subscription_expires ON subscriptions (expires_at)"))
            changes.append("Created subscriptions table")

        # 9. User notifications table
        if not table_exists('user_notifications'):
            db.session.execute(text("""
                CREATE TABLE user_notifications (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    signal_id INTEGER NOT NULL,
                    sent_at DATETIME,
                    success BOOLEAN DEFAULT 1,
                    error TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (signal_id) REFERENCES signals (id)
                )
            """))
            db.session.execute(text("CREATE INDEX idx_user_notification_lookup ON user_notifications (user_id, signal_id)"))
            db.session.execute(text("CREATE INDEX idx_user_notification_sent ON user_notifications (sent_at)"))
            changes.append("Created user_notifications table")

        # 10. User email verification and password reset columns
        if table_exists('users'):
            cols = get_table_columns('users')

            # Email verification
            if 'email_verification_token' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN email_verification_token VARCHAR(64)"))
                changes.append("Added users.email_verification_token")
            if 'email_verification_expires' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN email_verification_expires DATETIME"))
                changes.append("Added users.email_verification_expires")

            # Password reset
            if 'password_reset_token' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN password_reset_token VARCHAR(64)"))
                changes.append("Added users.password_reset_token")
            if 'password_reset_expires' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN password_reset_expires DATETIME"))
                changes.append("Added users.password_reset_expires")

            # Two-factor authentication (TOTP)
            if 'totp_secret' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(32)"))
                changes.append("Added users.totp_secret")
            if 'totp_enabled' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
                changes.append("Added users.totp_enabled")

            # Notification preferences
            if 'notify_enabled' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_enabled BOOLEAN DEFAULT 1"))
                changes.append("Added users.notify_enabled")
            if 'notify_signals' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_signals BOOLEAN DEFAULT 1"))
                changes.append("Added users.notify_signals")
            if 'notify_patterns' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_patterns BOOLEAN DEFAULT 0"))
                changes.append("Added users.notify_patterns")
            if 'notify_priority' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_priority INTEGER DEFAULT 3"))
                changes.append("Added users.notify_priority")
            if 'notify_min_confluence' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_min_confluence INTEGER DEFAULT 2"))
                changes.append("Added users.notify_min_confluence")
            if 'notify_directions' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN notify_directions VARCHAR(20) DEFAULT 'both'"))
                changes.append("Added users.notify_directions")
            if 'quiet_hours_enabled' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN quiet_hours_enabled BOOLEAN DEFAULT 0"))
                changes.append("Added users.quiet_hours_enabled")
            if 'quiet_hours_start' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN quiet_hours_start INTEGER DEFAULT 22"))
                changes.append("Added users.quiet_hours_start")
            if 'quiet_hours_end' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN quiet_hours_end INTEGER DEFAULT 7"))
                changes.append("Added users.quiet_hours_end")

        # 11. Payments table
        if not table_exists('payments'):
            db.session.execute(text("""
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    provider VARCHAR(20) NOT NULL,
                    external_id VARCHAR(100),
                    plan VARCHAR(20) NOT NULL,
                    billing_cycle VARCHAR(20) DEFAULT 'monthly',
                    amount FLOAT NOT NULL,
                    currency VARCHAR(10) DEFAULT 'USD',
                    crypto_currency VARCHAR(10),
                    crypto_amount FLOAT,
                    status VARCHAR(20) DEFAULT 'pending',
                    created_at DATETIME,
                    completed_at DATETIME,
                    expires_at DATETIME,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """))
            db.session.execute(text("CREATE INDEX idx_payment_user ON payments (user_id)"))
            db.session.execute(text("CREATE INDEX idx_payment_status ON payments (status)"))
            db.session.execute(text("CREATE INDEX idx_payment_provider ON payments (provider, external_id)"))
            changes.append("Created payments table")

        db.session.commit()

        if changes:
            print("Migrations applied:")
            for c in changes:
                print(f"  - {c}")
        else:
            print("Database is up to date. No migrations needed.")


if __name__ == '__main__':
    migrate()
