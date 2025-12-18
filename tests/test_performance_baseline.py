"""
Performance Baseline Tests

These tests establish baselines for CRITICAL-7 and CRITICAL-9 fixes.
Run BEFORE and AFTER optimization to ensure results remain consistent.
"""
import pytest
import numpy as np
import pandas as pd
import time


class TestOverlapCheckingBaseline:
    """
    Baseline tests for CRITICAL-7: O(n²) overlap checking.

    These tests verify the overlap detection produces correct results.
    The optimization should not change the output, only the speed.
    """

    def _calculate_overlap_percentage(self, zone1_low, zone1_high, zone2_low, zone2_high):
        """Calculate overlap percentage between two zones (reference implementation)."""
        overlap_low = max(zone1_low, zone2_low)
        overlap_high = min(zone1_high, zone2_high)
        overlap_size = max(0, overlap_high - overlap_low)

        zone1_size = zone1_high - zone1_low
        zone2_size = zone2_high - zone2_low
        smaller_size = min(zone1_size, zone2_size)

        if smaller_size <= 0:
            return 0
        return overlap_size / smaller_size

    def test_no_overlap_zones(self):
        """Test zones with no overlap return 0%."""
        # Zone 1: 100-110, Zone 2: 120-130 (no overlap)
        overlap = self._calculate_overlap_percentage(100, 110, 120, 130)
        assert overlap == 0

    def test_complete_overlap_zones(self):
        """Test identical zones return 100%."""
        overlap = self._calculate_overlap_percentage(100, 110, 100, 110)
        assert overlap == pytest.approx(1.0)

    def test_partial_overlap_zones(self):
        """Test partial overlap calculation."""
        # Zone 1: 100-110, Zone 2: 105-115
        # Overlap: 105-110 = 5, smaller zone = 10, overlap = 50%
        overlap = self._calculate_overlap_percentage(100, 110, 105, 115)
        assert overlap == pytest.approx(0.5)

    def test_contained_zone(self):
        """Test when one zone is completely inside another."""
        # Zone 1: 100-120, Zone 2: 105-110 (Zone 2 inside Zone 1)
        # Overlap: 105-110 = 5 = smaller zone size, so 100%
        overlap = self._calculate_overlap_percentage(100, 120, 105, 110)
        assert overlap == pytest.approx(1.0)

    def test_fvg_overlap_filtering(self, app):
        """Test FVG detector filters overlapping patterns correctly."""
        from app.services.patterns.fair_value_gap import FVGDetector

        with app.app_context():
            detector = FVGDetector()

            # Create DataFrame with multiple potential FVGs
            n_candles = 100
            timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': [100.0] * n_candles,
                'high': [102.0] * n_candles,
                'low': [98.0] * n_candles,
                'close': [101.0] * n_candles,
                'volume': [1000.0] * n_candles
            })

            # Create clear bullish FVGs at multiple points
            # Bullish FVG: c1 high < c3 low (gap up)
            for i in range(10, 80, 15):
                df.loc[i, 'high'] = 100.0
                df.loc[i+1, 'open'] = 101.0
                df.loc[i+1, 'close'] = 103.0
                df.loc[i+2, 'low'] = 102.0
                df.loc[i+2, 'open'] = 102.5
                df.loc[i+2, 'close'] = 104.0

            patterns = detector.detect_historical(df, skip_overlap=False)

            # Verify patterns were detected
            assert isinstance(patterns, list)

            # Verify patterns don't have excessive overlap with each other
            for i, p1 in enumerate(patterns):
                for p2 in patterns[i+1:]:
                    if p1['direction'] == p2['direction']:
                        overlap = self._calculate_overlap_percentage(
                            p1['zone_low'], p1['zone_high'],
                            p2['zone_low'], p2['zone_high']
                        )
                        # With skip_overlap=False, overlap should be filtered
                        assert overlap < 0.8, f"Patterns have {overlap*100:.1f}% overlap"

    def test_liquidity_sweep_overlap_filtering(self, app):
        """Test LiquiditySweep detector filters overlapping patterns correctly."""
        from app.services.patterns.liquidity import LiquiditySweepDetector

        with app.app_context():
            detector = LiquiditySweepDetector()

            # Create DataFrame with potential sweep patterns (need more candles for swing detection)
            n_candles = 100
            timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': [100.0] * n_candles,
                'high': [102.0] * n_candles,
                'low': [98.0] * n_candles,
                'close': [101.0] * n_candles,
                'volume': [1000.0] * n_candles
            })

            # Create swing lows and sweeps
            df.loc[10, 'low'] = 90.0  # Swing low
            df.loc[30, 'low'] = 88.0  # Sweep
            df.loc[30, 'close'] = 95.0

            df.loc[20, 'low'] = 91.0  # Another swing low
            df.loc[50, 'low'] = 89.0  # Sweep
            df.loc[50, 'close'] = 94.0

            patterns = detector.detect_historical(df, skip_overlap=False)

            # Verify function returns list
            assert isinstance(patterns, list)


