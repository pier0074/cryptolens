"""
Pattern Detection Package
"""
from app.services.patterns.base import PatternDetector
from app.services.patterns.imbalance import ImbalanceDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector

# All available pattern types
PATTERN_TYPES = ['imbalance', 'order_block', 'liquidity_sweep']


def get_detector(pattern_type: str) -> PatternDetector:
    """Get the appropriate pattern detector"""
    detectors = {
        'imbalance': ImbalanceDetector,
        'order_block': OrderBlockDetector,
        'liquidity_sweep': LiquiditySweepDetector,
    }
    detector_class = detectors.get(pattern_type)
    if detector_class:
        return detector_class()
    return None


def get_all_detectors() -> list:
    """Get all pattern detectors"""
    return [
        ImbalanceDetector(),
        OrderBlockDetector(),
        LiquiditySweepDetector(),
    ]


def scan_all_patterns(pattern_types: list = None) -> dict:
    """
    Scan all active symbols for patterns

    Args:
        pattern_types: List of pattern types to scan (default: all)

    Returns:
        Dict with results
    """
    from app.models import Symbol
    from app.config import Config

    symbols = Symbol.query.filter_by(is_active=True).all()

    if pattern_types is None:
        pattern_types = PATTERN_TYPES

    results = {
        'patterns_found': 0,
        'by_type': {},
        'by_symbol': {}
    }

    for pattern_type in pattern_types:
        detector = get_detector(pattern_type)
        if not detector:
            continue

        results['by_type'][pattern_type] = 0

        for symbol in symbols:
            if symbol.symbol not in results['by_symbol']:
                results['by_symbol'][symbol.symbol] = 0

            for tf in Config.TIMEFRAMES:
                try:
                    patterns = detector.detect(symbol.symbol, tf)
                    count = len(patterns)
                    results['patterns_found'] += count
                    results['by_type'][pattern_type] += count
                    results['by_symbol'][symbol.symbol] += count
                except Exception as e:
                    print(f"Error scanning {symbol.symbol} {tf} for {pattern_type}: {e}")

    return results


def scan_symbol(symbol: str, pattern_types: list = None) -> dict:
    """
    Scan a single symbol for all pattern types

    Returns:
        Dict with patterns by timeframe
    """
    from app.config import Config

    if pattern_types is None:
        pattern_types = PATTERN_TYPES

    results = {}

    for tf in Config.TIMEFRAMES:
        results[tf] = []

        for pattern_type in pattern_types:
            detector = get_detector(pattern_type)
            if detector:
                try:
                    patterns = detector.detect(symbol, tf)
                    results[tf].extend(patterns)
                except Exception:
                    pass

    return results
