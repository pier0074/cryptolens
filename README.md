# CryptoLens

**Smart Money Pattern Detection for Crypto Trading**

Detects SMC patterns (Fair Value Gaps, Order Blocks, Liquidity Sweeps) across multiple timeframes, sends push notifications, and provides a web dashboard for visualization and trade journaling.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![Tests](https://img.shields.io/badge/Tests-164%20passing-brightgreen.svg)

## Features

- **Pattern Detection**: FVG, Order Blocks, Liquidity Sweeps across 6 timeframes
- **Smart Filtering**: Minimum zone size (0.15%), overlap deduplication, timeframe-based expiry
- **Push Notifications**: Free via NTFY.sh with dynamic tags
- **Portfolio & Journal**: Trade logging, journal entries, performance analytics
- **Backtesting**: Test pattern performance on historical data

## Quick Start

```bash
# Clone and install
git clone https://github.com/pier0074/cryptolens.git
cd cryptolens
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Fetch historical data (1 year)
python scripts/fetch_historical.py

# Run the web app
python run.py
```

Visit `http://localhost:5000`

## Background Processing (Cron)

CryptoLens uses lightweight cron scripts instead of APScheduler for better CPU efficiency:

```bash
# Edit crontab
crontab -e

# Add these entries:
# Fetch latest candles (every minute, async parallel)
* * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch.py

# Detect patterns and send notifications (every 5 minutes)
*/5 * * * * cd /path/to/cryptolens && venv/bin/python scripts/detect.py

# Cleanup expired patterns (every 30 minutes)
*/30 * * * * cd /path/to/cryptolens && venv/bin/python scripts/cleanup_patterns.py
```

### Scripts

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `fetch.py` | Async parallel fetch of latest 1m candles | Every 1 min |
| `detect.py` | Aggregate, detect patterns, send notifications | Every 5 min |
| `cleanup_patterns.py` | Mark expired patterns | Every 30 min |
| `fetch_historical.py` | Download historical data | Manual/daily |
| `scan.py` | Combined fetch+detect (legacy) | Every 5 min |

### Historical Data

```bash
python scripts/fetch_historical.py              # Fetch 1 year
python scripts/fetch_historical.py --days=30    # Fetch 30 days
python scripts/fetch_historical.py --status     # Check DB status
python scripts/fetch_historical.py --force      # Re-fetch all (fills gaps)
python scripts/fetch_historical.py --delete     # Delete DB and start fresh
```

## Pattern Expiry

Patterns auto-expire based on timeframe (LTF changes faster than HTF):

| Timeframe | Expiry |
|-----------|--------|
| 1m | 4 hours |
| 5m | 12 hours |
| 15m | 24 hours |
| 1h | 3 days |
| 4h | 7 days |
| 1d | 14 days |

## Notifications

1. Install [NTFY app](https://ntfy.sh/) on your phone
2. Subscribe to your topic (default: `cryptolens-signals`)
3. Test from Settings page

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List symbols |
| `/api/candles/<symbol>/<tf>` | GET | Candle data |
| `/api/patterns` | GET | Detected patterns |
| `/api/signals` | GET | Trade signals |
| `/api/matrix` | GET | Pattern matrix |
| `/api/scan/run` | POST | Trigger manual scan |
| `/api/scheduler/status` | GET | Scanner status |

## Testing

```bash
python -m pytest                    # Run all tests
python -m pytest --cov=app          # With coverage
python -m pytest tests/test_api.py  # Specific file
```

## Project Structure

```
cryptolens/
├── app/
│   ├── routes/          # Web routes (dashboard, patterns, signals, portfolio, api)
│   ├── services/        # Business logic (patterns/, signals, notifier, aggregator)
│   └── templates/       # HTML templates
├── scripts/
│   ├── fetch.py         # Async parallel candle fetcher
│   ├── detect.py        # Pattern detection
│   ├── cleanup_patterns.py
│   ├── fetch_historical.py
│   └── scan.py          # Combined (legacy)
├── tests/               # 164 tests
└── run.py
```

## Disclaimer

This software is for educational purposes only. Trading involves significant risk.

## License

MIT
