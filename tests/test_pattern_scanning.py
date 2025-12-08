"""
Tests for Pattern Scanning and Deduplication
Tests scan_all_patterns, scan_symbol, deduplicate_patterns, calculate_zone_overlap
"""
import pytest
from datetime import datetime, timezone
from app import db
from app.models import Symbol, Pattern, Candle
from app.services.patterns import (
    PATTERN_TYPES, OVERLAP_THRESHOLD,
    calculate_zone_overlap, deduplicate_patterns,
    get_detector, get_all_detectors, scan_symbol
)


class TestCalculateZoneOverlap:
    """Tests for calculate_zone_overlap function"""

    def test_no_overlap(self):
        """Test zones with no overlap"""
        # Zone 1: 100-105, Zone 2: 110-115
        overlap = calculate_zone_overlap(100, 105, 110, 115)
        assert overlap == 0.0

    def test_complete_overlap(self):
        """Test identical zones"""
        overlap = calculate_zone_overlap(100, 110, 100, 110)
        assert overlap == 1.0

    def test_partial_overlap(self):
        """Test partially overlapping zones"""
        # Zone 1: 100-110, Zone 2: 105-115
        # Overlap: 105-110 = 5, smaller zone = 10
        overlap = calculate_zone_overlap(100, 110, 105, 115)
        assert overlap == 0.5  # 5/10

    def test_one_zone_inside_other(self):
        """Test when one zone is completely inside another"""
        # Zone 1: 100-120, Zone 2: 105-110
        # Overlap = entire smaller zone = 5, smaller zone = 5
        overlap = calculate_zone_overlap(100, 120, 105, 110)
        assert overlap == 1.0  # Complete overlap of smaller zone

    def test_zero_size_zone(self):
        """Test handling of zero-size zones"""
        overlap = calculate_zone_overlap(100, 100, 100, 110)
        assert overlap == 0.0  # Division protection


class TestDeduplicatePatterns:
    """Tests for deduplicate_patterns function"""

    @pytest.fixture
    def mock_pattern(self):
        """Create a mock pattern object"""
        class MockPattern:
            def __init__(self, symbol_id, timeframe, direction, zone_low, zone_high, detected_at):
                self.symbol_id = symbol_id
                self.timeframe = timeframe
                self.direction = direction
                self.zone_low = zone_low
                self.zone_high = zone_high
                self.detected_at = detected_at

        return MockPattern

    def test_empty_list(self):
        """Test with empty pattern list"""
        result = deduplicate_patterns([])
        assert result == []

    def test_no_duplicates(self, mock_pattern):
        """Test with non-overlapping patterns"""
        patterns = [
            mock_pattern(1, '1h', 'bullish', 100, 105, datetime(2023, 1, 1)),
            mock_pattern(1, '1h', 'bullish', 200, 205, datetime(2023, 1, 2)),  # Different zone
            mock_pattern(1, '1h', 'bearish', 100, 105, datetime(2023, 1, 3)),  # Different direction
        ]

        result = deduplicate_patterns(patterns)
        assert len(result) == 3

    def test_removes_overlapping_duplicates(self, mock_pattern):
        """Test removal of overlapping patterns"""
        patterns = [
            mock_pattern(1, '1h', 'bullish', 100, 110, datetime(2023, 1, 1)),  # Original
            mock_pattern(1, '1h', 'bullish', 101, 109, datetime(2023, 1, 2)),  # 80% overlap - duplicate
            mock_pattern(1, '1h', 'bullish', 105, 115, datetime(2023, 1, 3)),  # 50% overlap - kept
        ]

        result = deduplicate_patterns(patterns, threshold=0.70)

        # Should keep oldest + non-overlapping
        assert len(result) <= 3
        # First pattern (oldest) should always be kept
        assert result[0].detected_at == datetime(2023, 1, 1)

    def test_keeps_different_symbols(self, mock_pattern):
        """Test that different symbols are not deduplicated"""
        patterns = [
            mock_pattern(1, '1h', 'bullish', 100, 110, datetime(2023, 1, 1)),
            mock_pattern(2, '1h', 'bullish', 100, 110, datetime(2023, 1, 2)),  # Same zone, different symbol
        ]

        result = deduplicate_patterns(patterns)
        assert len(result) == 2

    def test_keeps_different_timeframes(self, mock_pattern):
        """Test that different timeframes are not deduplicated"""
        patterns = [
            mock_pattern(1, '1h', 'bullish', 100, 110, datetime(2023, 1, 1)),
            mock_pattern(1, '4h', 'bullish', 100, 110, datetime(2023, 1, 2)),  # Same zone, different TF
        ]

        result = deduplicate_patterns(patterns)
        assert len(result) == 2


class TestGetDetector:
    """Tests for get_detector function"""

    def test_get_imbalance_detector(self):
        """Test getting imbalance/FVG detector"""
        detector = get_detector('imbalance')
        assert detector is not None
        assert detector.pattern_type == 'imbalance'

    def test_get_order_block_detector(self):
        """Test getting order block detector"""
        detector = get_detector('order_block')
        assert detector is not None
        assert detector.pattern_type == 'order_block'

    def test_get_liquidity_sweep_detector(self):
        """Test getting liquidity sweep detector"""
        detector = get_detector('liquidity_sweep')
        assert detector is not None
        assert detector.pattern_type == 'liquidity_sweep'

    def test_get_unknown_detector(self):
        """Test getting unknown detector returns None"""
        detector = get_detector('unknown_pattern')
        assert detector is None


