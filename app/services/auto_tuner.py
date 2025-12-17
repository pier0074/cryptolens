"""
Auto-tuner service for applying optimization results to user preferences.

This service allows premium/admin users to copy the best parameters
from optimization runs to their symbol notification preferences.
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from app import db
from app.models import (
    OptimizationRun, Symbol, UserSymbolPreference
)

logger = logging.getLogger(__name__)


class AutoTuner:
    """Service for applying optimization results to user preferences."""

    def get_best_params_by_symbol(
        self,
        symbol: Optional[str] = None,
        pattern_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        metric: str = 'total_profit_pct',
        min_trades: int = 10
    ) -> Dict[str, Any]:
        """Get best parameters grouped by symbol.

        Args:
            symbol: Filter by specific symbol (optional)
            pattern_type: Filter by pattern type (optional)
            timeframe: Filter by timeframe (optional)
            metric: Metric to optimize ('total_profit_pct', 'win_rate', 'sharpe_ratio')
            min_trades: Minimum trades required for valid result

        Returns:
            Dict with best params per symbol, including nested pattern-specific params
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

        # Order by the selected metric
        if metric == 'win_rate':
            query = query.order_by(OptimizationRun.win_rate.desc())
        elif metric == 'sharpe_ratio':
            query = query.order_by(OptimizationRun.sharpe_ratio.desc())
        else:
            query = query.order_by(OptimizationRun.total_profit_pct.desc())

        runs = query.all()

        # Group by symbol
        results = {}
        for run in runs:
            sym = run.symbol
            if sym not in results:
                results[sym] = {
                    'symbol': sym,
                    'best_overall': None,
                    'by_pattern': {},
                    'by_timeframe': {},
                }

            # Track best overall for this symbol
            if results[sym]['best_overall'] is None:
                results[sym]['best_overall'] = self._run_to_params(run)

            # Track best by pattern type
            pt = run.pattern_type
            if pt not in results[sym]['by_pattern']:
                results[sym]['by_pattern'][pt] = self._run_to_params(run)

            # Track best by timeframe
            tf = run.timeframe
            if tf not in results[sym]['by_timeframe']:
                results[sym]['by_timeframe'][tf] = self._run_to_params(run)

        return results

    def _run_to_params(self, run: OptimizationRun) -> Dict[str, Any]:
        """Convert optimization run to params dict."""
        return {
            'run_id': run.id,
            'symbol': run.symbol,
            'timeframe': run.timeframe,
            'pattern_type': run.pattern_type,
            'rr_target': run.rr_target,
            'sl_buffer_pct': run.sl_buffer_pct,
            'min_zone_pct': run.min_zone_pct,
            'win_rate': run.win_rate,
            'total_profit_pct': run.total_profit_pct,
            'sharpe_ratio': run.sharpe_ratio,
            'profit_factor': run.profit_factor,
            'total_trades': run.total_trades,
            'max_drawdown_pct': run.max_drawdown_pct,
        }

    def apply_best_params_to_user(
        self,
        user_id: int,
        symbol: str,
        pattern_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        metric: str = 'total_profit_pct',
        min_trades: int = 10
    ) -> Dict[str, Any]:
        """Apply best optimization parameters to a user's symbol preference.

        Args:
            user_id: User ID to apply params to
            symbol: Symbol to configure
            pattern_type: Optional specific pattern type
            timeframe: Optional specific timeframe
            metric: Metric to optimize by
            min_trades: Minimum trades for valid result

        Returns:
            Dict with result status and applied parameters
        """
        # Get the symbol ID
        sym = Symbol.query.filter_by(symbol=symbol).first()
        if not sym:
            return {'success': False, 'error': f'Symbol {symbol} not found'}

        # Find best params
        query = OptimizationRun.query.filter(
            OptimizationRun.status == 'completed',
            OptimizationRun.symbol == symbol,
            OptimizationRun.total_trades >= min_trades
        )

        if pattern_type:
            query = query.filter(OptimizationRun.pattern_type == pattern_type)
        if timeframe:
            query = query.filter(OptimizationRun.timeframe == timeframe)

        # Order by metric
        if metric == 'win_rate':
            query = query.order_by(OptimizationRun.win_rate.desc())
        elif metric == 'sharpe_ratio':
            query = query.order_by(OptimizationRun.sharpe_ratio.desc())
        else:
            query = query.order_by(OptimizationRun.total_profit_pct.desc())

        best_run = query.first()

        if not best_run:
            return {
                'success': False,
                'error': f'No optimization results found for {symbol}'
            }

        # Get or create user preference
        pref = UserSymbolPreference.get_or_create(user_id, sym.id)

        # Apply parameters
        pref.set_params_from_optimization(
            rr_target=best_run.rr_target,
            sl_buffer_pct=best_run.sl_buffer_pct,
            min_zone_pct=best_run.min_zone_pct,
            pattern_type=pattern_type,
            optimization_run_id=best_run.id
        )

        db.session.commit()

        logger.info(
            f"Applied optimization params to user {user_id} for {symbol}: "
            f"RR={best_run.rr_target}, SL={best_run.sl_buffer_pct}%"
        )

        return {
            'success': True,
            'symbol': symbol,
            'pattern_type': pattern_type,
            'applied_params': {
                'rr_target': best_run.rr_target,
                'sl_buffer_pct': best_run.sl_buffer_pct,
                'min_zone_pct': best_run.min_zone_pct,
            },
            'source_run': {
                'id': best_run.id,
                'timeframe': best_run.timeframe,
                'pattern_type': best_run.pattern_type,
                'win_rate': best_run.win_rate,
                'total_profit_pct': best_run.total_profit_pct,
                'total_trades': best_run.total_trades,
            }
        }

    def apply_all_best_params_to_user(
        self,
        user_id: int,
        symbols: Optional[List[str]] = None,
        metric: str = 'total_profit_pct',
        min_trades: int = 10,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Apply best params for all symbols to a user.

        Args:
            user_id: User ID
            symbols: List of symbols to apply (None = all with optimization data)
            metric: Metric to optimize by
            min_trades: Minimum trades required
            dry_run: If True, don't actually apply changes

        Returns:
            Dict with results for each symbol
        """
        best_by_symbol = self.get_best_params_by_symbol(
            metric=metric,
            min_trades=min_trades
        )

        if symbols:
            # Filter to requested symbols
            best_by_symbol = {s: v for s, v in best_by_symbol.items() if s in symbols}

        results = {
            'success': True,
            'applied': [],
            'skipped': [],
            'errors': [],
            'dry_run': dry_run,
        }

        for symbol, data in best_by_symbol.items():
            if data['best_overall'] is None:
                results['skipped'].append({
                    'symbol': symbol,
                    'reason': 'No valid optimization results'
                })
                continue

            if dry_run:
                results['applied'].append({
                    'symbol': symbol,
                    'params': data['best_overall'],
                    'would_apply': True
                })
            else:
                result = self.apply_best_params_to_user(
                    user_id=user_id,
                    symbol=symbol,
                    metric=metric,
                    min_trades=min_trades
                )
                if result['success']:
                    results['applied'].append({
                        'symbol': symbol,
                        'params': result['applied_params'],
                        'source': result['source_run']
                    })
                else:
                    results['errors'].append({
                        'symbol': symbol,
                        'error': result['error']
                    })

        return results

    def get_comparison_data(
        self,
        symbol: str,
        pattern_type: str,
        timeframe: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get data for parameter comparison heatmap.

        Returns a grid of RR vs SL% with win_rate and profit values.
        """
        query = OptimizationRun.query.filter(
            OptimizationRun.status == 'completed',
            OptimizationRun.symbol == symbol,
            OptimizationRun.pattern_type == pattern_type,
            OptimizationRun.total_trades >= 5
        )

        if timeframe:
            query = query.filter(OptimizationRun.timeframe == timeframe)

        runs = query.all()

        if not runs:
            return {'success': False, 'error': 'No data available'}

        # Build heatmap data
        rr_values = sorted(set(r.rr_target for r in runs))
        sl_values = sorted(set(r.sl_buffer_pct for r in runs))

        # Create grids
        win_rate_grid = []
        profit_grid = []
        trades_grid = []

        for rr in rr_values:
            win_row = []
            profit_row = []
            trades_row = []
            for sl in sl_values:
                # Find run with this combination
                matching = [r for r in runs if r.rr_target == rr and r.sl_buffer_pct == sl]
                if matching:
                    # Average if multiple runs
                    avg_win = sum(r.win_rate or 0 for r in matching) / len(matching)
                    avg_profit = sum(r.total_profit_pct or 0 for r in matching) / len(matching)
                    total_trades = sum(r.total_trades or 0 for r in matching)
                    win_row.append(round(avg_win, 1))
                    profit_row.append(round(avg_profit, 2))
                    trades_row.append(total_trades)
                else:
                    win_row.append(None)
                    profit_row.append(None)
                    trades_row.append(0)
            win_rate_grid.append(win_row)
            profit_grid.append(profit_row)
            trades_grid.append(trades_row)

        # Find best cell
        best_profit_idx = None
        best_profit = float('-inf')
        best_winrate_idx = None
        best_winrate = float('-inf')

        for i, rr in enumerate(rr_values):
            for j, sl in enumerate(sl_values):
                if profit_grid[i][j] is not None and profit_grid[i][j] > best_profit:
                    best_profit = profit_grid[i][j]
                    best_profit_idx = (i, j)
                if win_rate_grid[i][j] is not None and win_rate_grid[i][j] > best_winrate:
                    best_winrate = win_rate_grid[i][j]
                    best_winrate_idx = (i, j)

        return {
            'success': True,
            'symbol': symbol,
            'pattern_type': pattern_type,
            'timeframe': timeframe,
            'rr_values': rr_values,
            'sl_values': sl_values,
            'win_rate_grid': win_rate_grid,
            'profit_grid': profit_grid,
            'trades_grid': trades_grid,
            'best_by_profit': {
                'rr': rr_values[best_profit_idx[0]] if best_profit_idx else None,
                'sl': sl_values[best_profit_idx[1]] if best_profit_idx else None,
                'value': best_profit if best_profit_idx else None,
            },
            'best_by_winrate': {
                'rr': rr_values[best_winrate_idx[0]] if best_winrate_idx else None,
                'sl': sl_values[best_winrate_idx[1]] if best_winrate_idx else None,
                'value': best_winrate if best_winrate_idx else None,
            },
        }

    def clear_user_custom_params(self, user_id: int, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Clear custom parameters for a user, reverting to system defaults.

        Args:
            user_id: User ID
            symbol: Optional specific symbol to clear (None = all)

        Returns:
            Dict with cleared symbol count
        """
        query = UserSymbolPreference.query.filter_by(user_id=user_id)

        if symbol:
            sym = Symbol.query.filter_by(symbol=symbol).first()
            if sym:
                query = query.filter_by(symbol_id=sym.id)

        prefs = query.all()
        cleared = 0

        for pref in prefs:
            if pref.custom_rr is not None or pref.pattern_params is not None:
                pref.clear_custom_params()
                cleared += 1

        db.session.commit()

        return {
            'success': True,
            'cleared_count': cleared,
            'symbol': symbol,
        }


# Singleton instance
auto_tuner = AutoTuner()
