"""
Scheduler Service
Automatically fetches candles and scans for patterns at regular intervals
"""
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('scheduler')

# Global scheduler instance
scheduler = None


def fetch_latest_candles():
    """Fetch latest candles for all symbols (1m timeframe)"""
    from flask import current_app
    from app import create_app, db
    from app.models import Symbol
    from app.services.data_fetcher import fetch_candles
    from app.services.aggregator import aggregate_all_timeframes

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        total_fetched = 0

        for symbol in symbols:
            try:
                # Fetch latest 1m candles
                new_count, _ = fetch_candles(symbol.symbol, '1m', limit=10)
                total_fetched += new_count

                # Quick aggregation for recent candles
                if new_count > 0:
                    aggregate_all_timeframes(symbol.symbol)

            except Exception as e:
                logger.error(f"Error fetching {symbol.symbol}: {e}")

        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Fetched {total_fetched} new candles")
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
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Found {result['patterns_found']} patterns")

            # Generate signals for high confluence
            signal_result = scan_and_generate_signals()
            if signal_result['signals_generated'] > 0:
                logger.info(f"Generated {signal_result['signals_generated']} signals, "
                           f"sent {signal_result['notifications_sent']} notifications")

            return result

        except Exception as e:
            logger.error(f"Error scanning patterns: {e}")
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
                logger.error(f"Error updating patterns for {symbol.symbol}: {e}")

        if updated_count > 0:
            logger.info(f"Updated {updated_count} pattern statuses")

        return updated_count


def run_scheduled_tasks():
    """Run all scheduled tasks in sequence"""
    logger.info(f"\n{'='*40}")
    logger.info(f"Running scheduled scan at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Fetch latest candles
    fetch_latest_candles()

    # 2. Scan for new patterns
    scan_patterns()

    # 3. Update existing pattern status
    update_pattern_status()

    logger.info(f"{'='*40}\n")


def start_scheduler(app=None):
    """Start the background scheduler"""
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler already running")
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
    logger.info("Scheduler started - scanning every 1 minute")

    return scheduler


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler

    if scheduler:
        scheduler.shutdown()
        scheduler = None
        logger.info("Scheduler stopped")


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
