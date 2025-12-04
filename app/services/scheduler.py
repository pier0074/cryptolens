"""
Scheduler Service (Cron-based)

All scheduling is handled via system cron with a single script:
  * * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch.py

This module provides API endpoints for status and manual triggers.
"""
import subprocess
import os
from app.services.logger import log_system


def get_scheduler_status():
    """Get scheduler status info including last update time."""
    from app.models import Candle
    from sqlalchemy import func

    # Get most recent candle timestamp to show when cron last ran
    latest = Candle.query.with_entities(func.max(Candle.timestamp)).filter(
        Candle.timeframe == '1m'
    ).scalar()

    return {
        'mode': 'cron',
        'last_update': latest,  # timestamp in ms, null if no data
        'message': 'All operations run via cron scripts',
        'cron_setup': [
            '* * * * * cd /path && venv/bin/python scripts/fetch.py',
            '0 * * * * cd /path && venv/bin/python scripts/fetch_historical.py --gaps'
        ],
        'operations': [
            'Fetch 1m candles (parallel)',
            'Aggregate to higher timeframes',
            'Detect patterns',
            'Generate signals & notify',
            'Expire old patterns',
            'Fill data gaps (hourly)'
        ]
    }


def start_scheduler(app=None):
    """Legacy - scheduler is now cron-based."""
    log_system("Scheduler is managed via cron", level='INFO')
    return None


def stop_scheduler():
    """Legacy - scheduler is now cron-based."""
    log_system("Scheduler is managed via cron", level='INFO')


def run_once():
    """Run a single fetch cycle manually."""
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'scripts', 'fetch.py'
    )

    try:
        result = subprocess.run(
            ['python', script_path, '--verbose'],
            capture_output=True,
            text=True,
            timeout=120
        )
        return {
            'success': result.returncode == 0,
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Fetch timed out after 2 minutes'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
