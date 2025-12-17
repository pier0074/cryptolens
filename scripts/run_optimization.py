#!/usr/bin/env python
"""
Run parameter optimization for backtesting.

Usage:
    python scripts/run_optimization.py --symbol BTC/USDT       # Single symbol
    python scripts/run_optimization.py --all-symbols           # All active symbols
    python scripts/run_optimization.py --list                  # List all jobs
    python scripts/run_optimization.py --results               # Show all results
    python scripts/run_optimization.py --best                  # Show best parameters

Options:
    --symbol        Run optimization for a specific symbol
    --all-symbols   Run optimization for all active symbols
    --timeframes    Comma-separated timeframes (default: 1h,4h)
    --patterns      Comma-separated patterns (default: imbalance,order_block)
    --list          List all optimization jobs
    --results       Show all optimization results
    --best          Show best parameters by symbol
    --verbose       Show detailed progress

The script automatically uses the full available date range from candles.
"""
import sys
import os
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import (
    OptimizationJob, OptimizationRun, Symbol, Candle,
    DEFAULT_PARAMETER_GRID, QUICK_PARAMETER_GRID
)
from app.services.optimizer import optimizer


def get_date_range_for_symbol(symbol_name, timeframe='1h'):
    """Get the available date range for a symbol from candles."""
    symbol = Symbol.query.filter_by(symbol=symbol_name).first()
    if not symbol:
        return None, None

    # Get earliest and latest candle
    earliest = Candle.query.filter_by(
        symbol_id=symbol.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.asc()).first()

    latest = Candle.query.filter_by(
        symbol_id=symbol.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).first()

    if not earliest or not latest:
        return None, None

    start_date = datetime.fromtimestamp(earliest.timestamp / 1000, tz=timezone.utc)
    end_date = datetime.fromtimestamp(latest.timestamp / 1000, tz=timezone.utc)

    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')


def progress_callback(completed, total):
    """Print progress bar"""
    pct = int(completed / total * 100) if total > 0 else 0
    bar_len = 40
    filled = int(bar_len * completed / total) if total > 0 else 0
    bar = '=' * filled + '-' * (bar_len - filled)
    print(f'\r  [{bar}] {pct}% ({completed}/{total})', end='', flush=True)


def run_optimization(symbols, timeframes, pattern_types, verbose=False, incremental=False):
    """Run optimization for given symbols."""
    if incremental:
        run_incremental_optimization(symbols, timeframes, pattern_types, verbose)
        return

    # Get date range from first symbol's candles
    start_date, end_date = get_date_range_for_symbol(symbols[0], timeframes[0])

    if not start_date:
        print(f"Error: No candle data found for {symbols[0]}")
        return

    print(f"\n{'='*60}")
    print(f"PARAMETER OPTIMIZATION")
    print(f"{'='*60}")
    print(f"  Symbols: {', '.join(symbols)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print(f"  Patterns: {', '.join(pattern_types)}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"{'='*60}\n")

    # Create job
    job_name = f"Optimization {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    job = optimizer.create_job(
        name=job_name,
        symbols=symbols,
        timeframes=timeframes,
        pattern_types=pattern_types,
        start_date=start_date,
        end_date=end_date,
        parameter_grid=QUICK_PARAMETER_GRID,
    )

    print(f"Created job #{job.id}: {job.name}")
    print(f"  Total runs: {job.total_runs}")
    print()

    # Run job
    callback = progress_callback if verbose else None
    result = optimizer.run_job(job.id, progress_callback=callback)

    if verbose:
        print()  # New line after progress bar

    if 'error' in result:
        print(f"\nError: {result['error']}")
        return

    print(f"\n{'='*60}")
    print(f"COMPLETED")
    print(f"{'='*60}")
    print(f"  Successful: {result['completed']}")
    print(f"  Failed: {result['failed']}")

    if result.get('best_params'):
        bp = result['best_params']
        print(f"\n  BEST RESULT:")
        print(f"    {bp['symbol']} {bp['timeframe']} {bp['pattern_type']}")
        print(f"    RR: {bp['params']['rr_target']}, SL: {bp['params']['sl_buffer_pct']}%")
        print(f"    Win Rate: {bp['win_rate']}%, Profit: {bp['total_profit_pct']}%")
        print(f"    Trades: {bp['total_trades']}")

    print(f"\nView all results: python scripts/run_optimization.py --results")
    print(f"Or visit: /admin/optimization/results")


