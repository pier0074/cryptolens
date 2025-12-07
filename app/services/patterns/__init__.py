"""
Pattern Detection Package
"""
import logging
from app.services.patterns.base import PatternDetector
from app.services.patterns.imbalance import ImbalanceDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector

logger = logging.getLogger(__name__)

# All available pattern types
PATTERN_TYPES = ['imbalance', 'order_block', 'liquidity_sweep']

# Overlap threshold for deduplication (70% = patterns must differ by at least 30%)
OVERLAP_THRESHOLD = 0.70


def calculate_zone_overlap(zone1_low, zone1_high, zone2_low, zone2_high) -> float:
    """
    Calculate the overlap percentage between two zones.
    Returns value between 0 (no overlap) and 1 (complete overlap).
    """
    # Find the overlap range
    overlap_low = max(zone1_low, zone2_low)
    overlap_high = min(zone1_high, zone2_high)

    if overlap_high <= overlap_low:
        return 0.0  # No overlap

    overlap_size = overlap_high - overlap_low
    zone1_size = zone1_high - zone1_low
    zone2_size = zone2_high - zone2_low

    if zone1_size == 0 or zone2_size == 0:
        return 0.0

    # Return the overlap as percentage of the smaller zone
    smaller_zone = min(zone1_size, zone2_size)
    return overlap_size / smaller_zone


def deduplicate_patterns(patterns: list, threshold: float = OVERLAP_THRESHOLD) -> list:
    """
    Remove duplicate/overlapping patterns from a list.
    Keeps the pattern detected first (oldest).

    Args:
        patterns: List of Pattern objects
        threshold: Overlap threshold (0-1), patterns with higher overlap are considered duplicates

    Returns:
        Deduplicated list of patterns
    """
    if not patterns:
        return []

    # Sort by detected_at (oldest first) to keep oldest pattern
    sorted_patterns = sorted(patterns, key=lambda p: p.detected_at)

    unique = []
    for pattern in sorted_patterns:
        is_duplicate = False

        for existing in unique:
            # Only compare patterns of same symbol, timeframe, and direction
            if (existing.symbol_id == pattern.symbol_id and
                existing.timeframe == pattern.timeframe and
                existing.direction == pattern.direction):

                overlap = calculate_zone_overlap(
                    existing.zone_low, existing.zone_high,
                    pattern.zone_low, pattern.zone_high
                )

                if overlap >= threshold:
                    is_duplicate = True
                    break

        if not is_duplicate:
            unique.append(pattern)

    return unique


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
    Scan all active symbols for patterns.

    Optimized to load DataFrame once per symbol/timeframe and pass to all detectors,
    avoiding redundant database queries.

    Args:
        pattern_types: List of pattern types to scan (default: all)

    Returns:
        Dict with results
    """
    from app.models import Symbol
    from app.config import Config
    from app.services.aggregator import get_candles_as_dataframe

    symbols = Symbol.query.filter_by(is_active=True).all()

    if pattern_types is None:
        pattern_types = PATTERN_TYPES

    results = {
        'patterns_found': 0,
        'by_type': {},
        'by_symbol': {}
    }

    # Initialize counters
    for pattern_type in pattern_types:
        results['by_type'][pattern_type] = 0

    # Get all detectors upfront
    detectors = [(pt, get_detector(pt)) for pt in pattern_types]
    detectors = [(pt, d) for pt, d in detectors if d is not None]

    for symbol in symbols:
        if symbol.symbol not in results['by_symbol']:
            results['by_symbol'][symbol.symbol] = 0

        for tf in Config.TIMEFRAMES:
            # Load DataFrame once per symbol/timeframe
            try:
                df = get_candles_as_dataframe(symbol.symbol, tf, limit=200)
            except Exception as e:
                logger.warning(f"Error loading candles for {symbol.symbol} {tf}: {e}")
                continue

            # Pass to all detectors
            for pattern_type, detector in detectors:
                try:
                    patterns = detector.detect(symbol.symbol, tf, df=df)
                    count = len(patterns)
                    results['patterns_found'] += count
                    results['by_type'][pattern_type] += count
                    results['by_symbol'][symbol.symbol] += count
                except Exception as e:
                    logger.warning(f"Error scanning {symbol.symbol} {tf} for {pattern_type}: {e}")

    return results


def scan_symbol(symbol: str, pattern_types: list = None) -> dict:
    """
    Scan a single symbol for all pattern types.

    Optimized to load DataFrame once per timeframe and pass to all detectors.

    Returns:
        Dict with patterns by timeframe
    """
    from app.config import Config
    from app.services.aggregator import get_candles_as_dataframe

    if pattern_types is None:
        pattern_types = PATTERN_TYPES

    results = {}

    # Get all detectors upfront
    detectors = [(pt, get_detector(pt)) for pt in pattern_types]
    detectors = [(pt, d) for pt, d in detectors if d is not None]

    for tf in Config.TIMEFRAMES:
        results[tf] = []

        # Load DataFrame once per timeframe
        try:
            df = get_candles_as_dataframe(symbol, tf, limit=200)
        except Exception:
            continue

        # Pass to all detectors
        for pattern_type, detector in detectors:
            try:
                patterns = detector.detect(symbol, tf, df=df)
                results[tf].extend(patterns)
            except Exception:
                pass

    return results
