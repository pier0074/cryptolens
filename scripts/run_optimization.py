#!/usr/bin/env python
"""
Run parameter optimization jobs.

Usage:
    python scripts/run_optimization.py --new                    # Create and run new quick job
    python scripts/run_optimization.py --job-id ID              # Run existing job
    python scripts/run_optimization.py --list                   # List all jobs
    python scripts/run_optimization.py --best                   # Show best parameters

Options:
    --new           Create and run a new optimization job
    --job-id ID     Run an existing job by ID
    --list          List all optimization jobs
    --best          Show best parameters from all completed runs
    --symbols       Comma-separated symbols (default: BTC/USDT,ETH/USDT)
    --timeframes    Comma-separated timeframes (default: 1h,4h)
    --patterns      Comma-separated patterns (default: imbalance,order_block)
    --start-date    Start date YYYY-MM-DD (default: 90 days ago)
    --end-date      End date YYYY-MM-DD (default: today)
    --full-grid     Use full parameter grid instead of quick grid
    --verbose       Show detailed progress

Cron setup (run weekly on Sunday at 2 AM):
    0 2 * * 0 cd /path/to/cryptolens && venv/bin/python scripts/run_optimization.py --new
"""
import sys
import os
import argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import (
    OptimizationJob, OptimizationRun, Symbol,
    DEFAULT_PARAMETER_GRID, QUICK_PARAMETER_GRID
)
from app.services.optimizer import optimizer


def progress_callback(completed, total):
    """Print progress bar"""
    pct = int(completed / total * 100) if total > 0 else 0
    bar_len = 40
    filled = int(bar_len * completed / total) if total > 0 else 0
    bar = '=' * filled + '-' * (bar_len - filled)
    print(f'\r  [{bar}] {pct}% ({completed}/{total})', end='', flush=True)


def create_and_run_job(args):
    """Create a new job and run it"""
    # Parse symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]
    else:
        # Get active symbols from DB
        active_symbols = Symbol.query.filter_by(is_active=True).limit(5).all()
        symbols = [s.symbol for s in active_symbols] if active_symbols else ['BTC/USDT', 'ETH/USDT']

    # Parse timeframes
    if args.timeframes:
        timeframes = [t.strip() for t in args.timeframes.split(',')]
    else:
        timeframes = ['1h', '4h']

    # Parse patterns
    if args.patterns:
        pattern_types = [p.strip() for p in args.patterns.split(',')]
    else:
        pattern_types = ['imbalance', 'order_block']

    # Parse dates
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if args.start_date:
        start_date = args.start_date
    else:
        start_dt = datetime.now(timezone.utc) - timedelta(days=90)
        start_date = start_dt.strftime('%Y-%m-%d')

    # Select parameter grid
    param_grid = DEFAULT_PARAMETER_GRID if args.full_grid else QUICK_PARAMETER_GRID

    # Create job
    job_name = f"Optimization {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    print(f"Creating optimization job: {job_name}")
    print(f"  Symbols: {symbols}")
    print(f"  Timeframes: {timeframes}")
    print(f"  Patterns: {pattern_types}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Grid: {'full' if args.full_grid else 'quick'}")

    job = optimizer.create_job(
        name=job_name,
        symbols=symbols,
        timeframes=timeframes,
        pattern_types=pattern_types,
        start_date=start_date,
        end_date=end_date,
        parameter_grid=param_grid,
    )

    print(f"  Total runs: {job.total_runs}")
    print()

    # Run job
    run_job(job.id, args.verbose)


def run_job(job_id, verbose=False):
    """Run an existing job"""
    job = OptimizationJob.query.get(job_id)
    if not job:
        print(f"Error: Job {job_id} not found")
        return

    print(f"Running job {job_id}: {job.name}")
    print(f"  Status: {job.status}")
    print(f"  Total runs: {job.total_runs}")
    print()

    callback = progress_callback if verbose else None
    result = optimizer.run_job(job_id, progress_callback=callback)

    if verbose:
        print()  # New line after progress bar

    if 'error' in result:
        print(f"Error: {result['error']}")
        return

    print(f"\nCompleted!")
    print(f"  Successful: {result['completed']}")
    print(f"  Failed: {result['failed']}")

    if result.get('best_params'):
        bp = result['best_params']
        print(f"\nBest parameters:")
        print(f"  Symbol: {bp['symbol']}")
        print(f"  Timeframe: {bp['timeframe']}")
        print(f"  Pattern: {bp['pattern_type']}")
        print(f"  RR Target: {bp['params']['rr_target']}")
        print(f"  SL Buffer: {bp['params']['sl_buffer_pct']}%")
        print(f"  Win Rate: {bp['win_rate']}%")
        print(f"  Total Profit: {bp['total_profit_pct']}%")
        print(f"  Total Trades: {bp['total_trades']}")


def list_jobs():
    """List all optimization jobs"""
    jobs = OptimizationJob.query.order_by(OptimizationJob.created_at.desc()).all()

    if not jobs:
        print("No optimization jobs found")
        return

    print(f"{'ID':<5} {'Name':<40} {'Status':<12} {'Progress':<15} {'Created':<20}")
    print('-' * 95)

    for job in jobs:
        progress = f"{job.completed_runs + job.failed_runs}/{job.total_runs}"
        created = job.created_at.strftime('%Y-%m-%d %H:%M') if job.created_at else 'N/A'
        print(f"{job.id:<5} {job.name[:40]:<40} {job.status:<12} {progress:<15} {created:<20}")


def show_best_params(args):
    """Show best parameters from all completed runs"""
    print("Best parameters by profit:\n")

    # Get best for each pattern type
    for pattern_type in ['imbalance', 'order_block', 'liquidity_sweep']:
        best = optimizer.get_best_params(
            pattern_type=pattern_type,
            metric='total_profit_pct',
            min_trades=10
        )

        if best:
            print(f"  {pattern_type}:")
            print(f"    Symbol: {best['symbol']} {best['timeframe']}")
            print(f"    RR: {best['params']['rr_target']}, SL: {best['params']['sl_buffer_pct']}%")
            print(f"    Win Rate: {best['win_rate']}%, Profit: {best['total_profit_pct']}%")
            print(f"    Trades: {best['total_trades']}, Sharpe: {best['sharpe_ratio']}")
            print()
        else:
            print(f"  {pattern_type}: No data")
            print()


def main():
    parser = argparse.ArgumentParser(description='Run parameter optimization')
    parser.add_argument('--new', action='store_true', help='Create and run new job')
    parser.add_argument('--job-id', type=int, help='Run existing job by ID')
    parser.add_argument('--list', action='store_true', help='List all jobs')
    parser.add_argument('--best', action='store_true', help='Show best parameters')
    parser.add_argument('--symbols', type=str, help='Comma-separated symbols')
    parser.add_argument('--timeframes', type=str, help='Comma-separated timeframes')
    parser.add_argument('--patterns', type=str, help='Comma-separated pattern types')
    parser.add_argument('--start-date', type=str, help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', type=str, help='End date YYYY-MM-DD')
    parser.add_argument('--full-grid', action='store_true', help='Use full parameter grid')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed progress')

    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Ensure tables exist
        db.create_all()

        if args.list:
            list_jobs()
        elif args.best:
            show_best_params(args)
        elif args.job_id:
            run_job(args.job_id, args.verbose)
        elif args.new:
            create_and_run_job(args)
        else:
            parser.print_help()


if __name__ == '__main__':
    main()
