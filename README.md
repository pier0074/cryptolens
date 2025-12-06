# CryptoLens

**Smart Money Concepts (SMC) Pattern Detection for Crypto Trading**

Automated detection of institutional trading patterns across multiple timeframes with push notifications, interactive charts, trade journaling, and portfolio management.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![SQLite](https://img.shields.io/badge/SQLite-3-lightgrey.svg)

## Features

- **Pattern Detection**: FVG, Order Blocks, Liquidity Sweeps across 6 timeframes
- **Multi-TF Confluence**: Signals generated when patterns align across timeframes
- **Interactive Charts**: TradingView-style charts with pattern visualization
- **Smart Price Formatting**: Auto-adjusts decimals for micro-cap to large-cap tokens
- **Push Notifications**: Per-user unique topics via NTFY.sh with customizable filters
- **Portfolio & Journal**: Trade logging with PnL tracking and journal entries
- **User Authentication**: Registration, login, email verification, password reset, 2FA (TOTP)
- **3-Tier Subscriptions**: Free, Pro, and Premium plans with feature restrictions
- **Payment Integration**: LemonSqueezy (card) and NOWPayments (50+ cryptocurrencies)
- **Notification Preferences**: Direction filter, confluence threshold, quiet hours
- **Event-Driven**: Each symbol processed immediately after fetch

---

## Subscription Tiers

| Feature | Free | Pro | Premium |
|---------|------|-----|---------|
| Symbols | BTC only | Up to 10 | Unlimited |
| Dashboard | Limited | Full | Full |
| Patterns Page | - | Last 100 | Full history |
| Signals Page | - | Last 50 | Full history |
| Portfolio | - | 3 portfolios | Unlimited |
| Backtest | - | - | Full access |
| Analytics | - | Basic | Full |
| Daily Notifications | 3 | 100 | Unlimited |
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

# Fetch historical data
python scripts/fetch_historical.py -v

# Run the web app
python run.py
```

Visit `http://localhost:5000` and register a new account.

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

### Scripts

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `fetch.py` | Fetch + aggregate + detect + expire + notify | Every 1 min |
| `compute_stats.py` | Cache stats for fast page loads | Every 5 min |
| `db_health.py` | Verify data integrity, fix issues | Daily (3 AM) |
| `fetch_historical.py` | Initial data load / backfill gaps | Manual |
| `migrate_all.py` | Database migrations (idempotent) | Manual |

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

| Page | Features | Free | Pro | Premium |
|------|----------|:----:|:---:|:-------:|
| **Landing** | Public marketing page with pricing | ✓ | ✓ | ✓ |
| **Dashboard** | Pattern matrix, data freshness, quick scan | ✓ | ✓ | ✓ |
| **Patterns** | TradingView charts, pattern zones, timeframe selector | ✗ | ✓ | ✓ |
| **Signals** | Symbol search, direction filter, confluence scores | ✗ | ✓ | ✓ |
| **Portfolio** | Multi-portfolio, trade logging, PnL tracking, journal | ✗ | ✓ | ✓ |
| **Backtest** | Strategy backtesting with historical data | ✗ | ✗ | ✓ |
| **Stats** | Database stats, candle counts, verification status | ✓ | ✓ | ✓ |
| **Analytics** | Performance metrics and analysis | ✗ | ✓ | ✓ |
| **Logs** | Application logs viewer | ✓ | ✓ | ✓ |
| **Settings** | Symbols, notifications, risk parameters | ✗ | ✓ | ✓ |
| **Profile** | Account info, 2FA, notification preferences | ✓ | ✓ | ✓ |
| **Upgrade** | Payment page (card & crypto) | ✓ | ✓ | ✓ |

---

## Authentication

### Registration
- Email verification required before full access
- Unique NTFY topic generated per user
- Password requirements: 8+ chars, uppercase, lowercase, digit

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

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List tracked symbols |
| `/api/patterns` | GET | Detected patterns |
| `/api/signals` | GET | Trade signals |
| `/api/matrix` | GET | Pattern matrix |
| `/api/scan/run` | POST | Trigger manual scan |
| `/api/subscription/status` | GET | Check subscription status |

---

## Testing

```bash
python -m pytest                    # All tests (311 tests)
python -m pytest --cov=app          # With coverage
python -m pytest tests/test_auth.py # Auth tests only
```

---

## Project Structure

```
cryptolens/
├── app/
│   ├── routes/          # Web routes (api, auth, dashboard, patterns, etc.)
│   ├── services/        # Business logic (auth, email, notifier, signals, etc.)
│   │   └── patterns/    # FVG, OB, Sweep detectors
│   ├── templates/       # Jinja2 HTML templates
│   ├── decorators.py    # Access control decorators
│   └── models.py        # SQLAlchemy models (User, Subscription, etc.)
├── scripts/
│   ├── fetch.py         # Real-time fetch + detection
│   ├── fetch_historical.py
│   ├── compute_stats.py # Cache stats
│   ├── db_health.py     # Data verification
│   └── migrate_all.py   # DB migrations
├── tests/               # Test suite (311 tests)
├── crontab.txt          # Cron configuration
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

This software is for educational purposes only. Trading cryptocurrencies involves significant risk of loss. Past pattern performance does not guarantee future results. Always use proper risk management.

## License

MIT
