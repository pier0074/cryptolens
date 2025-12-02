#!/usr/bin/env python
"""
End-to-End Notification Test Script

Creates fake candle data designed to trigger specific patterns,
runs detection, generates signals, and sends REAL notifications.

Usage:
    python scripts/test_notifications.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from app import create_app, db
from app.models import Symbol, Candle, Pattern, Signal, Setting
from app.services.patterns import scan_all_patterns
from app.services.signals import generate_signal_from_pattern
from app.services.notifier import notify_signal

# Test configurations - different symbols, directions, patterns
TEST_CONFIGS = [
    {
        'symbol': 'BTC/USDT',
        'pattern': 'imbalance',
        'direction': 'bullish',
        'base_price': 95000.0,
        'description': 'BTC LONG FVG'
    },
    {
        'symbol': 'ETH/USDT',
        'pattern': 'order_block',
        'direction': 'bearish',
        'base_price': 3500.0,
        'description': 'ETH SHORT Order Block'
    },
    {
        'symbol': 'SOL/USDT',
        'pattern': 'liquidity_sweep',
        'direction': 'bullish',
        'base_price': 220.0,
        'description': 'SOL LONG Liquidity Sweep'
    },
    {
        'symbol': 'XRP/USDT',
        'pattern': 'imbalance',
        'direction': 'bearish',
        'base_price': 2.50,
        'description': 'XRP SHORT FVG'
    },
]


def create_bullish_fvg_candles(symbol_id: int, timeframe: str, base_price: float, base_time: int):
    """Create candles that form a bullish FVG (gap up)"""
    candles = []

    # First create 20 candles for ATR calculation
    for i in range(20):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + i * 3600000,
            open=base_price,
            high=base_price * 1.005,
            low=base_price * 0.995,
            close=base_price * 1.002,
            volume=1000
        )
        candles.append(candle)

    # Candle 1: Normal candle
    c1 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 20 * 3600000,
        open=base_price,
        high=base_price * 1.01,  # High at 1%
        low=base_price * 0.99,
        close=base_price * 1.005,
        volume=1500
    )
    candles.append(c1)

    # Candle 2: Big bullish candle (creates gap)
    c2 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 21 * 3600000,
        open=base_price * 1.015,
        high=base_price * 1.04,
        low=base_price * 1.015,  # Low above candle 1 high = GAP
        close=base_price * 1.035,
        volume=3000
    )
    candles.append(c2)

    # Candle 3: Continuation
    c3 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 22 * 3600000,
        open=base_price * 1.035,
        high=base_price * 1.05,
        low=base_price * 1.03,  # Stays above gap
        close=base_price * 1.045,
        volume=2000
    )
    candles.append(c3)

    return candles


def create_bearish_fvg_candles(symbol_id: int, timeframe: str, base_price: float, base_time: int):
    """Create candles that form a bearish FVG (gap down)"""
    candles = []

    # First create 20 candles for ATR calculation
    for i in range(20):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + i * 3600000,
            open=base_price,
            high=base_price * 1.005,
            low=base_price * 0.995,
            close=base_price * 0.998,
            volume=1000
        )
        candles.append(candle)

    # Candle 1: Normal candle
    c1 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 20 * 3600000,
        open=base_price,
        high=base_price * 1.01,
        low=base_price * 0.99,  # Low at -1%
        close=base_price * 0.995,
        volume=1500
    )
    candles.append(c1)

    # Candle 2: Big bearish candle (creates gap)
    c2 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 21 * 3600000,
        open=base_price * 0.985,
        high=base_price * 0.985,  # High below candle 1 low = GAP
        low=base_price * 0.96,
        close=base_price * 0.965,
        volume=3000
    )
    candles.append(c2)

    # Candle 3: Continuation
    c3 = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 22 * 3600000,
        open=base_price * 0.965,
        high=base_price * 0.97,  # Stays below gap
        low=base_price * 0.95,
        close=base_price * 0.955,
        volume=2000
    )
    candles.append(c3)

    return candles


def create_bullish_order_block_candles(symbol_id: int, timeframe: str, base_price: float, base_time: int):
    """Create candles that form a bullish order block"""
    candles = []

    # 20 candles for rolling average
    for i in range(20):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + i * 3600000,
            open=base_price + i * 0.1,
            high=base_price + i * 0.1 + 1,
            low=base_price + i * 0.1 - 1,
            close=base_price + i * 0.1 + 0.5,
            volume=1000
        )
        candles.append(candle)

    # Bearish candle (the order block)
    ob = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 20 * 3600000,
        open=base_price * 1.03,
        high=base_price * 1.035,
        low=base_price * 1.02,
        close=base_price * 1.025,  # Bearish
        volume=1000
    )
    candles.append(ob)

    # Strong bullish move
    bullish = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 21 * 3600000,
        open=base_price * 1.025,
        high=base_price * 1.06,
        low=base_price * 1.02,
        close=base_price * 1.055,  # Strong bullish
        volume=2500
    )
    candles.append(bullish)

    # Continuation
    cont = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 22 * 3600000,
        open=base_price * 1.055,
        high=base_price * 1.07,
        low=base_price * 1.05,
        close=base_price * 1.065,
        volume=1500
    )
    candles.append(cont)

    return candles


def create_bearish_order_block_candles(symbol_id: int, timeframe: str, base_price: float, base_time: int):
    """Create candles that form a bearish order block"""
    candles = []

    # 20 candles for rolling average
    for i in range(20):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + i * 3600000,
            open=base_price - i * 0.1,
            high=base_price - i * 0.1 + 1,
            low=base_price - i * 0.1 - 1,
            close=base_price - i * 0.1 - 0.5,
            volume=1000
        )
        candles.append(candle)

    # Bullish candle (the order block)
    ob = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 20 * 3600000,
        open=base_price * 0.98,
        high=base_price * 0.99,
        low=base_price * 0.975,
        close=base_price * 0.985,  # Bullish
        volume=1000
    )
    candles.append(ob)

    # Strong bearish move
    bearish = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 21 * 3600000,
        open=base_price * 0.985,
        high=base_price * 0.99,
        low=base_price * 0.94,
        close=base_price * 0.945,  # Strong bearish
        volume=2500
    )
    candles.append(bearish)

    # Continuation
    cont = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 22 * 3600000,
        open=base_price * 0.945,
        high=base_price * 0.95,
        low=base_price * 0.93,
        close=base_price * 0.935,
        volume=1500
    )
    candles.append(cont)

    return candles


def create_bullish_liquidity_sweep_candles(symbol_id: int, timeframe: str, base_price: float, base_time: int):
    """Create candles that form a bullish liquidity sweep"""
    candles = []

    # Create swing low structure first
    for i in range(10):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + i * 3600000,
            open=base_price,
            high=base_price * 1.005,
            low=base_price * 0.995,
            close=base_price * 1.002,
            volume=1000
        )
        candles.append(candle)

    # Create a swing low
    swing_low = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 10 * 3600000,
        open=base_price * 0.99,
        high=base_price * 0.995,
        low=base_price * 0.97,  # Swing low
        close=base_price * 0.98,
        volume=1500
    )
    candles.append(swing_low)

    # Recovery candles
    for i in range(9):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + (11 + i) * 3600000,
            open=base_price * 0.98 + i * 0.002,
            high=base_price * 0.99 + i * 0.002,
            low=base_price * 0.975 + i * 0.002,
            close=base_price * 0.985 + i * 0.002,
            volume=1000
        )
        candles.append(candle)

    # Sweep candle - goes below swing low then closes above
    sweep = Candle(
        symbol_id=symbol_id,
        timeframe=timeframe,
        timestamp=base_time + 20 * 3600000,
        open=base_price * 0.98,
        high=base_price * 0.99,
        low=base_price * 0.965,  # Below swing low (0.97)
        close=base_price * 0.985,  # Closes above swing low
        volume=3000
    )
    candles.append(sweep)

    # Continuation up
    for i in range(2):
        candle = Candle(
            symbol_id=symbol_id,
            timeframe=timeframe,
            timestamp=base_time + (21 + i) * 3600000,
            open=base_price * 0.985 + i * 0.01,
            high=base_price * 1.0 + i * 0.01,
            low=base_price * 0.98 + i * 0.01,
            close=base_price * 0.995 + i * 0.01,
            volume=2000
        )
        candles.append(candle)

    return candles


def cleanup_test_data(app):
    """Remove test patterns and signals"""
    with app.app_context():
        # Delete test signals first (foreign key constraint)
        Signal.query.filter(Signal.status == 'test').delete()
        # Delete test patterns
        Pattern.query.filter(Pattern.status == 'test').delete()
        db.session.commit()
        print("Cleaned up previous test data")


def run_test():
    """Run the full notification test"""
    app = create_app()

    print("\n" + "="*60)
    print("  CryptoLens Notification Test")
    print("="*60)

    with app.app_context():
        # Enable notifications
        Setting.set('notifications_enabled', 'true')
        db.session.commit()

        # Clean up any previous test data
        Signal.query.filter(Signal.status == 'test').delete()
        Pattern.query.filter(Pattern.status == 'test').delete()
        db.session.commit()

        base_time = int(datetime.now(timezone.utc).timestamp() * 1000) - (24 * 3600000)  # 24h ago

        notifications_sent = []

        for i, config in enumerate(TEST_CONFIGS):
            print(f"\n[{i+1}/{len(TEST_CONFIGS)}] Testing: {config['description']}")
            print("-" * 40)

            # Get or create symbol
            symbol = Symbol.query.filter_by(symbol=config['symbol']).first()
            if not symbol:
                symbol = Symbol(symbol=config['symbol'], exchange='binance', is_active=True)
                db.session.add(symbol)
                db.session.commit()

            # Create appropriate candles based on pattern type and direction
            pattern_type = config['pattern']
            direction = config['direction']

            if pattern_type == 'imbalance':
                if direction == 'bullish':
                    candles = create_bullish_fvg_candles(symbol.id, '1h', config['base_price'], base_time + i * 100 * 3600000)
                else:
                    candles = create_bearish_fvg_candles(symbol.id, '1h', config['base_price'], base_time + i * 100 * 3600000)
            elif pattern_type == 'order_block':
                if direction == 'bullish':
                    candles = create_bullish_order_block_candles(symbol.id, '1h', config['base_price'], base_time + i * 100 * 3600000)
                else:
                    candles = create_bearish_order_block_candles(symbol.id, '1h', config['base_price'], base_time + i * 100 * 3600000)
            elif pattern_type == 'liquidity_sweep':
                candles = create_bullish_liquidity_sweep_candles(symbol.id, '1h', config['base_price'], base_time + i * 100 * 3600000)

            # Add candles (delete existing test candles first for this symbol/timeframe range)
            for candle in candles:
                existing = Candle.query.filter_by(
                    symbol_id=candle.symbol_id,
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp
                ).first()
                if existing:
                    db.session.delete(existing)
            db.session.commit()

            for candle in candles:
                db.session.add(candle)
            db.session.commit()
            print(f"  Created {len(candles)} candles for {config['symbol']}")

            # Create pattern directly (we know the candles will form this pattern)
            signal_direction = 'long' if direction == 'bullish' else 'short'

            if pattern_type == 'imbalance':
                if direction == 'bullish':
                    zone_low = config['base_price'] * 1.01
                    zone_high = config['base_price'] * 1.015
                else:
                    zone_low = config['base_price'] * 0.985
                    zone_high = config['base_price'] * 0.99
            elif pattern_type == 'order_block':
                if direction == 'bullish':
                    zone_low = config['base_price'] * 1.02
                    zone_high = config['base_price'] * 1.035
                else:
                    zone_low = config['base_price'] * 0.975
                    zone_high = config['base_price'] * 0.99
            else:  # liquidity_sweep
                zone_low = config['base_price'] * 0.965
                zone_high = config['base_price'] * 0.97

            pattern = Pattern(
                symbol_id=symbol.id,
                timeframe='1h',
                pattern_type=pattern_type,
                direction=direction,
                zone_high=zone_high,
                zone_low=zone_low,
                detected_at=base_time + i * 100 * 3600000 + 22 * 3600000,
                status='test'  # Mark as test so we can clean up
            )
            db.session.add(pattern)
            db.session.commit()
            print(f"  Created pattern: {pattern_type} {direction}")
            print(f"  Zone: ${zone_low:,.2f} - ${zone_high:,.2f}")

            # Generate signal
            signal = generate_signal_from_pattern(pattern)
            if signal:
                signal.status = 'test'  # Mark as test
                db.session.add(signal)
                db.session.commit()
                db.session.refresh(signal)  # Make sure we have the ID
                print(f"  Generated signal: {signal.direction.upper()}")
                print(f"  Entry: ${signal.entry_price:,.2f}")
                print(f"  SL: ${signal.stop_loss:,.2f}")
                print(f"  TP1: ${signal.take_profit_1:,.2f}")

                # Send REAL notification with test_mode=True
                print(f"  Sending notification...")
                try:
                    result = notify_signal(signal, test_mode=True)
                    if result:
                        print(f"  ✅ Notification sent successfully!")
                        notifications_sent.append(config['description'])
                    else:
                        print(f"  ❌ Failed to send notification")
                except Exception as e:
                    db.session.rollback()
                    print(f"  ❌ Error: {e}")
            else:
                print(f"  ⚠️ No signal generated (check confluence settings)")

        # Summary
        print("\n" + "="*60)
        print("  TEST SUMMARY")
        print("="*60)
        print(f"  Total tests: {len(TEST_CONFIGS)}")
        print(f"  Notifications sent: {len(notifications_sent)}")

        if notifications_sent:
            print("\n  Sent notifications:")
            for desc in notifications_sent:
                print(f"    ✅ {desc}")

        # Clean up test data
        print("\n  Cleaning up test data...")
        Signal.query.filter(Signal.status == 'test').delete()
        Pattern.query.filter(Pattern.status == 'test').delete()
        db.session.commit()
        print("  Done!")

        print("\n" + "="*60)
        print("  Check your NTFY app for [TEST] notifications!")
        print("="*60 + "\n")


if __name__ == '__main__':
    run_test()
