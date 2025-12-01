"""
Scheduler Service
Automatically fetches candles and scans for patterns at regular intervals
"""
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.services.logger import log_fetch, log_aggregate, log_scan, log_signal, log_system, log_error

# Global scheduler instance
scheduler = None


def fetch_latest_candles():
    """Fetch latest candles for all symbols (1m timeframe)"""
    from app import create_app, db
    from app.models import Symbol
    from app.services.data_fetcher import fetch_candles
    from app.services.aggregator import aggregate_all_timeframes

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        total_fetched = 0
        symbols_updated = []

        for symbol in symbols:
            try:
                # Fetch latest 1m candles
                new_count, _ = fetch_candles(symbol.symbol, '1m', limit=10)
                total_fetched += new_count

                # Quick aggregation for recent candles
                if new_count > 0:
                    symbols_updated.append(symbol.symbol)
                    agg_result = aggregate_all_timeframes(symbol.symbol)
                    log_aggregate(
                        f"Aggregated {sum(agg_result.values())} candles",
                        symbol=symbol.symbol,
                        details=agg_result
                    )

            except Exception as e:
                log_error(f"Error fetching: {e}", symbol=symbol.symbol)

        log_fetch(
            f"Fetched {total_fetched} new candles from {len(symbols_updated)} symbols",
            details={'symbols': symbols_updated, 'total': total_fetched}
        )
        return total_fetched


def scan_patterns():
    """Scan all symbols for patterns across all timeframes"""
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import scan_all_patterns
    from app.services.signals import scan_and_generate_signals
    from app.config import Config

    app = create_app()
    with app.app_context():
        try:
            # Scan for patterns
            result = scan_all_patterns()
            log_scan(
                f"Found {result['patterns_found']} patterns across {result['symbols_scanned']} symbols",
                details=result
            )

            # Generate signals for high confluence
            signal_result = scan_and_generate_signals()
            if signal_result['signals_generated'] > 0:
                log_signal(
                    f"Generated {signal_result['signals_generated']} signals, sent {signal_result['notifications_sent']} notifications",
                    details=signal_result
                )

            return result

        except Exception as e:
            log_error(f"Error scanning patterns: {e}")
            return {'error': str(e)}


def update_pattern_status():
    """Update status of existing patterns (check if filled)"""
    from app import create_app, db
    from app.models import Symbol, Pattern
    from app.services.patterns import get_all_detectors
    from app.services.data_fetcher import get_latest_candles

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()
        updated_count = 0

        for symbol in symbols:
            try:
                # Get current price from latest candle
                candles = get_latest_candles(symbol.symbol, '1m', limit=1)
                if candles:
                    current_price = candles[-1]['close']

                    # Update patterns for all timeframes and all pattern types
                    for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
                        for detector in detectors:
                            if hasattr(detector, 'update_pattern_status'):
                                updated = detector.update_pattern_status(symbol.symbol, tf, current_price)
                                updated_count += updated

            except Exception as e:
                log_error(f"Error updating patterns: {e}", symbol=symbol.symbol)

        if updated_count > 0:
            log_scan(f"Updated {updated_count} pattern statuses (filled/invalidated)")

        return updated_count


def run_scheduled_tasks():
    """Run all scheduled tasks in sequence"""
    log_system(f"Starting scheduled scan cycle")

    # 1. Fetch latest candles
    fetch_latest_candles()

    # 2. Scan for new patterns
    scan_patterns()

    # 3. Update existing pattern status
    update_pattern_status()

    log_system(f"Completed scheduled scan cycle")


def start_scheduler(app=None):
    """Start the background scheduler"""
    global scheduler

    if scheduler is not None:
        log_system("Scheduler already running", level='WARNING')
        return scheduler

    scheduler = BackgroundScheduler()

    # Schedule tasks
    # 1-minute interval for candle fetching and pattern scanning
    scheduler.add_job(
        run_scheduled_tasks,
        trigger=IntervalTrigger(minutes=1),
        id='scan_patterns',
        name='Fetch candles and scan patterns',
        replace_existing=True
    )

    # Run immediately on start
    scheduler.add_job(
        run_scheduled_tasks,
        id='initial_scan',
        name='Initial scan on startup'
    )

    scheduler.start()
    log_system("Scheduler started - scanning every 1 minute")

    return scheduler


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler

    if scheduler:
        scheduler.shutdown()
        scheduler = None
        log_system("Scheduler stopped")


def get_scheduler_status():
    """Get current scheduler status"""
    global scheduler

    if scheduler is None:
        return {'running': False, 'jobs': []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time.isoformat() if job.next_run_time else None
        })

    return {
        'running': scheduler.running,
        'jobs': jobs
    }
