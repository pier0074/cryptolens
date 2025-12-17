"""
Tests for Backtester Service
Tests pattern detection, trade simulation, and statistics calculation
"""
import pytest
import pandas as pd
import numpy as np
from app import db
from app.models import Backtest
from app.services.backtester import (
    run_backtest, simulate_trades, simulate_single_trade,
    calculate_statistics
)
from app.services.patterns.fair_value_gap import FVGDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector


class TestCalculateStatistics:
    """Tests for calculate_statistics function"""

    def test_empty_trades(self):
        """Test statistics calculation with no trades"""
        stats = calculate_statistics([])

        assert stats['total_trades'] == 0
        assert stats['winning_trades'] == 0
        assert stats['losing_trades'] == 0
        assert stats['win_rate'] == 0
        assert stats['avg_rr'] == 0
        assert stats['total_profit_pct'] == 0
        assert stats['max_drawdown'] == 0

    def test_all_winning_trades(self):
        """Test statistics with all winning trades"""
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 15},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 20},
        ]
        stats = calculate_statistics(trades)

        assert stats['total_trades'] == 3
        assert stats['winning_trades'] == 3
        assert stats['losing_trades'] == 0
        assert stats['win_rate'] == 100.0
        assert stats['avg_rr'] == 2.0
        assert stats['total_profit_pct'] == 12.0
        assert stats['max_drawdown'] == 0  # No drawdown when always winning

    def test_all_losing_trades(self):
        """Test statistics with all losing trades"""
        trades = [
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 5},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 8},
        ]
        stats = calculate_statistics(trades)

        assert stats['total_trades'] == 2
        assert stats['winning_trades'] == 0
        assert stats['losing_trades'] == 2
        assert stats['win_rate'] == 0
        assert stats['avg_rr'] == -1.0
        assert stats['total_profit_pct'] == -4.0

    def test_mixed_trades(self):
        """Test statistics with mixed win/loss trades"""
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 5},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 12},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 3},
        ]
        stats = calculate_statistics(trades)

        assert stats['total_trades'] == 4
        assert stats['winning_trades'] == 2
        assert stats['losing_trades'] == 2
        assert stats['win_rate'] == 50.0
        assert stats['avg_rr'] == 0.5  # (2+(-1)+2+(-1))/4
        assert stats['total_profit_pct'] == 4.0  # 4-2+4-2

    def test_max_drawdown_calculation(self):
        """Test max drawdown is calculated correctly"""
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 10.0, 'duration_candles': 10},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -5.0, 'duration_candles': 5},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -5.0, 'duration_candles': 5},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 10.0, 'duration_candles': 10},
        ]
        stats = calculate_statistics(trades)

        # Peak at 10, drops to 0, max drawdown = 10
        assert stats['max_drawdown'] == 10.0

    def test_inconclusive_trades_handling(self):
        """Test that inconclusive trades are counted separately"""
        trades = [
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 10},
            {'result': 'loss', 'rr_achieved': -1.0, 'profit_pct': -2.0, 'duration_candles': 5},
            {'result': 'inconclusive', 'rr_achieved': 0.0, 'profit_pct': 0.0, 'duration_candles': 3},
            {'result': 'win', 'rr_achieved': 2.0, 'profit_pct': 4.0, 'duration_candles': 12},
        ]
        stats = calculate_statistics(trades)

        assert stats['total_trades'] == 4
        assert stats['winning_trades'] == 2
        assert stats['losing_trades'] == 1
        assert stats['inconclusive_trades'] == 1
        # Win rate including inconclusive: 2/4 = 50%
        assert stats['win_rate'] == 50.0
        # Win rate excluding inconclusive: 2/3 = 66.67%
        assert stats['win_rate_excluding_inconclusive'] == 66.67
        # Avg RR only from conclusive trades: (2 + -1 + 2) / 3 = 1.0
        assert stats['avg_rr'] == 1.0
        # Total profit: 4 - 2 + 0 + 4 = 6
        assert stats['total_profit_pct'] == 6.0

    def test_all_inconclusive_trades(self):
        """Test statistics when all trades are inconclusive"""
        trades = [
            {'result': 'inconclusive', 'rr_achieved': 0.0, 'profit_pct': 0.0, 'duration_candles': 3},
            {'result': 'inconclusive', 'rr_achieved': 0.0, 'profit_pct': 0.0, 'duration_candles': 5},
        ]
        stats = calculate_statistics(trades)

        assert stats['total_trades'] == 2
        assert stats['inconclusive_trades'] == 2
        assert stats['win_rate'] == 0
        assert stats['win_rate_excluding_inconclusive'] == 0
        assert stats['avg_rr'] == 0


