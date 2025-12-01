#!/usr/bin/env python3
"""
Pattern Scanner Script
Scans all symbols for patterns and generates signals
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import Symbol
from app.services.patterns import scan_all_patterns
from app.services.patterns.imbalance import ImbalanceDetector
from app.services.signals import scan_and_generate_signals, check_confluence
from app.config import Config


def main():
    """Scan for patterns and generate signals"""
    app = create_app()

    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()

        print("CryptoLens Pattern Scanner")
        print("=" * 50)
        print(f"Scanning {len(symbols)} symbols across {len(Config.TIMEFRAMES)} timeframes...")
        print()

        detector = ImbalanceDetector()
        total_patterns = 0

        for symbol in symbols:
            patterns_found = []

            for tf in Config.TIMEFRAMES:
                patterns = detector.detect(symbol.symbol, tf)
                if patterns:
                    patterns_found.extend(patterns)

            if patterns_found:
                print(f"\n{symbol.symbol}:")
                for p in patterns_found:
                    direction = "🟢 BULL" if p['direction'] == 'bullish' else "🔴 BEAR"
                    print(f"  {p['timeframe']}: {direction} @ ${p['zone_low']:.2f} - ${p['zone_high']:.2f}")
                total_patterns += len(patterns_found)

            # Check confluence
            confluence = check_confluence(symbol.symbol)
            if confluence['score'] >= 2:
                print(f"  ⚡ Confluence: {confluence['score']}/6 TFs - {confluence['dominant'].upper()}")
                print(f"     Aligned: {', '.join(confluence['aligned_timeframes'])}")

        print("\n" + "=" * 50)
        print(f"Total patterns found: {total_patterns}")

        # Generate signals for high confluence
        print("\nGenerating signals for high confluence...")
        results = scan_and_generate_signals()
        print(f"  Signals generated: {results['signals_generated']}")
        print(f"  Notifications sent: {results['notifications_sent']}")


if __name__ == '__main__':
    main()
