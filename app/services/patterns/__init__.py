"""
Pattern Detection Package
"""
from app.services.patterns.base import PatternDetector
from app.services.patterns.imbalance import ImbalanceDetector


def get_detector(pattern_type: str) -> PatternDetector:
    """Get the appropriate pattern detector"""
    detectors = {
        'imbalance': ImbalanceDetector,
    }
    detector_class = detectors.get(pattern_type)
    if detector_class:
        return detector_class()
    return None


def scan_all_patterns() -> dict:
    """
    Scan all active symbols for all pattern types

    Returns:
        Dict with results
    """
    from app.models import Symbol
    from app.config import Config

    symbols = Symbol.query.filter_by(is_active=True).all()
    results = {'patterns_found': 0, 'signals_generated': 0}

    detector = ImbalanceDetector()

    for symbol in symbols:
        for tf in Config.TIMEFRAMES:
            patterns = detector.detect(symbol.symbol, tf)
            results['patterns_found'] += len(patterns)

    return results
