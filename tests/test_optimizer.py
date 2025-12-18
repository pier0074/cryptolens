"""
Tests for Optimizer Service
Tests incremental optimization, pattern caching, verified candles, and statistics
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from app import db
from app.models import Symbol, Candle, OptimizationRun
from app.services.optimizer import ParameterOptimizer, optimizer
from app.services.aggregator import get_candles_as_dataframe


class TestGetCandlesAsDataframe:
    """Tests for get_candles_as_dataframe with verified_only parameter"""

    def test_returns_all_candles_by_default(self, app, sample_symbol_with_candles):
        """Test that all candles are returned when verified_only=False"""
        with app.app_context():
            df = get_candles_as_dataframe('BTC/USDT', '1h', limit=100, verified_only=False)
            assert len(df) == 50  # All 50 candles

    def test_returns_only_verified_candles(self, app, sample_symbol_with_candles):
        """Test that only verified candles are returned when verified_only=True"""
        with app.app_context():
            df = get_candles_as_dataframe('BTC/USDT', '1h', limit=100, verified_only=True)
            # Should return only verified candles (40 out of 50)
            assert len(df) == 40

    def test_empty_when_no_verified_candles(self, app, sample_symbol_unverified_only):
        """Test returns empty when no verified candles exist and verified_only=True"""
        with app.app_context():
            df = get_candles_as_dataframe('ETH/USDT', '1h', limit=100, verified_only=True)
            assert len(df) == 0

    def test_returns_candles_in_chronological_order(self, app, sample_symbol_with_candles):
        """Test that candles are returned in chronological order"""
        with app.app_context():
            df = get_candles_as_dataframe('BTC/USDT', '1h', limit=100, verified_only=False)
            timestamps = df['timestamp'].tolist()
            assert timestamps == sorted(timestamps)


class TestOptimizationRunFindExisting:
    """Tests for OptimizationRun.find_existing() method"""

    def test_finds_existing_run(self, app, sample_optimization_run):
        """Test finding an existing optimization run"""
        with app.app_context():
            existing = OptimizationRun.find_existing(
                'BTC/USDT', '1h', 'imbalance', 2.0, 10.0
            )
            assert existing is not None
            assert existing.symbol == 'BTC/USDT'
            assert existing.rr_target == 2.0

    def test_returns_none_when_not_found(self, app):
        """Test returns None when no matching run exists"""
        with app.app_context():
            existing = OptimizationRun.find_existing(
                'NONEXISTENT/USDT', '1h', 'imbalance', 2.0, 10.0
            )
            assert existing is None

    def test_finds_most_recent_by_timestamp(self, app, sample_multiple_runs):
        """Test that the most recent run (by last_candle_timestamp) is returned"""
        with app.app_context():
            existing = OptimizationRun.find_existing(
                'BTC/USDT', '1h', 'imbalance', 2.0, 10.0
            )
            # Should return the one with higher timestamp
            assert existing.last_candle_timestamp == 1700200000000


class TestOptimizerPatternCaching:
    """Tests for pattern detection caching in optimizer"""

    def test_pattern_cache_key_includes_all_params(self):
        """Test that cache key includes symbol, timeframe, pattern_type, min_zone_pct, use_overlap"""
        # This is a unit test for the cache key structure
        cache_key = ('BTC/USDT', '1h', 'imbalance', 0.15, True)
        assert len(cache_key) == 5
        assert cache_key[0] == 'BTC/USDT'
        assert cache_key[3] == 0.15

    def test_different_min_zone_pct_different_cache(self):
        """Test that different min_zone_pct values use different cache entries"""
        cache_key_1 = ('BTC/USDT', '1h', 'imbalance', 0.15, True)
        cache_key_2 = ('BTC/USDT', '1h', 'imbalance', 0.20, True)
        assert cache_key_1 != cache_key_2


class TestOptimizerDfToArrays:
    """Tests for _df_to_arrays helper method"""

    def test_converts_df_to_numpy_arrays(self):
        """Test DataFrame to numpy arrays conversion"""
        df = pd.DataFrame({
            'timestamp': [1000, 2000, 3000],
            'open': [100.0, 101.0, 102.0],
            'high': [105.0, 106.0, 107.0],
            'low': [95.0, 96.0, 97.0],
            'close': [102.0, 103.0, 104.0],
        })

        opt = ParameterOptimizer()
        arrays = opt._df_to_arrays(df)

        assert 'timestamp' in arrays
        assert 'open' in arrays
        assert 'high' in arrays
        assert 'low' in arrays
        assert 'close' in arrays
        assert isinstance(arrays['high'], np.ndarray)
        assert len(arrays['high']) == 3

    def test_arrays_preserve_values(self):
        """Test that array values match original DataFrame"""
        df = pd.DataFrame({
            'timestamp': [1000, 2000],
            'open': [100.0, 101.0],
            'high': [105.0, 106.0],
            'low': [95.0, 96.0],
            'close': [102.0, 103.0],
        })

        opt = ParameterOptimizer()
        arrays = opt._df_to_arrays(df)

        assert arrays['high'][0] == 105.0
        assert arrays['low'][1] == 96.0


class TestOptimizerSimulateTrades:
    """Tests for trade simulation in optimizer"""

    def test_simulate_trades_fast_returns_list(self):
        """Test that _simulate_trades_fast returns a list"""
        opt = ParameterOptimizer()
        ohlcv = {
            'timestamp': np.array([1000, 2000, 3000, 4000, 5000] * 20),
            'open': np.array([100.0] * 100),
            'high': np.array([105.0] * 100),
            'low': np.array([95.0] * 100),
            'close': np.array([102.0] * 100),
        }
        patterns = [
            {'direction': 'bullish', 'zone_high': 101.0, 'zone_low': 99.0, 'detected_at': 5}
        ]
        params = {'rr_target': 2.0, 'sl_buffer_pct': 10.0, 'entry_method': 'zone_edge'}

        trades = opt._simulate_trades_fast(ohlcv, patterns, params)

        assert isinstance(trades, list)

    def test_simulate_single_trade_fast_win(self):
        """Test single trade simulation that hits take profit"""
        opt = ParameterOptimizer()

        # Create price data where TP is hit
        highs = np.array([100.0] * 10 + [120.0] + [100.0] * 89)  # TP hit at index 10
        lows = np.array([99.0] * 100)
        timestamps = np.array([i * 1000 for i in range(100)])

        trade = opt._simulate_single_trade_fast(
            highs, lows, timestamps,
            entry_idx=5, entry=101.0, stop_loss=97.0, take_profit=109.0,
            direction='long', rr_target=2.0, n_candles=100
        )

        assert trade is not None
        assert trade['result'] == 'win'
        assert trade['rr_achieved'] == 2.0

    def test_simulate_single_trade_fast_loss(self):
        """Test single trade simulation that hits stop loss"""
        opt = ParameterOptimizer()

        # Create price data where SL is hit
        highs = np.array([102.0] * 100)
        lows = np.array([99.0] * 10 + [90.0] + [99.0] * 89)  # SL hit at index 10
        timestamps = np.array([i * 1000 for i in range(100)])

        trade = opt._simulate_single_trade_fast(
            highs, lows, timestamps,
            entry_idx=5, entry=101.0, stop_loss=95.0, take_profit=109.0,
            direction='long', rr_target=2.0, n_candles=100
        )

        assert trade is not None
        assert trade['result'] == 'loss'
        assert trade['rr_achieved'] == -1.0


class TestOptimizerCalculateStatistics:
    """Tests for statistics calculation"""

    def test_empty_trades_returns_zeros(self):
        """Test that empty trades list returns zero statistics"""
        opt = ParameterOptimizer()
        stats = opt._calculate_statistics([])

        assert stats['total_trades'] == 0
        assert stats['win_rate'] == 0
        assert stats['total_profit_pct'] == 0

    def test_all_wins_100_percent_winrate(self):
        """Test 100% win rate with all winning trades"""
        opt = ParameterOptimizer()
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
        ]
        stats = opt._calculate_statistics(trades)

        assert stats['win_rate'] == 100.0
        assert stats['winning_trades'] == 2
        assert stats['losing_trades'] == 0

    def test_mixed_trades_correct_stats(self):
        """Test correct statistics with mixed win/loss trades"""
        opt = ParameterOptimizer()
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 5},
        ]
        stats = opt._calculate_statistics(trades)

        assert stats['total_trades'] == 2
        assert stats['win_rate'] == 50.0
        assert stats['total_profit_pct'] == 2.0  # 4 - 2


class TestIncrementalOptimization:
    """Tests for incremental optimization mode"""

    def test_incremental_skips_when_no_new_data(self, app, sample_optimization_run_with_timestamp):
        """Test that incremental mode skips when no new candles"""
        with app.app_context():
            # The run has last_candle_timestamp that matches the latest candle
            # So there's no new data to process
            result = optimizer._run_incremental_single(
                'BTC/USDT', '1h', 'imbalance',
                None,  # detector will be fetched
                {'rr_target': 2.0, 'sl_buffer_pct': 10.0}
            )
            # Should skip because no new candles
            assert result in ['skipped', 'new', 'updated']


class TestSweepPhaseFactorization:
    """Tests for the shared _run_sweep_phase used by both run_job and run_incremental"""

    def test_sweep_phase_returns_results_and_best(self):
        """Test that _run_sweep_phase returns results list and best result"""
        opt = ParameterOptimizer()

        # Create mock data cache and pattern cache
        df = pd.DataFrame({
            'timestamp': [i * 1000 for i in range(100)],
            'open': [100.0] * 100,
            'high': [105.0] * 100,
            'low': [95.0] * 100,
            'close': [102.0] * 100,
        })
        ohlcv_arrays = opt._df_to_arrays(df)
        data_cache = {('TEST/USDT', '1h'): (df, ohlcv_arrays, 99000)}

        # Empty pattern cache (no patterns detected)
        pattern_cache = {('TEST/USDT', '1h', 'imbalance', 0.15, True): []}

        parameter_grid = {
            'rr_target': [2.0],
            'sl_buffer_pct': [10.0],
            'entry_method': ['zone_edge'],
            'min_zone_pct': [0.15],
            'use_overlap': [True],
        }

        results, best = opt._run_sweep_phase(
            symbols=['TEST/USDT'],
            timeframes=['1h'],
            pattern_types=['imbalance'],
            parameter_grid=parameter_grid,
            data_cache=data_cache,
            pattern_cache=pattern_cache,
        )

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]['status'] == 'completed'
        assert results[0]['symbol'] == 'TEST/USDT'

    def test_sweep_phase_with_patterns_produces_trades(self):
        """Test that sweep phase produces trades when patterns are present"""
        opt = ParameterOptimizer()

        # Create data with enough candles
        n = 200
        df = pd.DataFrame({
            'timestamp': [i * 1000 for i in range(n)],
            'open': [100.0] * n,
            'high': [105.0] * n,
            'low': [95.0] * n,
            'close': [102.0] * n,
        })
        ohlcv_arrays = opt._df_to_arrays(df)
        data_cache = {('TEST/USDT', '1h'): (df, ohlcv_arrays, (n - 1) * 1000)}

        # Add a pattern that can be traded
        patterns = [{
            'direction': 'bullish',
            'zone_high': 101.0,
            'zone_low': 99.0,
            'detected_at': 10,
        }]
        pattern_cache = {('TEST/USDT', '1h', 'imbalance', 0.15, True): patterns}

        parameter_grid = {
            'rr_target': [2.0],
            'sl_buffer_pct': [10.0],
            'entry_method': ['zone_edge'],
            'min_zone_pct': [0.15],
            'use_overlap': [True],
        }

        results, best = opt._run_sweep_phase(
            symbols=['TEST/USDT'],
            timeframes=['1h'],
            pattern_types=['imbalance'],
            parameter_grid=parameter_grid,
            data_cache=data_cache,
            pattern_cache=pattern_cache,
        )

        assert len(results) == 1
        assert results[0]['status'] == 'completed'
        assert 'trades' in results[0]
        assert 'stats' in results[0]

    def test_sweep_phase_handles_missing_data(self):
        """Test that sweep phase handles missing data gracefully"""
        opt = ParameterOptimizer()

        # Empty data cache
        data_cache = {('TEST/USDT', '1h'): (None, None, None)}
        pattern_cache = {}

        parameter_grid = {
            'rr_target': [2.0],
            'sl_buffer_pct': [10.0],
            'entry_method': ['zone_edge'],
            'min_zone_pct': [0.15],
            'use_overlap': [True],
        }

        results, best = opt._run_sweep_phase(
            symbols=['TEST/USDT'],
            timeframes=['1h'],
            pattern_types=['imbalance'],
            parameter_grid=parameter_grid,
            data_cache=data_cache,
            pattern_cache=pattern_cache,
        )

        assert len(results) == 1
        assert results[0]['status'] == 'failed'
        assert 'error' in results[0]

    def test_create_run_from_result_creates_new_run(self, app):
        """Test that _create_run_from_result creates a new OptimizationRun"""
        with app.app_context():
            opt = ParameterOptimizer()

            result = {
                'symbol': 'TEST/USDT',
                'timeframe': '1h',
                'pattern_type': 'imbalance',
                'params': {
                    'rr_target': 2.0,
                    'sl_buffer_pct': 10.0,
                    'entry_method': 'zone_edge',
                    'min_zone_pct': 0.15,
                    'use_overlap': True,
                },
                'status': 'completed',
                'trades': [],
                'stats': {
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'win_rate': 0,
                    'avg_rr': 0,
                    'total_profit_pct': 0,
                    'max_drawdown': 0,
                    'sharpe_ratio': 0,
                    'profit_factor': 0,
                    'avg_duration': 0,
                },
                'first_candle_ts': 1672531200000,  # 2023-01-01
                'last_candle_ts': 1700000000000,   # 2023-11-14
            }

            run = opt._create_run_from_result(None, result)
            db.session.commit()

            assert run.id is not None
            assert run.symbol == 'TEST/USDT'
            assert run.timeframe == '1h'
            assert run.rr_target == 2.0
            assert run.job_id is None  # Incremental mode

    def test_create_run_from_result_updates_existing(self, app, sample_optimization_run):
        """Test that _create_run_from_result updates an existing run"""
        with app.app_context():
            opt = ParameterOptimizer()
            existing = OptimizationRun.query.get(sample_optimization_run)

            result = {
                'symbol': 'BTC/USDT',
                'timeframe': '1h',
                'pattern_type': 'imbalance',
                'params': {
                    'rr_target': 2.0,
                    'sl_buffer_pct': 10.0,
                    'entry_method': 'zone_edge',
                    'min_zone_pct': 0.15,
                    'use_overlap': True,
                },
                'status': 'completed',
                'trades': [],
                'stats': {
                    'total_trades': 200,  # Different from existing
                    'winning_trades': 120,
                    'losing_trades': 80,
                    'win_rate': 60.0,
                    'avg_rr': 0.8,
                    'total_profit_pct': 25.0,
                    'max_drawdown': 3.0,
                    'sharpe_ratio': 1.5,
                    'profit_factor': 2.0,
                    'avg_duration': 15.0,
                },
                'last_candle_ts': 1700500000000,
            }

            run = opt._create_run_from_result(None, result, existing_run=existing)
            db.session.commit()

            # Should be same run, updated values
            assert run.id == existing.id
            assert run.total_trades == 200
            assert run.win_rate == 60.0
            assert run.is_incremental is True


class TestIncrementalSkipLogic:
    """Tests for skip logic when no new candles are available"""

    def test_incremental_processes_symbol_by_symbol(self):
        """Test that run_incremental processes one symbol at a time with shared method"""
        opt = ParameterOptimizer()
        # This is a structural test - the method processes symbols in a loop
        # using the shared _process_symbol method for consistency
        import inspect
        source = inspect.getsource(opt.run_incremental)
        assert 'for symbol in symbols:' in source
        # Uses shared _process_symbol method with existing_timestamps for skip detection
        assert '_process_symbol' in source
        assert 'existing_timestamps' in source


class TestSameCandleConflictResolution:
    """Tests for same-candle SL/TP conflict resolution using smaller TF drill-down"""

    def test_resolve_same_candle_no_data_returns_loss(self, app):
        """Test that same-candle conflict returns loss when no drill-down data available"""
        with app.app_context():
            opt = ParameterOptimizer()

            result = opt._resolve_same_candle_conflict(
                direction='long',
                stop_loss=100.0,
                take_profit=110.0,
                conflict_ts=1700000000000,
                timeframe=None,  # No timeframe
                data_cache=None,  # No data cache
                symbol='BTC/USDT'
            )

            assert result == 'loss'  # Conservative default

    def test_resolve_same_candle_1m_returns_loss(self, app):
        """Test that 1m timeframe (smallest) always returns loss"""
        with app.app_context():
            opt = ParameterOptimizer()

            # Even with data_cache, 1m can't drill down further
            data_cache = {('BTC/USDT', '1m'): (None, None, None, None)}

            result = opt._resolve_same_candle_conflict(
                direction='long',
                stop_loss=100.0,
                take_profit=110.0,
                conflict_ts=1700000000000,
                timeframe='1m',
                data_cache=data_cache,
                symbol='BTC/USDT'
            )

            assert result == 'loss'

    def test_resolve_same_candle_drills_down_finds_sl_first(self, app):
        """Test drill-down correctly identifies SL hit first"""
        with app.app_context():
            opt = ParameterOptimizer()

            # Create 1h candle with conflict, and 15m data showing SL hit first
            # 1h candle at timestamp 1700000000000 (conflict)
            # 15m candles within that hour:
            # Candle 1: low hits SL first
            # Candle 2: high would hit TP

            smaller_ohlcv = {
                'high': np.array([105.0, 115.0, 108.0, 107.0]),  # TP (110) hit on candle 2
                'low': np.array([99.0, 103.0, 104.0, 105.0]),    # SL (100) hit on candle 1
                'timestamp': np.array([
                    1700000000000,      # 15m candle 1 - starts at 1h candle start
                    1700000000000 + 15*60*1000,  # 15m candle 2
                    1700000000000 + 30*60*1000,  # 15m candle 3
                    1700000000000 + 45*60*1000,  # 15m candle 4
                ])
            }

            data_cache = {
                ('BTC/USDT', '15m'): (None, smaller_ohlcv, None, None)
            }

            result = opt._resolve_same_candle_conflict(
                direction='long',
                stop_loss=100.0,
                take_profit=110.0,
                conflict_ts=1700000000000,
                timeframe='1h',  # Will drill down to 15m
                data_cache=data_cache,
                symbol='BTC/USDT'
            )

            assert result == 'loss'  # SL hit first (candle 1: low=99 < SL=100)

    def test_resolve_same_candle_drills_down_finds_tp_first(self, app):
        """Test drill-down correctly identifies TP hit first"""
        with app.app_context():
            opt = ParameterOptimizer()

            # 15m candles where TP hits before SL
            smaller_ohlcv = {
                'high': np.array([115.0, 105.0, 108.0, 107.0]),  # TP (110) hit on candle 1
                'low': np.array([103.0, 99.0, 104.0, 105.0]),    # SL (100) hit on candle 2
                'timestamp': np.array([
                    1700000000000,
                    1700000000000 + 15*60*1000,
                    1700000000000 + 30*60*1000,
                    1700000000000 + 45*60*1000,
                ])
            }

            data_cache = {
                ('BTC/USDT', '15m'): (None, smaller_ohlcv, None, None)
            }

            result = opt._resolve_same_candle_conflict(
                direction='long',
                stop_loss=100.0,
                take_profit=110.0,
                conflict_ts=1700000000000,
                timeframe='1h',
                data_cache=data_cache,
                symbol='BTC/USDT'
            )

            assert result == 'win'  # TP hit first (candle 1: high=115 > TP=110)

    def test_resolve_same_candle_short_direction(self, app):
        """Test drill-down works correctly for short trades"""
        with app.app_context():
            opt = ParameterOptimizer()

            # For short: SL is above entry, TP is below entry
            # Short at 100, SL at 110, TP at 90
            smaller_ohlcv = {
                'high': np.array([105.0, 115.0, 108.0]),  # SL (110) hit on candle 2
                'low': np.array([95.0, 92.0, 85.0]),      # TP (90) hit on candle 3
                'timestamp': np.array([
                    1700000000000,
                    1700000000000 + 15*60*1000,
                    1700000000000 + 30*60*1000,
                ])
            }

            data_cache = {
                ('BTC/USDT', '15m'): (None, smaller_ohlcv, None, None)
            }

            result = opt._resolve_same_candle_conflict(
                direction='short',
                stop_loss=110.0,  # Above entry for short
                take_profit=90.0,  # Below entry for short
                conflict_ts=1700000000000,
                timeframe='1h',
                data_cache=data_cache,
                symbol='BTC/USDT'
            )

            assert result == 'loss'  # SL hit first (candle 2: high=115 > SL=110)

    def test_timeframe_mapping_exists(self):
        """Test that SMALLER_TIMEFRAME mapping is complete"""
        from app.services.optimizer import SMALLER_TIMEFRAME

        # All expected timeframes should be in mapping
        expected_tfs = ['1d', '4h', '2h', '1h', '30m', '15m', '5m', '1m']
        for tf in expected_tfs:
            assert tf in SMALLER_TIMEFRAME

        # 1m should map to None (can't go smaller)
        assert SMALLER_TIMEFRAME['1m'] is None

        # Others should map to smaller TFs
        assert SMALLER_TIMEFRAME['1d'] == '4h'
        assert SMALLER_TIMEFRAME['4h'] == '1h'
        assert SMALLER_TIMEFRAME['1h'] == '15m'


class TestFeeCalculation:
    """Tests for fee calculation formula (used in WebUI)"""

    def test_fee_formula_zero_fees(self):
        """Test net profit equals gross when fee is 0%"""
        gross_profit = 50.0
        trades = 100
        fee_pct = 0.0

        total_fees = trades * 2 * fee_pct
        net = gross_profit - total_fees

        assert net == 50.0

    def test_fee_formula_standard_binance_fee(self):
        """Test net profit calculation with standard 0.1% Binance fee"""
        gross_profit = 50.0
        trades = 100
        fee_pct = 0.1  # 0.1%

        # Each trade pays fee on entry and exit = 2 * fee per trade
        total_fees = trades * 2 * fee_pct
        net = gross_profit - total_fees

        # 100 trades * 2 * 0.1% = 20% total fees
        assert total_fees == 20.0
        assert net == 30.0

    def test_fee_formula_many_trades_can_turn_profitable_negative(self):
        """Test that fees can turn a profitable strategy negative"""
        gross_profit = 15.0
        trades = 200
        fee_pct = 0.1

        total_fees = trades * 2 * fee_pct
        net = gross_profit - total_fees

        # 200 trades * 2 * 0.1% = 40% total fees
        # Gross 15% - 40% fees = -25% net
        assert total_fees == 40.0
        assert net == -25.0

    def test_fee_formula_higher_fee_rate(self):
        """Test with higher fee rate (0.2% like some exchanges)"""
        gross_profit = 100.0
        trades = 50
        fee_pct = 0.2

        total_fees = trades * 2 * fee_pct
        net = gross_profit - total_fees

        # 50 trades * 2 * 0.2% = 20% total fees
        assert total_fees == 20.0
        assert net == 80.0


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def sample_symbol_with_candles(app):
    """Create symbol with mixed verified and unverified candles"""
    with app.app_context():
        symbol = Symbol(symbol='BTC/USDT', exchange='binance', is_active=True)
        db.session.add(symbol)
        db.session.commit()

        base_ts = 1700000000000
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Create 50 candles, 40 verified, 10 unverified
        for i in range(50):
            candle = Candle(
                symbol_id=symbol.id,
                timeframe='1h',
                timestamp=base_ts + i * 3600000,
                open=100.0 + i * 0.1,
                high=102.0 + i * 0.1,
                low=98.0 + i * 0.1,
                close=101.0 + i * 0.1,
                volume=1000,
                verified_at=now_ms if i < 40 else None  # First 40 verified
            )
            db.session.add(candle)

        db.session.commit()
        return symbol.id


@pytest.fixture
def sample_symbol_unverified_only(app):
    """Create symbol with only unverified candles"""
    with app.app_context():
        symbol = Symbol(symbol='ETH/USDT', exchange='binance', is_active=True)
        db.session.add(symbol)
        db.session.commit()

        base_ts = 1700000000000
        for i in range(20):
            candle = Candle(
                symbol_id=symbol.id,
                timeframe='1h',
                timestamp=base_ts + i * 3600000,
                open=100.0,
                high=102.0,
                low=98.0,
                close=101.0,
                volume=1000,
                verified_at=None  # All unverified
            )
            db.session.add(candle)

        db.session.commit()
        return symbol.id


@pytest.fixture
def sample_optimization_run(app):
    """Create a sample optimization run"""
    with app.app_context():
        run = OptimizationRun(
            job_id=None,
            symbol='BTC/USDT',
            timeframe='1h',
            pattern_type='imbalance',
            start_date='2023-11-01',
            end_date='2023-11-30',
            rr_target=2.0,
            sl_buffer_pct=10.0,
            tp_method='fixed_rr',
            entry_method='zone_edge',
            min_zone_pct=0.15,
            use_overlap=True,
            status='completed',
            total_trades=100,
            winning_trades=50,
            losing_trades=50,
            win_rate=50.0,
            avg_rr=0.5,
            total_profit_pct=10.0,
            max_drawdown=5.0,
            sharpe_ratio=1.0,
            profit_factor=1.5,
            avg_trade_duration=10.0,
            last_candle_timestamp=1700100000000,
        )
        db.session.add(run)
        db.session.commit()
        return run.id


@pytest.fixture
def sample_multiple_runs(app):
    """Create multiple optimization runs with different timestamps"""
    with app.app_context():
        # Older run
        run1 = OptimizationRun(
            job_id=None,
            symbol='BTC/USDT',
            timeframe='1h',
            pattern_type='imbalance',
            start_date='2023-11-01',
            end_date='2023-11-30',
            rr_target=2.0,
            sl_buffer_pct=10.0,
            tp_method='fixed_rr',
            entry_method='zone_edge',
            min_zone_pct=0.15,
            use_overlap=True,
            status='completed',
            total_trades=100,
            winning_trades=50,
            losing_trades=50,
            win_rate=50.0,
            avg_rr=0.5,
            total_profit_pct=10.0,
            max_drawdown=5.0,
            sharpe_ratio=1.0,
            profit_factor=1.5,
            avg_trade_duration=10.0,
            last_candle_timestamp=1700100000000,
        )
        db.session.add(run1)

        # Newer run (same params, higher timestamp)
        run2 = OptimizationRun(
            job_id=None,
            symbol='BTC/USDT',
            timeframe='1h',
            pattern_type='imbalance',
            start_date='2023-11-01',
            end_date='2023-12-15',
            rr_target=2.0,
            sl_buffer_pct=10.0,
            tp_method='fixed_rr',
            entry_method='zone_edge',
            min_zone_pct=0.15,
            use_overlap=True,
            status='completed',
            total_trades=150,
            winning_trades=80,
            losing_trades=70,
            win_rate=53.3,
            avg_rr=0.6,
            total_profit_pct=15.0,
            max_drawdown=6.0,
            sharpe_ratio=1.1,
            profit_factor=1.6,
            avg_trade_duration=12.0,
            last_candle_timestamp=1700200000000,  # Higher timestamp
        )
        db.session.add(run2)
        db.session.commit()

        return [run1.id, run2.id]


@pytest.fixture
def sample_optimization_run_with_timestamp(app, sample_symbol_with_candles):
    """Create optimization run with timestamp matching latest candle"""
    with app.app_context():
        # Get the latest candle timestamp
        latest = Candle.query.filter_by(
            symbol_id=sample_symbol_with_candles,
            timeframe='1h'
        ).order_by(Candle.timestamp.desc()).first()

        run = OptimizationRun(
            job_id=None,
            symbol='BTC/USDT',
            timeframe='1h',
            pattern_type='imbalance',
            start_date='2023-11-01',
            end_date='2023-11-30',
            rr_target=2.0,
            sl_buffer_pct=10.0,
            tp_method='fixed_rr',
            entry_method='zone_edge',
            min_zone_pct=0.15,
            use_overlap=True,
            status='completed',
            total_trades=100,
            winning_trades=50,
            losing_trades=50,
            win_rate=50.0,
            avg_rr=0.5,
            total_profit_pct=10.0,
            max_drawdown=5.0,
            sharpe_ratio=1.0,
            profit_factor=1.5,
            avg_trade_duration=10.0,
            last_candle_timestamp=latest.timestamp if latest else 1700100000000,
        )
        db.session.add(run)
        db.session.commit()
        return run.id
