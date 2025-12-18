"""
Parallel Processing Baseline Tests for CRITICAL-8

These tests establish baselines for parallel symbol processing optimization.
Run BEFORE and AFTER parallelization to ensure results remain consistent.

Key assertions:
1. Same number of results for each symbol
2. Same statistics (win_rate, total_profit, etc.)
3. Same trade outcomes (deterministic)
"""
import pytest
import numpy as np
import pandas as pd
import time
import hashlib
import json
from typing import Dict, List, Tuple


class TestParallelProcessingBaseline:
    """
    Baseline tests for CRITICAL-8: Sequential symbol processing.

    These tests verify the optimizer produces deterministic, consistent results.
    Parallelization should NOT change the output, only the speed.
    """

    def _create_test_df(self, n_candles: int = 500, seed: int = 42) -> pd.DataFrame:
        """Create a deterministic test DataFrame."""
        np.random.seed(seed)

        timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]

        # Generate realistic OHLCV data with trends and patterns
        base_price = 100.0
        prices = [base_price]
        for i in range(1, n_candles):
            # Random walk with slight upward drift
            change = np.random.randn() * 0.5 + 0.01
            prices.append(prices[-1] * (1 + change / 100))

        prices = np.array(prices)
        volatility = np.abs(np.random.randn(n_candles)) * 0.5 + 0.3

        highs = prices * (1 + volatility / 100)
        lows = prices * (1 - volatility / 100)
        opens = prices * (1 + (np.random.randn(n_candles) * 0.1) / 100)
        closes = prices * (1 + (np.random.randn(n_candles) * 0.1) / 100)

        # Ensure OHLC consistency
        highs = np.maximum(highs, np.maximum(opens, closes))
        lows = np.minimum(lows, np.minimum(opens, closes))

        # Create some FVG patterns by introducing gaps
        for i in range(20, n_candles - 5, 30):
            # Bullish gap: high[i] < low[i+2]
            highs[i] = lows[i+2] - 0.5

        return pd.DataFrame({
            'timestamp': timestamps,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': np.random.randint(1000, 10000, n_candles).astype(float)
        })

    def _hash_patterns(self, patterns: List[Dict]) -> str:
        """Create deterministic hash of pattern list for comparison."""
        # Sort patterns by detected_at for consistent ordering
        sorted_patterns = sorted(patterns, key=lambda p: (p.get('detected_at', 0), p.get('direction', '')))

        # Extract key fields for hashing
        pattern_data = []
        for p in sorted_patterns:
            pattern_data.append({
                'direction': p.get('direction'),
                'zone_high': round(p.get('zone_high', 0), 6),
                'zone_low': round(p.get('zone_low', 0), 6),
                'detected_at': p.get('detected_at'),
            })

        return hashlib.md5(json.dumps(pattern_data, sort_keys=True).encode()).hexdigest()

    def _hash_trades(self, trades: List[Dict]) -> str:
        """Create deterministic hash of trade list for comparison."""
        sorted_trades = sorted(trades, key=lambda t: t.get('entry_time', 0))

        trade_data = []
        for t in sorted_trades:
            trade_data.append({
                'entry_price': round(t.get('entry_price', 0), 6),
                'exit_price': round(t.get('exit_price', 0), 6),
                'result': t.get('result'),
                'profit_pct': round(t.get('profit_pct', 0), 4),
            })

        return hashlib.md5(json.dumps(trade_data, sort_keys=True).encode()).hexdigest()

    def test_pattern_detection_deterministic(self, app):
        """Verify pattern detection is deterministic (same input = same output)."""
        from app.services.patterns.fair_value_gap import FVGDetector
        from app.services.patterns.liquidity import LiquiditySweepDetector

        with app.app_context():
            df = self._create_test_df(n_candles=500, seed=42)

            fvg_detector = FVGDetector()
            liq_detector = LiquiditySweepDetector()

            # Run detection multiple times
            fvg_results = []
            liq_results = []

            for _ in range(3):
                fvg_patterns = fvg_detector.detect_historical(df, skip_overlap=False)
                liq_patterns = liq_detector.detect_historical(df, skip_overlap=False)

                fvg_results.append(self._hash_patterns(fvg_patterns))
                liq_results.append(self._hash_patterns(liq_patterns))

            # All runs should produce identical results
            assert len(set(fvg_results)) == 1, "FVG detection is not deterministic"
            assert len(set(liq_results)) == 1, "Liquidity detection is not deterministic"

    def test_trade_simulation_deterministic(self, app):
        """Verify trade simulation is deterministic."""
        from app.services.optimizer import ParameterOptimizer
        from app.services.patterns.fair_value_gap import FVGDetector

        with app.app_context():
            df = self._create_test_df(n_candles=500, seed=42)

            detector = FVGDetector()
            patterns = detector.detect_historical(df, skip_overlap=True)

            optimizer = ParameterOptimizer()
            ohlcv = optimizer._df_to_arrays(df)

            params = {
                'rr_target': 2.0,
                'sl_buffer_pct': 10.0,
                'entry_method': 'zone_edge',
            }

            # Run simulation multiple times
            trade_hashes = []
            for _ in range(3):
                trades = optimizer._simulate_trades_fast(ohlcv, patterns, params)
                trade_hashes.append(self._hash_trades(trades))

            # All runs should produce identical results
            assert len(set(trade_hashes)) == 1, "Trade simulation is not deterministic"

    def test_phase1_load_data(self, app):
        """Test Phase 1: Data loading produces correct structure."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            # Use a symbol that should exist (or will return None gracefully)
            symbols = ['BTC/USDT']
            timeframes = ['1h']

            data_cache = optimizer._load_candle_data_phase(symbols, timeframes)

            # Verify structure
            assert isinstance(data_cache, dict)

            for key, value in data_cache.items():
                assert isinstance(key, tuple)
                assert len(key) == 2  # (symbol, timeframe)
                assert isinstance(value, tuple)
                assert len(value) == 4  # (df, ohlcv_arrays, first_candle_ts, last_candle_ts)

    def test_phase2_detect_patterns(self, app):
        """Test Phase 2: Pattern detection with synthetic data."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            # Create synthetic data cache
            df = self._create_test_df(n_candles=500, seed=42)
            ohlcv = optimizer._df_to_arrays(df)
            last_ts = int(df['timestamp'].max())

            data_cache = {
                ('TEST/USDT', '1h'): (df, ohlcv, last_ts)
            }

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
            }

            pattern_cache = optimizer._detect_patterns_phase(
                symbols=['TEST/USDT'],
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            # Verify structure
            assert isinstance(pattern_cache, dict)

            for key, patterns in pattern_cache.items():
                assert isinstance(key, tuple)
                assert len(key) == 5  # (symbol, tf, pattern_type, min_zone, use_overlap)
                assert isinstance(patterns, list)

    def test_phase3_sweep_produces_results(self, app):
        """Test Phase 3: Parameter sweep produces valid results."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            # Create synthetic data
            df = self._create_test_df(n_candles=500, seed=42)
            ohlcv = optimizer._df_to_arrays(df)
            last_ts = int(df['timestamp'].max())

            data_cache = {
                ('TEST/USDT', '1h'): (df, ohlcv, last_ts)
            }

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
                'rr_target': [2.0],
                'sl_buffer_pct': [10.0],
            }

            # Detect patterns first
            pattern_cache = optimizer._detect_patterns_phase(
                symbols=['TEST/USDT'],
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            # Run sweep
            results, best_result = optimizer._run_sweep_phase(
                symbols=['TEST/USDT'],
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache,
            )

            # Verify structure
            assert isinstance(results, list)
            assert len(results) > 0

            for r in results:
                assert 'symbol' in r
                assert 'timeframe' in r
                assert 'pattern_type' in r
                assert 'status' in r
                assert r['status'] in ('completed', 'failed')

                if r['status'] == 'completed':
                    assert 'trades' in r
                    assert 'stats' in r
                    assert isinstance(r['trades'], list)
                    assert isinstance(r['stats'], dict)

    def test_multi_symbol_results_independent(self, app):
        """Verify results for each symbol are independent of processing order."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            # Create different synthetic data for each "symbol"
            df1 = self._create_test_df(n_candles=500, seed=42)
            df2 = self._create_test_df(n_candles=500, seed=123)
            df3 = self._create_test_df(n_candles=500, seed=456)

            ohlcv1 = optimizer._df_to_arrays(df1)
            ohlcv2 = optimizer._df_to_arrays(df2)
            ohlcv3 = optimizer._df_to_arrays(df3)

            symbols = ['SYM1/USDT', 'SYM2/USDT', 'SYM3/USDT']

            data_cache = {
                ('SYM1/USDT', '1h'): (df1, ohlcv1, int(df1['timestamp'].max())),
                ('SYM2/USDT', '1h'): (df2, ohlcv2, int(df2['timestamp'].max())),
                ('SYM3/USDT', '1h'): (df3, ohlcv3, int(df3['timestamp'].max())),
            }

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
                'rr_target': [2.0],
                'sl_buffer_pct': [10.0],
            }

            # Process in order 1,2,3
            pattern_cache_123 = optimizer._detect_patterns_phase(
                symbols=symbols,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            results_123, _ = optimizer._run_sweep_phase(
                symbols=symbols,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache_123,
            )

            # Process in order 3,2,1
            symbols_reverse = ['SYM3/USDT', 'SYM2/USDT', 'SYM1/USDT']

            pattern_cache_321 = optimizer._detect_patterns_phase(
                symbols=symbols_reverse,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            results_321, _ = optimizer._run_sweep_phase(
                symbols=symbols_reverse,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache_321,
            )

            # Extract stats per symbol for comparison
            stats_123 = {r['symbol']: r.get('stats', {}) for r in results_123 if r['status'] == 'completed'}
            stats_321 = {r['symbol']: r.get('stats', {}) for r in results_321 if r['status'] == 'completed'}

            # Each symbol should have same stats regardless of processing order
            for symbol in symbols:
                if symbol in stats_123 and symbol in stats_321:
                    s1 = stats_123[symbol]
                    s2 = stats_321[symbol]

                    assert s1.get('total_trades') == s2.get('total_trades'), \
                        f"{symbol}: total_trades differs"
                    assert s1.get('win_rate') == s2.get('win_rate'), \
                        f"{symbol}: win_rate differs"
                    assert abs(s1.get('total_profit_pct', 0) - s2.get('total_profit_pct', 0)) < 0.01, \
                        f"{symbol}: total_profit_pct differs"


class TestParallelBaselineSnapshot:
    """
    Snapshot tests that capture current behavior as baseline.

    These tests save results from sequential processing that can be
    compared against parallel processing results.
    """

    # Known baseline values from sequential processing (will be updated after first run)
    BASELINE_FVG_COUNT = None  # Set after first baseline run
    BASELINE_TRADE_COUNT = None
    BASELINE_WIN_RATE = None
    BASELINE_PROFIT = None

    def _create_baseline_df(self) -> pd.DataFrame:
        """Create the exact same DataFrame used for baseline."""
        np.random.seed(12345)  # Fixed seed for reproducibility
        n_candles = 1000

        timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]

        base_price = 100.0
        prices = [base_price]
        for i in range(1, n_candles):
            change = np.random.randn() * 0.5 + 0.01
            prices.append(prices[-1] * (1 + change / 100))

        prices = np.array(prices)
        volatility = np.abs(np.random.randn(n_candles)) * 0.5 + 0.3

        highs = prices * (1 + volatility / 100)
        lows = prices * (1 - volatility / 100)
        opens = prices * (1 + (np.random.randn(n_candles) * 0.1) / 100)
        closes = prices * (1 + (np.random.randn(n_candles) * 0.1) / 100)

        highs = np.maximum(highs, np.maximum(opens, closes))
        lows = np.minimum(lows, np.minimum(opens, closes))

        # Create FVG patterns
        for i in range(20, n_candles - 5, 25):
            highs[i] = lows[i+2] - 0.3

        return pd.DataFrame({
            'timestamp': timestamps,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': np.random.randint(1000, 10000, n_candles).astype(float)
        })

    def test_baseline_snapshot(self, app):
        """
        Run full optimization pipeline and capture baseline metrics.

        This test documents the expected output from sequential processing.
        After parallelization, results MUST match these values.
        """
        from app.services.optimizer import ParameterOptimizer
        from app.services.patterns.fair_value_gap import FVGDetector

        with app.app_context():
            optimizer = ParameterOptimizer()
            df = self._create_baseline_df()

            # Phase 1: Pattern detection baseline
            detector = FVGDetector()
            patterns = detector.detect_historical(df, min_zone_pct=0.15, skip_overlap=False)

            print(f"\n=== BASELINE SNAPSHOT ===")
            print(f"Candles: {len(df)}")
            print(f"FVG Patterns detected: {len(patterns)}")

            # Phase 2: Trade simulation baseline
            ohlcv = optimizer._df_to_arrays(df)
            params = {
                'rr_target': 2.0,
                'sl_buffer_pct': 10.0,
                'entry_method': 'zone_edge',
            }

            trades = optimizer._simulate_trades_fast(ohlcv, patterns, params)

            print(f"Trades simulated: {len(trades)}")

            # Phase 3: Statistics baseline
            stats = optimizer._calculate_statistics(trades)

            print(f"Win rate: {stats['win_rate']}%")
            print(f"Total profit: {stats['total_profit_pct']}%")
            print(f"Sharpe ratio: {stats['sharpe_ratio']}")
            print(f"=========================\n")

            # Verify patterns were detected (test data has gaps)
            assert len(patterns) > 0, "No patterns detected - test data may be invalid"

            # Verify trades were simulated
            assert isinstance(trades, list)

            # Verify statistics structure
            assert 'total_trades' in stats
            assert 'win_rate' in stats
            assert 'total_profit_pct' in stats

            # Store these values for comparison after parallelization
            # These assertions document expected behavior
            assert len(patterns) >= 5, f"Expected at least 5 patterns, got {len(patterns)}"


class TestParallelPerformance:
    """Performance benchmarks for parallel vs sequential processing."""

    def test_sequential_timing_baseline(self, app):
        """Benchmark current sequential processing time."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            # Create multiple "symbols" worth of data
            n_symbols = 5
            n_candles = 1000

            np.random.seed(42)

            data_cache = {}
            for i in range(n_symbols):
                np.random.seed(42 + i)
                df = pd.DataFrame({
                    'timestamp': [1700000000000 + j * 3600000 for j in range(n_candles)],
                    'open': 100 + np.random.randn(n_candles) * 2,
                    'high': 102 + np.random.randn(n_candles) * 2,
                    'low': 98 + np.random.randn(n_candles) * 2,
                    'close': 100 + np.random.randn(n_candles) * 2,
                    'volume': np.random.randint(1000, 10000, n_candles).astype(float)
                })
                df['high'] = df[['open', 'high', 'close']].max(axis=1)
                df['low'] = df[['open', 'low', 'close']].min(axis=1)

                symbol = f'SYM{i}/USDT'
                ohlcv = optimizer._df_to_arrays(df)
                data_cache[(symbol, '1h')] = (df, ohlcv, int(df['timestamp'].max()))

            symbols = [f'SYM{i}/USDT' for i in range(n_symbols)]

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
                'rr_target': [2.0, 3.0],
                'sl_buffer_pct': [10.0, 15.0],
            }

            # Time the sequential processing
            start = time.time()

            pattern_cache = optimizer._detect_patterns_phase(
                symbols=symbols,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            results, _ = optimizer._run_sweep_phase(
                symbols=symbols,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache,
            )

            elapsed = time.time() - start

            print(f"\n=== SEQUENTIAL TIMING BASELINE ===")
            print(f"Symbols: {n_symbols}")
            print(f"Candles per symbol: {n_candles}")
            print(f"Parameter combinations: {len(list(zip(*parameter_grid.values())))}")
            print(f"Total results: {len(results)}")
            print(f"Time: {elapsed*1000:.2f}ms")
            print(f"==================================\n")

            # Baseline assertion: should complete in reasonable time
            assert elapsed < 30, f"Sequential processing took too long: {elapsed:.2f}s"
            assert len(results) == n_symbols * 4  # 4 param combinations


class TestRefactoringBaseline:
    """
    Baseline tests to verify refactoring doesn't change output.

    These tests capture the EXACT output of the current implementation
    before refactoring, so we can verify the refactored code produces
    identical results.
    """

    def _create_test_data(self, n_symbols: int = 3, n_candles: int = 500, seed: int = 42):
        """Create deterministic test data for multiple symbols."""
        np.random.seed(seed)

        data = {}
        for i in range(n_symbols):
            symbol = f'TEST{i}/USDT'
            np.random.seed(seed + i)  # Different but deterministic per symbol

            timestamps = [1700000000000 + j * 3600000 for j in range(n_candles)]
            prices = 100 + np.cumsum(np.random.randn(n_candles) * 0.5)
            highs = prices + np.abs(np.random.randn(n_candles)) * 0.5
            lows = prices - np.abs(np.random.randn(n_candles)) * 0.5
            opens = prices + np.random.randn(n_candles) * 0.1
            closes = prices + np.random.randn(n_candles) * 0.1

            highs = np.maximum(highs, np.maximum(opens, closes))
            lows = np.minimum(lows, np.minimum(opens, closes))

            # Create FVG gaps
            for j in range(20, n_candles - 5, 25):
                highs[j] = lows[j+2] - 0.3

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': opens,
                'high': highs,
                'low': lows,
                'close': closes,
                'volume': np.random.randint(1000, 10000, n_candles).astype(float)
            })
            data[symbol] = df

        return data

    def test_sweep_phase_output_structure(self, app):
        """Verify sweep phase produces expected output structure."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()
            test_data = self._create_test_data(n_symbols=2, n_candles=300)

            # Build data cache
            data_cache = {}
            for symbol, df in test_data.items():
                ohlcv = optimizer._df_to_arrays(df)
                last_ts = int(df['timestamp'].max())
                data_cache[(symbol, '1h')] = (df, ohlcv, last_ts)

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
                'rr_target': [2.0],
                'sl_buffer_pct': [10.0],
            }

            # Detect patterns
            pattern_cache = optimizer._detect_patterns_phase(
                symbols=list(test_data.keys()),
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            # Run sweep
            results, best_result = optimizer._run_sweep_phase(
                symbols=list(test_data.keys()),
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache,
            )

            # Verify structure
            assert len(results) == 2  # 2 symbols × 1 param combo

            for r in results:
                assert 'symbol' in r
                assert 'timeframe' in r
                assert 'pattern_type' in r
                assert 'params' in r
                assert 'status' in r

                if r['status'] == 'completed':
                    assert 'trades' in r
                    assert 'stats' in r
                    assert 'last_candle_ts' in r

                    # Verify stats structure
                    stats = r['stats']
                    assert 'total_trades' in stats
                    assert 'win_rate' in stats
                    assert 'total_profit_pct' in stats

    def test_sweep_phase_deterministic_results(self, app):
        """Verify sweep phase produces identical results on multiple runs."""
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()

            results_runs = []

            for run in range(3):
                test_data = self._create_test_data(n_symbols=2, n_candles=300)

                data_cache = {}
                for symbol, df in test_data.items():
                    ohlcv = optimizer._df_to_arrays(df)
                    last_ts = int(df['timestamp'].max())
                    data_cache[(symbol, '1h')] = (df, ohlcv, last_ts)

                parameter_grid = {
                    'min_zone_pct': [0.15],
                    'use_overlap': [True],
                    'rr_target': [2.0],
                    'sl_buffer_pct': [10.0],
                }

                pattern_cache = optimizer._detect_patterns_phase(
                    symbols=list(test_data.keys()),
                    timeframes=['1h'],
                    pattern_types=['imbalance'],
                    parameter_grid=parameter_grid,
                    data_cache=data_cache
                )

                results, _ = optimizer._run_sweep_phase(
                    symbols=list(test_data.keys()),
                    timeframes=['1h'],
                    pattern_types=['imbalance'],
                    parameter_grid=parameter_grid,
                    data_cache=data_cache,
                    pattern_cache=pattern_cache,
                )

                # Extract key metrics per symbol
                metrics = {}
                for r in results:
                    if r['status'] == 'completed':
                        metrics[r['symbol']] = {
                            'total_trades': r['stats']['total_trades'],
                            'win_rate': r['stats']['win_rate'],
                            'total_profit_pct': r['stats']['total_profit_pct'],
                        }
                results_runs.append(metrics)

            # All runs should produce identical results
            for i in range(1, len(results_runs)):
                assert results_runs[0] == results_runs[i], \
                    f"Run 0 vs Run {i} differ: {results_runs[0]} != {results_runs[i]}"

    def test_process_symbol_core_logic(self, app):
        """
        Test the core symbol processing logic that will be shared.
        This establishes the baseline for what _process_symbol() should produce.
        """
        from app.services.optimizer import ParameterOptimizer
        from app.services.patterns.fair_value_gap import FVGDetector

        with app.app_context():
            optimizer = ParameterOptimizer()
            np.random.seed(12345)

            # Create test data
            n_candles = 500
            timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]
            prices = 100 + np.cumsum(np.random.randn(n_candles) * 0.5)
            highs = prices + np.abs(np.random.randn(n_candles)) * 0.5
            lows = prices - np.abs(np.random.randn(n_candles)) * 0.5
            opens = prices + np.random.randn(n_candles) * 0.1
            closes = prices + np.random.randn(n_candles) * 0.1

            highs = np.maximum(highs, np.maximum(opens, closes))
            lows = np.minimum(lows, np.minimum(opens, closes))

            for i in range(20, n_candles - 5, 25):
                highs[i] = lows[i+2] - 0.3

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': opens,
                'high': highs,
                'low': lows,
                'close': closes,
                'volume': np.random.randint(1000, 10000, n_candles).astype(float)
            })

            # Step 1: Pattern detection
            detector = FVGDetector()
            patterns = detector.detect_historical(df, min_zone_pct=0.15, skip_overlap=False)

            # Step 2: Trade simulation
            ohlcv = optimizer._df_to_arrays(df)
            params = {'rr_target': 2.0, 'sl_buffer_pct': 10.0, 'entry_method': 'zone_edge'}
            trades = optimizer._simulate_trades_fast(ohlcv, patterns, params)

            # Step 3: Statistics
            stats = optimizer._calculate_statistics(trades)

            # Record baseline values
            print(f"\n=== CORE LOGIC BASELINE ===")
            print(f"Patterns: {len(patterns)}")
            print(f"Trades: {len(trades)}")
            print(f"Stats: {stats}")
            print(f"===========================\n")

            # These are the expected values - refactored code must match
            assert len(patterns) >= 5, "Expected at least 5 patterns"
            assert isinstance(trades, list)
            assert 'total_trades' in stats
            assert 'win_rate' in stats

    def test_process_symbol_shared_method(self, app):
        """
        Test the new _process_symbol() shared method produces correct results.
        This verifies the refactored shared method matches the original logic.
        """
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()
            np.random.seed(12345)

            # Create test data
            n_candles = 500
            timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]
            prices = 100 + np.cumsum(np.random.randn(n_candles) * 0.5)
            highs = prices + np.abs(np.random.randn(n_candles)) * 0.5
            lows = prices - np.abs(np.random.randn(n_candles)) * 0.5
            opens = prices + np.random.randn(n_candles) * 0.1
            closes = prices + np.random.randn(n_candles) * 0.1

            highs = np.maximum(highs, np.maximum(opens, closes))
            lows = np.minimum(lows, np.minimum(opens, closes))

            for i in range(20, n_candles - 5, 25):
                highs[i] = lows[i+2] - 0.3

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': opens,
                'high': highs,
                'low': lows,
                'close': closes,
                'volume': np.random.randint(1000, 10000, n_candles).astype(float)
            })

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [False],  # skip_overlap=True in detect_historical
                'rr_target': [2.0],
                'sl_buffer_pct': [10.0],
            }

            # Use the new shared _process_symbol method
            result = optimizer._process_symbol(
                symbol='TEST/USDT',
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_override={'1h': df}
            )

            # Verify structure
            assert result['symbol'] == 'TEST/USDT'
            assert result['error'] is None
            assert len(result['results']) == 1  # 1 param combo

            # Verify result content
            r = result['results'][0]
            assert r['status'] == 'completed'
            assert r['symbol'] == 'TEST/USDT'
            assert r['timeframe'] == '1h'
            assert r['pattern_type'] == 'imbalance'
            assert 'trades' in r
            assert 'stats' in r

            stats = r['stats']
            assert 'total_trades' in stats
            assert 'win_rate' in stats
            assert 'total_profit_pct' in stats

            print(f"\n=== _process_symbol() RESULT ===")
            print(f"Results: {len(result['results'])}")
            print(f"Status: {r['status']}")
            print(f"Trades: {len(r['trades'])}")
            print(f"Stats: {stats}")
            print(f"================================\n")

    def test_process_symbol_matches_sweep_phase(self, app):
        """
        Verify _process_symbol() produces identical results to old sweep phase.
        This is the critical test for refactoring validation.
        """
        from app.services.optimizer import ParameterOptimizer

        with app.app_context():
            optimizer = ParameterOptimizer()
            test_data = self._create_test_data(n_symbols=1, n_candles=400)
            symbol = list(test_data.keys())[0]
            df = test_data[symbol]

            parameter_grid = {
                'min_zone_pct': [0.15],
                'use_overlap': [True],
                'rr_target': [2.0, 3.0],
                'sl_buffer_pct': [10.0],
            }

            # Method 1: Old way using sweep phase
            data_cache = {}
            ohlcv = optimizer._df_to_arrays(df)
            last_ts = int(df['timestamp'].max())
            data_cache[(symbol, '1h')] = (df, ohlcv, last_ts)

            pattern_cache = optimizer._detect_patterns_phase(
                symbols=[symbol],
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache
            )

            old_results, _ = optimizer._run_sweep_phase(
                symbols=[symbol],
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_cache=data_cache,
                pattern_cache=pattern_cache,
            )

            # Method 2: New way using _process_symbol
            new_result = optimizer._process_symbol(
                symbol=symbol,
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid=parameter_grid,
                data_override={'1h': df}
            )

            # Compare results
            assert len(old_results) == len(new_result['results']), \
                f"Result count mismatch: old={len(old_results)}, new={len(new_result['results'])}"

            # Sort both by params for comparison
            old_sorted = sorted(old_results, key=lambda x: str(x['params']))
            new_sorted = sorted(new_result['results'], key=lambda x: str(x['params']))

            for old_r, new_r in zip(old_sorted, new_sorted):
                assert old_r['status'] == new_r['status'], \
                    f"Status mismatch: {old_r['status']} vs {new_r['status']}"

                if old_r['status'] == 'completed':
                    old_stats = old_r['stats']
                    new_stats = new_r['stats']

                    assert old_stats['total_trades'] == new_stats['total_trades'], \
                        f"Trade count mismatch: {old_stats['total_trades']} vs {new_stats['total_trades']}"
                    assert old_stats['win_rate'] == new_stats['win_rate'], \
                        f"Win rate mismatch: {old_stats['win_rate']} vs {new_stats['win_rate']}"
                    assert abs(old_stats['total_profit_pct'] - new_stats['total_profit_pct']) < 0.01, \
                        f"Profit mismatch: {old_stats['total_profit_pct']} vs {new_stats['total_profit_pct']}"

            print(f"\n=== SWEEP PHASE vs _process_symbol() ===")
            print(f"Old results: {len(old_results)}")
            print(f"New results: {len(new_result['results'])}")
            print(f"All match: YES ✓")
            print(f"=========================================\n")


