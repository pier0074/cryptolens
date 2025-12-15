# CryptoLens Architecture Documentation

Technical architecture overview for developers and maintainers.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Data Flow](#data-flow)
4. [Database Schema](#database-schema)
5. [Security Architecture](#security-architecture)
6. [Background Processing](#background-processing)
7. [Caching Strategy](#caching-strategy)
8. [API Design](#api-design)
9. [Pattern Detection](#pattern-detection)
10. [Notification System](#notification-system)

---

## System Overview

CryptoLens is a Flask-based web application for detecting Smart Money Concepts (SMC) trading patterns across cryptocurrency markets.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              CLIENTS                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  Web Browser    │    Mobile App (NTFY)    │    API Consumers            │
└────────┬────────┴───────────┬─────────────┴──────────┬──────────────────┘
         │                    │                        │
         ▼                    ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           NGINX (Reverse Proxy)                          │
│                    SSL Termination │ Static Files │ Load Balancing       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         GUNICORN (WSGI Server)                           │
│                         Multiple Worker Processes                        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FLASK APPLICATION                                │
├─────────────────────────────────────────────────────────────────────────┤
│  Routes     │  Services    │  Models      │  Jobs        │  Templates   │
│  (API/Web)  │  (Business)  │  (ORM)       │  (Background)│  (Jinja2)    │
└──────┬──────┴──────┬───────┴──────┬───────┴──────┬───────┴──────────────┘
       │             │              │              │
       ▼             ▼              ▼              ▼
┌────────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────┐
│   Redis    │ │   MySQL   │ │   NTFY    │ │    CCXT       │
│  (Cache)   │ │ (Database)│ │  (Push)   │ │  (Exchange)   │
└────────────┘ └───────────┘ └───────────┘ └───────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Web Server | Nginx | Reverse proxy, SSL, static files |
| WSGI | Gunicorn | Python application server |
| Framework | Flask 3.0 | Web framework |
| Database | MySQL 8.0+ | Primary data store |
| Cache | Redis 6+ | Caching, rate limiting, job queue |
| ORM | SQLAlchemy 2.0 | Database abstraction |
| Task Queue | RQ (Redis Queue) | Background job processing |
| Exchange API | CCXT | Cryptocurrency exchange data |
| Notifications | NTFY | Push notifications |
| Monitoring | Prometheus | Metrics collection |
| Error Tracking | Self-hosted (MySQL) | Error capture and alerting |

---

## Component Architecture

### Application Structure

```
app/
├── __init__.py          # Application factory, extensions
├── config.py            # Configuration classes
├── constants.py         # Application constants
├── decorators.py        # Access control decorators
├── exceptions.py        # Domain exceptions
│
├── models/              # SQLAlchemy models
│   ├── __init__.py      # Model exports
│   ├── base.py          # Base utilities
│   ├── user.py          # User, Subscription, UserNotification
│   ├── trading.py       # Symbol, Candle, Pattern, Signal
│   ├── portfolio.py     # Portfolio, Trade, JournalEntry
│   ├── system.py        # Setting, Log, CronJob, Payment
│   └── api.py           # ApiKey, IpRule, ApiKeyUsage
│
├── routes/              # HTTP endpoints
│   ├── api.py           # REST API
│   ├── auth.py          # Authentication + Profile
│   ├── dashboard.py     # Main dashboard
│   ├── patterns.py      # Patterns + Signals (tabbed)
│   ├── admin.py         # Admin panel (Quick Actions + grouped nav)
│   ├── payments.py      # Payment processing
│   ├── metrics.py       # Prometheus metrics
│   └── docs.py          # API documentation
│
├── services/            # Business logic
│   ├── auth.py          # Authentication service
│   ├── email.py         # Email sending
│   ├── notifier.py      # Push notifications
│   ├── async_notifier.py # Async notifications
│   ├── data_fetcher.py  # Exchange data fetching
│   ├── signal_processor.py # Signal generation
│   ├── scheduler.py     # Job scheduling
│   ├── lockout.py       # Account lockout
│   ├── encryption.py    # Data encryption
│   └── patterns/        # Pattern detectors
│       ├── fair_value_gap.py # Fair Value Gap (FVG) detection
│       ├── order_block.py    # Order Block (OB) detection
│       └── liquidity.py      # Liquidity Sweep (Sweep) detection
│
├── jobs/                # Background jobs
│   ├── queue.py         # Queue configuration
│   ├── notifications.py # Notification jobs
│   ├── scanner.py       # Pattern scanning
│   └── maintenance.py   # Cleanup jobs
│
└── templates/           # Jinja2 templates
    ├── base.html
    ├── dashboard/
    ├── patterns/
    └── ...
```

### Extension Initialization

```python
# app/__init__.py
db = SQLAlchemy()           # Database ORM
csrf = CSRFProtect()        # CSRF protection
limiter = Limiter()         # Rate limiting
cache = Cache()             # Caching layer
```

---

## Data Flow

### Pattern Detection Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Exchange   │────▶│ Data Fetcher │────▶│   Candles    │
│   (Binance)  │     │   Service    │     │   (DB)       │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                                  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Pattern    │◀────│   Pattern    │◀────│   Candle     │
│   (DB)       │     │   Detector   │     │   Data       │
└──────┬───────┘     └──────────────┘     └──────────────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Signal     │────▶│ Notification │────▶│   NTFY       │
│   Processor  │     │   Service    │     │   (Push)     │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Request Flow

```
HTTP Request
     │
     ▼
┌─────────────────┐
│   Rate Limiter  │ ──▶ 429 Too Many Requests
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CSRF Validation │ ──▶ 403 Forbidden (POST/PUT/DELETE)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Authentication  │ ──▶ 401 Unauthorized (protected routes)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Authorization   │ ──▶ 403 Forbidden (tier/role check)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Route Handler  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Service Layer  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Data Layer    │ ◀──▶ MySQL / Redis
└────────┬────────┘
         │
         ▼
HTTP Response
```

---

## Database Schema

### Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│     User     │───────│ Subscription │       │   Setting    │
├──────────────┤       ├──────────────┤       ├──────────────┤
│ id           │       │ id           │       │ key          │
│ email        │       │ user_id (FK) │       │ value        │
│ password_hash│       │ plan         │       └──────────────┘
│ is_admin     │       │ status       │
│ is_verified  │       │ expires_at   │       ┌──────────────┐
│ tier         │       └──────────────┘       │    ApiKey    │
│ ntfy_topic   │                              ├──────────────┤
└──────┬───────┘───────────────────────────────│ id           │
       │                                       │ user_id (FK) │
       │                                       │ key_hash     │
       │                                       │ name         │
       │                                       │ scopes       │
       │                                       │ rate_limit   │
       │                                       │ expires_at   │
       │                                       │ is_active    │
       │                                       └──────────────┘
       │
       │ 1:N
       ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Portfolio   │───────│    Trade     │───────│   TradeTag   │
├──────────────┤       ├──────────────┤       ├──────────────┤
│ id           │       │ id           │       │ id           │
│ user_id (FK) │       │ portfolio_id │       │ trade_id     │
│ name         │       │ symbol       │       │ tag          │
│ description  │       │ direction    │       └──────────────┘
└──────────────┘       │ entry_price  │
                       │ exit_price   │
                       │ pnl          │
                       └──────────────┘

┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│    Symbol    │───────│    Candle    │       │   Pattern    │
├──────────────┤       ├──────────────┤       ├──────────────┤
│ id           │       │ id           │       │ id           │
│ symbol       │       │ symbol_id    │       │ symbol_id    │
│ is_active    │       │ timeframe    │       │ timeframe    │
└──────┬───────┘       │ timestamp    │       │ pattern_type │
       │               │ open/high/   │       │ direction    │
       │ 1:N           │ low/close    │       │ zone_high    │
       │               │ volume       │       │ zone_low     │
       ▼               └──────────────┘       │ status       │
┌──────────────┐                              │ strength     │
│    Signal    │                              └──────────────┘
├──────────────┤
│ id           │
│ symbol_id    │
│ direction    │
│ confluence   │
│ timeframes   │
│ status       │
└──────────────┘
```

### Key Indexes

```sql
-- Performance-critical indexes
CREATE INDEX idx_candles_symbol_tf_ts ON candles(symbol_id, timeframe, timestamp DESC);
CREATE INDEX idx_patterns_status_detected ON patterns(status, detected_at DESC);
CREATE INDEX idx_signals_status_created ON signals(status, created_at DESC);
CREATE INDEX idx_signals_created ON signals(created_at DESC);
CREATE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_user ON api_keys(user_id);
```

---

## Security Architecture

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION FLOW                       │
└─────────────────────────────────────────────────────────────┘

1. Login Request
   ┌──────────┐     ┌──────────────┐     ┌──────────────┐
   │  Client  │────▶│ Rate Limiter │────▶│   Lockout    │
   └──────────┘     │ (5/min)      │     │   Check      │
                    └──────────────┘     └──────┬───────┘
                                                │
                                                ▼
2. Credential Verification                 ┌──────────────┐
                                           │  Verify      │
                                           │  Password    │
                                           └──────┬───────┘
                                                  │
                                 ┌────────────────┴────────────────┐
                                 ▼                                 ▼
3. Success Path              ┌──────────┐                   ┌──────────┐
                             │ Clear    │                   │ Record   │
                             │ Lockout  │                   │ Failure  │
                             └────┬─────┘                   └────┬─────┘
                                  │                              │
                                  ▼                              ▼
4. 2FA Check (if enabled)   ┌──────────┐                   ┌──────────┐
                            │ Verify   │                   │ Check    │
                            │ TOTP     │                   │ Lockout  │
                            └────┬─────┘                   └──────────┘
                                 │
                                 ▼
5. Session Creation         ┌──────────┐
                            │ Create   │
                            │ Session  │
                            │ (7 days) │
                            └──────────┘
```

### Security Layers

| Layer | Implementation | Purpose |
|-------|----------------|---------|
| HTTPS | Nginx + Let's Encrypt | Transport encryption |
| CSRF | Flask-WTF | Cross-site request forgery protection |
| Rate Limiting | Flask-Limiter + Redis | Brute force prevention |
| Account Lockout | Custom service | Failed login protection |
| Password Hashing | Werkzeug (pbkdf2) | Credential storage |
| Session Security | Secure cookies | Session protection |
| 2FA | TOTP (pyotp) | Multi-factor authentication |
| API Keys | SHA256 hashing + scopes | Machine-to-machine auth with per-key rate limits, IP rules |
| Encryption | Fernet (AES-128) | Secrets at rest |

### Subscription Tier Access Control

```python
# Decorator-based access control
@login_required           # Must be logged in
@subscription_required    # Must have active subscription
@tier_required('pro')     # Minimum tier requirement
@admin_required           # Admin only
```

---

## Background Processing

### Job Queue Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      JOB QUEUES                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  HIGH Priority Queue (notifications)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ send_signal_notification_job                          │   │
│  │ send_bulk_notifications_job                           │   │
│  │ Timeout: 60s                                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  DEFAULT Priority Queue (pattern scanning)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ scan_patterns_job                                     │   │
│  │ process_signals_job                                   │   │
│  │ Timeout: 300s                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  LOW Priority Queue (maintenance)                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ cleanup_old_data_job                                  │   │
│  │ update_stats_cache_job                                │   │
│  │ expire_patterns_job                                   │   │
│  │ Timeout: 300s                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│                      RQ WORKERS                              │
│         (Process jobs from all queues by priority)          │
└─────────────────────────────────────────────────────────────┘
```

### Cron Schedule

| Schedule | Job | Description |
|----------|-----|-------------|
| `* * * * *` | `fetch.py` | Fetch candles, detect patterns, send notifications |
| `*/5 * * * *` | `compute_stats.py` | Update stats cache |
| `0 3 * * *` | `db_health.py` | Database integrity check |

---

## Caching Strategy

### Cache Layers

```
┌─────────────────────────────────────────────────────────────┐
│                     CACHE HIERARCHY                          │
└─────────────────────────────────────────────────────────────┘

Layer 1: Application Cache (Flask-Caching + Redis)
├── Pattern Matrix: 60s TTL
├── Stats Cache: 300s TTL
├── Last Data Update: 60s TTL
└── Session Data: 7 days TTL

Layer 2: Database Query Cache (MySQL)
├── Prepared statements
└── Connection pooling (10 connections, 20 overflow)

Layer 3: HTTP Cache (Nginx)
├── Static files: 30 days
└── API responses: No cache (dynamic)
```

### Cache Keys

```python
# Pattern matrix
'pattern_matrix'           # Full matrix data, 60s TTL

# Stats cache
'global_stats'             # Dashboard stats, 300s TTL
'symbol_stats_{symbol_id}' # Per-symbol stats, 300s TTL

# Context processor
'last_data_update'         # Template variable, 60s TTL
```

---

## API Design

### REST Conventions

| Method | Usage | Example |
|--------|-------|---------|
| GET | Retrieve resources | `GET /api/patterns` |
| POST | Create/trigger actions | `POST /api/scan` |
| PUT | Update resources | `PUT /api/settings` |
| DELETE | Remove resources | `DELETE /api/portfolio/1` |

### Response Format

All API endpoints return a standardized envelope format:

```json
// Success response
{
  "success": true,
  "data": {
    "id": 1,
    "symbol": "BTC/USDT",
    "direction": "bullish"
  },
  "error": null,
  "meta": {
    "timestamp": "2025-01-01T00:00:00Z",
    "request_id": "abc123",
    "count": 1
  }
}

// Error response
{
  "success": false,
  "data": null,
  "error": "Not found: Symbol not found",
  "meta": {
    "timestamp": "2025-01-01T00:00:00Z",
    "request_id": "xyz789"
  }
}

// List response
{
  "success": true,
  "data": [
    {"id": 1, "symbol": "BTC/USDT"},
    {"id": 2, "symbol": "ETH/USDT"}
  ],
  "error": null,
  "meta": {
    "timestamp": "2025-01-01T00:00:00Z",
    "count": 2
  }
}
```

### API Authentication

API endpoints require authentication via API key (Premium tier or admin):

```
X-API-Key: your-api-key-here
# OR
?api_key=your-api-key-here
```

**API Key Features:**
- **Per-key rate limits**: Requests per minute/hour/day (e.g., `60/min`, `1000/day`)
- **IP rules**: Whitelist/blacklist with CIDR support (e.g., `192.168.1.0/24`)
- **Scopes**: Fine-grained permissions (`read:symbols`, `write:scan`, `admin:scheduler`)
- **Expiry dates**: Optional key expiration
- **Usage tracking**: Request counts, last used timestamp

### Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| Public endpoints | 200 | 1 minute |
| `/api/scan` | 1 | 1 minute |
| `/api/fetch` | 5 | 1 minute |
| `/auth/login` | 5 | 1 minute |

---

## Pattern Detection

### Detection Algorithm

```
For each symbol and timeframe:
┌─────────────────────────────────────────────────────────────┐
│ 1. Load recent candles (configurable limit)                  │
│ 2. Run pattern detectors:                                    │
│    ├── Fair Value Gap (FVG) detector                         │
│    ├── Order Block (OB) detector                             │
│    └── Liquidity Sweep detector                              │
│ 3. For each detected pattern:                                │
│    ├── Calculate zone boundaries                             │
│    ├── Calculate strength score (0-1)                        │
│    ├── Set expiration based on timeframe                     │
│    └── Store in database                                     │
│ 4. Check for filled patterns (price touched zone)            │
│ 5. Check for expired patterns (past expiration)              │
└─────────────────────────────────────────────────────────────┘
```

### Signal Generation

```
For all active patterns:
┌─────────────────────────────────────────────────────────────┐
│ 1. Group patterns by symbol and direction                    │
│ 2. Count timeframes with same direction                      │
│ 3. If count >= min_confluence (default: 2):                  │
│    ├── Generate signal                                       │
│    ├── Calculate entry/SL/TP prices                          │
│    └── Trigger notifications                                 │
└─────────────────────────────────────────────────────────────┘
```

### Pattern Expiry Rules

| Timeframe | Expiry Period | Candles Loaded |
|-----------|---------------|----------------|
| 1m | 4 hours | 500 |
| 5m | 12 hours | 400 |
| 15m | 24 hours | 300 |
| 1h | 3 days | 250 |
| 4h | 7 days | 200 |
| 1d | 14 days | 150 |

---

## Notification System

### Notification Flow

```
Signal Generated
      │
      ▼
┌──────────────┐
│ Check User   │
│ Preferences  │
├──────────────┤
│ - Direction  │
│ - Confluence │
│ - Quiet Hours│
│ - Daily Limit│
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Check Tier   │
│ Restrictions │
├──────────────┤
│ Free: 1/day  │
│ Pro: 20/day  │
│ Premium: ∞   │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│ Build        │────▶│ Send via     │
│ Notification │     │ NTFY         │
│ Message      │     │ (async)      │
└──────────────┘     └──────────────┘
```

### Async Notification Sending

```python
# Connection pooling for concurrent sends
connector = aiohttp.TCPConnector(
    limit=100,           # Max total connections
    limit_per_host=30    # Max per host
)

# Concurrent sending to all subscribers
results = await asyncio.gather(
    *[send_to_user_async(session, user, ...) for user in subscribers],
    return_exceptions=True
)
```

---

## Monitoring

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `cryptolens_http_requests_total` | Counter | HTTP request count |
| `cryptolens_http_request_duration_seconds` | Histogram | Request latency |
| `cryptolens_patterns_active` | Gauge | Active pattern count |
| `cryptolens_signals_total` | Counter | Signals generated |
| `cryptolens_notifications_sent_total` | Counter | Notifications sent |
| `cryptolens_users_active` | Gauge | Active user count |
| `cryptolens_subscriptions_active` | Gauge | Active subscriptions |
| `cryptolens_cache_hits_total` | Counter | Cache hits |
| `cryptolens_cache_misses_total` | Counter | Cache misses |
| `cryptolens_job_queue_size` | Gauge | Job queue size |
| `cryptolens_job_processing_seconds` | Histogram | Job processing time |

### Health Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `/api/health` | Overall health | `{status, database, cache}` |
| `/metrics` | Prometheus metrics | Prometheus format |

---

## Development Guidelines

### Adding a New Pattern Detector

1. Create detector in `app/services/patterns/`
2. Implement `detect()` function returning list of patterns
3. Register in `app/services/patterns/__init__.py`
4. Add tests in `tests/test_patterns/`

### Adding a New API Endpoint

1. Add route in `app/routes/api.py`
2. Document in `app/static/openapi.yaml`
3. Add tests in `tests/test_api.py`

### Database Migrations

```bash
# Add migration to scripts/migrate_all.py
# Run: python scripts/migrate_all.py
```

---

## Support

For questions and issues:
- GitHub: https://github.com/pier0074/cryptolens/issues
- API Docs: `/api/docs`
