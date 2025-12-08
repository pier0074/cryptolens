# CryptoLens Production Deployment Guide

Complete guide to deploying CryptoLens on a production server.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Server Setup](#server-setup)
3. [PostgreSQL Setup](#postgresql-setup)
4. [Redis Setup](#redis-setup)
5. [Application Setup](#application-setup)
6. [Environment Configuration](#environment-configuration)
7. [Database Migration](#database-migration)
8. [Gunicorn Setup](#gunicorn-setup)
9. [Nginx Configuration](#nginx-configuration)
10. [SSL/HTTPS Setup](#sslhttps-setup)
11. [Background Workers](#background-workers)
12. [Cron Jobs](#cron-jobs)
13. [Monitoring Setup](#monitoring-setup)
14. [Backup Strategy](#backup-strategy)
15. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Ubuntu 22.04 LTS or similar Linux server
- Python 3.9+
- PostgreSQL 14+
- Redis 6+
- Nginx
- Domain name with DNS configured
- SMTP server for email (Gmail, SendGrid, etc.)

**Recommended server specs:**
- 2+ CPU cores
- 4GB+ RAM
- 40GB+ SSD storage

---

## Server Setup

### 1. Update system and install dependencies

```bash
sudo apt update && sudo apt upgrade -y

# Install Python and build tools
sudo apt install -y python3 python3-pip python3-venv python3-dev
sudo apt install -y build-essential libpq-dev

# Install Nginx
sudo apt install -y nginx

# Install Certbot for SSL
sudo apt install -y certbot python3-certbot-nginx

# Install supervisor for process management
sudo apt install -y supervisor
```

### 2. Create application user

```bash
sudo useradd -m -s /bin/bash cryptolens
sudo usermod -aG sudo cryptolens
```

---

## PostgreSQL Setup

### 1. Install PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib
```

### 2. Create database and user

```bash
sudo -u postgres psql

-- In PostgreSQL shell:
CREATE USER cryptolens WITH PASSWORD 'your-secure-password-here';
CREATE DATABASE cryptolens_prod OWNER cryptolens;
GRANT ALL PRIVILEGES ON DATABASE cryptolens_prod TO cryptolens;

-- Enable required extensions
\c cryptolens_prod
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For text search

\q
```

### 3. Configure PostgreSQL for production

Edit `/etc/postgresql/14/main/postgresql.conf`:

```ini
# Connection settings
listen_addresses = 'localhost'
max_connections = 100

# Memory settings (adjust based on server RAM)
shared_buffers = 1GB              # 25% of RAM
effective_cache_size = 3GB        # 75% of RAM
work_mem = 16MB
maintenance_work_mem = 256MB

# Write-ahead log
wal_buffers = 64MB
checkpoint_completion_target = 0.9
```

Restart PostgreSQL:

```bash
sudo systemctl restart postgresql
```

---

## Redis Setup

### 1. Install Redis

```bash
sudo apt install -y redis-server
```

### 2. Configure Redis

Edit `/etc/redis/redis.conf`:

```ini
# Bind to localhost only
bind 127.0.0.1

# Set password (optional but recommended)
requirepass your-redis-password

# Memory management
maxmemory 512mb
maxmemory-policy allkeys-lru

# Persistence (RDB snapshots)
save 900 1
save 300 10
save 60 10000
```

Restart Redis:

```bash
sudo systemctl enable redis-server
sudo systemctl restart redis-server
```

### 3. Redis Usage in CryptoLens

Redis is used for:

1. **Cache**: Session data, API responses, computed stats
2. **Rate Limiting**: API and login rate limits (Flask-Limiter)
3. **Job Queues**: Background job processing (RQ)

**Environment variables:**

```bash
# Redis URL for cache and jobs
REDIS_URL=redis://localhost:6379/0

# Rate limiter storage (REQUIRED for production)
RATELIMIT_STORAGE_URL=redis://localhost:6379/1

# If Redis has a password:
REDIS_URL=redis://:your-redis-password@localhost:6379/0
RATELIMIT_STORAGE_URL=redis://:your-redis-password@localhost:6379/1
```

> **Important**: Without `RATELIMIT_STORAGE_URL`, rate limiting uses in-memory storage which doesn't work across multiple workers or server restarts.

---

## Application Setup

### 1. Clone repository

```bash
sudo -u cryptolens -i
cd ~
git clone https://github.com/pier0074/cryptolens.git
cd cryptolens
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create directories

```bash
mkdir -p data logs
chmod 755 data logs
```

---

## Environment Configuration

### 1. Create production .env file

```bash
nano .env
```

Add the following configuration:

```bash
# ===========================================
# CRYPTOLENS PRODUCTION CONFIGURATION
# ===========================================

# Flask Configuration
SECRET_KEY=generate-a-64-char-random-string-here
FLASK_ENV=production

# Database (PostgreSQL)
DATABASE_URL=postgresql://cryptolens:your-db-password@localhost:5432/cryptolens_prod

# Redis Cache
REDIS_URL=redis://:your-redis-password@localhost:6379/0

# Email Configuration (SMTP)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=noreply@yourdomain.com

# NTFY Notifications
NTFY_URL=https://ntfy.sh

# Encryption Key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ENCRYPTION_KEY=your-fernet-key-here

# Error Tracking (Self-hosted - no external service required)
# Uses PostgreSQL for storage and sends email alerts for critical errors
ERROR_TRACKING_ENABLED=true
APP_VERSION=1.0.0

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Payment Providers (Optional)
LEMONSQUEEZY_API_KEY=
LEMONSQUEEZY_WEBHOOK_SECRET=
NOWPAYMENTS_API_KEY=
NOWPAYMENTS_IPN_SECRET=

# Server
SERVER_NAME=cryptolens
```

### 2. Generate secret keys

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate ENCRYPTION_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Set file permissions

```bash
chmod 600 .env
```

---

## Database Migration

### 1. Run migrations

```bash
source venv/bin/activate
python scripts/migrate_all.py
```

### 2. Create admin account

```bash
python scripts/create_admin.py
```

### 3. Fetch initial data

```bash
python scripts/fetch_historical.py -v
```

---

## Gunicorn Setup

### 1. Create Gunicorn config

```bash
nano gunicorn.conf.py
```

```python
# Gunicorn configuration for CryptoLens

import multiprocessing

# Server socket
bind = "127.0.0.1:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5

# Process naming
proc_name = "cryptolens"

# Logging
accesslog = "/home/cryptolens/cryptolens/logs/gunicorn-access.log"
errorlog = "/home/cryptolens/cryptolens/logs/gunicorn-error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Server mechanics
daemon = False
pidfile = "/home/cryptolens/cryptolens/gunicorn.pid"
user = "cryptolens"
group = "cryptolens"

# SSL (if not using Nginx for SSL termination)
# keyfile = "/path/to/key.pem"
# certfile = "/path/to/cert.pem"

# Restart workers after this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Graceful timeout
graceful_timeout = 30
```

### 2. Create systemd service

```bash
sudo nano /etc/systemd/system/cryptolens.service
```

```ini
[Unit]
Description=CryptoLens Gunicorn Application
After=network.target postgresql.service redis.service

[Service]
User=cryptolens
Group=cryptolens
WorkingDirectory=/home/cryptolens/cryptolens
Environment="PATH=/home/cryptolens/cryptolens/venv/bin"
ExecStart=/home/cryptolens/cryptolens/venv/bin/gunicorn -c gunicorn.conf.py "app:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Enable and start service

```bash
sudo systemctl daemon-reload
sudo systemctl enable cryptolens
sudo systemctl start cryptolens
sudo systemctl status cryptolens
```

---

## Nginx Configuration

### 1. Create Nginx site config

```bash
sudo nano /etc/nginx/sites-available/cryptolens
```

```nginx
upstream cryptolens {
    server 127.0.0.1:8000 fail_timeout=0;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    # SSL certificates (will be configured by Certbot)
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Logging
    access_log /var/log/nginx/cryptolens-access.log;
    error_log /var/log/nginx/cryptolens-error.log;

    # Max upload size
    client_max_body_size 10M;

    # Static files
    location /static/ {
        alias /home/cryptolens/cryptolens/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Favicon
    location /favicon.ico {
        alias /home/cryptolens/cryptolens/app/static/favicon.ico;
        expires 30d;
    }

    # Metrics endpoint (restrict to internal/monitoring)
    location /metrics {
        # Allow from Prometheus server IP
        # allow 10.0.0.0/8;
        # deny all;

        proxy_pass http://cryptolens;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Main application
    location / {
        proxy_pass http://cryptolens;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint
    location /api/health {
        proxy_pass http://cryptolens;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. Enable site and test

```bash
sudo ln -s /etc/nginx/sites-available/cryptolens /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## SSL/HTTPS Setup

### 1. Obtain SSL certificate with Certbot

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

### 2. Auto-renewal (usually configured automatically)

```bash
sudo certbot renew --dry-run
```

---

## Background Workers

### 1. Create RQ worker service

```bash
sudo nano /etc/systemd/system/cryptolens-worker.service
```

```ini
[Unit]
Description=CryptoLens RQ Worker
After=network.target redis.service postgresql.service

[Service]
User=cryptolens
Group=cryptolens
WorkingDirectory=/home/cryptolens/cryptolens
Environment="PATH=/home/cryptolens/cryptolens/venv/bin"
ExecStart=/home/cryptolens/cryptolens/venv/bin/python worker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Enable and start worker

```bash
sudo systemctl daemon-reload
sudo systemctl enable cryptolens-worker
sudo systemctl start cryptolens-worker
sudo systemctl status cryptolens-worker
```

---

## Cron Jobs

### 1. Set up cron for cryptolens user

```bash
sudo -u cryptolens crontab -e
```

Add the following:

```cron
# CryptoLens Production Cron Jobs
# ================================

# Activate virtual environment for all jobs
SHELL=/bin/bash
PATH=/home/cryptolens/cryptolens/venv/bin:/usr/local/bin:/usr/bin:/bin

# Change to app directory
CRYPTOLENS_DIR=/home/cryptolens/cryptolens

# Real-time data fetch + pattern detection (every minute)
* * * * * cd $CRYPTOLENS_DIR && python scripts/fetch.py >> logs/fetch.log 2>&1

# Stats cache update (every 5 minutes)
*/5 * * * * cd $CRYPTOLENS_DIR && python scripts/compute_stats.py >> logs/stats.log 2>&1

# Database health check (daily at 3 AM)
0 3 * * * cd $CRYPTOLENS_DIR && python scripts/db_health.py >> logs/db_health.log 2>&1

# Log rotation (weekly)
0 4 * * 0 find $CRYPTOLENS_DIR/logs -name "*.log" -mtime +30 -delete
```

---

## Monitoring Setup

### 1. Prometheus (Optional)

If you want to collect metrics, install Prometheus:

```bash
# Download and install Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-2.45.0.linux-amd64.tar.gz
sudo mv prometheus-2.45.0.linux-amd64 /opt/prometheus
```

Add CryptoLens to Prometheus config `/opt/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'cryptolens'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### 2. Error Tracking (Self-Hosted)

CryptoLens includes a built-in error tracking system that stores errors in PostgreSQL and sends email alerts for critical errors. No external services (like Sentry or Docker) are required.

**Features:**
- Automatic error capture for all unhandled exceptions
- Error grouping by hash (similar errors are consolidated)
- Request context capture (endpoint, user, IP, headers)
- Email alerts for critical errors (database, payment, security)
- Admin dashboard at `/admin/errors`

**Configuration in `.env`:**
```bash
# Enable/disable error tracking
ERROR_TRACKING_ENABLED=true

# Set admin email to receive critical error alerts
# (Configure via Admin Settings or database Setting table)
```

**View errors:**
- Navigate to Admin Panel > Error Tracking
- Filter by status (new, acknowledged, resolved)
- View full traceback and request context
- Mark errors as resolved with notes

**Critical error types that trigger email alerts:**
- DatabaseError, OperationalError, IntegrityError
- ConnectionError, TimeoutError
- AuthenticationError, PaymentError, SecurityError

**Error cleanup:**
Old resolved/ignored errors are automatically cleaned up after 30 days to prevent database bloat.

### 3. Health check monitoring

Set up an uptime monitor (UptimeRobot, Pingdom, etc.) to check:

```
https://yourdomain.com/api/health
```

Expected response when healthy:
```json
{
  "status": "healthy",
  "database": "connected",
  "cache": "connected"
}
```

---

## Backup Strategy

### 1. Database backup script

```bash
nano /home/cryptolens/backup.sh
```

```bash
#!/bin/bash
# CryptoLens Database Backup Script

BACKUP_DIR="/home/cryptolens/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="cryptolens_prod"

mkdir -p $BACKUP_DIR

# PostgreSQL backup
pg_dump -U cryptolens $DB_NAME | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Keep only last 7 days of backups
find $BACKUP_DIR -name "db_*.sql.gz" -mtime +7 -delete

echo "Backup completed: db_$DATE.sql.gz"
```

```bash
chmod +x /home/cryptolens/backup.sh
```

### 2. Add to cron (daily at 2 AM)

```cron
0 2 * * * /home/cryptolens/backup.sh >> /home/cryptolens/cryptolens/logs/backup.log 2>&1
```

### 3. Off-site backup (recommended)

Use `rclone` or similar to sync backups to cloud storage:

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Configure (follow prompts for your cloud provider)
rclone config

# Add to cron to sync backups
0 5 * * * rclone sync /home/cryptolens/backups remote:cryptolens-backups
```

---

## Troubleshooting

### Check service status

```bash
sudo systemctl status cryptolens
sudo systemctl status cryptolens-worker
sudo systemctl status nginx
sudo systemctl status postgresql
sudo systemctl status redis
```

### View logs

```bash
# Application logs
tail -f /home/cryptolens/cryptolens/logs/gunicorn-error.log

# Nginx logs
tail -f /var/log/nginx/cryptolens-error.log

# System journal
sudo journalctl -u cryptolens -f
```

### Common issues

**1. 502 Bad Gateway**
- Check if Gunicorn is running: `sudo systemctl status cryptolens`
- Check Gunicorn logs: `tail -f logs/gunicorn-error.log`

**2. Database connection errors**
- Verify PostgreSQL is running: `sudo systemctl status postgresql`
- Check DATABASE_URL in `.env`
- Test connection: `psql -U cryptolens -d cryptolens_prod`

**3. Redis connection errors**
- Verify Redis is running: `sudo systemctl status redis`
- Check REDIS_URL in `.env`
- Test connection: `redis-cli ping`

**4. Static files not loading**
- Check Nginx config paths
- Verify file permissions: `ls -la app/static/`

**5. Email not sending**
- Verify SMTP credentials in `.env`
- Check for Gmail app password (not regular password)
- Test: `python -c "from app.services.email import send_test_email; send_test_email()"`

### Restart all services

```bash
sudo systemctl restart postgresql redis cryptolens cryptolens-worker nginx
```

---

## Security Checklist

- [ ] Change all default passwords (admin, database, Redis)
- [ ] Secure `.env` file permissions (`chmod 600`)
- [ ] Enable firewall (UFW): only allow 22, 80, 443
- [ ] Set up fail2ban for SSH
- [ ] Configure automatic security updates
- [ ] Enable PostgreSQL SSL (for remote connections)
- [ ] Set up log rotation
- [ ] Configure backup encryption
- [ ] Review Nginx security headers
- [ ] Verify error tracking is enabled (check `/admin/errors`)

---

## Quick Reference

| Service | Port | Config Location |
|---------|------|-----------------|
| Nginx | 80, 443 | `/etc/nginx/sites-available/cryptolens` |
| Gunicorn | 8000 | `/home/cryptolens/cryptolens/gunicorn.conf.py` |
| PostgreSQL | 5432 | `/etc/postgresql/14/main/postgresql.conf` |
| Redis | 6379 | `/etc/redis/redis.conf` |
| Prometheus | 9090 | `/opt/prometheus/prometheus.yml` |

| Command | Description |
|---------|-------------|
| `sudo systemctl restart cryptolens` | Restart web app |
| `sudo systemctl restart cryptolens-worker` | Restart background worker |
| `sudo -u cryptolens crontab -l` | View cron jobs |
| `tail -f logs/gunicorn-error.log` | Watch app logs |
| `python scripts/migrate_all.py` | Run migrations |

---

## Support

For issues and feature requests, visit:
https://github.com/pier0074/cryptolens/issues
