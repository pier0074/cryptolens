"""
Scheduler Service (Simplified)

The actual scheduling is now done via cron:
  */5 * * * * cd /path/to/cryptolens && venv/bin/python scripts/scan.py
  */30 * * * * cd /path/to/cryptolens && venv/bin/python scripts/cleanup_patterns.py

This module provides API compatibility for status endpoints.
"""
from datetime import datetime, timezone
from app.services.logger import log_system


def get_scheduler_status():
    """
    Get scheduler status.
    Now returns info about cron-based scanning.
    """
    return {
        'running': False,
        'mode': 'cron',
        'message': 'Scanning is now handled via cron scripts for better CPU efficiency',
        'scripts': {
            'scan': 'scripts/scan.py (recommended: every 5 minutes)',
            'cleanup': 'scripts/cleanup_patterns.py (recommended: every 30 minutes)',
            'historical': 'scripts/fetch_historical.py (manual or daily)'
        },
        'cron_examples': [
            '*/5 * * * * cd /path/to/cryptolens && venv/bin/python scripts/scan.py',
            '*/30 * * * * cd /path/to/cryptolens && venv/bin/python scripts/cleanup_patterns.py'
        ]
    }


def start_scheduler(app=None):
    """
    Legacy function - now just logs that cron should be used.
    """
    log_system("Scheduler start requested - please use cron scripts instead", level='WARNING')
    return None


def stop_scheduler():
    """
    Legacy function - no-op since we don't use APScheduler anymore.
    """
    log_system("Scheduler stop requested - scheduler is managed via cron", level='INFO')


def run_once():
    """
    Run a single scan cycle manually.
    Useful for testing or manual triggers.
    """
    import subprocess
    import os

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'scripts', 'scan.py'
    )

    try:
        result = subprocess.run(
            ['python', script_path, '--verbose'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        return {
            'success': result.returncode == 0,
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Scan timed out after 5 minutes'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
