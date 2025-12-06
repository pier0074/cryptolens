#!/usr/bin/env python3
"""
Create default admin and test accounts for CryptoLens.

This script creates:
- Admin user (premium + admin privileges)
- Test users for each tier (free, pro, premium)

Idempotent - safe to run multiple times.

Usage:
    python scripts/create_admin.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app import create_app, db
from app.models import User, Subscription
from app.services.auth import generate_unique_topic


# Test account credentials
TEST_ACCOUNTS = [
    {
        'email': 'admin@cryptolens.local',
        'username': 'admin',
        'password': 'Admin123',
        'plan': 'premium',  # Plan name for Subscription
        'is_admin': True,
    },
    {
        'email': 'free@cryptolens.local',
        'username': 'freeuser',
        'password': 'Free123',
        'plan': 'free',
        'is_admin': False,
    },
    {
        'email': 'pro@cryptolens.local',
        'username': 'prouser',
        'password': 'Pro123',
        'plan': 'pro',
        'is_admin': False,
    },
    {
        'email': 'premium@cryptolens.local',
        'username': 'premiumuser',
        'password': 'Premium123',
        'plan': 'premium',
        'is_admin': False,
    },
]


def create_test_accounts():
    """Create all test accounts."""
    app = create_app()
    with app.app_context():
        created = []
        skipped = []

        for account in TEST_ACCOUNTS:
            existing = User.query.filter_by(email=account['email']).first()
            if existing:
                skipped.append(account)
                continue

            # Create user with ntfy_topic (subscription_tier is a computed property)
            user = User(
                email=account['email'],
                username=account['username'],
                is_admin=account['is_admin'],
                is_verified=True,
                ntfy_topic=generate_unique_topic()
            )
            user.set_password(account['password'])
            db.session.add(user)
            db.session.flush()  # Get the user.id

            # Create subscription for the user
            subscription = Subscription(
                user_id=user.id,
                plan=account['plan'],
                status='active',
                starts_at=datetime.now(timezone.utc),
                expires_at=None  # Never expires for test accounts
            )
            db.session.add(subscription)
            db.session.commit()

            account['ntfy_topic'] = user.ntfy_topic
            account['tier'] = user.subscription_tier  # Computed from subscription
            created.append(account)

        # Print results
        if created:
            print("=" * 60)
            print("CREATED ACCOUNTS:")
            print("=" * 60)
            for acc in created:
                role = "Admin + Premium" if acc['is_admin'] else acc['tier'].title()
                print(f"\n  [{role}]")
                print(f"    Email:      {acc['email']}")
                print(f"    Password:   {acc['password']}")
                print(f"    NTFY Topic: {acc.get('ntfy_topic', 'N/A')}")
            print("\n" + "=" * 60)
            print("IMPORTANT: Change passwords after testing!")
            print("=" * 60)

        if skipped:
            print("\nSKIPPED (already exist):")
            for acc in skipped:
                print(f"  - {acc['email']}")

        if not created and not skipped:
            print("No accounts to create.")

        return created, skipped


def main():
    """Main entry point."""
    print("\nCryptoLens Test Account Setup")
    print("-" * 40)
    create_test_accounts()
    print()


if __name__ == '__main__':
    main()