def run_incremental_optimization(symbols, timeframes, pattern_types, verbose=False):
    """Run incremental optimization - only process new candles."""
    print(f"\n{'='*60}")
    print(f"INCREMENTAL OPTIMIZATION")
    print(f"{'='*60}")
    print(f"  Symbols: {', '.join(symbols)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print(f"  Patterns: {', '.join(pattern_types)}")
    print(f"  Mode: Incremental (only new candles)")
    print(f"{'='*60}\n")

    callback = progress_callback if verbose else None
    result = optimizer.run_incremental(
        symbols=symbols,
        timeframes=timeframes,
        pattern_types=pattern_types,
        parameter_grid=QUICK_PARAMETER_GRID,
        progress_callback=callback
    )

    if verbose:
        print()  # New line after progress bar

    print(f"\n{'='*60}")
    print(f"COMPLETED")
    print(f"{'='*60}")
    print(f"  Updated existing: {result['updated']}")
    print(f"  New runs created: {result['new_runs']}")
    print(f"  Skipped (no new data): {result['skipped']}")
    print(f"  Errors: {result['errors']}")

    print(f"\nView all results: python scripts/run_optimization.py --results")
    print(f"Or visit: /admin/optimization/results")


def list_jobs():
    """List all optimization jobs."""
    jobs = OptimizationJob.query.order_by(OptimizationJob.created_at.desc()).all()

    if not jobs:
        print("No optimization jobs found")
        return

    print(f"\n{'ID':<5} {'Name':<35} {'Status':<12} {'Progress':<12} {'Created':<20}")
    print('-' * 90)

    for job in jobs:
        progress = f"{job.completed_runs}/{job.total_runs}"
        created = job.created_at.strftime('%Y-%m-%d %H:%M') if job.created_at else 'N/A'
        print(f"{job.id:<5} {job.name[:35]:<35} {job.status:<12} {progress:<12} {created:<20}")


def show_results():
    """Show all optimization results."""
    runs = OptimizationRun.query.filter(
        OptimizationRun.status == 'completed',
        OptimizationRun.total_trades >= 5
    ).order_by(
        OptimizationRun.total_profit_pct.desc()
    ).all()

    if not runs:
        print("No optimization results found (min 5 trades required)")
        return

    print(f"\n{'Symbol':<12} {'TF':<5} {'Pattern':<15} {'RR':<5} {'SL%':<5} {'Trades':<7} {'Win%':<7} {'Profit%':<10} {'Sharpe':<8}")
    print('-' * 90)

    best_profit = runs[0].total_profit_pct if runs else 0

    for i, run in enumerate(runs[:50]):  # Top 50
        is_best = run.total_profit_pct == best_profit
        marker = '*' if is_best else ' '

        print(f"{marker}{run.symbol:<11} {run.timeframe:<5} {run.pattern_type:<15} "
              f"{run.rr_target:<5} {run.sl_buffer_pct:<5} {run.total_trades:<7} "
              f"{run.win_rate or 0:<7.1f} {run.total_profit_pct or 0:<10.2f} "
              f"{run.sharpe_ratio or 0:<8.2f}")

    print(f"\n* = Best result | Showing top 50 of {len(runs)} results")


def show_best_params():
    """Show best parameters by symbol."""
    # Get unique symbols
    symbols = db.session.query(OptimizationRun.symbol).distinct().all()
    symbols = [s[0] for s in symbols]

    if not symbols:
        print("No optimization results found")
        return

    print(f"\n{'='*70}")
    print("BEST PARAMETERS BY SYMBOL")
    print(f"{'='*70}\n")

    for symbol in sorted(symbols):
        print(f"{symbol}:")

        for pattern_type in ['imbalance', 'order_block', 'liquidity_sweep']:
            best = OptimizationRun.query.filter(
                OptimizationRun.symbol == symbol,
                OptimizationRun.pattern_type == pattern_type,
                OptimizationRun.status == 'completed',
                OptimizationRun.total_trades >= 5
            ).order_by(
                OptimizationRun.total_profit_pct.desc()
            ).first()

            if best:
                print(f"  {pattern_type:20} RR={best.rr_target}, SL={best.sl_buffer_pct}% "
                      f"→ Win:{best.win_rate:.1f}%, Profit:{best.total_profit_pct:.2f}%, "
                      f"Trades:{best.total_trades}")
            else:
                print(f"  {pattern_type:20} No data")
        print()


def reset_optimization_data(confirm_code=None):
    """Delete all optimization data with safety confirmation."""
    import random
    from sqlalchemy import text

    # Count existing data using raw SQL to avoid column issues
    job_count = db.session.execute(text("SELECT COUNT(*) FROM optimization_jobs")).scalar() or 0
    run_count = db.session.execute(text("SELECT COUNT(*) FROM optimization_runs")).scalar() or 0

    if job_count == 0 and run_count == 0:
        print("No optimization data to delete.")
        return

    print(f"\n{'='*60}")
    print("⚠️  WARNING: DESTRUCTIVE OPERATION")
    print(f"{'='*60}")
    print(f"  This will permanently delete:")
    print(f"    - {job_count} optimization jobs")
    print(f"    - {run_count} optimization runs (backtest results)")
    print(f"\n  This action CANNOT be undone!")
    print(f"{'='*60}\n")

    # Generate random confirmation code
    expected_code = str(random.randint(1000, 9999))

    if confirm_code:
        # Code provided via CLI
        user_code = confirm_code
    else:
        # Interactive mode
        print(f"  To confirm, type this code: {expected_code}")
        user_code = input("  Enter code: ").strip()

    if user_code != expected_code:
        print("\n❌ Confirmation code does not match. Aborting.")
        return

    # Delete all data using raw SQL
    print("\nDeleting optimization data...")

    # Delete runs first (foreign key constraint)
    db.session.execute(text("DELETE FROM optimization_runs"))
    db.session.execute(text("DELETE FROM optimization_jobs"))
    db.session.commit()

    print(f"\n✅ Deleted {job_count} jobs and {run_count} runs.")
    print("   Database optimization data has been reset.")


def main():
    parser = argparse.ArgumentParser(description='Run parameter optimization')
    parser.add_argument('--symbol', type=str, help='Single symbol to optimize')
    parser.add_argument('--all-symbols', action='store_true', help='Optimize all active symbols')
    parser.add_argument('--timeframes', type=str, default='5m,15m,30m,1h,2h,4h,1d', help='Comma-separated timeframes')
    parser.add_argument('--patterns', type=str, default='imbalance,order_block,liquidity_sweep',
                        help='Comma-separated pattern types')
    parser.add_argument('--incremental', '-i', action='store_true',
                        help='Incremental mode: only process new candles since last run')
    parser.add_argument('--list', action='store_true', help='List all jobs')
    parser.add_argument('--results', action='store_true', help='Show all results')
    parser.add_argument('--best', action='store_true', help='Show best parameters')
    parser.add_argument('--reset', action='store_true', help='Delete ALL optimization data (requires confirmation)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed progress')

    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all()

        if args.reset:
            reset_optimization_data()
        elif args.list:
            list_jobs()
        elif args.results:
            show_results()
        elif args.best:
            show_best_params()
        elif args.symbol:
            symbols = [args.symbol.strip()]
            timeframes = [t.strip() for t in args.timeframes.split(',')]
            patterns = [p.strip() for p in args.patterns.split(',')]
            run_optimization(symbols, timeframes, patterns, args.verbose, args.incremental)
        elif args.all_symbols:
            active_symbols = Symbol.query.filter_by(is_active=True).all()
            if not active_symbols:
                print("No active symbols found")
                return
            symbols = [s.symbol for s in active_symbols]
            timeframes = [t.strip() for t in args.timeframes.split(',')]
            patterns = [p.strip() for p in args.patterns.split(',')]
            run_optimization(symbols, timeframes, patterns, args.verbose, args.incremental)
        else:
            parser.print_help()
            print("\nExamples:")
            print("  python scripts/run_optimization.py --symbol BTC/USDT -v")
            print("  python scripts/run_optimization.py --all-symbols -v")
            print("  python scripts/run_optimization.py --all-symbols -i -v  # Incremental (only new candles)")
            print("  python scripts/run_optimization.py --results")
            print("  python scripts/run_optimization.py --best")
            print("  python scripts/run_optimization.py --reset              # Delete all data (with confirmation)")


if __name__ == '__main__':
    main()
