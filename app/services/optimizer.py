"""
Parameter Optimizer Service
Automated parameter sweep for backtesting optimization

Performance optimizations:
- Pattern detection cached per symbol/timeframe/pattern_type
- Vectorized trade simulation using numpy
- Batch DB commits every 50 runs
- Progress saved frequently for resumability
"""
import json
import itertools
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from app import db
from app.models import (
    OptimizationJob, OptimizationRun,
    DEFAULT_PARAMETER_GRID, QUICK_PARAMETER_GRID,
    Symbol
)
from app.services.aggregator import get_candles_as_dataframe
from app.services.patterns.fair_value_gap import FVGDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector
from app.services.logger import log_system

# Detector instances (reuse to avoid re-initialization)
_detectors = {
    'imbalance': FVGDetector(),
    'order_block': OrderBlockDetector(),
    'liquidity_sweep': LiquiditySweepDetector(),
}

# Batch commit size - balance between performance and data safety
BATCH_COMMIT_SIZE = 50


class ParameterOptimizer:
    """Automated parameter sweep for backtesting"""

    def __init__(self):
        self.current_job = None

    def create_job(
        self,
        name: str,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        start_date: str,
        end_date: str,
        parameter_grid: Dict = None,
        description: str = None
    ) -> OptimizationJob:
        """
        Create a new optimization job.

        Args:
            name: Job name
            symbols: List of trading pairs
            timeframes: List of timeframes
            pattern_types: List of pattern types
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            parameter_grid: Optional custom parameter grid
            description: Optional job description

        Returns:
            Created OptimizationJob
        """
        if parameter_grid is None:
            parameter_grid = QUICK_PARAMETER_GRID

        # Calculate total combinations
        param_combinations = list(itertools.product(*parameter_grid.values()))
        scope_combinations = len(symbols) * len(timeframes) * len(pattern_types)
        total_runs = len(param_combinations) * scope_combinations

        job = OptimizationJob(
            name=name,
            description=description,
            status='pending',
            symbols=json.dumps(symbols),
            timeframes=json.dumps(timeframes),
            pattern_types=json.dumps(pattern_types),
            start_date=start_date,
            end_date=end_date,
            parameter_grid=json.dumps(parameter_grid),
            total_runs=total_runs,
            completed_runs=0,
            failed_runs=0,
        )
        db.session.add(job)
        db.session.commit()

        log_system(f"Created optimization job '{name}' with {total_runs} runs")

        return job

    def run_job(self, job_id: int, progress_callback=None) -> Dict:
        """
        Execute all runs for a job.

        Optimized approach:
        1. Load candle data once per symbol/timeframe
        2. Cache pattern detection per symbol/timeframe/pattern_type
        3. Only vary parameters for trade simulation
        4. Batch DB commits for performance
        5. Save progress frequently for resumability

        Args:
            job_id: Job ID to execute
            progress_callback: Optional callback(completed, total) for progress updates

        Returns:
            Summary dict with results
        """
        job = OptimizationJob.query.get(job_id)
        if not job:
            return {'error': f'Job {job_id} not found'}

        if job.status not in ['pending', 'failed']:
            return {'error': f'Job {job_id} is already {job.status}'}

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()

        log_system(f"Starting optimization job {job_id}: {job.name}")

        symbols = job.symbols_list
        timeframes = job.timeframes_list
        pattern_types = job.pattern_types_list
        param_grid = job.parameter_grid_dict

        # Generate all parameter combinations
        param_keys = list(param_grid.keys())
        param_combinations = list(itertools.product(*param_grid.values()))

        completed = 0
        failed = 0
        best_result = None
        best_profit = float('-inf')
        pending_commits = 0

        # Pattern cache: (symbol, timeframe, pattern_type, min_zone_pct, use_overlap) -> patterns
        pattern_cache = {}

        try:
            # Iterate through all scope combinations
            for symbol in symbols:
                for timeframe in timeframes:
                    # Load data once for this symbol/timeframe
                    df = self._get_candle_data(symbol, timeframe, job.start_date, job.end_date)

                    if df is None or len(df) < 20:
                        # Mark all runs for this scope as failed
                        for pattern_type in pattern_types:
                            for params in param_combinations:
                                self._create_failed_run(
                                    job, symbol, timeframe, pattern_type,
                                    dict(zip(param_keys, params)),
                                    "Insufficient data"
                                )
                                failed += 1
                                pending_commits += 1
                        continue

                    # Convert DataFrame to numpy arrays once for faster trade simulation
                    ohlcv_arrays = self._df_to_arrays(df)

                    for pattern_type in pattern_types:
                        detector = _detectors.get(pattern_type)
                        if not detector:
                            for params in param_combinations:
                                self._create_failed_run(
                                    job, symbol, timeframe, pattern_type,
                                    dict(zip(param_keys, params)),
                                    f"Unknown pattern type: {pattern_type}"
                                )
                                failed += 1
                                pending_commits += 1
                            continue

                        for params in param_combinations:
                            param_dict = dict(zip(param_keys, params))

                            # Get cached patterns or detect new ones
                            min_zone_pct = param_dict.get('min_zone_pct', 0.15)
                            use_overlap = param_dict.get('use_overlap', True)
                            cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)

                            if cache_key not in pattern_cache:
                                patterns = detector.detect_historical(
                                    df,
                                    min_zone_pct=min_zone_pct,
                                    skip_overlap=not use_overlap
                                )
                                pattern_cache[cache_key] = patterns
                            else:
                                patterns = pattern_cache[cache_key]

                            try:
                                result = self._run_single_optimization_fast(
                                    job, ohlcv_arrays, symbol, timeframe, pattern_type,
                                    patterns, param_dict
                                )
                                completed += 1
                                pending_commits += 1

                                # Track best result
                                if result and result.total_profit_pct > best_profit:
                                    best_profit = result.total_profit_pct
                                    best_result = result

                            except Exception as e:
                                self._create_failed_run(
                                    job, symbol, timeframe, pattern_type,
                                    param_dict, str(e)
                                )
                                failed += 1
                                pending_commits += 1

                            # Update progress
                            job.completed_runs = completed
                            job.failed_runs = failed
                            if progress_callback:
                                progress_callback(completed + failed, job.total_runs)

                            # Batch commit for performance (every BATCH_COMMIT_SIZE runs)
                            if pending_commits >= BATCH_COMMIT_SIZE:
                                db.session.commit()
                                pending_commits = 0

            # Final commit for any remaining
            if pending_commits > 0:
                db.session.commit()

            # Update best params
            if best_result:
                job.best_params = {
                    'params': best_result.params_dict,
                    'symbol': best_result.symbol,
                    'timeframe': best_result.timeframe,
                    'pattern_type': best_result.pattern_type,
                    'win_rate': best_result.win_rate,
                    'total_profit_pct': best_result.total_profit_pct,
                    'total_trades': best_result.total_trades,
                }

            job.status = 'completed'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()

            log_system(
                f"Completed optimization job {job_id}: {completed} completed, {failed} failed"
            )

            return {
                'success': True,
                'job_id': job_id,
                'completed': completed,
                'failed': failed,
                'best_params': job.best_params,
            }

        except Exception as e:
            job.status = 'failed'
            db.session.commit()
            log_system(f"Optimization job {job_id} failed: {str(e)}", level='ERROR')
            return {'error': str(e)}

    def _get_candle_data(
        self, symbol: str, timeframe: str, start_date: str = None, end_date: str = None
    ) -> Optional[pd.DataFrame]:
        """
        Get candle data for a symbol/timeframe.

        Uses verified candles only to ensure backtest accuracy.
        Falls back to all candles if no verified candles exist.
        No date filtering - uses ALL available candles.
        """
        try:
            # Try verified candles first (recommended for accurate backtesting)
            df = get_candles_as_dataframe(symbol, timeframe, verified_only=True)

            if df.empty:
                # Fallback to all candles if no verified data exists
                df = get_candles_as_dataframe(symbol, timeframe, verified_only=False)

            if df.empty:
                return None

            # No date filtering - use ALL available candles
            return df if len(df) >= 20 else None

        except Exception:
            return None

    def _df_to_arrays(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Convert DataFrame to numpy arrays for faster access in trade simulation"""
        return {
            'timestamp': df['timestamp'].values,
            'open': df['open'].values,
            'high': df['high'].values,
            'low': df['low'].values,
            'close': df['close'].values,
        }

    def _run_single_optimization_fast(
        self,
        job: OptimizationJob,
        ohlcv: Dict[str, np.ndarray],
        symbol: str,
        timeframe: str,
        pattern_type: str,
        patterns: List[Dict],
        params: Dict
    ) -> OptimizationRun:
        """
        Run a single optimization with specific parameters using pre-computed patterns.
        Uses numpy arrays for faster trade simulation.
        """
        # Simulate trades using vectorized numpy operations
        trades = self._simulate_trades_fast(ohlcv, patterns, params)

        # Calculate statistics
        stats = self._calculate_statistics(trades)

        # Create run record
        run = OptimizationRun(
            job_id=job.id,
            symbol=symbol,
            timeframe=timeframe,
            pattern_type=pattern_type,
            start_date=job.start_date,
            end_date=job.end_date,
            rr_target=params.get('rr_target', 2.0),
            sl_buffer_pct=params.get('sl_buffer_pct', 10.0),
            tp_method=params.get('tp_method', 'fixed_rr'),
            entry_method=params.get('entry_method', 'zone_edge'),
            min_zone_pct=params.get('min_zone_pct', 0.15),
            use_overlap=params.get('use_overlap', True),
            status='completed',
            total_trades=stats['total_trades'],
            winning_trades=stats['winning_trades'],
            losing_trades=stats['losing_trades'],
            win_rate=stats['win_rate'],
            avg_rr=stats['avg_rr'],
            total_profit_pct=stats['total_profit_pct'],
            max_drawdown=stats['max_drawdown'],
            sharpe_ratio=stats['sharpe_ratio'],
            profit_factor=stats['profit_factor'],
            avg_trade_duration=stats['avg_duration'],
            results_json=json.dumps(trades[:100]),  # Store first 100 trades
        )
        db.session.add(run)

        return run

    def _simulate_trades_fast(
        self,
        ohlcv: Dict[str, np.ndarray],
        patterns: List[Dict],
        params: Dict
    ) -> List[Dict]:
        """
        Simulate trades using numpy arrays for faster execution.
        This is the performance-critical function optimized with vectorized operations.
        """
        trades = []
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0) / 100.0
        entry_method = params.get('entry_method', 'zone_edge')

        highs = ohlcv['high']
        lows = ohlcv['low']
        timestamps = ohlcv['timestamp']
        n_candles = len(highs)

        for pattern in patterns:
            entry_idx = pattern['detected_at']
            if entry_idx + 10 >= n_candles:
                continue

            zone_high = pattern['zone_high']
            zone_low = pattern['zone_low']
            zone_size = zone_high - zone_low
            buffer = zone_size * sl_buffer_pct

            # Calculate entry, SL, TP based on entry method
            if pattern['direction'] == 'bullish':
                if entry_method == 'zone_mid':
                    entry = (zone_high + zone_low) / 2
                else:  # zone_edge
                    entry = zone_high

                stop_loss = zone_low - buffer
                risk = entry - stop_loss
                take_profit = entry + (risk * rr_target)
                direction = 'long'
            else:
                if entry_method == 'zone_mid':
                    entry = (zone_high + zone_low) / 2
                else:  # zone_edge
                    entry = zone_low

                stop_loss = zone_high + buffer
                risk = stop_loss - entry
                take_profit = entry - (risk * rr_target)
                direction = 'short'

            # Simulate trade outcome using numpy slicing
            trade = self._simulate_single_trade_fast(
                highs, lows, timestamps, entry_idx, entry, stop_loss, take_profit,
                direction, rr_target, n_candles
            )
            if trade:
                trades.append(trade)

        return trades

    def _simulate_single_trade_fast(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        timestamps: np.ndarray,
        entry_idx: int,
        entry: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        rr_target: float,
        n_candles: int
    ) -> Optional[Dict]:
        """Simulate a single trade using numpy arrays for speed"""
        entry_triggered = False
        entry_candle = None

        for j in range(entry_idx + 1, n_candles):
            if not entry_triggered:
                if direction == 'long':
                    if lows[j] <= entry:
                        entry_triggered = True
                        entry_candle = j
                else:
                    if highs[j] >= entry:
                        entry_triggered = True
                        entry_candle = j
            else:
                # Check for SL or TP
                if direction == 'long':
                    if lows[j] <= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': int(timestamps[entry_candle]),
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif highs[j] >= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': int(timestamps[entry_candle]),
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                else:
                    if highs[j] >= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': int(timestamps[entry_candle]),
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif lows[j] <= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': int(timestamps[entry_candle]),
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }

        return None

    def _run_single_optimization(
        self,
        job: OptimizationJob,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        pattern_type: str,
        detector,
        params: Dict
    ) -> OptimizationRun:
        """Run a single optimization with specific parameters"""
        # Detect patterns
        use_overlap = params.get('use_overlap', True)
        min_zone_pct = params.get('min_zone_pct', 0.15)

        patterns = detector.detect_historical(
            df,
            min_zone_pct=min_zone_pct,
            skip_overlap=not use_overlap
        )

        # Simulate trades
        trades = self._simulate_trades(df, patterns, params)

        # Calculate statistics
        stats = self._calculate_statistics(trades)

        # Create run record
        run = OptimizationRun(
            job_id=job.id,
            symbol=symbol,
            timeframe=timeframe,
            pattern_type=pattern_type,
            start_date=job.start_date,
            end_date=job.end_date,
            rr_target=params.get('rr_target', 2.0),
            sl_buffer_pct=params.get('sl_buffer_pct', 10.0),
            tp_method=params.get('tp_method', 'fixed_rr'),
            entry_method=params.get('entry_method', 'zone_edge'),
            min_zone_pct=min_zone_pct,
            use_overlap=use_overlap,
            status='completed',
            total_trades=stats['total_trades'],
            winning_trades=stats['winning_trades'],
            losing_trades=stats['losing_trades'],
            win_rate=stats['win_rate'],
            avg_rr=stats['avg_rr'],
            total_profit_pct=stats['total_profit_pct'],
            max_drawdown=stats['max_drawdown'],
            sharpe_ratio=stats['sharpe_ratio'],
            profit_factor=stats['profit_factor'],
            avg_trade_duration=stats['avg_duration'],
            results_json=json.dumps(trades[:100]),  # Store first 100 trades
        )
        db.session.add(run)

        return run

    def _create_failed_run(
        self,
        job: OptimizationJob,
        symbol: str,
        timeframe: str,
        pattern_type: str,
        params: Dict,
        error_message: str
    ) -> OptimizationRun:
        """Create a failed run record"""
        run = OptimizationRun(
            job_id=job.id,
            symbol=symbol,
            timeframe=timeframe,
            pattern_type=pattern_type,
            start_date=job.start_date,
            end_date=job.end_date,
            rr_target=params.get('rr_target', 2.0),
            sl_buffer_pct=params.get('sl_buffer_pct', 10.0),
            tp_method=params.get('tp_method', 'fixed_rr'),
            entry_method=params.get('entry_method', 'zone_edge'),
            min_zone_pct=params.get('min_zone_pct', 0.15),
            use_overlap=params.get('use_overlap', True),
            status='failed',
            error_message=error_message,
        )
        db.session.add(run)
        return run

    def _simulate_trades(self, df: pd.DataFrame, patterns: List[Dict], params: Dict) -> List[Dict]:
        """Simulate trades for detected patterns"""
        trades = []
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0) / 100.0
        entry_method = params.get('entry_method', 'zone_edge')

        for pattern in patterns:
            entry_idx = pattern['detected_at']
            if entry_idx + 10 >= len(df):
                continue

            zone_high = pattern['zone_high']
            zone_low = pattern['zone_low']
            zone_size = zone_high - zone_low
            buffer = zone_size * sl_buffer_pct

            # Calculate entry, SL, TP based on entry method
            if pattern['direction'] == 'bullish':
                if entry_method == 'zone_mid':
                    entry = (zone_high + zone_low) / 2
                else:  # zone_edge
                    entry = zone_high

                stop_loss = zone_low - buffer
                risk = entry - stop_loss
                take_profit = entry + (risk * rr_target)
                direction = 'long'
            else:
                if entry_method == 'zone_mid':
                    entry = (zone_high + zone_low) / 2
                else:  # zone_edge
                    entry = zone_low

                stop_loss = zone_high + buffer
                risk = stop_loss - entry
                take_profit = entry - (risk * rr_target)
                direction = 'short'

            # Simulate trade outcome
            trade = self._simulate_single_trade(
                df, entry_idx, entry, stop_loss, take_profit, direction, rr_target
            )
            if trade:
                trades.append(trade)

        return trades

    def _simulate_single_trade(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        entry: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        rr_target: float
    ) -> Optional[Dict]:
        """Simulate a single trade"""
        entry_triggered = False
        entry_candle = None

        for j in range(entry_idx + 1, len(df)):
            candle = df.iloc[j]

            if not entry_triggered:
                if direction == 'long':
                    if candle['low'] <= entry:
                        entry_triggered = True
                        entry_candle = j
                else:
                    if candle['high'] >= entry:
                        entry_triggered = True
                        entry_candle = j
            else:
                # Check for SL or TP
                if direction == 'long':
                    if candle['low'] <= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': int(df.iloc[entry_candle]['timestamp']),
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif candle['high'] >= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': int(df.iloc[entry_candle]['timestamp']),
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                else:
                    if candle['high'] >= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': int(df.iloc[entry_candle]['timestamp']),
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif candle['low'] <= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': int(df.iloc[entry_candle]['timestamp']),
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }

        return None

    def _calculate_statistics(self, trades: List[Dict]) -> Dict:
        """Calculate performance statistics from trades"""
        if not trades:
            return {
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
            }

        winning = [t for t in trades if t['result'] == 'win']
        losing = [t for t in trades if t['result'] == 'loss']

        total_trades = len(trades)
        winning_trades = len(winning)
        losing_trades = len(losing)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # Average R:R
        avg_rr = sum(t['rr_achieved'] for t in trades) / total_trades if total_trades > 0 else 0

        # Total profit
        profits = [t['profit_pct'] for t in trades]
        total_profit_pct = sum(profits)

        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cumulative += t['profit_pct']
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        # Sharpe ratio (simplified)
        if len(profits) > 1:
            returns_std = np.std(profits)
            avg_return = np.mean(profits)
            sharpe_ratio = (avg_return / returns_std) if returns_std > 0 else 0
        else:
            sharpe_ratio = 0

        # Profit factor
        gross_wins = sum(t['profit_pct'] for t in winning) if winning else 0
        gross_losses = abs(sum(t['profit_pct'] for t in losing)) if losing else 1
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else gross_wins

        # Average duration
        avg_duration = sum(t['duration_candles'] for t in trades) / total_trades if total_trades > 0 else 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),
            'avg_rr': round(avg_rr, 2),
            'total_profit_pct': round(total_profit_pct, 2),
            'max_drawdown': round(max_dd, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'profit_factor': round(profit_factor, 2),
            'avg_duration': round(avg_duration, 1),
        }

    def get_best_params(
        self,
        symbol: str = None,
        pattern_type: str = None,
        timeframe: str = None,
        metric: str = 'total_profit_pct',
        min_trades: int = 10
    ) -> Optional[Dict]:
        """
        Get best parameters from completed runs.

        Args:
            symbol: Filter by symbol (optional)
            pattern_type: Filter by pattern type (optional)
            timeframe: Filter by timeframe (optional)
            metric: Metric to optimize ('total_profit_pct', 'win_rate', 'sharpe_ratio', 'profit_factor')
            min_trades: Minimum trades required

        Returns:
            Dict with best parameters and results
        """
        query = OptimizationRun.query.filter(
            OptimizationRun.status == 'completed',
            OptimizationRun.total_trades >= min_trades
        )

        if symbol:
            query = query.filter(OptimizationRun.symbol == symbol)
        if pattern_type:
            query = query.filter(OptimizationRun.pattern_type == pattern_type)
        if timeframe:
            query = query.filter(OptimizationRun.timeframe == timeframe)

        # Order by metric
        if metric == 'win_rate':
            query = query.order_by(OptimizationRun.win_rate.desc())
        elif metric == 'sharpe_ratio':
            query = query.order_by(OptimizationRun.sharpe_ratio.desc())
        elif metric == 'profit_factor':
            query = query.order_by(OptimizationRun.profit_factor.desc())
        else:  # default: total_profit_pct
            query = query.order_by(OptimizationRun.total_profit_pct.desc())

        best_run = query.first()

        if not best_run:
            return None

        return {
            'run_id': best_run.id,
            'symbol': best_run.symbol,
            'timeframe': best_run.timeframe,
            'pattern_type': best_run.pattern_type,
            'params': best_run.params_dict,
            'total_trades': best_run.total_trades,
            'win_rate': best_run.win_rate,
            'total_profit_pct': best_run.total_profit_pct,
            'max_drawdown': best_run.max_drawdown,
            'sharpe_ratio': best_run.sharpe_ratio,
            'profit_factor': best_run.profit_factor,
        }

    def get_job_summary(self, job_id: int) -> Optional[Dict]:
        """Get summary of a job's results"""
        job = OptimizationJob.query.get(job_id)
        if not job:
            return None

        # Get top runs by profit
        top_by_profit = OptimizationRun.query.filter(
            OptimizationRun.job_id == job_id,
            OptimizationRun.status == 'completed',
            OptimizationRun.total_trades >= 5
        ).order_by(
            OptimizationRun.total_profit_pct.desc()
        ).limit(10).all()

        # Get top runs by win rate
        top_by_winrate = OptimizationRun.query.filter(
            OptimizationRun.job_id == job_id,
            OptimizationRun.status == 'completed',
            OptimizationRun.total_trades >= 5
        ).order_by(
            OptimizationRun.win_rate.desc()
        ).limit(10).all()

        return {
            'job': job.to_dict(),
            'top_by_profit': [r.to_dict() for r in top_by_profit],
            'top_by_winrate': [r.to_dict() for r in top_by_winrate],
        }

    def run_incremental(
        self,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        parameter_grid: Dict = None,
        progress_callback=None
    ) -> Dict:
        """
        Run incremental optimization - only process new candles since last run.

        Performance optimizations (matching full optimization):
        1. Load candle data once per symbol/timeframe (not per parameter!)
        2. Cache pattern detection per (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)
        3. Use numpy arrays for fast trade simulation
        4. Batch DB commits every 50 runs
        5. Pre-load existing runs into dict for O(1) lookups (instead of individual DB queries)

        Returns:
            Summary dict with results
        """
        if parameter_grid is None:
            parameter_grid = QUICK_PARAMETER_GRID

        param_keys = list(parameter_grid.keys())
        param_combinations = list(itertools.product(*parameter_grid.values()))

        updated = 0
        new_runs = 0
        skipped = 0
        errors = 0
        pending_commits = 0
        best_result = None
        best_profit = float('-inf')

        total = len(symbols) * len(timeframes) * len(pattern_types) * len(param_combinations)
        processed = 0

        log_system(f"Starting incremental optimization for {len(symbols)} symbols")

        # Pre-load all existing runs into a dict for O(1) lookups (major performance optimization)
        # Key: (symbol, timeframe, pattern_type, rr_target, sl_buffer_pct) -> OptimizationRun
        existing_runs = {}
        all_existing = OptimizationRun.query.filter(
            OptimizationRun.symbol.in_(symbols),
            OptimizationRun.timeframe.in_(timeframes),
            OptimizationRun.pattern_type.in_(pattern_types),
            OptimizationRun.status == 'completed'
        ).all()
        for run in all_existing:
            key = (run.symbol, run.timeframe, run.pattern_type, run.rr_target, run.sl_buffer_pct)
            existing_runs[key] = run

        # Pattern cache: (symbol, timeframe, pattern_type, min_zone_pct, use_overlap) -> patterns
        pattern_cache = {}
        # Data cache: (symbol, timeframe) -> (df, ohlcv_arrays, last_candle_ts)
        data_cache = {}

        for symbol in symbols:
            for timeframe in timeframes:
                # Load data ONCE per symbol/timeframe (major optimization)
                cache_key = (symbol, timeframe)
                if cache_key not in data_cache:
                    df = get_candles_as_dataframe(symbol, timeframe, verified_only=True)
                    if df is None or df.empty:
                        df = get_candles_as_dataframe(symbol, timeframe, verified_only=False)

                    if df is None or df.empty or len(df) < 20:
                        data_cache[cache_key] = (None, None, None)
                    else:
                        ohlcv_arrays = self._df_to_arrays(df)
                        last_candle_ts = int(df['timestamp'].max())
                        data_cache[cache_key] = (df, ohlcv_arrays, last_candle_ts)

                df, ohlcv_arrays, last_candle_ts = data_cache[cache_key]

                if df is None:
                    # Skip all runs for this scope
                    skipped += len(pattern_types) * len(param_combinations)
                    processed += len(pattern_types) * len(param_combinations)
                    if progress_callback:
                        progress_callback(processed, total)
                    continue

                for pattern_type in pattern_types:
                    detector = _detectors.get(pattern_type)
                    if not detector:
                        errors += len(param_combinations)
                        processed += len(param_combinations)
                        continue

                    for params in param_combinations:
                        param_dict = dict(zip(param_keys, params))
                        processed += 1

                        try:
                            # Get cached patterns or detect new ones
                            min_zone_pct = param_dict.get('min_zone_pct', 0.15)
                            use_overlap = param_dict.get('use_overlap', True)
                            pattern_cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)

                            if pattern_cache_key not in pattern_cache:
                                patterns = detector.detect_historical(
                                    df,
                                    min_zone_pct=min_zone_pct,
                                    skip_overlap=not use_overlap
                                )
                                pattern_cache[pattern_cache_key] = patterns
                            else:
                                patterns = pattern_cache[pattern_cache_key]

                            # Lookup existing run from pre-loaded dict (O(1) instead of DB query)
                            rr_target = param_dict.get('rr_target', 2.0)
                            sl_buffer_pct = param_dict.get('sl_buffer_pct', 10.0)
                            existing_key = (symbol, timeframe, pattern_type, rr_target, sl_buffer_pct)
                            existing = existing_runs.get(existing_key)

                            result, run = self._run_incremental_single_fast(
                                symbol, timeframe, pattern_type,
                                df, ohlcv_arrays, last_candle_ts, patterns, param_dict,
                                existing
                            )

                            if result == 'updated':
                                updated += 1
                            elif result == 'new':
                                new_runs += 1
                                # Add new run to cache for future lookups
                                if run:
                                    existing_runs[existing_key] = run
                            else:
                                skipped += 1

                            # Track best result
                            if run and run.total_profit_pct is not None and run.total_profit_pct > best_profit:
                                best_profit = run.total_profit_pct
                                best_result = run

                            pending_commits += 1

                        except Exception as e:
                            log_system(
                                f"Incremental error {symbol}/{timeframe}/{pattern_type}: {e}",
                                level='ERROR'
                            )
                            errors += 1

                        if progress_callback:
                            progress_callback(processed, total)

                        # Batch commit for performance (every BATCH_COMMIT_SIZE runs)
                        if pending_commits >= BATCH_COMMIT_SIZE:
                            db.session.commit()
                            pending_commits = 0

        # Final commit for any remaining
        if pending_commits > 0:
            db.session.commit()

        log_system(
            f"Incremental optimization complete: {updated} updated, {new_runs} new, "
            f"{skipped} skipped, {errors} errors"
        )

        # Build best result dict
        best_result_dict = None
        if best_result:
            best_result_dict = {
                'symbol': best_result.symbol,
                'timeframe': best_result.timeframe,
                'pattern_type': best_result.pattern_type,
                'rr_target': best_result.rr_target,
                'sl_buffer_pct': best_result.sl_buffer_pct,
                'win_rate': best_result.win_rate,
                'total_profit_pct': best_result.total_profit_pct,
                'total_trades': best_result.total_trades,
            }

        return {
            'success': True,
            'updated': updated,
            'new_runs': new_runs,
            'skipped': skipped,
            'errors': errors,
            'total': total,
            'best_result': best_result_dict,
        }

    def _run_incremental_single(
        self,
        symbol: str,
        timeframe: str,
        pattern_type: str,
        detector,
        params: Dict
    ) -> str:
        """
        Run incremental optimization for a single parameter combination.

        Returns:
            'updated' - existing run was updated with new data
            'new' - no existing run, created new one
            'skipped' - no new data available
        """
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0)

        # Find existing run
        existing = OptimizationRun.find_existing(
            symbol, timeframe, pattern_type, rr_target, sl_buffer_pct
        )

        # Get all available VERIFIED candles (for accurate incremental updates)
        df = get_candles_as_dataframe(symbol, timeframe, verified_only=True)
        if df is None or df.empty:
            # Fallback to all candles if no verified data
            df = get_candles_as_dataframe(symbol, timeframe, verified_only=False)
        if df is None or df.empty or len(df) < 20:
            return 'skipped'

        last_candle_ts = int(df['timestamp'].max())

        if existing and existing.last_candle_timestamp:
            # Check if we have new data
            if last_candle_ts <= existing.last_candle_timestamp:
                return 'skipped'

            # Get only new candles (plus some overlap for open trades)
            overlap_candles = 100  # Look back for resolving open trades
            new_df = df[df['timestamp'] > existing.last_candle_timestamp - (overlap_candles * self._get_timeframe_ms(timeframe))]

            if len(new_df) < 5:
                return 'skipped'

            # Resolve open trades
            open_trades = existing.open_trades
            resolved_trades, still_open = self._resolve_open_trades(
                new_df, open_trades, rr_target
            )

            # Detect new patterns from new data only
            new_patterns_df = df[df['timestamp'] > existing.last_candle_timestamp]
            if len(new_patterns_df) >= 20:
                new_patterns = detector.detect_historical(
                    new_patterns_df,
                    min_zone_pct=params.get('min_zone_pct', 0.15),
                    skip_overlap=not params.get('use_overlap', True)
                )

                # Simulate new trades
                new_trades, new_open = self._simulate_trades_with_open(
                    df, new_patterns, params, existing.last_candle_timestamp
                )
            else:
                new_trades = []
                new_open = []

            # Merge results
            all_closed_trades = (existing.results or []) + resolved_trades + new_trades
            all_open_trades = still_open + new_open

            # Recalculate statistics
            stats = self._calculate_statistics(all_closed_trades)

            # Update existing run
            existing.total_trades = stats['total_trades']
            existing.winning_trades = stats['winning_trades']
            existing.losing_trades = stats['losing_trades']
            existing.win_rate = stats['win_rate']
            existing.avg_rr = stats['avg_rr']
            existing.total_profit_pct = stats['total_profit_pct']
            existing.max_drawdown = stats['max_drawdown']
            existing.sharpe_ratio = stats['sharpe_ratio']
            existing.profit_factor = stats['profit_factor']
            existing.avg_trade_duration = stats['avg_duration']
            existing.results_json = json.dumps(all_closed_trades[-100:])
            existing.open_trades = all_open_trades
            existing.last_candle_timestamp = last_candle_ts
            existing.end_date = datetime.fromtimestamp(last_candle_ts / 1000).strftime('%Y-%m-%d')
            existing.updated_at = datetime.now(timezone.utc)
            existing.is_incremental = True

            return 'updated'

        else:
            # No existing run - create new one
            start_ts = int(df['timestamp'].min())
            start_date = datetime.fromtimestamp(start_ts / 1000).strftime('%Y-%m-%d')
            end_date = datetime.fromtimestamp(last_candle_ts / 1000).strftime('%Y-%m-%d')

            patterns = detector.detect_historical(
                df,
                min_zone_pct=params.get('min_zone_pct', 0.15),
                skip_overlap=not params.get('use_overlap', True)
            )

            trades, open_trades = self._simulate_trades_with_open(df, patterns, params)
            stats = self._calculate_statistics(trades)

            run = OptimizationRun(
                job_id=None,  # No job for incremental runs
                symbol=symbol,
                timeframe=timeframe,
                pattern_type=pattern_type,
                start_date=start_date,
                end_date=end_date,
                rr_target=rr_target,
                sl_buffer_pct=sl_buffer_pct,
                tp_method=params.get('tp_method', 'fixed_rr'),
                entry_method=params.get('entry_method', 'zone_edge'),
                min_zone_pct=params.get('min_zone_pct', 0.15),
                use_overlap=params.get('use_overlap', True),
                status='completed',
                total_trades=stats['total_trades'],
                winning_trades=stats['winning_trades'],
                losing_trades=stats['losing_trades'],
                win_rate=stats['win_rate'],
                avg_rr=stats['avg_rr'],
                total_profit_pct=stats['total_profit_pct'],
                max_drawdown=stats['max_drawdown'],
                sharpe_ratio=stats['sharpe_ratio'],
                profit_factor=stats['profit_factor'],
                avg_trade_duration=stats['avg_duration'],
                results_json=json.dumps(trades[-100:]),
                open_trades_json=json.dumps(open_trades),
                last_candle_timestamp=last_candle_ts,
                is_incremental=True,
            )
            db.session.add(run)

            return 'new'

    def _run_incremental_single_fast(
        self,
        symbol: str,
        timeframe: str,
        pattern_type: str,
        df: pd.DataFrame,
        ohlcv: Dict[str, np.ndarray],
        last_candle_ts: int,
        patterns: List[Dict],
        params: Dict,
        existing: Optional[OptimizationRun] = None
    ) -> Tuple[str, Optional[OptimizationRun]]:
        """
        Fast incremental optimization using pre-loaded data and cached patterns.
        Uses numpy arrays for trade simulation (matching full optimization speed).

        Args:
            existing: Pre-loaded existing run (from batch lookup) or None

        Returns:
            Tuple of (status, run):
            - ('updated', run) - existing run was updated with new data
            - ('new', run) - no existing run, created new one
            - ('skipped', existing_run) - no new data available
        """
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0)

        if existing and existing.last_candle_timestamp:
            # Check if we have new data
            if last_candle_ts <= existing.last_candle_timestamp:
                return ('skipped', existing)

            # Get only new candles for pattern detection (using df for indexing)
            new_mask = df['timestamp'] > existing.last_candle_timestamp
            new_candle_count = new_mask.sum()

            if new_candle_count < 5:
                return ('skipped', existing)

            # Resolve open trades using numpy arrays (fast)
            open_trades = existing.open_trades
            resolved_trades, still_open = self._resolve_open_trades_fast(
                ohlcv, open_trades, existing.last_candle_timestamp
            )

            # Detect new patterns from new data only
            new_patterns_df = df[new_mask]
            if len(new_patterns_df) >= 20:
                # Filter patterns to only those in new data range
                new_patterns = [p for p in patterns
                               if p['detected_at'] < len(df) and
                               df.iloc[p['detected_at']]['timestamp'] > existing.last_candle_timestamp]

                # Simulate new trades using numpy (fast)
                new_trades, new_open = self._simulate_trades_with_open_fast(
                    ohlcv, new_patterns, params, existing.last_candle_timestamp
                )
            else:
                new_trades = []
                new_open = []

            # Merge results
            all_closed_trades = (existing.results or []) + resolved_trades + new_trades
            all_open_trades = still_open + new_open

            # Recalculate statistics
            stats = self._calculate_statistics(all_closed_trades)

            # Update existing run
            existing.total_trades = stats['total_trades']
            existing.winning_trades = stats['winning_trades']
            existing.losing_trades = stats['losing_trades']
            existing.win_rate = stats['win_rate']
            existing.avg_rr = stats['avg_rr']
            existing.total_profit_pct = stats['total_profit_pct']
            existing.max_drawdown = stats['max_drawdown']
            existing.sharpe_ratio = stats['sharpe_ratio']
            existing.profit_factor = stats['profit_factor']
            existing.avg_trade_duration = stats['avg_duration']
            existing.results_json = json.dumps(all_closed_trades[-100:])
            existing.open_trades = all_open_trades
            existing.last_candle_timestamp = last_candle_ts
            existing.end_date = datetime.fromtimestamp(last_candle_ts / 1000).strftime('%Y-%m-%d')
            existing.updated_at = datetime.now(timezone.utc)
            existing.is_incremental = True

            return ('updated', existing)

        else:
            # No existing run - create new one using fast numpy simulation
            start_ts = int(df['timestamp'].min())
            start_date = datetime.fromtimestamp(start_ts / 1000).strftime('%Y-%m-%d')
            end_date = datetime.fromtimestamp(last_candle_ts / 1000).strftime('%Y-%m-%d')

            trades, open_trades = self._simulate_trades_with_open_fast(ohlcv, patterns, params)
            stats = self._calculate_statistics(trades)

            run = OptimizationRun(
                job_id=None,  # No job for incremental runs
                symbol=symbol,
                timeframe=timeframe,
                pattern_type=pattern_type,
                start_date=start_date,
                end_date=end_date,
                rr_target=rr_target,
                sl_buffer_pct=sl_buffer_pct,
                tp_method=params.get('tp_method', 'fixed_rr'),
                entry_method=params.get('entry_method', 'zone_edge'),
                min_zone_pct=params.get('min_zone_pct', 0.15),
                use_overlap=params.get('use_overlap', True),
                status='completed',
                total_trades=stats['total_trades'],
                winning_trades=stats['winning_trades'],
                losing_trades=stats['losing_trades'],
                win_rate=stats['win_rate'],
                avg_rr=stats['avg_rr'],
                total_profit_pct=stats['total_profit_pct'],
                max_drawdown=stats['max_drawdown'],
                sharpe_ratio=stats['sharpe_ratio'],
                profit_factor=stats['profit_factor'],
                avg_trade_duration=stats['avg_duration'],
                results_json=json.dumps(trades[-100:]),
                open_trades_json=json.dumps(open_trades),
                last_candle_timestamp=last_candle_ts,
                is_incremental=True,
            )
            db.session.add(run)

            return ('new', run)

    def _simulate_trades_with_open_fast(
        self,
        ohlcv: Dict[str, np.ndarray],
        patterns: List[Dict],
        params: Dict,
        after_timestamp: int = None
    ) -> tuple:
        """
        Fast trade simulation using numpy arrays, returning both closed and open trades.

        Returns:
            (closed_trades, open_trades)
        """
        closed_trades = []
        open_trades = []
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0) / 100.0
        entry_method = params.get('entry_method', 'zone_edge')

        highs = ohlcv['high']
        lows = ohlcv['low']
        timestamps = ohlcv['timestamp']
        n_candles = len(highs)

        for pattern in patterns:
            entry_idx = pattern['detected_at']

            # Skip patterns before the after_timestamp if specified
            if after_timestamp and entry_idx < n_candles and timestamps[entry_idx] <= after_timestamp:
                continue

            if entry_idx + 5 >= n_candles:
                continue

            zone_high = pattern['zone_high']
            zone_low = pattern['zone_low']
            zone_size = zone_high - zone_low
            buffer = zone_size * sl_buffer_pct

            if pattern['direction'] == 'bullish':
                entry = zone_high if entry_method == 'zone_edge' else (zone_high + zone_low) / 2
                stop_loss = zone_low - buffer
                risk = entry - stop_loss
                take_profit = entry + (risk * rr_target)
                direction = 'long'
            else:
                entry = zone_low if entry_method == 'zone_edge' else (zone_high + zone_low) / 2
                stop_loss = zone_high + buffer
                risk = stop_loss - entry
                take_profit = entry - (risk * rr_target)
                direction = 'short'

            trade = self._simulate_single_trade_with_open_fast(
                highs, lows, timestamps, entry_idx, entry, stop_loss, take_profit,
                direction, rr_target, n_candles
            )

            if trade:
                if trade.get('status') == 'open':
                    open_trades.append(trade)
                else:
                    closed_trades.append(trade)

        return closed_trades, open_trades

    def _simulate_single_trade_with_open_fast(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        timestamps: np.ndarray,
        entry_idx: int,
        entry: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        rr_target: float,
        n_candles: int
    ) -> Optional[Dict]:
        """Fast single trade simulation using numpy, returning open if not resolved"""
        entry_triggered = False
        entry_candle = None
        entry_time = None

        for j in range(entry_idx + 1, n_candles):
            if not entry_triggered:
                if direction == 'long' and lows[j] <= entry:
                    entry_triggered = True
                    entry_candle = j
                    entry_time = int(timestamps[j])
                elif direction == 'short' and highs[j] >= entry:
                    entry_triggered = True
                    entry_candle = j
                    entry_time = int(timestamps[j])
            else:
                # Check for SL or TP
                if direction == 'long':
                    if lows[j] <= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif highs[j] >= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                else:
                    if highs[j] >= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif lows[j] <= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[j]),
                            'duration_candles': int(j - entry_candle)
                        }

        # Trade not resolved - return as open
        if entry_triggered:
            return {
                'status': 'open',
                'entry_price': float(entry),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'direction': direction,
                'rr_target': float(rr_target),
                'entry_time': entry_time,
            }

        return None

    def _resolve_open_trades_fast(
        self,
        ohlcv: Dict[str, np.ndarray],
        open_trades: List[Dict],
        after_timestamp: int
    ) -> tuple:
        """
        Resolve open trades with new candle data using numpy arrays.

        Returns:
            (resolved_trades, still_open_trades)
        """
        resolved = []
        still_open = []

        highs = ohlcv['high']
        lows = ohlcv['low']
        timestamps = ohlcv['timestamp']
        n_candles = len(highs)

        for trade in open_trades:
            entry = trade['entry_price']
            stop_loss = trade['stop_loss']
            take_profit = trade['take_profit']
            direction = trade['direction']
            entry_time = trade['entry_time']
            rr_target = trade.get('rr_target', 2.0)

            was_resolved = False

            for idx in range(n_candles):
                # Skip candles before entry
                if timestamps[idx] <= entry_time:
                    continue

                if direction == 'long':
                    if lows[idx] <= stop_loss:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': stop_loss,
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[idx]),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                    elif highs[idx] >= take_profit:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': take_profit,
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': rr_target,
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[idx]),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                else:
                    if highs[idx] >= stop_loss:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': stop_loss,
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[idx]),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                    elif lows[idx] <= take_profit:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': take_profit,
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': rr_target,
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(timestamps[idx]),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break

            if not was_resolved:
                still_open.append(trade)

        return resolved, still_open

    def _simulate_trades_with_open(
        self,
        df: pd.DataFrame,
        patterns: List[Dict],
        params: Dict,
        after_timestamp: int = None
    ) -> tuple:
        """
        Simulate trades, returning both closed and open trades.

        Returns:
            (closed_trades, open_trades)
        """
        closed_trades = []
        open_trades = []
        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0) / 100.0
        entry_method = params.get('entry_method', 'zone_edge')

        for pattern in patterns:
            entry_idx = pattern['detected_at']

            # Skip patterns before the after_timestamp if specified
            if after_timestamp and df.iloc[entry_idx]['timestamp'] <= after_timestamp:
                continue

            if entry_idx + 5 >= len(df):
                continue

            zone_high = pattern['zone_high']
            zone_low = pattern['zone_low']
            zone_size = zone_high - zone_low
            buffer = zone_size * sl_buffer_pct

            if pattern['direction'] == 'bullish':
                entry = zone_high if entry_method == 'zone_edge' else (zone_high + zone_low) / 2
                stop_loss = zone_low - buffer
                risk = entry - stop_loss
                take_profit = entry + (risk * rr_target)
                direction = 'long'
            else:
                entry = zone_low if entry_method == 'zone_edge' else (zone_high + zone_low) / 2
                stop_loss = zone_high + buffer
                risk = stop_loss - entry
                take_profit = entry - (risk * rr_target)
                direction = 'short'

            trade = self._simulate_single_trade_with_open(
                df, entry_idx, entry, stop_loss, take_profit, direction, rr_target
            )

            if trade:
                if trade.get('status') == 'open':
                    open_trades.append(trade)
                else:
                    closed_trades.append(trade)

        return closed_trades, open_trades

    def _simulate_single_trade_with_open(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        entry: float,
        stop_loss: float,
        take_profit: float,
        direction: str,
        rr_target: float
    ) -> Optional[Dict]:
        """Simulate a single trade, returning open if not resolved"""
        entry_triggered = False
        entry_candle = None
        entry_time = None

        for j in range(entry_idx + 1, len(df)):
            candle = df.iloc[j]

            if not entry_triggered:
                if direction == 'long' and candle['low'] <= entry:
                    entry_triggered = True
                    entry_candle = j
                    entry_time = int(candle['timestamp'])
                elif direction == 'short' and candle['high'] >= entry:
                    entry_triggered = True
                    entry_candle = j
                    entry_time = int(candle['timestamp'])
            else:
                # Check for SL or TP
                if direction == 'long':
                    if candle['low'] <= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif candle['high'] >= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                else:
                    if candle['high'] >= stop_loss:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(stop_loss),
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }
                    elif candle['low'] <= take_profit:
                        return {
                            'entry_price': float(entry),
                            'exit_price': float(take_profit),
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': float(rr_target),
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': int(j - entry_candle)
                        }

        # Trade not resolved - return as open
        if entry_triggered:
            return {
                'status': 'open',
                'entry_price': float(entry),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'direction': direction,
                'rr_target': float(rr_target),
                'entry_time': entry_time,
            }

        return None

    def _resolve_open_trades(
        self,
        df: pd.DataFrame,
        open_trades: List[Dict],
        rr_target: float
    ) -> tuple:
        """
        Resolve open trades with new candle data.

        Returns:
            (resolved_trades, still_open_trades)
        """
        resolved = []
        still_open = []

        for trade in open_trades:
            entry = trade['entry_price']
            stop_loss = trade['stop_loss']
            take_profit = trade['take_profit']
            direction = trade['direction']
            entry_time = trade['entry_time']

            was_resolved = False

            for idx in range(len(df)):
                candle = df.iloc[idx]

                # Skip candles before entry
                if candle['timestamp'] <= entry_time:
                    continue

                if direction == 'long':
                    if candle['low'] <= stop_loss:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': stop_loss,
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                    elif candle['high'] >= take_profit:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': take_profit,
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': trade['rr_target'],
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                else:
                    if candle['high'] >= stop_loss:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': stop_loss,
                            'direction': direction,
                            'result': 'loss',
                            'rr_achieved': -1.0,
                            'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break
                    elif candle['low'] <= take_profit:
                        resolved.append({
                            'entry_price': entry,
                            'exit_price': take_profit,
                            'direction': direction,
                            'result': 'win',
                            'rr_achieved': trade['rr_target'],
                            'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                            'entry_time': entry_time,
                            'exit_time': int(candle['timestamp']),
                            'duration_candles': idx
                        })
                        was_resolved = True
                        break

            if not was_resolved:
                still_open.append(trade)

        return resolved, still_open

    def _get_timeframe_ms(self, timeframe: str) -> int:
        """Convert timeframe to milliseconds"""
        multipliers = {
            '1m': 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
        }
        return multipliers.get(timeframe, 60 * 60 * 1000)


# Singleton instance
optimizer = ParameterOptimizer()
