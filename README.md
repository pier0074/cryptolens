# CryptoLens

**Smart Money Concepts (SMC) Pattern Detection for Crypto Trading**

Automated detection of institutional trading patterns across multiple timeframes with push notifications, interactive charts, trade journaling, and portfolio management.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![MySQL](https://img.shields.io/badge/MySQL-8.0-blue.svg)

## Features

- **Pattern Detection**: FVG, OB, Sweep patterns across 6 timeframes
- **Multi-TF Confluence**: Signals generated when patterns align across timeframes
- **Interactive Charts**: TradingView-style charts with pattern visualization
- **Smart Price Formatting**: Auto-adjusts decimals for micro-cap to large-cap tokens
- **Push Notifications**: Per-user unique topics via NTFY.sh with customizable filters
- **Portfolio & Journal**: Trade logging with PnL tracking and journal entries
- **User Authentication**: Registration, login, email verification, password reset, 2FA (TOTP)
- **3-Tier Subscriptions**: Free, Pro, and Premium plans with feature restrictions
- **Payment Integration**: LemonSqueezy (card) and NOWPayments (BTC, ETH, USDT)
- **Notification Preferences**: Direction filter, confluence threshold, quiet hours
- **Event-Driven**: Each symbol processed immediately after fetch

---

## Subscription Tiers

| Feature | Free | Pro | Premium |
|---------|------|-----|---------|
| Symbols | BTC/USDT only | 5 symbols | Unlimited |
| Pattern Types | FVG only | All 3 patterns | All 3 patterns |
| Patterns Page | - | Last 100 | Full history |
| Signals Page | - | Last 50 | Full history |
| Portfolio | - | 1 portfolio, 5tx/day | Unlimited |
| Backtest | - | - | Full access |
| Analytics | - | Full | Full |
| Notifications | 1/day, 10min delay | 20/day | Unlimited |
| API Access | - | - | Full |

---

## Pattern Types & How to Trade Them

### Fair Value Gap (FVG)

**What it is**: A 3-candle pattern where the middle candle's body creates a gap between the wicks of candles 1 and 3. This gap represents aggressive buying/selling where price moved so fast it left unfilled orders.

**How to identify**:
- Bullish FVG: Candle 1 high < Candle 3 low (gap up)
- Bearish FVG: Candle 1 low > Candle 3 high (gap down)

**How to trade**:
1. Wait for price to retrace back into the FVG zone
2. Entry: At the zone edge (conservative) or midpoint (aggressive)
3. Stop Loss: Beyond the opposite edge of the zone + buffer
4. Take Profit: 1:2 or 1:3 risk-reward ratio

```
Bullish FVG Trade Setup:
                    ┌─────┐
                    │     │ ← Candle 3
              ┌─────┤     │
    ══════════╪═════╪═════╪══════  ← FVG Zone (entry area)
              │     └─────┘
        ┌─────┤ ← Candle 1
        │     │
        └─────┘
```

### Order Block (OB)

**What it is**: The last opposing candle before a strong impulsive move. Represents where institutions placed large orders that caused the move.

**How to identify**:
- Bullish OB: Last red candle before a strong green impulse
- Bearish OB: Last green candle before a strong red impulse
- The impulse must break structure (new high/low)

**How to trade**:
1. Mark the order block candle's high and low
2. Wait for price to return to this zone
3. Entry: Within the OB body
4. Stop Loss: Beyond the OB wick
5. Target: Previous swing high/low or 1:2 RR

```
Bullish Order Block:
        ┌─────┐
        │ ▲▲▲ │ ← Strong impulse up
        │ ▲▲▲ │
   ═════╪═════╪═════  ← Order Block zone
        │ ▼   │ ← Last red candle (OB)
        └─────┘
```

### Liquidity Sweep

**What it is**: A move that takes out obvious highs/lows (stop losses) before reversing. Institutions hunt liquidity pools where retail traders place stops.

**How to identify**:
- Price breaks a recent high/low with a wick
- Closes back inside the previous range
- Often followed by impulsive move in opposite direction

**How to trade**:
1. Identify obvious swing highs/lows where stops cluster
2. Wait for a sweep (wick beyond, close inside)
3. Entry: After the sweep candle closes
4. Stop Loss: Beyond the sweep wick
5. Target: Opposite side of the range or imbalance

```
Liquidity Sweep (bearish):
   ──────────── Previous High
        │
   ═════╪═════ ← Sweep wick
        │
   ─────┴───── ← Close back inside
        ↓
     Reversal
```

---

## Confluence Signals

CryptoLens generates signals when **multiple timeframes show patterns in the same direction**:

| Confluence Score | Meaning | Reliability |
|-----------------|---------|-------------|
| 2 TFs aligned | Moderate signal | Standard |
| 3+ TFs aligned | Strong signal | High |
| HTF + LTF aligned | Very strong | Highest |

Example: BTC shows bullish FVG on 4h + bullish OB on 1h + bullish FVG on 15m = 3 TF confluence (strong long signal)

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/pier0074/cryptolens.git
cd cryptolens
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database and SMTP settings

# Create MySQL database and tables
make db-create

# Create test accounts (admin + one per tier)
make db-user

# Fetch historical data (from fetch_start_date setting, default: 2024-01-01)
python scripts/fetch_historical.py -v

# Run the web app
flask run --debug
```

### Makefile Commands

```bash
make help          # Show all commands
make db-create     # Create database and tables
make db-user       # Create test accounts
make db-reset      # Drop + recreate + create users
make db-drop       # Drop database
make dev           # Start development server
make test          # Run tests
```

Visit `http://localhost:5000` and login with a test account:

### Test Accounts

| Tier | Email | Password | Access |
|------|-------|----------|--------|
| Admin | `admin@cryptolens.local` | `Admin123` | Full access + admin panel |
| Free | `free@cryptolens.local` | `Free123` | BTC/USDT, FVG only |
| Pro | `pro@cryptolens.local` | `Pro123` | 5 symbols, all patterns |
| Premium | `premium@cryptolens.local` | `Premium123` | Unlimited |

**Important**: Change these passwords after testing!

---

## Environment Configuration

Create a `.env` file with:

```bash
# Flask
SECRET_KEY=your-secret-key-here
FLASK_ENV=development  # or 'production'

# Database (MySQL)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASS=your-password
DB_NAME=cryptolens

# Production Database (used when FLASK_ENV=production)
# PROD_DB_HOST=your-prod-host.com
# PROD_DB_USER=cryptolens_user
# PROD_DB_PASS=secure-password
# PROD_DB_NAME=cryptolens_prod

# Email (for verification and password reset)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com

# NTFY (self-hosted or ntfy.sh)
NTFY_URL=https://ntfy.sh

# Logging
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=colored      # colored, json, simple

# Security (required for production)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
ENCRYPTION_KEY=your-encryption-key
ENCRYPTION_SALT=your-salt

# Scheduler (APScheduler for background jobs)
SCHEDULER_ENABLED=false  # Use cron instead for production

# API Settings
ALLOW_UNAUTHENTICATED_API=false  # Never enable in production

# Gunicorn (production)
GUNICORN_WORKERS=4      # Default: cpu_count * 2 + 1
```

**Database Notes:**
- MySQL 8.0+ required (uses BigInteger for millisecond timestamps)
- Auto-detects production environment (FLASK_ENV, common PaaS indicators)
- Falls back to `DB_*` vars if `PROD_DB_*` not set in production

---

## Background Processing (Cron)

A ready-to-use `crontab.txt` is included. Install with:

```bash
crontab crontab.txt
```

### Scripts Overview

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `fetch.py` | Fetch + aggregate + detect + expire + notify | Every 1 min |
| `compute_stats.py` | Cache stats for fast page loads | Every 5 min |
| `db_health.py` | Verify data integrity, fix issues | Daily (3 AM) |
| `fetch_historical.py` | Initial data load / backfill gaps | Manual |
| `migrate_all.py` | Database migrations (idempotent) | Manual |

---

### Script Details

#### `fetch.py` - Real-time Candle Fetcher

Fetches new 1m candles from Binance, aggregates to higher timeframes (5m, 15m, 30m, 1h, 2h, 4h, 1d), detects patterns, generates signals, expires old patterns, and logs the run to the database.

| Parameter | Description |
|-----------|-------------|
| `--verbose`, `-v` | Verbose output - shows per-symbol progress and timing |
| `--gaps` | Gap fill mode (marks as "gaps" job in cron logs) |

```bash
# Standard run (cron)
python scripts/fetch.py

# Verbose with per-symbol details
python scripts/fetch.py -v
```

**Optimized Parallel Fetching**:
- **Batch timestamp query**: Single DB query for all symbols (vs N sequential queries)
- **True parallel fetch**: All symbols fetch simultaneously using ccxt's built-in rate limiting
- **Aligned timestamps**: All symbols start fetching from the same aligned timestamp
- **Separated phases**: Fetch all → Process all (network I/O doesn't block CPU work)

**Performance**: 5 symbols, 2000 candles each = ~2-3 seconds (vs ~470s sequential)

**Auto-catchup**: If you haven't run fetch for several days, it automatically fetches all missing candles in batches of 1000 until caught up.

**Rate Limiting**: Uses ccxt's built-in rate limiting with retry logic for rate limit errors, timeouts, and network issues.

---

#### `compute_stats.py` - Stats Cache Builder

Pre-computes database statistics (candle counts, pattern stats, price changes, data freshness) and caches them for fast dashboard page loads.

| Parameter | Description |
|-----------|-------------|
| *(none)* | No parameters - runs full stats computation |

```bash
python scripts/compute_stats.py
```

---

#### `db_health.py` - Data Integrity Checker

Performs incremental verification of candle data. Checks for gaps, OHLCV validity (high >= low, etc.), and timestamp alignment for higher timeframes.

| Parameter | Description |
|-----------|-------------|
| `--fix` | Auto-fix: delete bad candles, fetch missing 1m data from exchange, re-aggregate |
| `--symbol`, `-s` | Check specific symbol (e.g., `BTC/USDT`) |
| `--quiet`, `-q` | Only show summary (suppresses per-symbol output) |
| `--reset` | Reset all verification flags (start fresh) |
| `--accept-gaps` | Mark current gaps as accepted (exchange has no data) |
| `--show-gaps` | Show all known/accepted gaps |
| `--clear-gaps` | Clear all known gaps (to re-check them) |

```bash
# Report only (no changes)
python scripts/db_health.py

# Auto-fix bad data (fetch missing, re-aggregate)
python scripts/db_health.py --fix

# Check single symbol
python scripts/db_health.py -s BTC/USDT

# Clear verification status and start fresh
python scripts/db_health.py --reset

# Fix silently (for cron)
python scripts/db_health.py -q --fix

# Show all known gaps
python scripts/db_health.py --show-gaps

# Mark current gaps as "OK" (exchange has no data)
python scripts/db_health.py --accept-gaps

# Clear known gaps to re-verify them
python scripts/db_health.py --clear-gaps
```

**Checks performed**:
1. **Gap detection** - Missing candles in sequence
2. **Timestamp alignment** - Higher TFs at correct boundaries (e.g., 15m at :00, :15, :30, :45)
3. **OHLCV sanity** - high >= low, high >= open/close, volume >= 0, prices > 0
4. **Continuity** - Open should approximately equal previous candle's close

**Gap Handling**:
- `--fix` attempts to fetch missing 1m candles from Binance
- If exchange returns no data (legitimate gap), it's marked as "known"
- Known gaps are skipped during verification (no errors)
- Higher timeframes are re-aggregated after filling gaps
- Use `--accept-gaps` to manually mark gaps as OK without fetching

---

#### `fetch_historical.py` - Historical Data Loader

Fetches historical candle data for initial setup or backfilling gaps. Uses the `fetch_start_date` setting from Admin > Symbols (default: 2024-01-01).

| Parameter | Description |
|-----------|-------------|
| `--days` | Override days (ignores fetch_start_date setting) |
| `--gaps` | Only fill gaps (skip full fetch) |
| `--full` | With `--gaps`: scan entire database, not just last X days |
| `--status` | Show database status (candle counts, date ranges) |
| `--delete` | Delete ALL data (requires typing 'DELETE' to confirm) |
| `--verbose`, `-v` | Verbose output with detailed progress |
| `--no-aggregate` | Skip aggregation to higher timeframes after fetch |

```bash
# Full fetch from fetch_start_date (default: 2024-01-01)
python scripts/fetch_historical.py

# Override with specific number of days
python scripts/fetch_historical.py --days=30

# Fill gaps in date range from fetch_start_date
python scripts/fetch_historical.py --gaps

# Fill ALL gaps in entire database (from beginning to now)
python scripts/fetch_historical.py --gaps --full -v

# Show database status
python scripts/fetch_historical.py --status

# Delete all data and refetch
python scripts/fetch_historical.py --delete

# Fetch without aggregating to higher timeframes
python scripts/fetch_historical.py --days=7 --no-aggregate
```

**Target Date Configuration:**
- Set in Admin > Symbols page ("Fetch Start Date")
- Default: 2024-01-01
- Use `--days` flag to override temporarily

**Gap fill mode** (`--gaps`):
1. Scans existing data from fetch_start_date to now
2. Detects missing candle sequences (gaps > 5 minutes)
3. Fetches only the missing ranges from Binance
4. Aggregates to higher timeframes automatically

**Error Handling & Resilience:**
- **Incremental saves**: Data saved every 10,000 candles (crash-safe)
- **Retry on timeout**: 3 retries with 10s delay, logs WARNING
- **Rate limit handling**: Dynamic cooloff (extracts wait time from error, default 30s, max 5min)
- **Error logging**: All errors logged with symbol, timestamp, and attempt count
- **Graceful degradation**: Skips problematic batches after max retries, continues with next

---

#### `migrate_all.py` - Database Migrations

Applies schema changes to existing databases. Fully idempotent - safe to run multiple times.

| Parameter | Description |
|-----------|-------------|
| *(none)* | No parameters - runs all pending migrations |

```bash
python scripts/migrate_all.py
```

**Note**: For new installations, this is NOT needed - `db.create_all()` includes everything. Only needed when upgrading existing databases.

---

### When to Use Which Script

| Scenario | Script | Command |
|----------|--------|---------|
| **First time setup** | `fetch_historical.py` | `python scripts/fetch_historical.py -v` |
| **Regular cron job** | `fetch.py` | `python scripts/fetch.py` |
| **Missing 1m candles** | `fetch_historical.py --gaps` | `python scripts/fetch_historical.py --gaps -v` |
| **Missing higher TF candles** | Re-aggregate | See "Re-aggregate" below |
| **Data looks wrong** | `db_health.py` | `python scripts/db_health.py --fix` |
| **Dashboard slow** | `compute_stats.py` | `python scripts/compute_stats.py` |
| **After code update** | `migrate_all.py` | `python scripts/migrate_all.py` |

---

### Common Scenarios

#### Initial Setup (New Installation)

```bash
# 1. Create database and tables
make db-create

# 2. Create test accounts
make db-user

# 3. Fetch historical data (from 2024-01-01, takes ~1 hour for 5 symbols)
python scripts/fetch_historical.py -v

# 4. Compute initial stats
python scripts/compute_stats.py

# 5. Verify data integrity
python scripts/db_health.py
```

#### Catching Up After Downtime

```bash
# Option 1: fetch.py auto-catches up (recommended for < 1 day gap)
python scripts/fetch.py -v

# Option 2: Gap fill mode (recommended for > 1 day gap)
python scripts/fetch_historical.py --gaps -v

# Option 3: Full scan for gaps in entire database
python scripts/fetch_historical.py --gaps --full -v
```

#### Re-aggregate Higher Timeframes

If 5m/15m/1h/etc candles are missing but 1m candles exist:

```bash
python -c "
from app import create_app
from app.models import Symbol
from app.services.aggregator import aggregate_all_timeframes

app = create_app()
with app.app_context():
    for sym in Symbol.query.filter_by(is_active=True).all():
        print(f'{sym.symbol}...', end=' ', flush=True)
        results = aggregate_all_timeframes(sym.symbol)
        print(f'{sum(results.values())} candles')
"
```

#### Fix Data Issues

```bash
# Check for issues (report only)
python scripts/db_health.py

# Auto-fix issues (fetch missing, delete invalid, re-aggregate)
python scripts/db_health.py --fix

# Check specific symbol
python scripts/db_health.py -s BTC/USDT --fix

# See what gaps exist
python scripts/db_health.py --show-gaps

# Mark gaps as OK (if exchange legitimately has no data)
python scripts/db_health.py --accept-gaps
```

#### Daily Maintenance (Manual)

The crontab handles this automatically, but manually:

```bash
# 1. Fetch latest candles
python scripts/fetch.py -v

# 2. Refresh stats cache
python scripts/compute_stats.py

# 3. Health check with auto-fix
python scripts/db_health.py --fix -q
```

---

### Shared Fetch Utilities

Both `fetch.py` and `fetch_historical.py` use shared modules in `scripts/utils/` for consistent behavior:

| Module | Purpose |
|--------|---------|
| `fetch_utils.py` | Batch timestamp queries, aligned fetch start, parallel fetching, candle saving |
| `retry.py` | Retry logic, rate limit handling, error classification |

**Key Functions in `fetch_utils.py`**:
- `get_all_last_timestamps(app, symbols)` - Single DB query for all symbols' last timestamps
- `get_aligned_fetch_start(timestamps, now_ms)` - Calculate aligned start time across symbols
- `fetch_symbol_batches(exchange, symbol, since, until)` - Async fetch with retry
- `fetch_symbols_parallel(symbols, since, until)` - True parallel fetch for multiple symbols
- `save_candles_to_db(app, symbol, candles)` - Save with deduplication

### API Rate Limiting & Error Handling

Both `fetch.py` and `fetch_historical.py` use a shared retry module (`scripts/utils/retry.py`) for consistent error handling.

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_RETRIES` | 3 | Max retries per batch |
| `RETRY_DELAY_SECONDS` | 5s | Delay between retries (general errors) |
| `TIMEOUT_RETRY_DELAY_SECONDS` | 10s | Delay after timeout |
| `DEFAULT_RATE_LIMIT_COOLOFF_SECONDS` | 30s | Default rate limit cooloff |

**Error Handling Behavior:**

| Error Type | Action | Log Level |
|------------|--------|-----------|
| Rate limit (429) | Extract wait time from error, cooloff (max 5min) | WARNING |
| Timeout | Retry after 10s | WARNING |
| Other errors | Retry after 5s | ERROR |
| Max retries exceeded | Skip batch, continue | ERROR |
| Too many consecutive errors (9) | Abort symbol fetch | ERROR |

**Dynamic Rate Limit Cooloff:**
The script parses error messages to extract the suggested wait time:
- `retry after 60 seconds` → waits 60s
- `Retry-After: 30` → waits 30s
- No time specified → waits 30s (default)
- Maximum wait capped at 300s (5 minutes)

To adjust settings, edit `scripts/utils/retry.py`:

```python
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
DEFAULT_RATE_LIMIT_COOLOFF_SECONDS = 30
TIMEOUT_RETRY_DELAY_SECONDS = 10
```

---

## Pattern Expiry

Patterns auto-expire based on timeframe significance:

| Timeframe | Expiry | Candles Loaded |
|-----------|--------|----------------|
| 1m | 4h | 500 |
| 5m | 12h | 400 |
| 15m | 24h | 300 |
| 1h | 3 days | 250 |
| 4h | 7 days | 200 |
| 1d | 14 days | 150 |

---

## Web Interface

### Navigation Structure

**Header**: Dashboard | Patterns | Portfolio | Analytics | Backtest | API | Admin (admin-only) | [Profile Avatar]

| Page | Features | Free | Pro | Premium |
|------|----------|------|-----|---------|
| **Landing** | Public marketing page with pricing | ✓ | ✓ | ✓ |
| **Dashboard** | Pattern matrix, data freshness | BTC/USDT only | 5 symbols | ✓ |
| **Patterns** | Tabbed view: Active Patterns + Signals, TradingView charts | ✗ | Last 100/50 | Full |
| **Portfolio** | Multi-portfolio, trade logging, PnL tracking, journal | ✗ | 1 portfolio, 5tx/day | Unlimited |
| **Analytics** | Performance metrics and analysis | ✗ | ✓ | ✓ |
| **Backtest** | Strategy backtesting with historical data | ✗ | ✗ | ✓ |
| **API** | Interactive API documentation (Swagger UI) | ✗ | ✗ | ✓ |
| **Profile** | Tabbed settings: Account, Security, Notifications, Trading, Subscription | ✓ | ✓ | ✓ |
| **Admin** | Quick Actions + grouped navigation (Users, System, Communications, Reference) | ✗ | ✗ | Admin |

### Profile Page Tabs
- **Account**: Username, email, timezone preferences
- **Security**: Password change, 2FA (TOTP) setup
- **Notifications**: NTFY setup, direction filter, confluence threshold, quiet hours
- **Trading**: Risk parameters, default settings
- **Subscription**: Current plan, upgrade options, payment history

### Admin Panel Features
- **Quick Actions**: Scan Now, Refresh Stats, Cleanup (DB health check)
- **Users**: User management, create user, subscriptions
- **System**: Cron jobs, error logs, settings
- **Communications**: Notifications, templates, scheduled broadcasts
- **Reference**: Documentation, API docs

### Pattern Access by Tier

| Pattern Type | Free | Pro | Premium |
|--------------|:----:|:---:|:-------:|
| Fair Value Gap (FVG) | ✓ | ✓ | ✓ |
| Order Block (OB) | ✗ | ✓ | ✓ |
| Liquidity Sweep (Sweep) | ✗ | ✓ | ✓ |

---

## Authentication

### Registration
- Email verification required before full access
- Unique NTFY topic generated per user (personal, non-transferable)
- Password requirements: 8+ chars, uppercase, lowercase, digit
- Terms of Service and Privacy Policy acknowledgment required
- Users must confirm they are 18+ years old

### Password Reset
- Request reset via email
- Secure token-based reset links
- Rate-limited to prevent abuse

---

## Notifications

1. Register and verify your email
2. Install [NTFY app](https://ntfy.sh/) on your phone
3. Go to Profile page to see your unique topic
4. Subscribe to your topic in the NTFY app
5. Test from Settings page

Each user has a unique notification topic, ensuring privacy.

---

## API

**Interactive Documentation**: Visit `/api/docs` for Swagger UI with full API documentation.

### Authentication

All data endpoints require API key authentication (Premium tier) or admin session.

**API Key Features:**
- Per-key rate limiting (requests per minute/hour/day)
- IP whitelist/blacklist with CIDR support
- Scope-based permissions (read:symbols, write:scan, admin:scheduler, etc.)
- Expiry dates
- Usage tracking

### Endpoints

| Endpoint | Method | Scope | Description |
|----------|--------|-------|-------------|
| `/api/health` | GET | None | Health check for monitoring |
| `/api/symbols` | GET | read:symbols | List tracked symbols |
| `/api/candles/{symbol}/{tf}` | GET | read:candles | Get candles for symbol/timeframe |
| `/api/patterns` | GET | read:patterns | Detected patterns |
| `/api/signals` | GET | read:signals | Trade signals |
| `/api/matrix` | GET | read:matrix | Pattern matrix data |
| `/api/scan` | POST | write:scan | Trigger manual pattern scan |
| `/api/fetch` | POST | write:fetch | Trigger manual data fetch |
| `/api/scan/run` | POST | write:scan | Run full fetch cycle |
| `/api/scheduler/status` | GET | admin:scheduler | Get scheduler status |
| `/api/docs` | GET | None | Swagger UI documentation |

### Response Format

All endpoints return a standardized response envelope:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": {
    "timestamp": "2025-01-01T00:00:00Z",
    "request_id": "abc123",
    "count": 10
  }
}
```

**Authentication**: Provide API Key via `X-API-Key` header or `api_key` query parameter.

---

## Monitoring & Observability

### Prometheus Metrics

A `/metrics` endpoint exposes Prometheus-compatible metrics:

- **Request metrics**: HTTP request count and latency by endpoint
- **Business metrics**: Active patterns, signals, users, subscriptions
- **Cache metrics**: Hit/miss ratios
- **Job metrics**: Queue sizes and processing times

Configure your Prometheus to scrape `http://your-server:5000/metrics`.

### Error Tracking (Self-Hosted)

Built-in error tracking that stores errors in MySQL and sends email alerts. No external services or Docker required.

**Features:**
- Automatic capture of all unhandled exceptions
- Error grouping by hash (similar errors consolidated)
- Request context capture (endpoint, user, IP, headers)
- Email alerts for critical errors
- Admin dashboard at `/admin/errors`

**Configuration:**
```bash
# Enable/disable in .env
ERROR_TRACKING_ENABLED=true
```

**Critical errors that trigger email alerts:**
- Database errors (DatabaseError, OperationalError, IntegrityError)
- Connection errors (ConnectionError, TimeoutError)
- Security errors (AuthenticationError, PaymentError, SecurityError)

View and manage errors in Admin Panel > Error Tracking.

---

## Testing

```bash
python -m pytest                    # All tests (607 tests)
python -m pytest --cov=app          # With coverage
python -m pytest tests/test_auth.py # Auth tests only
```

---

## Project Structure

```
cryptolens/
├── app/
│   ├── routes/          # Web routes (api, auth, dashboard, patterns, metrics, etc.)
│   ├── services/        # Business logic (auth, email, notifier, signals, etc.)
│   │   └── patterns/    # FVG, OB, Sweep detectors
│   ├── jobs/            # Background jobs (notifications, scanner, maintenance)
│   ├── models/          # SQLAlchemy models (user, trading, portfolio, system)
│   ├── templates/       # Jinja2 HTML templates
│   ├── decorators.py    # Access control decorators
│   ├── exceptions.py    # Domain exceptions
│   └── constants.py     # Application constants
├── scripts/
│   ├── fetch.py         # Real-time fetch + detection
│   ├── fetch_historical.py
│   ├── compute_stats.py # Cache stats
│   ├── db_health.py     # Data verification
│   ├── migrate_all.py   # DB migrations
│   └── utils/
│       ├── fetch_utils.py  # Shared fetch utilities
│       └── retry.py        # Retry and error handling
├── tests/               # Test suite (358 tests)
├── worker.py            # Background job worker (RQ)
├── crontab.txt          # Cron configuration
├── PRODUCTION.md        # Production deployment guide
└── run.py
```

---

## Roadmap

- [x] Two-factor authentication (TOTP)
- [x] User notification preferences
- [x] Payment integration (LemonSqueezy, NOWPayments)
- [x] Public landing page

### Future Enhancements
- [ ] Mobile app (iOS/Android)
- [ ] Additional exchanges (Binance, Bybit)
- [ ] Advanced backtesting strategies
- [ ] Social trading features
- [ ] Discord/Telegram bot integration

---

## Disclaimer

**IMPORTANT:** CryptoLens is for informational and educational purposes only. It does NOT provide financial, investment, legal, or tax advice.

- Cryptocurrency trading involves SUBSTANTIAL RISK OF LOSS and is not suitable for all investors
- You may lose some or all of your invested capital
- Past pattern performance does NOT guarantee future results
- You are SOLELY RESPONSIBLE for your own trading decisions
- Accounts are personal and non-transferable; sharing is prohibited
- All payments are non-refundable

Always consult qualified financial professionals before making investment decisions.

## License

MIT
