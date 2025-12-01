# CryptoLens 🔍

**Smart Money Pattern Detection System for Crypto Trading**

CryptoLens detects smart money patterns (Fair Value Gaps, Order Blocks, Liquidity Sweeps) across multiple timeframes, sends push notifications for trade setups, and provides a web dashboard for visualization and backtesting.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **3 Pattern Types**: Detects Fair Value Gaps (Imbalances), Order Blocks, and Liquidity Sweeps
- **Multi-Timeframe Analysis**: Scans 6 timeframes (1m, 5m, 15m, 1h, 4h, 1d)
- **Auto-Scanner**: Background scheduler scans for patterns every minute
- **Push Notifications**: Free push notifications via NTFY.sh - no account required
- **Interactive Dashboard**: Visual matrix showing patterns for 30 crypto pairs
- **Pattern Tabs**: Filter dashboard by pattern type (All, FVG, Order Blocks, Sweeps)
- **Performance Analytics**: Track pattern statistics, win rates, and backtest results
- **Candlestick Charts**: TradingView-style charts with pattern overlays
- **Backtesting**: Test strategy performance on historical data
- **REST API**: Full API for future automation

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
# Fetch 1 year of data for all 30 symbols
python scripts/fetch_historical.py

# Or fetch less data for faster testing
python scripts/fetch_historical.py --days=30
```

The fetcher shows detailed progress:
```
[1/30] Processing BTC/USDT...
──────────────────────────────────────────────────
📊 BTC/USDT
   Target: ~525,600 candles (1052 batches)
   Range: 2023-12-01 → 2024-12-01
   [ 10%] Batch 105/1052 | Date: 2024-01-12 | New: 52,500 | ETA: 8.5m
   [ 20%] Batch 210/1052 | Date: 2024-02-23 | New: 105,000 | ETA: 7.2m
   ...
   ✅ Done! 504,073 new + 21,527 existing | Aggregated: 5,230 | Time: 9.2m
```

### 4. Run the Application

```bash
python run.py
```

Visit `http://localhost:5000` in your browser.

The auto-scanner will start automatically, scanning for patterns every minute.

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

## Project Structure

```
cryptolens/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Configuration
│   ├── models.py            # Database models
│   ├── routes/              # Web routes
│   │   ├── dashboard.py     # Main dashboard + analytics
│   │   ├── patterns.py      # Pattern visualization
│   │   ├── signals.py       # Trade signals
│   │   ├── backtest.py      # Backtesting
│   │   ├── settings.py      # Settings
│   │   └── api.py           # REST API
│   ├── services/            # Business logic
│   │   ├── data_fetcher.py  # CCXT integration
│   │   ├── aggregator.py    # Timeframe aggregation
│   │   ├── scheduler.py     # Auto-scanner
│   │   ├── patterns/        # Pattern detectors
│   │   │   ├── imbalance.py    # Fair Value Gaps
│   │   │   ├── order_block.py  # Order Blocks
│   │   │   └── liquidity.py    # Liquidity Sweeps
│   │   ├── signals.py       # Signal generator
│   │   ├── notifier.py      # NTFY notifications
│   │   └── backtester.py    # Backtesting engine
│   └── templates/           # HTML templates
├── scripts/
│   ├── fetch_historical.py  # Download historical data
│   └── scan_patterns.py     # Run pattern scanner
├── data/                    # SQLite database
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
- [x] Auto-scheduled scanning (1-minute)
- [x] Performance analytics dashboard
- [x] Pattern type tabs on dashboard
- [ ] API trading integration (Kucoin)
- [ ] Mobile-responsive design improvements
- [ ] WebSocket real-time updates
- [ ] Multi-exchange support

## Disclaimer

⚠️ **This software is for educational purposes only.** Trading cryptocurrencies involves significant risk. Past performance does not guarantee future results. Always do your own research and never trade with money you can't afford to lose.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with ❤️ using Python, Flask, and CCXT
