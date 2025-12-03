#!/usr/bin/env python
"""
Pattern Cleanup Script
Marks expired patterns as 'expired' status based on timeframe-specific expiry.
Run via cron: */30 * * * * (every 30 minutes)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app import create_app, db
from app.models import Pattern
from app.config import Config


def cleanup_expired_patterns(dry_run=False):
    """
    Mark patterns as expired based on their timeframe expiry settings.

    Args:
        dry_run: If True, don't actually update, just show what would be changed

    Returns:
        Number of patterns marked as expired
    """
    app = create_app()
    with app.app_context():
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Get all active patterns
        active_patterns = Pattern.query.filter_by(status='active').all()

        expired_count = 0
        expired_by_tf = {}

        for pattern in active_patterns:
            # Get expiry hours for this timeframe
            expiry_hours = Config.PATTERN_EXPIRY_HOURS.get(
                pattern.timeframe,
                Config.DEFAULT_PATTERN_EXPIRY_HOURS
            )
            expiry_ms = expiry_hours * 60 * 60 * 1000
            expires_at = pattern.detected_at + expiry_ms

            if now_ms > expires_at:
                if not dry_run:
                    pattern.status = 'expired'

                expired_count += 1
                tf = pattern.timeframe
                expired_by_tf[tf] = expired_by_tf.get(tf, 0) + 1

        if not dry_run and expired_count > 0:
            db.session.commit()

        return expired_count, expired_by_tf


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Cleanup expired patterns')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    print("=" * 50)
    print("  CryptoLens Pattern Cleanup")
    print("=" * 50)

    if args.dry_run:
        print("  Mode: DRY RUN (no changes will be made)")

    expired_count, by_tf = cleanup_expired_patterns(dry_run=args.dry_run)

    if expired_count > 0:
        print(f"\n  {'Would expire' if args.dry_run else 'Expired'} {expired_count} patterns:")
        for tf, count in sorted(by_tf.items()):
            print(f"    - {tf}: {count} patterns")
    else:
        print("\n  No patterns to expire")

    print("\n" + "=" * 50)


if __name__ == '__main__':
    main()