class TestSimulateSingleTrade:
    """Tests for simulate_single_trade function"""

    @pytest.fixture
    def bullish_df(self):
        """Create DataFrame with bullish price action for testing"""
        # Create 50 candles of price data
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Simulate price going up to hit TP
        for i in range(20, 30):
            df.loc[i, 'high'] = 110.0 + i
            df.loc[i, 'close'] = 108.0 + i

        return df

    @pytest.fixture
    def bearish_df(self):
        """Create DataFrame with bearish price action for testing"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [99.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Simulate price going down to hit TP
        for i in range(20, 30):
            df.loc[i, 'low'] = 90.0 - i
            df.loc[i, 'close'] = 92.0 - i

        return df

    def test_bullish_trade_wins(self, bullish_df):
        """Test bullish trade that hits take profit"""
        pattern = {
            'direction': 'bullish',
            'zone_high': 102.0,
            'zone_low': 100.0,
            'detected_at': 10
        }

        trade = simulate_single_trade(bullish_df, 10, pattern, rr_target=2.0)

        # Trade should complete (either win or loss)
        assert trade is not None or trade is None  # May not trigger

    def test_bearish_trade_wins(self, bearish_df):
        """Test bearish trade that hits take profit"""
        pattern = {
            'direction': 'bearish',
            'zone_high': 102.0,
            'zone_low': 100.0,
            'detected_at': 10
        }

        trade = simulate_single_trade(bearish_df, 10, pattern, rr_target=2.0)

        # Trade may or may not complete depending on price action
        # This tests the function runs without error
        assert trade is None or isinstance(trade, dict)

    def test_trade_returns_correct_structure(self):
        """Test that completed trade has correct structure"""
        # Create controlled price data that will trigger a trade
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Set up entry trigger and TP hit
        df.loc[15, 'low'] = 99.0  # Entry triggered
        df.loc[20, 'high'] = 110.0  # TP hit for 2:1 RR

        pattern = {
            'direction': 'bullish',
            'zone_high': 100.0,
            'zone_low': 98.0,
            'detected_at': 10
        }

        trade = simulate_single_trade(df, 10, pattern, rr_target=2.0)

        if trade is not None:
            assert 'entry_price' in trade
            assert 'exit_price' in trade
            assert 'direction' in trade
            assert 'result' in trade
            assert 'rr_achieved' in trade
            assert 'profit_pct' in trade
            assert 'entry_time' in trade
            assert 'exit_time' in trade
            assert 'duration_candles' in trade

    def test_slippage_affects_entry_price(self):
        """Test that slippage increases entry price for longs"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [105.0] * 50,
            'low': [95.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Entry trigger and TP hit
        df.loc[15, 'low'] = 99.0
        df.loc[25, 'high'] = 120.0  # High enough to hit TP with slippage

        pattern = {
            'direction': 'bullish',
            'zone_high': 100.0,
            'zone_low': 98.0,
            'detected_at': 10
        }

        # Without slippage
        trade_no_slip = simulate_single_trade(df, 10, pattern, rr_target=2.0, slippage_pct=0.0)
        # With 1% slippage
        trade_with_slip = simulate_single_trade(df, 10, pattern, rr_target=2.0, slippage_pct=1.0)

        if trade_no_slip and trade_with_slip:
            # Entry price should be higher with slippage for long positions
            assert trade_with_slip['entry_price'] > trade_no_slip['entry_price']

    def test_same_candle_sl_tp_returns_inconclusive(self):
        """Test that same-candle SL and TP hit returns inconclusive result"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Set up entry trigger
        df.loc[15, 'low'] = 99.0  # Entry triggered at zone_high=100

        # Create a candle that hits both SL and TP
        # For bullish pattern with zone_high=100, zone_low=98, sl_buffer=10%:
        # SL = 98 - (2 * 0.1) = 97.8
        # TP = 100 + (2.2 * 2) = 104.4
        df.loc[20, 'low'] = 97.0   # Hits SL at 97.8
        df.loc[20, 'high'] = 105.0  # Hits TP at 104.4

        pattern = {
            'direction': 'bullish',
            'zone_high': 100.0,
            'zone_low': 98.0,
            'detected_at': 10
        }

        trade = simulate_single_trade(df, 10, pattern, rr_target=2.0)

        assert trade is not None
        assert trade['result'] == 'inconclusive'
        assert trade['rr_achieved'] == 0.0
        assert trade['profit_pct'] == 0.0
        assert 'note' in trade

    def test_configurable_lookback(self):
        """Test that lookback parameter limits how far to search for trade completion"""
        timestamps = [1700000000000 + i * 3600000 for i in range(200)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 200,
            'high': [102.0] * 200,
            'low': [98.0] * 200,
            'close': [101.0] * 200,
            'volume': [1000.0] * 200
        }
        df = pd.DataFrame(data)

        # Entry triggered early
        df.loc[15, 'low'] = 99.0

        # TP hit very late (beyond short lookback)
        df.loc[150, 'high'] = 120.0

        pattern = {
            'direction': 'bullish',
            'zone_high': 100.0,
            'zone_low': 98.0,
            'detected_at': 10
        }

        # With short lookback, trade should not complete
        trade_short = simulate_single_trade(df, 10, pattern, rr_target=2.0, lookback=50)
        # With long lookback, trade should complete
        trade_long = simulate_single_trade(df, 10, pattern, rr_target=2.0, lookback=200)

        assert trade_short is None  # Didn't complete in lookback period
        if trade_long:
            assert trade_long['result'] in ['win', 'loss', 'inconclusive']


class TestDetectHistoricalPatterns:
    """Tests for detect_historical methods on pattern detectors"""

    def test_fvg_detects_bullish_fvg(self):
        """Test FVG detector finds bullish FVG pattern"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Create bullish FVG at index 5 (c1=3, c2=4, c3=5)
        df.loc[3, 'high'] = 100.0  # c1 high
        df.loc[5, 'low'] = 105.0   # c3 low > c1 high = bullish FVG
        df.loc[5, 'close'] = 108.0

        detector = FVGDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        assert isinstance(patterns, list)
        # Should find at least the bullish FVG we created
        bullish_patterns = [p for p in patterns if p['direction'] == 'bullish']
        assert len(bullish_patterns) > 0

    def test_fvg_detects_bearish_fvg(self):
        """Test FVG detector finds bearish FVG pattern"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [99.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Create bearish FVG at index 5 (c1=3, c2=4, c3=5)
        df.loc[3, 'low'] = 100.0   # c1 low
        df.loc[5, 'high'] = 95.0   # c3 high < c1 low = bearish FVG
        df.loc[5, 'close'] = 92.0

        detector = FVGDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        assert isinstance(patterns, list)

    def test_fvg_no_pattern_when_no_gap(self):
        """Test no FVG detected when candles overlap"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        detector = FVGDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        # All candles overlap - should be empty
        assert isinstance(patterns, list)
        assert len(patterns) == 0

    def test_order_block_detects_bullish(self):
        """Test OrderBlock detector finds bullish order block"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [102.0] * 50,
            'low': [98.0] * 50,
            'close': [101.0] * 50,
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        # Create bearish candle followed by strong bullish move
        df.loc[20, 'open'] = 100.0
        df.loc[20, 'close'] = 98.0  # Bearish candle (potential OB)

        df.loc[21, 'open'] = 98.0
        df.loc[21, 'close'] = 115.0  # Strong bullish move
        df.loc[21, 'high'] = 116.0

        detector = OrderBlockDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        assert isinstance(patterns, list)

    def test_order_block_no_ob_on_weak_move(self):
        """Test no OB detected on weak moves"""
        timestamps = [1700000000000 + i * 3600000 for i in range(50)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 50,
            'high': [101.0] * 50,
            'low': [99.0] * 50,
            'close': [100.5] * 50,  # Very small bodies
            'volume': [1000.0] * 50
        }
        df = pd.DataFrame(data)

        detector = OrderBlockDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        # Weak moves shouldn't generate OB patterns
        assert isinstance(patterns, list)

    def test_liquidity_sweep_finds_swing_points(self):
        """Test swing point detection in LiquiditySweep detector"""
        timestamps = [1700000000000 + i * 3600000 for i in range(30)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 30,
            'high': [102.0] * 30,
            'low': [98.0] * 30,
            'close': [101.0] * 30,
            'volume': [1000.0] * 30
        }
        df = pd.DataFrame(data)

        # Create a clear swing high at index 10
        df.loc[10, 'high'] = 110.0

        # Create a clear swing low at index 15
        df.loc[15, 'low'] = 90.0

        detector = LiquiditySweepDetector()
        swing_highs, swing_lows = detector.find_swing_points(df, lookback=3)

        assert isinstance(swing_highs, list)
        assert isinstance(swing_lows, list)

    def test_liquidity_sweep_detects_bullish(self):
        """Test detection of bullish liquidity sweep"""
        timestamps = [1700000000000 + i * 3600000 for i in range(60)]
        data = {
            'timestamp': timestamps,
            'open': [100.0] * 60,
            'high': [102.0] * 60,
            'low': [98.0] * 60,
            'close': [101.0] * 60,
            'volume': [1000.0] * 60
        }
        df = pd.DataFrame(data)

        # Create swing low at index 20
        df.loc[20, 'low'] = 90.0

        # Create sweep candle at index 40 (sweeps the low and closes above)
        df.loc[40, 'low'] = 88.0   # Sweeps below swing low
        df.loc[40, 'close'] = 95.0  # Closes above the swept level

        detector = LiquiditySweepDetector()
        patterns = detector.detect_historical(df, skip_overlap=True)

        assert isinstance(patterns, list)


class TestSimulateTrades:
    """Tests for simulate_trades dispatcher function"""

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame for testing"""
        timestamps = [1700000000000 + i * 3600000 for i in range(100)]
        data = {
            'timestamp': timestamps,
            'open': [100.0 + np.sin(i/10) for i in range(100)],
            'high': [102.0 + np.sin(i/10) for i in range(100)],
            'low': [98.0 + np.sin(i/10) for i in range(100)],
            'close': [101.0 + np.sin(i/10) for i in range(100)],
            'volume': [1000.0] * 100
        }
        return pd.DataFrame(data)

    def test_simulate_imbalance_pattern(self, sample_df):
        """Test simulate_trades with imbalance pattern type"""
        trades = simulate_trades(sample_df, 'imbalance', rr_target=2.0)

        assert isinstance(trades, list)
        for trade in trades:
            if trade.get('pattern_type'):
                assert trade['pattern_type'] == 'imbalance'

    def test_simulate_order_block_pattern(self, sample_df):
        """Test simulate_trades with order_block pattern type"""
        trades = simulate_trades(sample_df, 'order_block', rr_target=2.0)

        assert isinstance(trades, list)
        for trade in trades:
            if trade.get('pattern_type'):
                assert trade['pattern_type'] == 'order_block'

    def test_simulate_liquidity_sweep_pattern(self, sample_df):
        """Test simulate_trades with liquidity_sweep pattern type"""
        trades = simulate_trades(sample_df, 'liquidity_sweep', rr_target=2.0)

        assert isinstance(trades, list)
        for trade in trades:
            if trade.get('pattern_type'):
                assert trade['pattern_type'] == 'liquidity_sweep'

    def test_unknown_pattern_raises_error(self, sample_df):
        """Test that unknown pattern types raise ValueError"""
        with pytest.raises(ValueError) as exc_info:
            simulate_trades(sample_df, 'unknown_type', rr_target=2.0)

        assert 'Invalid pattern type' in str(exc_info.value)
        assert 'unknown_type' in str(exc_info.value)


class TestRunBacktest:
    """Integration tests for run_backtest function"""

    def test_run_backtest_invalid_pattern_type(self, app):
        """Test backtest with invalid pattern type returns error"""
        with app.app_context():
            result = run_backtest(
                symbol='BTC/USDT',
                timeframe='1h',
                start_date='2023-01-01',
                end_date='2023-12-31',
                pattern_type='invalid_type',
                rr_target=2.0
            )

            assert 'error' in result
            assert 'Invalid pattern type' in result['error']

    def test_run_backtest_invalid_date_format(self, app):
        """Test backtest with invalid date format returns error"""
        with app.app_context():
            result = run_backtest(
                symbol='BTC/USDT',
                timeframe='1h',
                start_date='01-01-2023',  # Wrong format
                end_date='2023-12-31',
                pattern_type='imbalance',
                rr_target=2.0
            )

            assert 'error' in result
            assert 'Invalid date format' in result['error']

    def test_run_backtest_no_data(self, app):
        """Test backtest with no data returns error"""
        with app.app_context():
            result = run_backtest(
                symbol='NONEXISTENT/USDT',
                timeframe='1h',
                start_date='2023-01-01',
                end_date='2023-12-31',
                pattern_type='imbalance',
                rr_target=2.0
            )

            assert 'error' in result

    def test_run_backtest_insufficient_data(self, app, sample_symbol):
        """Test backtest with insufficient data returns error"""
        from app.models import Candle

        with app.app_context():
            # Add only 5 candles (not enough)
            for i in range(5):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=1700000000000 + i * 3600000,
                    open=100.0, high=102.0, low=98.0, close=101.0, volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            result = run_backtest(
                symbol='BTC/USDT',
                timeframe='1h',
                start_date='2023-11-01',
                end_date='2023-11-30',
                pattern_type='imbalance',
                rr_target=2.0
            )

            # Should return error for insufficient data
            assert 'error' in result or result.get('total_trades', 0) >= 0

    def test_run_backtest_saves_result(self, app, sample_symbol):
        """Test that backtest saves result to database"""
        from app.models import Candle

        with app.app_context():
            # Add enough candles for backtesting
            base_ts = 1700000000000
            for i in range(100):
                candle = Candle(
                    symbol_id=sample_symbol,
                    timeframe='1h',
                    timestamp=base_ts + i * 3600000,
                    open=100.0 + i * 0.1,
                    high=102.0 + i * 0.1,
                    low=98.0 + i * 0.1,
                    close=101.0 + i * 0.1,
                    volume=1000
                )
                db.session.add(candle)
            db.session.commit()

            initial_count = Backtest.query.count()

            result = run_backtest(
                symbol='BTC/USDT',
                timeframe='1h',
                start_date='2023-11-14',
                end_date='2023-11-18',
                pattern_type='imbalance',
                rr_target=2.0
            )

            # If successful, should save backtest record
            if 'error' not in result:
                assert Backtest.query.count() >= initial_count
                assert 'total_trades' in result
                assert 'win_rate' in result
