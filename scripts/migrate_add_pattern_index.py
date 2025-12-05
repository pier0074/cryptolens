#!/usr/bin/env python3
"""
Migration script to add idx_pattern_list index to existing databases.
Run once after updating to add the new index.

Usage:
    python scripts/migrate_add_pattern_index.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def migrate():
    app = create_app()
    with app.app_context():
        # Check if index already exists
        result = db.session.execute(db.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_pattern_list'"
        ))
        if result.fetchone():
            print("Index idx_pattern_list already exists. Skipping.")
            return

        # Create the index
        print("Creating index idx_pattern_list on patterns(status, detected_at)...")
        db.session.execute(db.text(
            "CREATE INDEX idx_pattern_list ON patterns(status, detected_at)"
        ))
        db.session.commit()
        print("Done! Index created successfully.")

if __name__ == '__main__':
    migrate()
