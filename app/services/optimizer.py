"""
Parameter Optimizer Service
Automated parameter sweep for backtesting optimization

Performance optimizations:
- Pattern detection cached per symbol/timeframe/pattern_type
- Vectorized trade simulation using numpy
- Batch DB commits every 50 runs
- Progress saved frequently for resumability
- Parallel symbol processing (CRITICAL-8 fix)
"""
import json
import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from app import db
from app.models import (
    OptimizationJob, OptimizationRun,
    QUICK_PARAMETER_GRID
)
from app.services.aggregator import get_candles_as_dataframe
from app.services.patterns.fair_value_gap import FVGDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector
from app.services.logger import log_system

# Batch commit size for DB operations
BATCH_COMMIT_SIZE = 50

# Default number of parallel workers (bounded to prevent memory issues)
# Each worker can use ~50MB per symbol, so 4 workers = ~200MB peak
DEFAULT_PARALLEL_WORKERS = 4
MAX_PARALLEL_WORKERS = 8

# Timeframe drill-down mapping for resolving same-candle SL/TP conflicts
# When both SL and TP are hit on the same candle, we look at smaller TF to determine which hit first
SMALLER_TIMEFRAME = {
    '1d': '4h',
    '4h': '1h',
    '2h': '30m',
    '1h': '15m',
    '30m': '5m',
    '15m': '5m',
    '5m': '1m',
    '1m': None,  # Can't go smaller, assume loss (conservative)
}

# Timeframe to milliseconds for timestamp calculations
TIMEFRAME_MS = {
    '1m': 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '2h': 2 * 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
}

# Maximum candles to look ahead for trade resolution (shared with backtester.py)
# Higher timeframes need shorter lookback (measured in candles)
MAX_TRADE_DURATION_BY_TF = {
    '1m': 2880,   # 48 hours (allows longer intraday trades)
    '5m': 576,    # 48 hours
    '15m': 192,   # 48 hours
    '30m': 120,   # 60 hours
    '1h': 100,    # ~4 days
    '2h': 80,     # ~6 days
    '4h': 60,     # ~10 days
    '1d': 30,     # ~30 days
}
DEFAULT_MAX_TRADE_DURATION = 100  # Fallback for unknown timeframes

# Minimum candles required after pattern detection to simulate a trade
MIN_CANDLES_AFTER_PATTERN = 5

# Detector instances (reuse to avoid re-initialization)
_detectors = {
    'imbalance': FVGDetector(),
    'order_block': OrderBlockDetector(),
    'liquidity_sweep': LiquiditySweepDetector(),
}


def _process_symbol_worker(
    symbol: str,
    timeframes: List[str],
    pattern_types: List[str],
    parameter_grid: Dict,
    existing_timestamps: Dict[str, int],
) -> Dict:
    """
    Worker function for parallel symbol processing.

    This function runs in a separate process and uses the shared
    _process_symbol() method via a new optimizer instance.

    Args:
        symbol: Trading symbol to process
        timeframes: List of timeframes
        pattern_types: List of pattern types
        parameter_grid: Parameter combinations to test
        existing_timestamps: Dict of {timeframe: last_candle_ts} from existing runs
                            for skip detection

    Returns:
        Dict with keys from _process_symbol() including:
            - skipped: True if skipped due to no new data
            - skip_count: number of skipped combinations
    """
    try:
        # Create Flask app context for database queries (read-only)
        from app import create_app
        app = create_app()

        with app.app_context():
            # Create optimizer instance and use shared _process_symbol method
            optimizer = ParameterOptimizer()
            result = optimizer._process_symbol(
                symbol=symbol,
                timeframes=timeframes,
                pattern_types=pattern_types,
                parameter_grid=parameter_grid,
                existing_timestamps=existing_timestamps,
            )

            return result

    except Exception as e:
        return {
            'symbol': symbol,
            'data_cache': {},
            'pattern_cache': {},
            'results': [],
            'best_result': None,
            'skipped': False,
            'skip_count': 0,
            'error': str(e),
        }


