# CryptoLens

**Smart Money Concepts (SMC) Pattern Detection for Crypto Trading**

Automated detection of institutional trading patterns across multiple timeframes with push notifications, interactive charts, trade journaling, and portfolio management.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![SQLite](https://img.shields.io/badge/SQLite-3-lightgrey.svg)

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
# Edit .env with your SMTP settings for email verification

# Run database migrations
python scripts/migrate_all.py

# Create test accounts (admin + one per tier)
python scripts/create_admin.py

# Fetch historical data
python scripts/fetch_historical.py -v

# Run the web app
python run.py
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
FLASK_ENV=production

# Email (for verification and password reset)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com

# NTFY (self-hosted or ntfy.sh)
NTFY_URL=https://ntfy.sh
```

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

**Auto-catchup**: If you haven't run fetch for several days, it automatically fetches all missing candles in batches of 1000 until caught up.

**Rate Limiting**: Uses semaphore to limit concurrent API requests (default: 5) with exponential backoff retry on rate limit errors.

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
| `--fix` | Auto-fix issues (deletes invalid candles) |
| `--symbol`, `-s` | Check specific symbol (e.g., `BTC/USDT`) |
| `--quiet`, `-q` | Only show summary (suppresses per-symbol output) |
| `--reset` | Reset all verification flags (start fresh) |

```bash
# Report only (no changes)
python scripts/db_health.py

# Auto-fix bad data
python scripts/db_health.py --fix

# Check single symbol
python scripts/db_health.py -s BTC/USDT

# Clear verification status and start fresh
python scripts/db_health.py --reset

# Fix silently (for cron)
python scripts/db_health.py -q --fix
```

**Checks performed**:
1. **Gap detection** - Missing candles in sequence (> 5 min gap)
2. **Timestamp alignment** - Higher TFs at correct boundaries (e.g., 15m at :00, :15, :30, :45)
3. **OHLCV sanity** - high >= low, high >= open/close, volume >= 0, prices > 0
4. **Continuity** - Open should approximately equal previous candle's close

---

#### `fetch_historical.py` - Historical Data Loader

Fetches historical candle data for initial setup or backfilling gaps. Supports parallel async fetching for speed.

| Parameter | Description |
|-----------|-------------|
| `--days` | Days of history to fetch (default: **365**) |
| `--gaps` | Only fill gaps (skip full fetch) |
| `--full` | With `--gaps`: scan entire database, not just last X days |
| `--status` | Show database status (candle counts, date ranges) |
| `--delete` | Delete ALL data (requires typing 'DELETE' to confirm) |
| `--verbose`, `-v` | Verbose output with detailed progress |
| `--no-aggregate` | Skip aggregation to higher timeframes after fetch |

```bash
# Full fetch - 1 year of history (default)
python scripts/fetch_historical.py

# Fetch specific number of days
python scripts/fetch_historical.py --days=30

# Fill gaps in last 7 days
python scripts/fetch_historical.py --gaps --days=7

# Fill ALL gaps in entire database (from beginning to now)
python scripts/fetch_historical.py --gaps --full -v

# Show database status
python scripts/fetch_historical.py --status

# Delete all data and refetch
python scripts/fetch_historical.py --delete

# Fetch without aggregating to higher timeframes
python scripts/fetch_historical.py --days=7 --no-aggregate
```

**Gap fill mode** (`--gaps`):
1. Scans existing data for the specified day range
2. Detects missing candle sequences (gaps > 5 minutes)
3. Fetches only the missing ranges from Binance
4. Aggregates to higher timeframes automatically

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

### Common Scenarios

#### Catching Up After Downtime

If you haven't fetched candles for several days:

```bash
# Option 1: Gap detection (recommended - only fetches what's missing)
python scripts/fetch_historical.py --gaps --days=7

# Option 2: Just run fetch.py - it auto-catches up
python scripts/fetch.py -v
```

`fetch.py` automatically detects the last candle timestamp and fetches all missing data in batches.

#### Initial Setup

```bash
# 1. Run migrations
python scripts/migrate_all.py

# 2. Fetch 1 year of history
python scripts/fetch_historical.py -v

# 3. Compute initial stats
python scripts/compute_stats.py

# 4. Verify data integrity
python scripts/db_health.py
```

#### Daily Maintenance

The crontab handles this automatically, but manually:

```bash
# Health check with auto-fix
python scripts/db_health.py --fix -q
```

---

### API Rate Limiting

Binance has strict rate limits. The scripts are configured to prevent rate limit errors:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_CONCURRENT_REQUESTS` | 5 | Max parallel API requests |
| `RATE_LIMIT_DELAY` | 0.2s | Delay between batch requests |
| `RATE_LIMIT_RETRY_DELAY` | 2.0s | Initial retry delay (exponential backoff) |
| `MAX_RETRIES` | 3 | Max retries for rate-limited requests |

To adjust these settings, edit `app/config.py`:

```python
MAX_CONCURRENT_REQUESTS = 3  # Lower for stricter rate limiting
RATE_LIMIT_DELAY = 0.5       # Higher delay between requests
```

If you frequently see rate limit errors, reduce `MAX_CONCURRENT_REQUESTS` to 3 or lower.

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

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | No | Health check for monitoring |
| `/api/symbols` | GET | No | List tracked symbols |
| `/api/candles/{symbol}/{tf}` | GET | No | Get candles for symbol/timeframe |
| `/api/patterns` | GET | No | Detected patterns |
| `/api/signals` | GET | No | Trade signals |
| `/api/matrix` | GET | No | Pattern matrix data |
| `/api/scan` | POST | API Key | Trigger manual pattern scan |
| `/api/fetch` | POST | API Key | Trigger manual data fetch |
| `/api/scan/run` | POST | API Key | Run full fetch cycle |
| `/api/docs` | GET | No | Swagger UI documentation |
| `/api/docs/openapi.yaml` | GET | No | OpenAPI specification (YAML) |
| `/api/docs/openapi.json` | GET | No | OpenAPI specification (JSON) |

**Note**: POST endpoints require API Key in `X-API-Key` header (set in Settings).

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

Built-in error tracking that stores errors in PostgreSQL and sends email alerts. No external services or Docker required.

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
│   └── migrate_all.py   # DB migrations
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
