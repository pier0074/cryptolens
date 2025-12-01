# CryptoLens 🔍

**Smart Money Pattern Detection System for Crypto Trading**

CryptoLens detects imbalance patterns (Fair Value Gaps) across multiple timeframes, sends push notifications for trade setups, and provides a web dashboard for visualization and backtesting.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **Pattern Detection**: Automatically detects Fair Value Gaps (Imbalances) across 6 timeframes
- **Multi-Timeframe Confluence**: Identifies when multiple timeframes align for higher probability setups
- **Push Notifications**: Free push notifications via NTFY.sh - no account required
- **Interactive Dashboard**: Visual matrix showing patterns for 30 crypto pairs
- **Candlestick Charts**: TradingView-style charts with pattern overlays
- **Backtesting**: Test strategy performance on historical data
- **REST API**: Full API for future automation

## Screenshots

### Dashboard - Pattern Matrix
View all symbols across all timeframes at a glance. Green = Bullish imbalance, Red = Bearish imbalance.

### Pattern Charts
Interactive candlestick charts with Fair Value Gap zones highlighted.

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

### 3. Run

```bash
python run.py
```

Visit `http://localhost:5000` in your browser.

### 4. Fetch Historical Data

```bash
python scripts/fetch_historical.py
```

### 5. Scan for Patterns

```bash
python scripts/scan_patterns.py
```

## Setup Notifications

1. Install the [NTFY app](https://ntfy.sh/) on your phone (iOS/Android)
2. Subscribe to your topic (default: `cryptolens-signals`)
3. Go to Settings in CryptoLens and test the notification

## How It Works

### Fair Value Gap (Imbalance) Detection

A Fair Value Gap occurs when price moves so aggressively that a gap forms between candles:

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

**Trading Logic:**
- **Bullish FVG**: Place limit buy order at zone high, stop loss below zone low
- **Bearish FVG**: Place limit sell order at zone low, stop loss above zone high
- **Target**: 1:2 or 1:3 risk/reward

### Confluence Scoring

CryptoLens scans 6 timeframes (1m, 5m, 15m, 1h, 4h, 1d). When 2+ timeframes show the same bias (bullish or bearish), it generates a signal with higher confidence.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List all symbols |
| `/api/candles/<symbol>/<tf>` | GET | Get candle data |
| `/api/patterns` | GET | Get detected patterns |
| `/api/signals` | GET | Get trade signals |
| `/api/matrix` | GET | Get pattern matrix |
| `/api/scan` | POST | Trigger pattern scan |

## Project Structure

```
cryptolens/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Configuration
│   ├── models.py            # Database models
│   ├── routes/              # Web routes
│   │   ├── dashboard.py
│   │   ├── patterns.py
│   │   ├── signals.py
│   │   ├── backtest.py
│   │   ├── settings.py
│   │   └── api.py
│   ├── services/            # Business logic
│   │   ├── data_fetcher.py  # CCXT integration
│   │   ├── aggregator.py    # Timeframe aggregation
│   │   ├── patterns/        # Pattern detectors
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

## Roadmap

- [ ] Additional patterns (Order Blocks, Liquidity Sweeps)
- [ ] Telegram notifications
- [ ] Auto-scheduled scanning
- [ ] Performance analytics dashboard
- [ ] API trading integration (Kucoin)
- [ ] Mobile-responsive design improvements

## Disclaimer

⚠️ **This software is for educational purposes only.** Trading cryptocurrencies involves significant risk. Past performance does not guarantee future results. Always do your own research and never trade with money you can't afford to lose.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with ❤️ using Python, Flask, and CCXT
