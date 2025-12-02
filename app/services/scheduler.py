"""
Scheduler Service
Smart scheduling that respects timeframe intervals and prevents overload.

Key improvements:
- 5-minute base interval (not 1 minute)
- Timeframe-aware: only check TFs that could have new data
- Coalescing: missed jobs get merged, not queued
- No auto-start: manual control via API
"""
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.services.logger import log_fetch, log_aggregate, log_scan, log_signal, log_system, log_error

# Global scheduler instance
scheduler = None

# Track last run times to avoid redundant work
last_fetch_time = None
last_scan_time = {}  # per timeframe


def get_timeframes_to_check():
    """
    Determine which timeframes need checking based on time elapsed.
    This prevents checking 1h candles every minute when they only update hourly.

    Returns list of timeframes that could have new data.
    """
    now = datetime.now(timezone.utc)
    minute = now.minute
    hour = now.hour

    timeframes = ['1m']  # Always check 1m

    if minute % 5 == 0:
        timeframes.append('5m')
    if minute % 15 == 0:
        timeframes.append('15m')
    if minute % 30 == 0:
        timeframes.append('30m')
    if minute == 0:
        timeframes.append('1h')
        if hour % 2 == 0:
            timeframes.append('2h')
        if hour % 4 == 0:
            timeframes.append('4h')

    # Daily only at midnight UTC
    if hour == 0 and minute == 0:
        timeframes.append('1d')

    return timeframes


def fetch_latest_candles():
    """Fetch latest candles for all symbols (1m timeframe only - others aggregate from this)"""
    global last_fetch_time
    from app import create_app, db
    from app.models import Symbol
    from app.services.data_fetcher import fetch_candles

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        total_fetched = 0
        symbols_updated = []

        for symbol in symbols:
            try:
                # Fetch latest 1m candles (small batch)
                new_count, _ = fetch_candles(symbol.symbol, '1m', limit=5)
                total_fetched += new_count

                if new_count > 0:
                    symbols_updated.append(symbol.symbol)

            except Exception as e:
                log_error(f"Error fetching: {e}", symbol=symbol.symbol)

        if total_fetched > 0:
            log_fetch(
                f"Fetched {total_fetched} candles from {len(symbols_updated)} symbols",
                details={'symbols': symbols_updated, 'total': total_fetched}
            )

        last_fetch_time = datetime.now(timezone.utc)
        return total_fetched, symbols_updated


def aggregate_timeframes(symbols_updated: list):
    """
    Aggregate candles only for timeframes that need updating.
    Much more efficient than aggregating everything every time.
    """
    from app import create_app
    from app.services.aggregator import aggregate_candles
    from app.config import Config

    timeframes_to_aggregate = get_timeframes_to_check()

    # Skip 1m (source data) - aggregate to higher timeframes only
    target_timeframes = [tf for tf in timeframes_to_aggregate if tf != '1m']

    if not target_timeframes or not symbols_updated:
        return

    app = create_app()
    with app.app_context():
        for symbol in symbols_updated:
            for tf in target_timeframes:
                try:
                    count = aggregate_candles(symbol, '1m', tf)
                    if count > 0:
                        log_aggregate(f"{symbol} Aggregated {count} candles", symbol=symbol)
                except Exception as e:
                    log_error(f"Aggregation error: {e}", symbol=symbol)


def scan_patterns_smart():
    """
    Scan for patterns only on timeframes that could have new patterns.
    """
    from app import create_app
    from app.models import Symbol
    from app.services.patterns import get_all_detectors, PATTERN_TYPES
    from app.config import Config

    timeframes_to_scan = get_timeframes_to_check()

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()

        patterns_found = 0

        for symbol in symbols:
            for tf in timeframes_to_scan:
                for detector in detectors:
                    try:
                        patterns = detector.detect(symbol.symbol, tf)
                        patterns_found += len(patterns)
                    except Exception as e:
                        pass  # Silent fail for individual patterns

        if patterns_found > 0:
            log_scan(f"Found {patterns_found} new patterns in {timeframes_to_scan}")

        return patterns_found


def update_pattern_status():
    """Update status of existing patterns (check if filled)"""
    from app import create_app, db
    from app.models import Symbol
    from app.services.patterns import get_all_detectors
    from app.services.data_fetcher import get_latest_candles

    app = create_app()
    with app.app_context():
        symbols = Symbol.query.filter_by(is_active=True).all()
        detectors = get_all_detectors()
        updated_count = 0

        timeframes_to_check = get_timeframes_to_check()

        for symbol in symbols:
            try:
                # Get current price from latest candle
                candles = get_latest_candles(symbol.symbol, '1m', limit=1)
                if candles:
                    current_price = candles[-1]['close']

                    # Only update patterns for relevant timeframes
                    for tf in timeframes_to_check:
                        for detector in detectors:
                            if hasattr(detector, 'update_pattern_status'):
                                updated = detector.update_pattern_status(symbol.symbol, tf, current_price)
                                updated_count += updated

            except Exception as e:
                pass  # Silent fail

        if updated_count > 0:
            log_scan(f"Updated {updated_count} pattern statuses")

        return updated_count


def generate_signals():
    """Generate signals for high confluence patterns"""
    from app import create_app
    from app.services.signals import scan_and_generate_signals

    app = create_app()
    with app.app_context():
        try:
            result = scan_and_generate_signals()
            if result['signals_generated'] > 0:
                log_signal(
                    f"Generated {result['signals_generated']} signals",
                    details=result
                )
            return result
        except Exception as e:
            log_error(f"Signal generation error: {e}")
            return {'signals_generated': 0}


def run_scheduled_tasks():
    """
    Run scheduled tasks efficiently.
    Only processes what needs to be processed based on time.
    """
    start_time = datetime.now(timezone.utc)
    log_system(f"Starting scan cycle")

    try:
        # 1. Fetch latest 1m candles
        fetched, symbols_updated = fetch_latest_candles()

        # 2. Aggregate to higher timeframes (only those that need it)
        if symbols_updated:
            aggregate_timeframes(symbols_updated)

        # 3. Scan for new patterns (only relevant timeframes)
        scan_patterns_smart()

        # 4. Update existing pattern status
        update_pattern_status()

        # 5. Generate signals
        generate_signals()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        log_system(f"Scan cycle completed in {elapsed:.1f}s")

    except Exception as e:
        log_error(f"Scheduled task error: {e}")


def start_scheduler(app=None):
    """Start the background scheduler with smart intervals"""
    global scheduler

    if scheduler is not None:
        log_system("Scheduler already running", level='WARNING')
        return scheduler

    scheduler = BackgroundScheduler(
        job_defaults={
            'coalesce': True,  # Merge missed jobs into one
            'max_instances': 1,  # Only one instance at a time
            'misfire_grace_time': 300  # 5 minute grace period
        }
    )

    # 5-minute interval (not 1 minute - that's too aggressive)
    scheduler.add_job(
        run_scheduled_tasks,
        trigger=IntervalTrigger(minutes=5),
        id='scan_patterns',
        name='Smart pattern scan (5-min interval)',
        replace_existing=True
    )

    scheduler.start()
    log_system("Scheduler started - smart scanning every 5 minutes")

    return scheduler


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler

    if scheduler:
        scheduler.shutdown(wait=False)
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


def run_once():
    """Run a single scan cycle manually (useful for testing)"""
    run_scheduled_tasks()