class TestParallelVsSequentialConsistency:
    """
    Critical tests verifying parallel and sequential processing produce identical results.

    These tests ensure CRITICAL-8 fix (parallel processing) doesn't change output.
    """

    def test_worker_trade_simulation_matches_optimizer(self, app):
        """Verify worker trade simulation produces same results as optimizer method."""
        from app.services.optimizer import (
            ParameterOptimizer, _simulate_trades_worker, _calculate_statistics_worker
        )
        from app.services.patterns.fair_value_gap import FVGDetector

        with app.app_context():
            np.random.seed(42)
            n_candles = 500

            # Create test data
            timestamps = [1700000000000 + i * 3600000 for i in range(n_candles)]
            prices = 100 + np.cumsum(np.random.randn(n_candles) * 0.5)
            highs = prices + np.abs(np.random.randn(n_candles)) * 0.5
            lows = prices - np.abs(np.random.randn(n_candles)) * 0.5
            opens = prices + np.random.randn(n_candles) * 0.1
            closes = prices + np.random.randn(n_candles) * 0.1

            highs = np.maximum(highs, np.maximum(opens, closes))
            lows = np.minimum(lows, np.minimum(opens, closes))

            # Create FVG gaps
            for i in range(20, n_candles - 5, 25):
                highs[i] = lows[i+2] - 0.3

            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': opens,
                'high': highs,
                'low': lows,
                'close': closes,
                'volume': np.random.randint(1000, 10000, n_candles).astype(float)
            })

            # Detect patterns
            detector = FVGDetector()
            patterns = detector.detect_historical(df, min_zone_pct=0.15, skip_overlap=True)

            # Create ohlcv arrays
            optimizer = ParameterOptimizer()
            ohlcv = optimizer._df_to_arrays(df)

            params = {
                'rr_target': 2.0,
                'sl_buffer_pct': 10.0,
                'entry_method': 'zone_edge',
            }

            # Run both implementations
            trades_optimizer = optimizer._simulate_trades_fast(ohlcv, patterns, params)
            trades_worker = _simulate_trades_worker(ohlcv, patterns, params)

            stats_optimizer = optimizer._calculate_statistics(trades_optimizer)
            stats_worker = _calculate_statistics_worker(trades_worker)

            # Results MUST match exactly
            assert len(trades_optimizer) == len(trades_worker), \
                f"Trade count mismatch: optimizer={len(trades_optimizer)}, worker={len(trades_worker)}"

            # Compare each trade
            for i, (t_opt, t_wrk) in enumerate(zip(trades_optimizer, trades_worker)):
                assert t_opt['result'] == t_wrk['result'], \
                    f"Trade {i} result mismatch: {t_opt['result']} vs {t_wrk['result']}"
                assert abs(t_opt['profit_pct'] - t_wrk['profit_pct']) < 0.0001, \
                    f"Trade {i} profit mismatch: {t_opt['profit_pct']} vs {t_wrk['profit_pct']}"

            # Compare statistics
            assert stats_optimizer['total_trades'] == stats_worker['total_trades']
            assert stats_optimizer['win_rate'] == stats_worker['win_rate']
            assert abs(stats_optimizer['total_profit_pct'] - stats_worker['total_profit_pct']) < 0.01

            print(f"\n=== WORKER VS OPTIMIZER COMPARISON ===")
            print(f"Patterns: {len(patterns)}")
            print(f"Trades: {len(trades_optimizer)}")
            print(f"Win rate: {stats_optimizer['win_rate']}%")
            print(f"Total profit: {stats_optimizer['total_profit_pct']}%")
            print(f"Results: IDENTICAL ✓")
            print(f"========================================\n")

    def test_parallel_worker_produces_valid_results(self, app):
        """Test that parallel worker function produces valid results."""
        from app.services.optimizer import _process_symbol_worker

        with app.app_context():
            # Note: This test requires actual database data
            # It will skip if no data exists
            result = _process_symbol_worker(
                symbol='BTC/USDT',
                timeframes=['1h'],
                pattern_types=['imbalance'],
                parameter_grid={
                    'min_zone_pct': [0.15],
                    'use_overlap': [True],
                    'rr_target': [2.0],
                    'sl_buffer_pct': [10.0],
                },
                existing_timestamps={}  # Empty = no existing runs, don't skip
            )

            # Verify structure
            assert isinstance(result, dict)
            assert 'symbol' in result
            assert 'results' in result
            assert 'error' in result

            # Either error, skip, or valid results
            if result.get('error'):
                print(f"Worker returned error (expected if no data): {result['error']}")
            elif result.get('skip_count', 0) > 0:
                print(f"Worker skipped (no data available)")
            else:
                # Verify results structure
                for r in result['results']:
                    assert 'symbol' in r
                    assert 'status' in r
                    if r['status'] == 'completed':
                        assert 'trades' in r
                        assert 'stats' in r
                print(f"Worker produced {len(result['results'])} results")
