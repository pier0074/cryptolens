# CryptoLens

**Smart Money Pattern Detection for Crypto Trading**

Detects SMC patterns (Fair Value Gaps, Order Blocks, Liquidity Sweeps) across multiple timeframes, sends push notifications, and provides a web dashboard for visualization and trade journaling.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![Tests](https://img.shields.io/badge/Tests-164%20passing-brightgreen.svg)

## Features

- **Pattern Detection**: FVG, Order Blocks, Liquidity Sweeps across 6 timeframes
- **Event-Driven**: Each symbol processed immediately after fetch (no waiting)
- **Push Notifications**: Free via NTFY.sh with dynamic tags
- **Portfolio & Journal**: Trade logging, journal entries, performance analytics
- **Pattern Expiry**: Timeframe-based auto-expiry (LTF=4h, HTF=14d)

## Quick Start

```bash
# Clone and install
git clone https://github.com/pier0074/cryptolens.git
cd cryptolens
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Fetch historical data (1 year)
python scripts/fetch_historical.py -v

# Run the web app
python run.py
```

Visit `http://localhost:5000`

## Background Processing (Cron)

Event-driven architecture for maximum reactivity:

```bash
crontab -e

# Real-time: Fetch → Aggregate → Detect → Notify (per symbol, as each completes)
* * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch.py

# Gap fill: Find and fill any missing candles
0 * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch_historical.py --gaps

# Cleanup: Mark expired patterns
*/30 * * * * cd /path/to/cryptolens && venv/bin/python scripts/cleanup_patterns.py
```

### Scripts

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `fetch.py` | Async fetch → aggregate → detect → notify (per symbol) | Every 1 min |
| `fetch_historical.py` | Initial load or gap filling | Manual / hourly |
| `cleanup_patterns.py` | Mark expired patterns | Every 30 min |

### How fetch.py Works

```
1. Fetch all 30 symbols in parallel (async)
2. As each symbol completes:
   → Save candles
   → Aggregate to higher timeframes
   → Detect patterns
   → Update pattern status
3. Generate signals (batch)

Result: BTC patterns detected in ~1s, not waiting for 29 other symbols
```

### Historical Data

```bash
python scripts/fetch_historical.py              # Full load (1 year)
python scripts/fetch_historical.py --days=30    # 30 days
python scripts/fetch_historical.py --gaps       # Find and fill gaps
python scripts/fetch_historical.py --status     # DB status
python scripts/fetch_historical.py --delete     # Reset DB
```

## Pattern Expiry

| Timeframe | Expiry | Rationale |
|-----------|--------|-----------|
| 1m | 4h | LTF structure changes quickly |
| 5m | 12h | |
| 1h | 3 days | MTF - stays relevant longer |
| 4h | 7 days | |
| 1d | 14 days | HTF - most significant |

## Notifications

1. Install [NTFY app](https://ntfy.sh/) on your phone
2. Subscribe to your topic (default: `cryptolens-signals`)
3. Test from Settings page

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List symbols |
| `/api/patterns` | GET | Detected patterns |
| `/api/signals` | GET | Trade signals |
| `/api/matrix` | GET | Pattern matrix |
| `/api/scan/run` | POST | Trigger manual scan |

## Testing

```bash
python -m pytest                    # All tests
python -m pytest --cov=app          # With coverage
```

## Project Structure

```
cryptolens/
├── app/
│   ├── routes/          # Web routes
│   ├── services/        # Business logic (patterns/, signals, notifier)
│   └── templates/       # HTML templates
├── scripts/
│   ├── fetch.py         # Real-time fetch with pattern detection
│   ├── fetch_historical.py  # Historical data & gap filling
│   └── cleanup_patterns.py  # Pattern expiry
├── tests/               # 164 tests
└── run.py
```

## Disclaimer

This software is for educational purposes only. Trading involves significant risk.

## License

MIT