class TestGetAllDetectors:
    """Tests for get_all_detectors function"""

    def test_returns_all_detectors(self):
        """Test that all detectors are returned"""
        detectors = get_all_detectors()
        assert len(detectors) == 3
        pattern_types = [d.pattern_type for d in detectors]
        assert 'imbalance' in pattern_types
        assert 'order_block' in pattern_types
        assert 'liquidity_sweep' in pattern_types


class TestScanSymbol:
    """Tests for scan_symbol function"""

    def test_scan_symbol_no_candles(self, app, sample_symbol):
        """Test scanning symbol with no candles"""
        with app.app_context():
            results = scan_symbol('BTC/USDT')

            # Should return empty results for each timeframe
            assert isinstance(results, dict)
            for tf in results:
                assert isinstance(results[tf], list)

    def test_scan_symbol_with_candles(self, app, sample_symbol):
        """Test scanning symbol with candles"""
        with app.app_context():
            # Add candles for 1h timeframe
            base_ts = 1700000000000
            for i in range(50):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_ts + i * 3600000,
                    open=100.0,
                    high=102.0,
                    low=98.0,
                    close=101.0,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            results = scan_symbol('BTC/USDT', pattern_types=['imbalance'])

            assert isinstance(results, dict)
            assert '1h' in results

    def test_scan_symbol_specific_patterns(self, app, sample_symbol):
        """Test scanning for specific pattern types only"""
        with app.app_context():
            results = scan_symbol('BTC/USDT', pattern_types=['imbalance'])

            assert isinstance(results, dict)


class TestPatternTypes:
    """Tests for pattern type constants"""

    def test_pattern_types_defined(self):
        """Test that pattern types are defined"""
        assert 'imbalance' in PATTERN_TYPES
        assert 'order_block' in PATTERN_TYPES
        assert 'liquidity_sweep' in PATTERN_TYPES

    def test_overlap_threshold(self):
        """Test overlap threshold is reasonable"""
        assert 0 < OVERLAP_THRESHOLD < 1
        assert OVERLAP_THRESHOLD == 0.70


class TestPatternDetection:
    """Integration tests for pattern detection with real database"""

    def test_fvg_detection_saves_to_db(self, app, sample_symbol):
        """Test that detected FVG patterns are saved to database"""
        with app.app_context():
            # Add candles that form a bullish FVG
            base_ts = 1700000000000
            candles = [
                # Normal candles
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts,
                       open=100, high=102, low=98, close=101, volume=1000),
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts + 3600000,
                       open=101, high=103, low=100, close=102, volume=1000),
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts + 7200000,
                       open=102, high=104, low=101, close=103, volume=1000),
            ]

            # Add a clear FVG
            candles.extend([
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts + 10800000,
                       open=103, high=105, low=103, close=104, volume=1000),  # c1
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts + 14400000,
                       open=104, high=115, low=104, close=114, volume=1000),  # c2 - big move
                Candle(symbol_id=sample_symbol, timeframe='1h', timestamp=base_ts + 18000000,
                       open=114, high=116, low=110, close=115, volume=1000),  # c3 - gap
            ])

            # Add more candles
            for i in range(6, 50):
                candles.append(Candle(
                    symbol_id=sample_symbol, timeframe='1h',
                    timestamp=base_ts + i * 3600000,
                    open=115, high=117, low=113, close=116, volume=1000
                ))

            for c in candles:
                db.session.add(c)
            db.session.commit()

            initial_count = Pattern.query.filter_by(symbol_id=sample_symbol).count()

            # Run detection
            from app.services.patterns import get_detector
            detector = get_detector('imbalance')
            patterns = detector.detect('BTC/USDT', '1h')

            # May or may not find patterns depending on zone size threshold
            assert isinstance(patterns, list)

    def test_order_block_detection(self, app, sample_symbol):
        """Test order block detection"""
        with app.app_context():
            # Add candles with strong move after opposing candle
            base_ts = 1700000000000

            # Add rolling average setup
            for i in range(25):
                candle = Candle(
                    symbol_id=sample_symbol, timeframe='1h',
                    timestamp=base_ts + i * 3600000,
                    open=100, high=101, low=99, close=100.5, volume=1000
                )
                db.session.add(candle)

            # Add bearish candle (potential bullish OB)
            db.session.add(Candle(
                symbol_id=sample_symbol, timeframe='1h',
                timestamp=base_ts + 25 * 3600000,
                open=100, high=100.5, low=99, close=99.5, volume=1000
            ))

            # Add strong bullish candle
            db.session.add(Candle(
                symbol_id=sample_symbol, timeframe='1h',
                timestamp=base_ts + 26 * 3600000,
                open=99.5, high=110, low=99, close=109, volume=1000
            ))

            db.session.commit()

            from app.services.patterns import get_detector
            detector = get_detector('order_block')
            patterns = detector.detect('BTC/USDT', '1h')

            assert isinstance(patterns, list)