class ParameterOptimizer:
    """Automated parameter sweep for backtesting"""

    def __init__(self):
        self.current_job = None

    def _process_symbol(
        self,
        symbol: str,
        timeframes: List[str],
        pattern_types: List[str],
        parameter_grid: Dict,
        data_override: Dict[str, pd.DataFrame] = None,
        existing_timestamps: Dict[str, int] = None,
    ) -> Dict:
        """
        Core symbol processing logic - SINGLE SOURCE OF TRUTH.

        This method is used by run_job(), run_incremental(), and parallel workers.
        It handles: data loading → skip check → pattern detection → parameter sweep.

        Args:
            symbol: Trading symbol to process
            timeframes: List of timeframes to process
            pattern_types: List of pattern types to detect
            parameter_grid: Parameter combinations to test
            data_override: Optional dict of {timeframe: DataFrame} for testing
            existing_timestamps: Optional dict of {timeframe: last_candle_ts} from
                                existing runs. If provided and no new data, skips
                                expensive Phase 2/3.

        Returns:
            Dict with keys:
                - symbol: the processed symbol
                - results: list of sweep results (each with trades, stats)
                - best_result: best result from sweep
                - data_cache: loaded candle data (for caller if needed)
                - pattern_cache: detected patterns (for caller if needed)
                - error: error message if failed, None otherwise
                - skipped: True if skipped due to no new data
        """
        result = {
            'symbol': symbol,
            'results': [],
            'best_result': None,
            'data_cache': {},
            'pattern_cache': {},
            'error': None,
            'skipped': False,
        }

        try:
            # Phase 1: Load candle data with detailed per-timeframe logging
            phase1_start = time.time()
            print(f"\n[Phase 1/3] Loading candle data ({symbol})...", flush=True)
            total_candles = 0

            for timeframe in timeframes:
                tf_start = time.time()
                if data_override and timeframe in data_override:
                    df = data_override[timeframe]
                    verified_status = ""
                else:
                    df = get_candles_as_dataframe(symbol, timeframe, verified_only=True)
                    verified_status = ""
                    if df is None or df.empty:
                        df = get_candles_as_dataframe(symbol, timeframe, verified_only=False)
                        verified_status = " [unverified!]"
                tf_time = time.time() - tf_start

                if df is not None and len(df) >= 20:
                    ohlcv = self._df_to_arrays(df)
                    first_ts = int(df['timestamp'].min())
                    last_ts = int(df['timestamp'].max())
                    result['data_cache'][(symbol, timeframe)] = (df, ohlcv, first_ts, last_ts)
                    total_candles += len(df)
                    print(f"  {symbol} {timeframe}: {len(df):,} candles ({tf_time:.2f}s){verified_status}", flush=True)
                else:
                    result['data_cache'][(symbol, timeframe)] = (None, None, None, None)
                    print(f"  {symbol} {timeframe}: No data ({tf_time:.2f}s)", flush=True)

            phase1_time = time.time() - phase1_start
            print(f"  ✓ [{symbol}] Phase 1 complete: {total_candles:,} candles in {phase1_time:.1f}s", flush=True)

            if total_candles == 0:
                print(f"  ✗ {symbol}: No data available - skipping", flush=True)
                param_keys = list(parameter_grid.keys())
                param_combinations = list(itertools.product(*parameter_grid.values()))
                for timeframe in timeframes:
                    for pattern_type in pattern_types:
                        for params in param_combinations:
                            result['results'].append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': dict(zip(param_keys, params)),
                                'status': 'failed',
                                'error': 'Insufficient data',
                                'last_candle_ts': None,
                            })
                return result

            # Check for new data if existing timestamps provided
            if existing_timestamps:
                has_new_data = False
                for timeframe in timeframes:
                    cached = result['data_cache'].get((symbol, timeframe))
                    if cached and cached[3]:  # last_candle_ts (index 3 now)
                        last_candle_ts = cached[3]
                        existing_ts = existing_timestamps.get(timeframe)
                        if existing_ts is None:
                            # No existing run for this timeframe = new data
                            has_new_data = True
                            break
                        elif last_candle_ts > existing_ts:
                            # Newer candles than existing run
                            has_new_data = True
                            break

                if not has_new_data:
                    param_combinations = list(itertools.product(*parameter_grid.values()))
                    skip_count = len(timeframes) * len(pattern_types) * len(param_combinations)
                    print(f"  ⏭ Skipped {symbol}: No new candles since last run", flush=True)
                    result['skipped'] = True
                    result['skip_count'] = skip_count
                    return result

            # Phase 2: Detect patterns with detailed per-timeframe logging
            phase2_start = time.time()
            min_zone_pcts = parameter_grid.get('min_zone_pct', [0.15])
            use_overlaps = parameter_grid.get('use_overlap', [True])
            total_patterns = 0

            print(f"\n[Phase 2/3] Detecting patterns ({len(pattern_types)} types × {len(timeframes)} timeframes)...", flush=True)

            for timeframe in timeframes:
                cached = result['data_cache'].get((symbol, timeframe), (None, None, None))
                df = cached[0]
                if df is None:
                    print(f"  {symbol} {timeframe}: SKIPPED (no data)", flush=True)
                    continue

                n_candles = len(df)
                tf_start = time.time()
                tf_patterns = 0
                pattern_details = []

                print(f"  {symbol} {timeframe}: Processing {n_candles:,} candles...", flush=True)

                for pattern_type in pattern_types:
                    detector = _detectors.get(pattern_type)
                    if not detector:
                        print(f"    ⚠ Unknown pattern type: {pattern_type}", flush=True)
                        continue

                    pt_start = time.time()
                    pt_count = 0

                    for min_zone_pct in min_zone_pcts:
                        for use_overlap in use_overlaps:
                            detect_start = time.time()
                            cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)
                            patterns = detector.detect_historical(
                                df,
                                min_zone_pct=min_zone_pct,
                                skip_overlap=not use_overlap
                            )
                            detect_duration = time.time() - detect_start
                            result['pattern_cache'][cache_key] = patterns
                            pt_count += len(patterns)
                            tf_patterns += len(patterns)
                            total_patterns += len(patterns)

                            # Log if detection takes more than 1 second
                            if detect_duration > 1.0:
                                print(f"    → {pattern_type} (zone={min_zone_pct}, overlap={use_overlap}): "
                                      f"{len(patterns)} patterns in {detect_duration:.2f}s", flush=True)

                    pt_duration = time.time() - pt_start
                    pattern_details.append(f"{pattern_type}:{pt_count}({pt_duration:.1f}s)")

                tf_duration = time.time() - tf_start
                print(f"    ✓ Done: {tf_patterns:,} patterns in {tf_duration:.2f}s [{', '.join(pattern_details)}]", flush=True)

            phase2_time = time.time() - phase2_start
            print(f"  ✓ [{symbol}] Phase 2 complete: {total_patterns:,} patterns in {phase2_time:.1f}s", flush=True)

            # Phase 3: Parameter sweep with logging
            phase3_start = time.time()
            param_keys = list(parameter_grid.keys())
            param_combinations = list(itertools.product(*parameter_grid.values()))
            total_combos = len(param_combinations) * len(timeframes) * len(pattern_types)
            best_profit = float('-inf')

            print(f"\n[Phase 3/3] Running parameter sweep ({total_combos:,} combinations)...", flush=True)

            for timeframe in timeframes:
                cached = result['data_cache'].get((symbol, timeframe), (None, None, None, None))
                df, ohlcv = cached[0], cached[1]
                first_candle_ts = cached[2] if len(cached) > 2 else None
                last_candle_ts = cached[3] if len(cached) > 3 else None

                if df is None:
                    for pattern_type in pattern_types:
                        for params in param_combinations:
                            result['results'].append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': dict(zip(param_keys, params)),
                                'status': 'failed',
                                'error': 'Insufficient data',
                                'first_candle_ts': None,
                                'last_candle_ts': None,
                            })
                    continue

                for pattern_type in pattern_types:
                    detector = _detectors.get(pattern_type)
                    if not detector:
                        for params in param_combinations:
                            result['results'].append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': dict(zip(param_keys, params)),
                                'status': 'failed',
                                'error': f'Unknown pattern type: {pattern_type}',
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            })
                        continue

                    for params in param_combinations:
                        param_dict = dict(zip(param_keys, params))

                        try:
                            min_zone_pct = param_dict.get('min_zone_pct', 0.15)
                            use_overlap = param_dict.get('use_overlap', True)
                            cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)
                            patterns = result['pattern_cache'].get(cache_key, [])

                            trades = self._simulate_trades_fast(
                                ohlcv, patterns, param_dict,
                                timeframe=timeframe,
                                data_cache=result.get('data_cache'),
                                symbol=symbol
                            )
                            stats = self._calculate_statistics(trades)

                            sweep_result = {
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': param_dict,
                                'status': 'completed',
                                'trades': trades,
                                'stats': stats,
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            }
                            result['results'].append(sweep_result)

                            if stats['total_profit_pct'] > best_profit:
                                best_profit = stats['total_profit_pct']
                                result['best_result'] = sweep_result

                        except Exception as e:
                            result['results'].append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': param_dict,
                                'status': 'failed',
                                'error': str(e),
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            })

            phase3_time = time.time() - phase3_start
            completed = sum(1 for r in result['results'] if r['status'] == 'completed')
            print(f"  ✓ [{symbol}] Phase 3 complete: {completed:,} runs in {phase3_time:.1f}s", flush=True)

        except Exception as e:
            result['error'] = str(e)
            print(f"  ✗ {symbol}: Error - {str(e)}", flush=True)

        return result

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

    def run_job(
        self,
        job_id: int,
        progress_callback=None,
        parallel: bool = False,
        max_workers: int = None
    ) -> Dict:
        """
        Execute all runs for a job.

        Uses the shared _process_symbol() method for each symbol, ensuring
        consistent behavior with run_incremental().

        Args:
            job_id: Job ID to execute
            progress_callback: Optional callback(completed, total) for progress updates
            parallel: If True, process symbols in parallel (default: False)
            max_workers: Number of parallel workers (default: 4, max: 8)

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

        completed = 0
        failed = 0
        best_result = None
        best_profit = float('-inf')
        pending_commits = 0
        processed_count = 0

        # Calculate total for progress
        param_combinations = list(itertools.product(*param_grid.values()))
        total_runs = len(symbols) * len(timeframes) * len(pattern_types) * len(param_combinations)

        try:
            # Process each symbol using shared _process_symbol() method
            for symbol in symbols:
                print(f"\n{'='*60}", flush=True)
                print(f"Processing {symbol}...", flush=True)

                # Use shared _process_symbol() - handles all phases with detailed logging
                symbol_result = self._process_symbol(
                    symbol=symbol,
                    timeframes=timeframes,
                    pattern_types=pattern_types,
                    parameter_grid=param_grid,
                )

                if symbol_result.get('error'):
                    for tf in timeframes:
                        for pt in pattern_types:
                            for params in param_combinations:
                                self._create_failed_run(
                                    job, symbol, tf, pt,
                                    dict(zip(param_grid.keys(), params)),
                                    symbol_result['error']
                                )
                                failed += 1
                    continue

                # Create OptimizationRun records from results
                symbol_completed = 0
                symbol_failed = 0

                for r in symbol_result['results']:
                    if r['status'] == 'completed':
                        run = self._create_run_from_result(job, r)
                        completed += 1
                        symbol_completed += 1
                        if run.total_profit_pct is not None and run.total_profit_pct > best_profit:
                            best_profit = run.total_profit_pct
                            best_result = run
                    else:
                        self._create_failed_run(
                            job, r['symbol'], r['timeframe'], r['pattern_type'],
                            r['params'], r.get('error', 'Unknown error')
                        )
                        failed += 1
                        symbol_failed += 1

                    pending_commits += 1
                    processed_count += 1

                    if progress_callback:
                        progress_callback(processed_count, total_runs)

                    if pending_commits >= BATCH_COMMIT_SIZE:
                        job.completed_runs = completed
                        job.failed_runs = failed
                        db.session.commit()
                        pending_commits = 0

                print(f"  ✓ {symbol}: {symbol_completed} completed, {symbol_failed} failed", flush=True)

            # Final commit
            if pending_commits > 0:
                job.completed_runs = completed
                job.failed_runs = failed
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

    # =========================================================================
    # SHARED OPTIMIZATION PHASES (used by both run_job and run_incremental)
    # =========================================================================

    def _run_sweep_phase(
        self,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        parameter_grid: Dict,
        data_cache: Dict,
        pattern_cache: Dict,
        progress_callback=None
    ) -> Tuple[List[Dict], Dict]:
        """
        Phase 3: Run parameter sweep over all combinations.

        This is the SINGLE implementation used by both run_job and run_incremental.
        Returns raw results that callers can use to create/update records.

        Returns:
            Tuple of (results_list, best_result_dict)
            Each result contains: symbol, timeframe, pattern_type, params, trades, stats
        """
        param_keys = list(parameter_grid.keys())
        param_combinations = list(itertools.product(*parameter_grid.values()))
        total = len(symbols) * len(timeframes) * len(pattern_types) * len(param_combinations)

        phase3_start = datetime.now(timezone.utc)
        print(f"\n[Phase 3/3] Running parameter sweep ({total:,} combinations)...", flush=True)

        results = []
        best_result = None
        best_profit = float('-inf')
        processed = 0

        for symbol in symbols:
            for timeframe in timeframes:
                cached = data_cache.get((symbol, timeframe), (None, None, None, None))
                df, ohlcv_arrays = cached[0], cached[1]
                first_candle_ts = cached[2] if len(cached) > 2 else None
                last_candle_ts = cached[3] if len(cached) > 3 else None

                if df is None:
                    # Mark as failed
                    for pattern_type in pattern_types:
                        for params in param_combinations:
                            processed += 1
                            results.append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': dict(zip(param_keys, params)),
                                'status': 'failed',
                                'error': 'Insufficient data',
                                'first_candle_ts': None,
                                'last_candle_ts': None,
                            })
                            if progress_callback:
                                progress_callback(processed, total)
                    continue

                for pattern_type in pattern_types:
                    detector = _detectors.get(pattern_type)
                    if not detector:
                        for params in param_combinations:
                            processed += 1
                            results.append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': dict(zip(param_keys, params)),
                                'status': 'failed',
                                'error': f'Unknown pattern type: {pattern_type}',
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            })
                            if progress_callback:
                                progress_callback(processed, total)
                        continue

                    for params in param_combinations:
                        param_dict = dict(zip(param_keys, params))
                        processed += 1

                        try:
                            # Get cached patterns
                            min_zone_pct = param_dict.get('min_zone_pct', 0.15)
                            use_overlap = param_dict.get('use_overlap', True)
                            cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)
                            patterns = pattern_cache.get(cache_key, [])

                            # Simulate trades (single shared implementation)
                            trades = self._simulate_trades_fast(
                                ohlcv_arrays, patterns, param_dict,
                                timeframe=timeframe,
                                data_cache=data_cache,
                                symbol=symbol
                            )
                            stats = self._calculate_statistics(trades)

                            result = {
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': param_dict,
                                'status': 'completed',
                                'trades': trades,
                                'stats': stats,
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            }
                            results.append(result)

                            # Track best
                            if stats['total_profit_pct'] > best_profit:
                                best_profit = stats['total_profit_pct']
                                best_result = result

                        except Exception as e:
                            results.append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'pattern_type': pattern_type,
                                'params': param_dict,
                                'status': 'failed',
                                'error': str(e),
                                'first_candle_ts': first_candle_ts,
                                'last_candle_ts': last_candle_ts,
                            })

                        if progress_callback:
                            progress_callback(processed, total)

        phase3_duration = (datetime.now(timezone.utc) - phase3_start).total_seconds()
        completed = len([r for r in results if r['status'] == 'completed'])
        print(f"  ✓ Phase 3 complete: {completed:,} runs in {phase3_duration:.1f}s", flush=True)

        return results, best_result

    def _load_candle_data_phase(
        self,
        symbols: List[str],
        timeframes: List[str]
    ) -> Dict[tuple, tuple]:
        """
        Phase 1: Load all candle data for given symbols/timeframes.

        Returns:
            data_cache: Dict[(symbol, timeframe)] -> (df, ohlcv_arrays, first_candle_ts, last_candle_ts)
        """
        data_cache = {}
        total_candles = 0
        phase_start = datetime.now(timezone.utc)

        print(f"\n[Phase 1/3] Loading candle data ({len(symbols)} symbols × {len(timeframes)} timeframes)...", flush=True)

        for symbol in symbols:
            for timeframe in timeframes:
                query_start = datetime.now(timezone.utc)
                df = get_candles_as_dataframe(symbol, timeframe, verified_only=True)
                verified_source = "verified"
                if df is None or df.empty:
                    df = get_candles_as_dataframe(symbol, timeframe, verified_only=False)
                    verified_source = "unverified"
                query_duration = (datetime.now(timezone.utc) - query_start).total_seconds()

                if df is not None and len(df) >= 20:
                    ohlcv_arrays = self._df_to_arrays(df)
                    first_candle_ts = int(df['timestamp'].min())
                    last_candle_ts = int(df['timestamp'].max())
                    data_cache[(symbol, timeframe)] = (df, ohlcv_arrays, first_candle_ts, last_candle_ts)
                    total_candles += len(df)
                    status = "" if verified_source == "verified" else " [unverified!]"
                    print(f"  {symbol} {timeframe}: {len(df):,} candles ({query_duration:.2f}s){status}", flush=True)
                else:
                    data_cache[(symbol, timeframe)] = (None, None, None, None)
                    print(f"  {symbol} {timeframe}: No data ({query_duration:.2f}s)")

        phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
        print(f"  ✓ Phase 1 complete: {total_candles:,} candles in {phase_duration:.1f}s", flush=True)

        return data_cache

    def _detect_patterns_phase(
        self,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        parameter_grid: Dict,
        data_cache: Dict[tuple, tuple]
    ) -> Dict[tuple, List]:
        """
        Phase 2: Detect all patterns for given symbols/timeframes/pattern_types.

        Returns:
            pattern_cache: Dict[(symbol, timeframe, pattern_type, min_zone_pct, use_overlap)] -> patterns
        """
        pattern_cache = {}
        total_patterns = 0
        phase_start = datetime.now(timezone.utc)

        min_zone_pcts = parameter_grid.get('min_zone_pct', [0.15])
        use_overlaps = parameter_grid.get('use_overlap', [True])

        print(f"\n[Phase 2/3] Detecting patterns ({len(pattern_types)} types × {len(timeframes)} timeframes)...", flush=True)

        for symbol in symbols:
            for timeframe in timeframes:
                cached = data_cache.get((symbol, timeframe), (None, None, None))
                df = cached[0] if len(cached) >= 1 else None
                if df is None:
                    print(f"  {symbol} {timeframe}: SKIPPED (no data)", flush=True)
                    continue

                n_candles = len(df)
                tf_start = datetime.now(timezone.utc)
                tf_patterns = 0
                pattern_details = []

                print(f"  {symbol} {timeframe}: Processing {n_candles:,} candles...", flush=True)

                for pattern_type in pattern_types:
                    detector = _detectors.get(pattern_type)
                    if not detector:
                        print(f"    ⚠ Unknown pattern type: {pattern_type}", flush=True)
                        continue

                    pt_start = datetime.now(timezone.utc)
                    pt_count = 0

                    for min_zone_pct in min_zone_pcts:
                        for use_overlap in use_overlaps:
                            detect_start = datetime.now(timezone.utc)
                            cache_key = (symbol, timeframe, pattern_type, min_zone_pct, use_overlap)
                            patterns = detector.detect_historical(
                                df,
                                min_zone_pct=min_zone_pct,
                                skip_overlap=not use_overlap
                            )
                            detect_duration = (datetime.now(timezone.utc) - detect_start).total_seconds()
                            pattern_cache[cache_key] = patterns
                            pt_count += len(patterns)
                            tf_patterns += len(patterns)
                            total_patterns += len(patterns)

                            # Log if detection takes more than 1 second
                            if detect_duration > 1.0:
                                print(f"    → {pattern_type} (zone={min_zone_pct}, overlap={use_overlap}): "
                                      f"{len(patterns)} patterns in {detect_duration:.2f}s", flush=True)

                    pt_duration = (datetime.now(timezone.utc) - pt_start).total_seconds()
                    pattern_details.append(f"{pattern_type}:{pt_count}({pt_duration:.1f}s)")

                tf_duration = (datetime.now(timezone.utc) - tf_start).total_seconds()
                print(f"    ✓ Done: {tf_patterns:,} patterns in {tf_duration:.2f}s [{', '.join(pattern_details)}]", flush=True)

        phase_duration = (datetime.now(timezone.utc) - phase_start).total_seconds()
        print(f"  ✓ Phase 2 complete: {total_patterns:,} patterns in {phase_duration:.1f}s", flush=True)

        return pattern_cache

    def _run_single_optimization_fast(
        self,
        job: OptimizationJob,
        ohlcv: Dict[str, np.ndarray],
        symbol: str,
        timeframe: str,
        pattern_type: str,
        patterns: List[Dict],
        params: Dict,
        data_cache: Dict = None
    ) -> OptimizationRun:
        """
        Run a single optimization with specific parameters using pre-computed patterns.
        Uses numpy arrays for faster trade simulation.
        """
        # Simulate trades using vectorized numpy operations
        trades = self._simulate_trades_fast(
            ohlcv, patterns, params,
            timeframe=timeframe,
            data_cache=data_cache,
            symbol=symbol
        )

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
            results_json=json.dumps(trades),  # Store all trades
        )
        db.session.add(run)

        return run

    def _simulate_trades_fast(
        self,
        ohlcv: Dict[str, np.ndarray],
        patterns: List[Dict],
        params: Dict,
        timeframe: str = None,
        data_cache: Dict = None,
        symbol: str = None
    ) -> List[Dict]:
        """
        Simulate trades using fully vectorized numpy operations.
        This is heavily optimized for speed - processes all patterns in batch.

        Args:
            ohlcv: Dict with 'high', 'low', 'timestamp' numpy arrays
            patterns: List of pattern dicts with 'detected_at', 'zone_high', 'zone_low', 'direction'
            params: Dict with 'rr_target', 'sl_buffer_pct', 'entry_method'
            timeframe: Current timeframe (for same-candle drill-down)
            data_cache: Dict[(symbol, tf)] -> (df, ohlcv, first_ts, last_ts) for drill-down
            symbol: Symbol being processed (for drill-down lookup)
        """
        if not patterns:
            return []

        rr_target = params.get('rr_target', 2.0)
        sl_buffer_pct = params.get('sl_buffer_pct', 10.0) / 100.0
        entry_method = params.get('entry_method', 'zone_edge')

        highs = ohlcv['high']
        lows = ohlcv['low']
        timestamps = ohlcv['timestamp']
        n_candles = len(highs)

        # Max candles to look ahead for trade resolution (timeframe-aware)
        max_trade_duration = MAX_TRADE_DURATION_BY_TF.get(timeframe, DEFAULT_MAX_TRADE_DURATION)

        trades = []

        # Process patterns in batch - vectorize the setup
        for pattern in patterns:
            entry_idx = pattern['detected_at']
            if entry_idx + MIN_CANDLES_AFTER_PATTERN >= n_candles:
                continue

            zone_high = pattern['zone_high']
            zone_low = pattern['zone_low']
            zone_size = zone_high - zone_low
            buffer = zone_size * sl_buffer_pct

            # Calculate entry, SL, TP based on direction
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

            # Limit search window
            start_idx = entry_idx + 1
            end_idx = min(entry_idx + max_trade_duration, n_candles)

            if start_idx >= end_idx:
                continue

            # Get slices for vectorized operations
            h_slice = highs[start_idx:end_idx]
            l_slice = lows[start_idx:end_idx]

            # Vectorized search for entry trigger
            if direction == 'long':
                entry_mask = l_slice <= entry
            else:
                entry_mask = h_slice >= entry

            if not np.any(entry_mask):
                continue  # No entry triggered

            entry_candle_offset = np.argmax(entry_mask)
            entry_candle = start_idx + entry_candle_offset

            # Now search for SL/TP after entry
            trade_start = entry_candle + 1
            trade_end = end_idx

            if trade_start >= trade_end:
                continue

            h_trade = highs[trade_start:trade_end]
            l_trade = lows[trade_start:trade_end]

            if direction == 'long':
                sl_mask = l_trade <= stop_loss
                tp_mask = h_trade >= take_profit
            else:
                sl_mask = h_trade >= stop_loss
                tp_mask = l_trade <= take_profit

            # Find first SL or TP hit
            sl_idx = np.argmax(sl_mask) if np.any(sl_mask) else len(sl_mask)
            tp_idx = np.argmax(tp_mask) if np.any(tp_mask) else len(tp_mask)

            # Check which was actually hit (argmax returns 0 if all False)
            sl_hit = sl_mask[sl_idx] if sl_idx < len(sl_mask) else False
            tp_hit = tp_mask[tp_idx] if tp_idx < len(tp_mask) else False

            if not sl_hit and not tp_hit:
                continue  # Trade not resolved

            # Determine outcome
            if sl_hit and tp_hit:
                # Both triggered - check if same candle
                if sl_idx == tp_idx:
                    # Same candle conflict - drill down to smaller TF or assume loss
                    conflict_candle_idx = trade_start + sl_idx
                    conflict_ts = int(timestamps[conflict_candle_idx])

                    result = self._resolve_same_candle_conflict(
                        direction=direction,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        conflict_ts=conflict_ts,
                        timeframe=timeframe,
                        data_cache=data_cache,
                        symbol=symbol
                    )

                    exit_idx = conflict_candle_idx
                    exit_price = take_profit if result == 'win' else stop_loss
                elif sl_idx < tp_idx:
                    result = 'loss'
                    exit_idx = trade_start + sl_idx
                    exit_price = stop_loss
                else:
                    result = 'win'
                    exit_idx = trade_start + tp_idx
                    exit_price = take_profit
            elif sl_hit:
                result = 'loss'
                exit_idx = trade_start + sl_idx
                exit_price = stop_loss
            else:
                result = 'win'
                exit_idx = trade_start + tp_idx
                exit_price = take_profit

            if result == 'win':
                trades.append({
                    'entry_price': float(entry),
                    'exit_price': float(exit_price),
                    'direction': direction,
                    'result': 'win',
                    'rr_achieved': float(rr_target),
                    'profit_pct': float(abs((exit_price - entry) / entry * 100)),
                    'entry_time': int(timestamps[entry_candle]),
                    'exit_time': int(timestamps[exit_idx]),
                    'duration_candles': int(exit_idx - entry_candle)
                })
            else:
                trades.append({
                    'entry_price': float(entry),
                    'exit_price': float(exit_price),
                    'direction': direction,
                    'result': 'loss',
                    'rr_achieved': -1.0,
                    'profit_pct': float(-abs((exit_price - entry) / entry * 100)),
                    'entry_time': int(timestamps[entry_candle]),
                    'exit_time': int(timestamps[exit_idx]),
                    'duration_candles': int(exit_idx - entry_candle)
                })

        return trades

    def _resolve_same_candle_conflict(
        self,
        direction: str,
        stop_loss: float,
        take_profit: float,
        conflict_ts: int,
        timeframe: str,
        data_cache: Dict,
        symbol: str
    ) -> str:
        """
        Resolve same-candle SL/TP conflict by drilling down to smaller timeframe.

        When both SL and TP are hit on the same candle, we can't know which hit first
        from the current timeframe data alone. This method looks at smaller TF candles
        within that period to determine the actual order.

        Args:
            direction: 'long' or 'short'
            stop_loss: Stop loss price level
            take_profit: Take profit price level
            conflict_ts: Timestamp of the conflict candle (start of candle)
            timeframe: Current timeframe (e.g., '4h')
            data_cache: Dict[(symbol, tf)] -> (df, ohlcv, first_ts, last_ts)
            symbol: Trading symbol

        Returns:
            'win' or 'loss'
        """
        # If no drill-down possible, assume loss (conservative)
        if not timeframe or not data_cache or not symbol:
            return 'loss'

        smaller_tf = SMALLER_TIMEFRAME.get(timeframe)
        if smaller_tf is None:
            # 1m is smallest - can't drill down further, assume loss
            return 'loss'

        # Get smaller TF data
        cache_key = (symbol, smaller_tf)
        if cache_key not in data_cache:
            # No smaller TF data available, assume loss
            return 'loss'

        _, smaller_ohlcv, _, _ = data_cache[cache_key]
        if smaller_ohlcv is None:
            return 'loss'

        smaller_highs = smaller_ohlcv['high']
        smaller_lows = smaller_ohlcv['low']
        smaller_timestamps = smaller_ohlcv['timestamp']

        # Find the candles within the conflict period
        # The conflict candle spans from conflict_ts to conflict_ts + timeframe_ms
        tf_ms = TIMEFRAME_MS.get(timeframe, 60 * 60 * 1000)
        conflict_end_ts = conflict_ts + tf_ms

        # Find indices of smaller TF candles within the conflict period
        mask = (smaller_timestamps >= conflict_ts) & (smaller_timestamps < conflict_end_ts)

        if not np.any(mask):
            # No smaller TF candles found in this period
            return 'loss'

        # Get the indices
        indices = np.where(mask)[0]

        # Scan through smaller TF candles to find which hit first
        for idx in indices:
            high = smaller_highs[idx]
            low = smaller_lows[idx]

            if direction == 'long':
                sl_hit = low <= stop_loss
                tp_hit = high >= take_profit

                if sl_hit and tp_hit:
                    # Still a conflict on this smaller candle - try to drill down further
                    smaller_smaller_tf = SMALLER_TIMEFRAME.get(smaller_tf)
                    if smaller_smaller_tf is None:
                        return 'loss'  # Can't go smaller, conservative

                    # Recursive drill-down
                    return self._resolve_same_candle_conflict(
                        direction=direction,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        conflict_ts=int(smaller_timestamps[idx]),
                        timeframe=smaller_tf,
                        data_cache=data_cache,
                        symbol=symbol
                    )
                elif sl_hit:
                    return 'loss'
                elif tp_hit:
                    return 'win'
            else:  # short
                sl_hit = high >= stop_loss
                tp_hit = low <= take_profit

                if sl_hit and tp_hit:
                    smaller_smaller_tf = SMALLER_TIMEFRAME.get(smaller_tf)
                    if smaller_smaller_tf is None:
                        return 'loss'

                    return self._resolve_same_candle_conflict(
                        direction=direction,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        conflict_ts=int(smaller_timestamps[idx]),
                        timeframe=smaller_tf,
                        data_cache=data_cache,
                        symbol=symbol
                    )
                elif sl_hit:
                    return 'loss'
                elif tp_hit:
                    return 'win'

        # Neither hit in smaller TF data (shouldn't happen, but be conservative)
        return 'loss'

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
        """Simulate a single trade using vectorized numpy operations"""
        start_idx = entry_idx + 1
        end_idx = min(entry_idx + DEFAULT_MAX_TRADE_DURATION, n_candles)

        if start_idx >= end_idx:
            return None

        h_slice = highs[start_idx:end_idx]
        l_slice = lows[start_idx:end_idx]

        # Vectorized entry search
        if direction == 'long':
            entry_mask = l_slice <= entry
        else:
            entry_mask = h_slice >= entry

        if not np.any(entry_mask):
            return None

        entry_offset = np.argmax(entry_mask)
        entry_candle = start_idx + entry_offset

        # Search for SL/TP after entry
        trade_start = entry_candle + 1
        if trade_start >= end_idx:
            return None

        h_trade = highs[trade_start:end_idx]
        l_trade = lows[trade_start:end_idx]

        if direction == 'long':
            sl_mask = l_trade <= stop_loss
            tp_mask = h_trade >= take_profit
        else:
            sl_mask = h_trade >= stop_loss
            tp_mask = l_trade <= take_profit

        sl_idx = np.argmax(sl_mask) if np.any(sl_mask) else len(sl_mask)
        tp_idx = np.argmax(tp_mask) if np.any(tp_mask) else len(tp_mask)

        sl_hit = sl_mask[sl_idx] if sl_idx < len(sl_mask) else False
        tp_hit = tp_mask[tp_idx] if tp_idx < len(tp_mask) else False

        if not sl_hit and not tp_hit:
            return None

        if sl_hit and tp_hit:
            if sl_idx <= tp_idx:
                result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
            else:
                result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit
        elif sl_hit:
            result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
        else:
            result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit

        return {
            'entry_price': float(entry),
            'exit_price': float(exit_price),
            'direction': direction,
            'result': result,
            'rr_achieved': float(rr_target) if result == 'win' else -1.0,
            'profit_pct': float(abs((exit_price - entry) / entry * 100) * (1 if result == 'win' else -1)),
            'entry_time': int(timestamps[entry_candle]),
            'exit_time': int(timestamps[exit_idx]),
            'duration_candles': int(exit_idx - entry_candle)
        }

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
            results_json=json.dumps(trades),  # Store all trades
        )
        db.session.add(run)

        return run

    def _create_run_from_result(
        self,
        job: Optional[OptimizationJob],
        result: Dict,
        existing_run: Optional[OptimizationRun] = None
    ) -> OptimizationRun:
        """
        Create or update an OptimizationRun from sweep result.

        Args:
            job: OptimizationJob (can be None for incremental runs)
            result: Dict from _run_sweep_phase containing stats, trades, params, etc.
            existing_run: Optional existing run to update (for incremental mode)

        Returns:
            Created or updated OptimizationRun
        """
        stats = result['stats']
        params = result['params']
        first_candle_ts = result.get('first_candle_ts')
        last_candle_ts = result.get('last_candle_ts')

        # Determine start/end dates
        if job:
            start_date = job.start_date
            end_date = job.end_date
        else:
            # Use actual data range from candle timestamps
            start_date = datetime.fromtimestamp(first_candle_ts / 1000).strftime('%Y-%m-%d') if first_candle_ts else None
            end_date = datetime.fromtimestamp(last_candle_ts / 1000).strftime('%Y-%m-%d') if last_candle_ts else None

        if existing_run:
            # Update existing run
            run = existing_run
            run.total_trades = stats['total_trades']
            run.winning_trades = stats['winning_trades']
            run.losing_trades = stats['losing_trades']
            run.win_rate = stats['win_rate']
            run.avg_rr = stats['avg_rr']
            run.total_profit_pct = stats['total_profit_pct']
            run.max_drawdown = stats['max_drawdown']
            run.sharpe_ratio = stats['sharpe_ratio']
            run.profit_factor = stats['profit_factor']
            run.avg_trade_duration = stats['avg_duration']
            run.results_json = json.dumps(result['trades'][-100:])
            run.last_candle_timestamp = last_candle_ts
            run.end_date = end_date
            run.updated_at = datetime.now(timezone.utc)
            run.is_incremental = True
        else:
            # Create new run
            run = OptimizationRun(
                job_id=job.id if job else None,
                symbol=result['symbol'],
                timeframe=result['timeframe'],
                pattern_type=result['pattern_type'],
                start_date=start_date,
                end_date=end_date,
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
                results_json=json.dumps(result['trades'][-100:]),
                last_candle_timestamp=last_candle_ts,
                is_incremental=job is None,
            )
            db.session.add(run)

        return run

    def _create_failed_run(
        self,
        job: Optional[OptimizationJob],
        symbol: str,
        timeframe: str,
        pattern_type: str,
        params: Dict,
        error_message: str
    ) -> OptimizationRun:
        """Create a failed run record"""
        run = OptimizationRun(
            job_id=job.id if job else None,
            symbol=symbol,
            timeframe=timeframe,
            pattern_type=pattern_type,
            start_date=job.start_date if job else None,
            end_date=job.end_date if job else None,
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
            if entry_idx + MIN_CANDLES_AFTER_PATTERN >= len(df):
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

        # Sharpe ratio (annualized)
        # Per-trade Sharpe = avg_return / std_dev
        # Annualized = per_trade * sqrt(trades_per_year)
        if len(profits) > 1:
            returns_std = np.std(profits)
            avg_return = np.mean(profits)
            per_trade_sharpe = (avg_return / returns_std) if returns_std > 0 else 0

            # Estimate trades per year from actual data
            try:
                first_trade_time = min(t['entry_time'] for t in trades)
                last_trade_time = max(t['exit_time'] for t in trades)
                time_span_ms = last_trade_time - first_trade_time
                time_span_years = time_span_ms / (365.25 * 24 * 60 * 60 * 1000)

                if time_span_years > 0.01:  # At least ~4 days of data
                    trades_per_year = len(trades) / time_span_years
                else:
                    trades_per_year = 252  # Default assumption: daily trading
            except (KeyError, TypeError):
                trades_per_year = 252  # Default if timestamps unavailable

            sharpe_ratio = per_trade_sharpe * np.sqrt(min(trades_per_year, 252))
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
        progress_callback=None,
        parallel: bool = False,
        max_workers: int = None
    ) -> Dict:
        """
        Run incremental optimization.

        By default processes ONE SYMBOL AT A TIME to save memory.
        Set parallel=True to process multiple symbols concurrently for 3-4x speedup.

        Args:
            symbols: List of trading pairs to optimize
            timeframes: List of timeframes
            pattern_types: List of pattern types
            parameter_grid: Parameter combinations to test
            progress_callback: Optional callback for progress updates
            parallel: If True, use parallel processing (default: False)
            max_workers: Number of parallel workers (default: 4, max: 8)

        Returns:
            Summary dict with results
        """
        if parameter_grid is None:
            parameter_grid = QUICK_PARAMETER_GRID

        # Use parallel processing if requested and multiple symbols
        if parallel and len(symbols) > 1:
            return self._run_incremental_parallel(
                symbols, timeframes, pattern_types, parameter_grid,
                progress_callback, max_workers
            )

        total_updated = 0
        total_new_runs = 0
        total_skipped = 0
        total_errors = 0
        best_result = None
        best_profit = float('-inf')

        # Process ONE SYMBOL AT A TIME using shared _process_symbol() method
        for symbol in symbols:
            # Pre-load existing runs for this symbol
            existing_runs = {}
            existing_timestamps = {}  # {timeframe: max_timestamp}
            all_existing = OptimizationRun.query.filter(
                OptimizationRun.symbol == symbol,
                OptimizationRun.timeframe.in_(timeframes),
                OptimizationRun.pattern_type.in_(pattern_types),
                OptimizationRun.status == 'completed'
            ).all()
            for run in all_existing:
                key = (run.symbol, run.timeframe, run.pattern_type, run.rr_target, run.sl_buffer_pct)
                existing_runs[key] = run
                # Track max timestamp per timeframe for skip detection
                if run.last_candle_timestamp:
                    if run.timeframe not in existing_timestamps:
                        existing_timestamps[run.timeframe] = run.last_candle_timestamp
                    else:
                        existing_timestamps[run.timeframe] = max(
                            existing_timestamps[run.timeframe],
                            run.last_candle_timestamp
                        )

            print(f"\n{'='*60}", flush=True)
            print(f"Processing {symbol}...", flush=True)

            # Use shared _process_symbol() - handles all phases and skip logic
            symbol_result = self._process_symbol(
                symbol=symbol,
                timeframes=timeframes,
                pattern_types=pattern_types,
                parameter_grid=parameter_grid,
                existing_timestamps=existing_timestamps if existing_runs else None,
            )

            if symbol_result.get('error'):
                param_combinations = list(itertools.product(*parameter_grid.values()))
                total_errors += len(timeframes) * len(pattern_types) * len(param_combinations)
                continue

            if symbol_result.get('skipped'):
                total_skipped += symbol_result.get('skip_count', 0)
                continue

            # Create/update records from results
            pending_commits = 0
            symbol_updated = 0
            symbol_new = 0

            for r in symbol_result['results']:
                params = r['params']
                rr_target = params.get('rr_target', 2.0)
                sl_buffer_pct = params.get('sl_buffer_pct', 10.0)
                existing_key = (r['symbol'], r['timeframe'], r['pattern_type'], rr_target, sl_buffer_pct)
                existing = existing_runs.get(existing_key)

                if r['status'] == 'completed':
                    run = self._create_run_from_result(None, r, existing_run=existing)
                    if existing:
                        total_updated += 1
                        symbol_updated += 1
                    else:
                        total_new_runs += 1
                        symbol_new += 1
                        existing_runs[existing_key] = run

                    if run.total_profit_pct is not None and run.total_profit_pct > best_profit:
                        best_profit = run.total_profit_pct
                        best_result = run
                else:
                    total_errors += 1

                pending_commits += 1
                if pending_commits >= BATCH_COMMIT_SIZE:
                    db.session.commit()
                    pending_commits = 0

            if pending_commits > 0:
                db.session.commit()

            print(f"  ✓ {symbol}: {symbol_new} new, {symbol_updated} updated", flush=True)

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
            'updated': total_updated,
            'new_runs': total_new_runs,
            'skipped': total_skipped,
            'errors': total_errors,
            'total': total_updated + total_new_runs + total_skipped,
            'best_result': best_result_dict,
        }

    def _run_incremental_parallel(
        self,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        parameter_grid: Dict,
        progress_callback=None,
        max_workers: int = None
    ) -> Dict:
        """
        Run incremental optimization with parallel symbol processing.

        Uses ProcessPoolExecutor to process multiple symbols concurrently.
        Each worker process loads data, detects patterns, and simulates trades.
        Database writes are done in the main process to avoid race conditions.

        Args:
            symbols: List of trading pairs
            timeframes: List of timeframes
            pattern_types: List of pattern types
            parameter_grid: Parameter combinations
            progress_callback: Optional progress callback
            max_workers: Number of workers (default: 4, max: 8)

        Returns:
            Summary dict with results
        """
        # Bound workers to prevent memory issues
        if max_workers is None:
            max_workers = DEFAULT_PARALLEL_WORKERS
        max_workers = min(max_workers, MAX_PARALLEL_WORKERS, len(symbols))

        print(f"\n{'='*60}", flush=True)
        print(f"PARALLEL PROCESSING: {len(symbols)} symbols with {max_workers} workers", flush=True)
        print(f"{'='*60}", flush=True)

        total_updated = 0
        total_new_runs = 0
        total_skipped = 0
        total_errors = 0
        best_result = None
        best_profit = float('-inf')

        # Pre-load existing runs for ALL symbols (needed for skip detection and DB updates)
        existing_runs_map = {}  # symbol -> {key: run}
        existing_timestamps_map = {}  # symbol -> {timeframe: max_timestamp}
        for symbol in symbols:
            existing_runs = {}
            existing_timestamps = {}
            all_existing = OptimizationRun.query.filter(
                OptimizationRun.symbol == symbol,
                OptimizationRun.timeframe.in_(timeframes),
                OptimizationRun.pattern_type.in_(pattern_types),
                OptimizationRun.status == 'completed'
            ).all()
            for run in all_existing:
                key = (run.symbol, run.timeframe, run.pattern_type, run.rr_target, run.sl_buffer_pct)
                existing_runs[key] = run
                # Track max timestamp per timeframe for skip detection
                if run.last_candle_timestamp:
                    if run.timeframe not in existing_timestamps:
                        existing_timestamps[run.timeframe] = run.last_candle_timestamp
                    else:
                        existing_timestamps[run.timeframe] = max(
                            existing_timestamps[run.timeframe],
                            run.last_candle_timestamp
                        )
            existing_runs_map[symbol] = existing_runs
            existing_timestamps_map[symbol] = existing_timestamps

        parallel_start = datetime.now(timezone.utc)
        completed_symbols = 0

        # Process symbols in parallel using ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all symbol processing tasks with existing timestamps for skip detection
            future_to_symbol = {
                executor.submit(
                    _process_symbol_worker,
                    symbol,
                    timeframes,
                    pattern_types,
                    parameter_grid,
                    existing_timestamps_map.get(symbol, {}) if existing_runs_map.get(symbol) else {}
                ): symbol
                for symbol in symbols
            }

            # Process results as they complete
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                completed_symbols += 1

                try:
                    worker_result = future.result()

                    if worker_result.get('error'):
                        print(f"  ✗ {symbol}: Error - {worker_result['error']}", flush=True)
                        param_combinations = list(itertools.product(*parameter_grid.values()))
                        total_errors += len(timeframes) * len(pattern_types) * len(param_combinations)
                        continue

                    if worker_result.get('skipped'):
                        total_skipped += worker_result.get('skip_count', 0)
                        continue

                    # Get existing runs for this symbol
                    existing_runs = existing_runs_map.get(symbol, {})

                    # Process results and create/update DB records
                    pending_commits = 0
                    symbol_updated = 0
                    symbol_new = 0
                    symbol_errors = 0

                    for r in worker_result.get('results', []):
                        params = r['params']
                        rr_target = params.get('rr_target', 2.0)
                        sl_buffer_pct = params.get('sl_buffer_pct', 10.0)
                        existing_key = (r['symbol'], r['timeframe'], r['pattern_type'], rr_target, sl_buffer_pct)
                        existing = existing_runs.get(existing_key)

                        if r['status'] == 'completed':
                            run = self._create_run_from_result(None, r, existing_run=existing)
                            if existing:
                                symbol_updated += 1
                            else:
                                symbol_new += 1
                                existing_runs[existing_key] = run

                            if run.total_profit_pct is not None and run.total_profit_pct > best_profit:
                                best_profit = run.total_profit_pct
                                best_result = run
                        else:
                            symbol_errors += 1

                        pending_commits += 1
                        if pending_commits >= BATCH_COMMIT_SIZE:
                            db.session.commit()
                            pending_commits = 0

                    if pending_commits > 0:
                        db.session.commit()

                    total_updated += symbol_updated
                    total_new_runs += symbol_new
                    total_errors += symbol_errors

                    print(f"  [{symbol}] ✓ {symbol_new} new, {symbol_updated} updated "
                          f"[{completed_symbols}/{len(symbols)}]", flush=True)

                except Exception as e:
                    print(f"  [{symbol}] ✗ Exception - {str(e)}", flush=True)
                    param_combinations = list(itertools.product(*parameter_grid.values()))
                    total_errors += len(timeframes) * len(pattern_types) * len(param_combinations)

        parallel_duration = (datetime.now(timezone.utc) - parallel_start).total_seconds()
        print(f"\n{'='*60}", flush=True)
        print(f"PARALLEL COMPLETE: {parallel_duration:.1f}s", flush=True)
        print(f"  Updated: {total_updated}, New: {total_new_runs}, "
              f"Skipped: {total_skipped}, Errors: {total_errors}", flush=True)
        print(f"{'='*60}\n", flush=True)

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
            'updated': total_updated,
            'new_runs': total_new_runs,
            'skipped': total_skipped,
            'errors': total_errors,
            'total': total_updated + total_new_runs + total_skipped,
            'best_result': best_result_dict,
            'parallel': True,
            'workers': max_workers,
            'duration_seconds': parallel_duration,
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
            existing.results_json = json.dumps(all_closed_trades)
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
                results_json=json.dumps(trades),
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
            existing.results_json = json.dumps(all_closed_trades)
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
                results_json=json.dumps(trades),
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
        Fast trade simulation using vectorized numpy, returning both closed and open trades.

        Returns:
            (closed_trades, open_trades)
        """
        if not patterns:
            return [], []

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

            if entry_idx + MIN_CANDLES_AFTER_PATTERN >= n_candles:
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

            # Vectorized trade simulation
            start_idx = entry_idx + 1
            end_idx = min(entry_idx + DEFAULT_MAX_TRADE_DURATION, n_candles)

            if start_idx >= end_idx:
                continue

            h_slice = highs[start_idx:end_idx]
            l_slice = lows[start_idx:end_idx]

            # Find entry trigger
            if direction == 'long':
                entry_mask = l_slice <= entry
            else:
                entry_mask = h_slice >= entry

            if not np.any(entry_mask):
                continue  # No entry triggered

            entry_offset = np.argmax(entry_mask)
            entry_candle = start_idx + entry_offset
            entry_time = int(timestamps[entry_candle])

            # Search for SL/TP after entry
            trade_start = entry_candle + 1
            if trade_start >= end_idx:
                # Entry at edge - trade is open
                open_trades.append({
                    'status': 'open',
                    'entry_price': float(entry),
                    'stop_loss': float(stop_loss),
                    'take_profit': float(take_profit),
                    'direction': direction,
                    'rr_target': float(rr_target),
                    'entry_time': entry_time,
                })
                continue

            h_trade = highs[trade_start:end_idx]
            l_trade = lows[trade_start:end_idx]

            if direction == 'long':
                sl_mask = l_trade <= stop_loss
                tp_mask = h_trade >= take_profit
            else:
                sl_mask = h_trade >= stop_loss
                tp_mask = l_trade <= take_profit

            sl_idx = np.argmax(sl_mask) if np.any(sl_mask) else len(sl_mask)
            tp_idx = np.argmax(tp_mask) if np.any(tp_mask) else len(tp_mask)

            sl_hit = sl_mask[sl_idx] if sl_idx < len(sl_mask) else False
            tp_hit = tp_mask[tp_idx] if tp_idx < len(tp_mask) else False

            if not sl_hit and not tp_hit:
                # Trade not resolved - still open
                open_trades.append({
                    'status': 'open',
                    'entry_price': float(entry),
                    'stop_loss': float(stop_loss),
                    'take_profit': float(take_profit),
                    'direction': direction,
                    'rr_target': float(rr_target),
                    'entry_time': entry_time,
                })
                continue

            # Determine outcome
            if sl_hit and tp_hit:
                if sl_idx <= tp_idx:
                    result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
                else:
                    result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit
            elif sl_hit:
                result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
            else:
                result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit

            closed_trades.append({
                'entry_price': float(entry),
                'exit_price': float(exit_price),
                'direction': direction,
                'result': result,
                'rr_achieved': float(rr_target) if result == 'win' else -1.0,
                'profit_pct': float(abs((exit_price - entry) / entry * 100) * (1 if result == 'win' else -1)),
                'entry_time': entry_time,
                'exit_time': int(timestamps[exit_idx]),
                'duration_candles': int(exit_idx - entry_candle)
            })

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
        """Fast single trade simulation using vectorized numpy, returning open if not resolved"""
        start_idx = entry_idx + 1
        end_idx = min(entry_idx + DEFAULT_MAX_TRADE_DURATION, n_candles)

        if start_idx >= end_idx:
            return None

        h_slice = highs[start_idx:end_idx]
        l_slice = lows[start_idx:end_idx]

        # Vectorized entry search
        if direction == 'long':
            entry_mask = l_slice <= entry
        else:
            entry_mask = h_slice >= entry

        if not np.any(entry_mask):
            return None

        entry_offset = np.argmax(entry_mask)
        entry_candle = start_idx + entry_offset
        entry_time = int(timestamps[entry_candle])

        # Search for SL/TP after entry
        trade_start = entry_candle + 1
        if trade_start >= end_idx:
            return {
                'status': 'open',
                'entry_price': float(entry),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'direction': direction,
                'rr_target': float(rr_target),
                'entry_time': entry_time,
            }

        h_trade = highs[trade_start:end_idx]
        l_trade = lows[trade_start:end_idx]

        if direction == 'long':
            sl_mask = l_trade <= stop_loss
            tp_mask = h_trade >= take_profit
        else:
            sl_mask = h_trade >= stop_loss
            tp_mask = l_trade <= take_profit

        sl_idx = np.argmax(sl_mask) if np.any(sl_mask) else len(sl_mask)
        tp_idx = np.argmax(tp_mask) if np.any(tp_mask) else len(tp_mask)

        sl_hit = sl_mask[sl_idx] if sl_idx < len(sl_mask) else False
        tp_hit = tp_mask[tp_idx] if tp_idx < len(tp_mask) else False

        if not sl_hit and not tp_hit:
            return {
                'status': 'open',
                'entry_price': float(entry),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'direction': direction,
                'rr_target': float(rr_target),
                'entry_time': entry_time,
            }

        if sl_hit and tp_hit:
            if sl_idx <= tp_idx:
                result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
            else:
                result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit
        elif sl_hit:
            result, exit_idx, exit_price = 'loss', trade_start + sl_idx, stop_loss
        else:
            result, exit_idx, exit_price = 'win', trade_start + tp_idx, take_profit

        return {
            'entry_price': float(entry),
            'exit_price': float(exit_price),
            'direction': direction,
            'result': result,
            'rr_achieved': float(rr_target) if result == 'win' else -1.0,
            'profit_pct': float(abs((exit_price - entry) / entry * 100) * (1 if result == 'win' else -1)),
            'entry_time': entry_time,
            'exit_time': int(timestamps[exit_idx]),
            'duration_candles': int(exit_idx - entry_candle)
        }

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

            # Use binary search to find first candle after entry_time (O(log n) vs O(n))
            start_idx = np.searchsorted(timestamps, entry_time, side='right')

            for idx in range(start_idx, n_candles):

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

            if entry_idx + MIN_CANDLES_AFTER_PATTERN >= len(df):
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
