#!/usr/bin/env python
"""
RQ Worker Entry Point
Run background jobs for CryptoLens

Usage:
    python worker.py              # Run worker for all queues
    python worker.py high         # Run worker for high priority only
    python worker.py default low  # Run worker for specific queues

Or use rq command directly:
    rq worker high default low --url redis://localhost:6379/0
"""
import os
import sys
import logging
from redis import Redis
from rq import Worker, Queue, Connection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('cryptolens.worker')

# Queue names in priority order
QUEUE_NAMES = ['high', 'default', 'low']


def get_redis_connection():
    """Get Redis connection."""
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return Redis.from_url(redis_url)


def run_worker(queue_names=None):
    """
    Run the RQ worker.

    Args:
        queue_names: List of queue names to listen to (default: all)
    """
    if queue_names is None:
        queue_names = QUEUE_NAMES

    redis_conn = get_redis_connection()

    with Connection(redis_conn):
        queues = [Queue(name) for name in queue_names]
        worker = Worker(queues)

        logger.info(f"Starting worker for queues: {', '.join(queue_names)}")
        logger.info(f"Redis: {os.getenv('REDIS_URL', 'redis://localhost:6379/0')}")

        worker.work(with_scheduler=True)


if __name__ == '__main__':
    # Get queue names from command line args
    queue_names = sys.argv[1:] if len(sys.argv) > 1 else None

    # Validate queue names
    if queue_names:
        invalid = [q for q in queue_names if q not in QUEUE_NAMES]
        if invalid:
            logger.error(f"Invalid queue names: {invalid}")
            logger.error(f"Valid queues: {QUEUE_NAMES}")
            sys.exit(1)

    run_worker(queue_names)
