#!/usr/bin/env python3
"""
Database Initialization Script

Usage:
    python scripts/init_db.py              # Initialize tables (database must exist)
    python scripts/init_db.py --create     # Create database + tables
    python scripts/init_db.py --drop       # Drop database
    python scripts/init_db.py --migrate    # Migrate from SQLite to MySQL
"""
import os
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def get_db_config():
    """Get database configuration from environment."""
    from app.config import is_production

    prefix = 'PROD_DB' if is_production() else 'DB'

    return {
        'host': os.getenv(f'{prefix}_HOST', os.getenv('DB_HOST', 'localhost')),
        'port': os.getenv(f'{prefix}_PORT', os.getenv('DB_PORT', '3306')),
        'user': os.getenv(f'{prefix}_USER', os.getenv('DB_USER', 'root')),
        'password': os.getenv(f'{prefix}_PASS', os.getenv('DB_PASS', '')),
        'database': os.getenv(f'{prefix}_NAME', os.getenv('DB_NAME', 'cryptolens')),
    }


def create_database():
    """Create the MySQL database using credentials from .env"""
    import pymysql

    config = get_db_config()

    print(f"Connecting to MySQL at {config['host']}:{config['port']} as {config['user']}...")

    try:
        conn = pymysql.connect(
            host=config['host'],
            port=int(config['port']),
            user=config['user'],
            password=config['password'],
        )
        cursor = conn.cursor()

        db_name = config['database']
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()

        print(f"Database '{db_name}' created successfully!")

        cursor.close()
        conn.close()

        # Now initialize tables
        init_database()

    except pymysql.err.OperationalError as e:
        print(f"Error connecting to MySQL: {e}")
        print("\nCheck your .env file:")
        print(f"  DB_HOST={config['host']}")
        print(f"  DB_PORT={config['port']}")
        print(f"  DB_USER={config['user']}")
        print(f"  DB_PASS={'*' * len(config['password']) if config['password'] else '(empty)'}")
        sys.exit(1)


def drop_database():
    """Drop the MySQL database."""
    import pymysql

    config = get_db_config()
    db_name = config['database']

    confirm = input(f"Are you sure you want to DROP database '{db_name}'? [y/N] ")
    if confirm.lower() != 'y':
        print("Cancelled.")
        return

    try:
        conn = pymysql.connect(
            host=config['host'],
            port=int(config['port']),
            user=config['user'],
            password=config['password'],
        )
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        conn.commit()
        cursor.close()
        conn.close()

        print(f"Database '{db_name}' dropped.")

    except pymysql.err.OperationalError as e:
        print(f"Error: {e}")
        sys.exit(1)


def init_database():
    """Create all database tables."""
    from app import create_app, db

    app = create_app()
    with app.app_context():
        db_url = app.config['SQLALCHEMY_DATABASE_URI']
        # Mask password in output
        if '@' in db_url:
            parts = db_url.split('@')
            masked = parts[0].rsplit(':', 1)[0] + ':***@' + parts[1]
        else:
            masked = db_url
        print(f"Database: {masked[:60]}...")
        print("Creating tables...")
        db.create_all()
        print("Done! All tables created.")


def migrate_sqlite_to_mysql(sqlite_path: str):
    """
    Migrate data from SQLite to MySQL.

    Args:
        sqlite_path: Path to SQLite database file
    """
    import sqlite3
    from sqlalchemy import text

    if not os.path.exists(sqlite_path):
        print(f"Error: SQLite file not found: {sqlite_path}")
        sys.exit(1)

    app = create_app()

    # Ensure we're connecting to MySQL
    db_url = app.config['SQLALCHEMY_DATABASE_URI']
    if 'mysql' not in db_url.lower():
        print("Error: DATABASE_URL must be MySQL for migration target")
        print(f"Current: {db_url}")
        sys.exit(1)

    print(f"Source: {sqlite_path}")
    print(f"Target: MySQL")
    print()

    # Tables to migrate (in order due to foreign keys)
    tables = [
        'settings',
        'symbols',
        'users',
        'subscriptions',
        'payments',
        'candles',
        'patterns',
        'signals',
        'notification_preferences',
        'portfolios',
        'trades',
        'cron_logs',
        'user_symbol_preferences',
    ]

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    with app.app_context():
        # Create tables first
        print("Creating MySQL tables...")
        db.create_all()

        for table in tables:
            try:
                # Check if table exists in SQLite
                sqlite_cursor.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
                )
                if not sqlite_cursor.fetchone():
                    print(f"  Skipping {table} (not in SQLite)")
                    continue

                # Get data from SQLite
                sqlite_cursor.execute(f"SELECT * FROM {table}")
                rows = sqlite_cursor.fetchall()

                if not rows:
                    print(f"  Skipping {table} (empty)")
                    continue

                # Get column names
                columns = [description[0] for description in sqlite_cursor.description]

                # Clear existing data in MySQL
                db.session.execute(text(f"DELETE FROM {table}"))

                # Insert data
                placeholders = ', '.join([f':{col}' for col in columns])
                cols_str = ', '.join([f'`{col}`' for col in columns])  # MySQL uses backticks

                insert_sql = text(f"INSERT INTO `{table}` ({cols_str}) VALUES ({placeholders})")

                for row in rows:
                    row_dict = {col: row[col] for col in columns}
                    db.session.execute(insert_sql, row_dict)

                db.session.commit()
                print(f"  Migrated {table}: {len(rows)} rows")

            except Exception as e:
                print(f"  Error migrating {table}: {e}")
                db.session.rollback()

    sqlite_conn.close()
    print("\nMigration complete!")


def main():
    parser = argparse.ArgumentParser(description='Initialize CryptoLens database')
    parser.add_argument('--create', action='store_true',
                        help='Create database and tables (reads credentials from .env)')
    parser.add_argument('--drop', action='store_true',
                        help='Drop the database')
    parser.add_argument('--migrate', type=str, metavar='SQLITE_PATH',
                        help='Migrate data from SQLite file to MySQL')

    args = parser.parse_args()

    if args.create:
        create_database()
    elif args.drop:
        drop_database()
    elif args.migrate:
        migrate_sqlite_to_mysql(args.migrate)
    else:
        init_database()


if __name__ == '__main__':
    main()
