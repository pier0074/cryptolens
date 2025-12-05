# Gunicorn configuration for production
# Usage: gunicorn -c gunicorn.conf.py "app:create_app()"

import os
import multiprocessing

# Server socket
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:5000')
backlog = 2048

# Worker processes
# Capped at 4 for SQLite compatibility (WAL mode helps but still limited)
workers = min(int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1)), 4)
worker_class = 'sync'
threads = 2
worker_connections = 1000
timeout = 120
graceful_timeout = 30
keepalive = 5

# Process naming
proc_name = 'cryptolens'

# Logging
accesslog = '-'  # stdout
errorlog = '-'   # stderr
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (uncomment for HTTPS)
# keyfile = '/path/to/keyfile'
# certfile = '/path/to/certfile'

# Hooks
def on_starting(server):
    print("CryptoLens starting...")

def on_exit(server):
    print("CryptoLens shutting down...")

def worker_exit(server, worker):
    pass
