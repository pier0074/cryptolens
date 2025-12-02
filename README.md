# CryptoLens

**Smart Money Pattern Detection System for Crypto Trading**

CryptoLens detects smart money patterns (Fair Value Gaps, Order Blocks, Liquidity Sweeps) across multiple timeframes, sends push notifications for trade setups, and provides a web dashboard for visualization, backtesting, and trade journaling.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![Tests](https://img.shields.io/badge/Tests-164%20passing-brightgreen.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

### Pattern Detection
- **3 Pattern Types**: Fair Value Gaps (Imbalances), Order Blocks, Liquidity Sweeps
- **Multi-Timeframe Analysis**: Scans 6 timeframes (1m, 5m, 15m, 1h, 4h, 1d)
- **Smart Filtering**: Minimum zone size (0.15%), overlap deduplication
- **Fill Tracking**: Monitors when price revisits pattern zones

### Scanning & Alerts
- **Smart Scheduler**: 5-minute intervals with timeframe-aware checks (only scans TFs that could have new data)
- **Scanner Toggle**: Enable/disable from UI with live status
- **Push Notifications**: Free via NTFY.sh with dynamic tags (direction, symbol, pattern)
- **Confluence Scoring**: Higher confidence when multiple timeframes align

### Portfolio & Journal (NEW)
- **Portfolio Management**: Track multiple portfolios with balance tracking
- **Trade Logging**: Entry/exit, stop loss, take profit, fees
- **Journal Entries**: Pre-trade, during, post-trade notes with mood tracking
- **Trade Tags**: Organize trades with custom colored tags
- **Analytics**: Win rate, profit factor, R-multiples, performance by symbol

### Dashboard & Analytics
- **Pattern Matrix**: Visual grid showing patterns for 30 crypto pairs
- **Performance Stats**: Win rates, backtest results
- **Database Stats**: Per-symbol ATH/ATL, candle counts, data freshness
- **Candlestick Charts**: TradingView-style with pattern overlays

### Technical
- **REST API**: Full API for automation
- **164 Tests**: Comprehensive test suite
- **CSRF Protection**: Secure forms
- **API Authentication**: Optional API key for sensitive endpoints

## Screenshots

### Dashboard - Pattern Matrix
View all symbols across all timeframes at a glance. Green = Bullish, Red = Bearish. Yellow border = Multiple patterns.

### Analytics Dashboard
Track pattern distribution, bullish vs bearish ratios, top symbols, and backtest performance.

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/pier0074/cryptolens.git
cd cryptolens

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your settings (optional)
```

### 3. Fetch Historical Data

```bash
# Fetch 1 year of data for all 30 symbols (auto-resumes if interrupted)
python scripts/fetch_historical.py

# Fetch less data for faster testing
python scripts/fetch_historical.py --days=30

# Check current database status
python scripts/fetch_historical.py --status

# Force re-fetch even if data exists (fills gaps)
python scripts/fetch_historical.py --force

# Delete all candles and start fresh (requires confirmation)
python scripts/fetch_historical.py --delete
```

Progress is tracked in the database - if the script crashes, it will automatically resume from where it left off.

The fetcher shows detailed progress:
```
════════════════════════════════════════════════════════════
  CryptoLens Historical Data Fetcher
════════════════════════════════════════════════════════════
  📈 Total symbols: 30
  ✅ Already complete: 5
  📥 Need fetching: 25
  📅 Days of history: 365 (1.0 years)
  📊 Est. candles/symbol: ~525,600

[1/25] Processing BTC/USDT...
──────────────────────────────────────────────────
📊 BTC/USDT
   Target: ~525,600 candles (526 batches)
   Range: 2024-12-01 → 2025-12-01
   [████████████████████████████░░] 95.0% | 2025-11-28 | 500,000 candles | ETA: 13s
   [██████████████████████████████] 100.0% | Complete | 525,600 candles
   📊 Aggregating 1m candles → 5m, 15m, 1h, 4h, 1d...
   📊 Created: 5m=105,120 | 15m=35,040 | 1h=8,760 | 4h=2,190 | 1d=365
   ✅ Done! 504,073 new + 21,527 existing | Aggregated: 151,475 | Time: 9.2m
```

### 4. Run the Application

```bash
python run.py
```

Visit `http://localhost:5000` in your browser.

The scanner can be started from Settings or via the API (disabled by default).

## Pattern Types

### 1. Fair Value Gap (Imbalance)

A gap between candles indicating aggressive price movement:

```
Bullish FVG:           Bearish FVG:
   │  │                    │  │
   │ ┌┴┐ Candle 3          └┬┘ │ Candle 3
   │ │ │                    │  │
   │ └─┘ ← Zone High        │  │
   ├──── GAP ────┤          ├──── GAP ────┤
   │ ┌─┐ ← Zone Low         │ ┌┴┐
   │ │ │                    │ │ │
   │ └┬┘ Candle 1           │ └─┘ Candle 1
   │  │                     │  │
```

### 2. Order Blocks

The last opposing candle before a strong move - represents institutional order flow:

- **Bullish OB**: Last bearish candle before strong bullish move
- **Bearish OB**: Last bullish candle before strong bearish move

### 3. Liquidity Sweeps

Price takes out a previous high/low (hunting stop losses) then reverses:

- **Bullish Sweep**: Price sweeps below a swing low, then closes back above
- **Bearish Sweep**: Price sweeps above a swing high, then closes back below

## Trading Logic

- **Entry**: Place limit order at pattern zone
- **Stop Loss**: Below/above the zone with ATR buffer
- **Take Profit**: 1:2 or 1:3 risk/reward ratio
- **Confluence**: Higher confidence when 2+ timeframes agree

## Setup Notifications

1. Install the [NTFY app](https://ntfy.sh/) on your phone (iOS/Android)
2. Subscribe to your topic (default: `cryptolens-signals`)
3. Go to Settings in CryptoLens and test the notification

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List all symbols |
| `/api/candles/<symbol>/<tf>` | GET | Get candle data |
| `/api/patterns` | GET | Get detected patterns |
| `/api/signals` | GET | Get trade signals |
| `/api/matrix` | GET | Get pattern matrix |
| `/api/scan` | POST | Trigger pattern scan |
| `/api/fetch` | POST | Trigger data fetch |
| `/api/scheduler/status` | GET | Get scanner status |
| `/api/scheduler/start` | POST | Start the scanner |
| `/api/scheduler/stop` | POST | Stop the scanner |
| `/api/scheduler/toggle` | POST | Toggle scanner on/off |
| `/portfolio/api/portfolios` | GET | List all portfolios |
| `/portfolio/api/portfolios/<id>` | GET | Get portfolio detail |
| `/portfolio/api/portfolios/<id>/trades` | GET | Get portfolio trades |
| `/portfolio/api/portfolios/<id>/stats` | GET | Get portfolio statistics |

## Testing

Run the test suite with coverage:

```bash
# Run all tests
python -m pytest

# Run with coverage report
python -m pytest --cov=app --cov-report=term

# Run specific test file
python -m pytest tests/test_signals.py -v
```

### Test Coverage

| Module | Stmts | Miss | Cover |
|--------|-------|------|-------|
| **Core** |  |  |  |
| `app/__init__.py` | 41 | 3 | 93% |
| `app/config.py` | 34 | 3 | 91% |
| `app/models.py` | 143 | 10 | 93% |
| **Routes** |  |  |  |
| `app/routes/api.py` | 127 | 18 | 86% |
| `app/routes/backtest.py` | 25 | 10 | 60% |
| `app/routes/dashboard.py` | 50 | 2 | 96% |
| `app/routes/logs.py` | 30 | 3 | 90% |
| `app/routes/patterns.py` | 30 | 0 | 100% |
| `app/routes/settings.py` | 74 | 10 | 86% |
| `app/routes/signals.py` | 30 | 2 | 93% |
| `app/routes/stats.py` | 61 | 14 | 77% |
| **Services** |  |  |  |
| `app/services/signals.py` | 128 | 23 | 82% |
| `app/services/notifier.py` | 100 | 9 | 91% |
| `app/services/logger.py` | 77 | 13 | 83% |
| `app/services/data_fetcher.py` | 126 | 86 | 32% |
| `app/services/aggregator.py` | 88 | 11 | 88% |
| `app/services/scheduler.py` | 98 | 76 | 22% |
| `app/services/backtester.py` | 98 | 98 | 0% |
| **Pattern Detectors** |  |  |  |
| `app/services/patterns/base.py` | 23 | 3 | 87% |
| `app/services/patterns/liquidity.py` | 106 | 23 | 78% |
| `app/services/patterns/order_block.py` | 93 | 25 | 73% |
| `app/services/patterns/imbalance.py` | 78 | 24 | 69% |
| `app/services/patterns/__init__.py` | 54 | 20 | 63% |
| **TOTAL** | **1714** | **486** | **72%** |

**Coverage Notes:**
- Core modules (models, config, init): 91-93%
- Pattern detectors: 63-87%
- Signal generation: 82%
- UI routes: 60-100% (patterns: 100%, dashboard: 96%, signals: 93%)
- Services: notifier 91%, aggregator 88%, logger 83%
- Backtester/Data Fetcher: 0-32% (require network mocking)

## Project Structure

```
cryptolens/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Configuration (pattern thresholds, timeframes)
│   ├── models.py            # Database models
│   ├── routes/              # Web routes
│   │   ├── dashboard.py     # Main dashboard + analytics
│   │   ├── patterns.py      # Pattern visualization
│   │   ├── signals.py       # Trade signals
│   │   ├── portfolio.py     # Portfolio & trade journal (NEW)
│   │   ├── backtest.py      # Backtesting
│   │   ├── settings.py      # Settings
│   │   ├── logs.py          # Logging viewer
│   │   ├── stats.py         # Database statistics
│   │   └── api.py           # REST API + scheduler control
│   ├── services/            # Business logic
│   │   ├── data_fetcher.py  # CCXT/Binance integration
│   │   ├── aggregator.py    # Timeframe aggregation
│   │   ├── scheduler.py     # Smart scanner (5-min interval)
│   │   ├── logger.py        # Centralized logging
│   │   ├── patterns/        # Pattern detectors
│   │   │   ├── base.py         # Base class with shared logic
│   │   │   ├── imbalance.py    # Fair Value Gaps
│   │   │   ├── order_block.py  # Order Blocks
│   │   │   └── liquidity.py    # Liquidity Sweeps
│   │   ├── signals.py       # Signal generator
│   │   ├── notifier.py      # NTFY notifications
│   │   └── backtester.py    # Backtesting engine
│   └── templates/           # HTML templates
│       └── portfolio/       # Portfolio UI templates (NEW)
├── scripts/
│   └── fetch_historical.py  # Download historical data
├── tests/                   # Test suite (164 tests)
│   ├── conftest.py          # Pytest fixtures
│   ├── test_api.py          # API tests (31)
│   ├── test_signals.py      # Signal tests (20)
│   ├── test_integration.py  # Integration tests (14)
│   ├── test_routes.py       # Route tests (37)
│   ├── test_services.py     # Service tests (26)
│   └── test_patterns/       # Pattern tests (36)
├── data/                    # SQLite database (WAL mode)
├── requirements.txt
└── run.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | auto-generated | Flask secret key |
| `DATABASE_URL` | `sqlite:///data/cryptolens.db` | Database path |
| `NTFY_TOPIC` | `cryptolens-signals` | NTFY notification topic |
| `NTFY_PRIORITY` | `4` | Notification priority (1-5) |
| `SCHEDULER_ENABLED` | `true` | Enable auto-scanner |
| `PORT` | `5000` | Server port |

## Roadmap

- [x] Fair Value Gap detection
- [x] Order Blocks detection
- [x] Liquidity Sweeps detection
- [x] Smart scheduled scanning (5-minute, timeframe-aware)
- [x] Performance analytics dashboard
- [x] Comprehensive logging system with web viewer
- [x] Scanner toggle in UI (on/off control)
- [x] Database statistics page (ATH/ATL, candle counts)
- [x] Test suite with 164 tests
- [x] Dynamic notification tags (direction/symbol/pattern)
- [x] Portfolio & trade journal system
- [x] DRY pattern detector architecture
- [ ] WebSocket real-time updates
- [ ] Multi-exchange support
- [ ] Mobile-responsive improvements

## Disclaimer

⚠️ **This software is for educational purposes only.** Trading cryptocurrencies involves significant risk. Past performance does not guarantee future results. Always do your own research and never trade with money you can't afford to lose.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with ❤️ using Python, Flask, and CCXT