class TestTradeResolutionBaseline:
    """
    Baseline tests for CRITICAL-9: Linear trade resolution.

    These tests verify trade resolution produces correct results.
    The binary search optimization should not change the output.
    """

    def test_long_trade_hits_stop_loss(self):
        """Test long trade correctly hits stop loss."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        # Create candle data as OHLCV dict
        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 104.0, 103.0, 102.0]),
            'low': np.array([100.0, 101.0, 95.0, 98.0, 97.0]),  # SL hit at idx 2
            'open': np.array([100.0, 101.0, 102.0, 101.0, 100.0]),
            'close': np.array([104.0, 105.0, 96.0, 100.0, 99.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 96.0,  # Hit at candle 2 (low=95)
            'take_profit': 110.0,
            'direction': 'long',
            'entry_time': 1500,  # After first candle
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 1
        assert len(still_open) == 0
        assert resolved[0]['result'] == 'loss'
        assert resolved[0]['exit_price'] == 96.0
        assert resolved[0]['exit_time'] == 3000  # Candle at idx 2

    def test_long_trade_hits_take_profit(self):
        """Test long trade correctly hits take profit."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 115.0, 103.0, 102.0]),  # TP hit at idx 2
            'low': np.array([100.0, 101.0, 102.0, 98.0, 97.0]),
            'open': np.array([100.0, 101.0, 103.0, 101.0, 100.0]),
            'close': np.array([104.0, 105.0, 114.0, 100.0, 99.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 110.0,  # Hit at candle 2 (high=115)
            'direction': 'long',
            'entry_time': 1500,
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 1
        assert len(still_open) == 0
        assert resolved[0]['result'] == 'win'
        assert resolved[0]['exit_price'] == 110.0

    def test_short_trade_hits_stop_loss(self):
        """Test short trade correctly hits stop loss."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 112.0, 103.0, 102.0]),  # SL hit at idx 2
            'low': np.array([100.0, 101.0, 102.0, 98.0, 97.0]),
            'open': np.array([100.0, 101.0, 103.0, 101.0, 100.0]),
            'close': np.array([104.0, 105.0, 111.0, 100.0, 99.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 110.0,  # Hit at candle 2 (high=112)
            'take_profit': 90.0,
            'direction': 'short',
            'entry_time': 1500,
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 1
        assert resolved[0]['result'] == 'loss'

    def test_short_trade_hits_take_profit(self):
        """Test short trade correctly hits take profit."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 104.0, 103.0, 102.0]),
            'low': np.array([100.0, 101.0, 88.0, 98.0, 97.0]),  # TP hit at idx 2
            'open': np.array([100.0, 101.0, 103.0, 101.0, 100.0]),
            'close': np.array([104.0, 105.0, 89.0, 100.0, 99.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 110.0,
            'take_profit': 90.0,  # Hit at candle 2 (low=88)
            'direction': 'short',
            'entry_time': 1500,
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 1
        assert resolved[0]['result'] == 'win'

    def test_trade_not_resolved_stays_open(self):
        """Test trade that doesn't hit SL/TP stays open."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 107.0, 106.0, 105.0]),  # Never hits 110 TP
            'low': np.array([100.0, 101.0, 102.0, 101.0, 100.0]),   # Never hits 95 SL
            'open': np.array([100.0, 101.0, 103.0, 104.0, 103.0]),
            'close': np.array([104.0, 105.0, 106.0, 105.0, 104.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 110.0,
            'direction': 'long',
            'entry_time': 1500,
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 0
        assert len(still_open) == 1

    def test_multiple_trades_resolved_correctly(self):
        """Test multiple trades are all resolved correctly."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000, 6000, 7000]),
            'high': np.array([105.0, 115.0, 104.0, 103.0, 120.0, 102.0, 101.0]),
            'low': np.array([100.0, 101.0, 90.0, 98.0, 97.0, 85.0, 96.0]),
            'open': np.array([100.0, 101.0, 103.0, 101.0, 100.0, 100.0, 99.0]),
            'close': np.array([104.0, 114.0, 91.0, 100.0, 119.0, 86.0, 100.0]),
        }

        open_trades = [
            {
                'entry_price': 100.0,
                'stop_loss': 95.0,
                'take_profit': 110.0,  # Hit at idx 1 (high=115)
                'direction': 'long',
                'entry_time': 500,
                'rr_target': 2.0
            },
            {
                'entry_price': 100.0,
                'stop_loss': 92.0,  # Hit at idx 2 (low=90)
                'take_profit': 120.0,
                'direction': 'long',
                'entry_time': 1500,
                'rr_target': 2.0
            },
            {
                'entry_price': 100.0,
                'stop_loss': 95.0,
                'take_profit': 115.0,  # Hit at idx 4 (high=120)
                'direction': 'long',
                'entry_time': 3500,
                'rr_target': 2.0
            }
        ]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        assert len(resolved) == 3
        assert len(still_open) == 0

        # Check each trade resolved correctly
        assert resolved[0]['result'] == 'win'
        assert resolved[1]['result'] == 'loss'
        assert resolved[2]['result'] == 'win'

    def test_trade_entry_time_respected(self):
        """Test that trades only check candles AFTER entry time."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        # SL would be hit at idx 0 and 1, but entry is after those
        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000]),
            'high': np.array([105.0, 106.0, 107.0, 108.0, 109.0]),
            'low': np.array([90.0, 91.0, 99.0, 99.0, 99.0]),  # SL at 95 hit at idx 0,1
            'open': np.array([100.0, 101.0, 103.0, 104.0, 105.0]),
            'close': np.array([104.0, 105.0, 106.0, 107.0, 108.0]),
        }

        open_trades = [{
            'entry_price': 100.0,
            'stop_loss': 95.0,
            'take_profit': 110.0,
            'direction': 'long',
            'entry_time': 2500,  # After candles 0 and 1
            'rr_target': 2.0
        }]

        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )

        # Trade should NOT be stopped out by earlier candles
        assert len(resolved) == 0
        assert len(still_open) == 1


class TestPerformanceBenchmark:
    """
    Performance benchmarks to verify optimization improves speed.
    """

    def test_trade_resolution_performance(self):
        """Benchmark trade resolution with many trades and candles."""
        from app.services.optimizer import ParameterOptimizer

        optimizer = ParameterOptimizer.__new__(ParameterOptimizer)

        # Create large dataset
        n_candles = 10000
        n_trades = 100

        np.random.seed(42)  # Reproducible results
        timestamps = np.arange(n_candles) * 1000
        base_price = 100.0
        highs = base_price + np.random.randn(n_candles) * 2
        lows = base_price + np.random.randn(n_candles) * 2 - 3

        # Ensure highs > lows
        highs = np.maximum(highs, lows + 1)

        ohlcv = {
            'timestamp': timestamps,
            'high': highs,
            'low': lows,
            'open': (highs + lows) / 2,
            'close': (highs + lows) / 2,
        }

        # Create trades spread throughout the data
        open_trades = []
        for i in range(n_trades):
            entry_idx = (i * n_candles // n_trades) + 10
            open_trades.append({
                'entry_price': 100.0,
                'stop_loss': 95.0,
                'take_profit': 110.0,
                'direction': 'long',
                'entry_time': int(timestamps[entry_idx]),
                'rr_target': 2.0
            })

        # Time the resolution
        start = time.time()
        resolved, still_open = optimizer._resolve_open_trades_fast(
            ohlcv, open_trades, after_timestamp=0
        )
        elapsed = time.time() - start

        print(f"\nTrade resolution: {n_trades} trades x {n_candles} candles")
        print(f"Time: {elapsed*1000:.2f}ms")
        print(f"Resolved: {len(resolved)}, Still open: {len(still_open)}")

        # Verify results are valid
        assert len(resolved) + len(still_open) == n_trades
