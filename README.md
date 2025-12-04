# CryptoLens

**Smart Money Concepts (SMC) Pattern Detection for Crypto Trading**

Automated detection of institutional trading patterns across multiple timeframes with push notifications, interactive charts, trade journaling, and portfolio management.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![Tests](https://img.shields.io/badge/Tests-164%20passing-brightgreen.svg)

## Features

- **Pattern Detection**: FVG, Order Blocks, Liquidity Sweeps across 6 timeframes
- **Multi-TF Confluence**: Signals generated when patterns align across timeframes
- **Interactive Charts**: TradingView-style charts with pattern visualization
- **Smart Price Formatting**: Auto-adjusts decimals for micro-cap to large-cap tokens
- **Push Notifications**: Free via NTFY.sh
- **Portfolio & Journal**: Trade logging with PnL tracking and journal entries
- **Event-Driven**: Each symbol processed immediately after fetch

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

# Fetch historical data
python scripts/fetch_historical.py -v

# Run the web app
python run.py
```

Visit `http://localhost:5000`

---

## Background Processing (Cron)

```bash
crontab -e

# All-in-one: Fetch (with auto gap-fill) → Aggregate → Detect → Expire → Notify
* * * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch.py
```

### Scripts

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `fetch.py` | Fetch + aggregate + detect + expire + notify (handles any gap) | Every 1 min |
| `fetch_historical.py` | Initial data load for new symbols | Manual (once) |

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

### Dashboard
- Real-time pattern matrix (symbol × timeframe)
- Data freshness indicator
- Quick scan button

### Patterns Page
- Interactive TradingView charts
- Pattern zones drawn from detection timestamp
- Timeframe selector with dynamic candle loading
- Smart price formatting for all token sizes

### Signals Page
- Symbol search with autocomplete
- Direction filter (Long/Short/All)
- Pattern type indicator
- Confluence score with aligned timeframes

### Portfolio
- Multiple portfolios support
- Trade creation from signals/patterns
- PnL tracking with R-multiple
- Journal entries per trade

---

## Notifications

1. Install [NTFY app](https://ntfy.sh/) on your phone
2. Subscribe to your topic (default: `cryptolens-signals`)
3. Test from Settings page

---

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/symbols` | GET | List tracked symbols |
| `/api/patterns` | GET | Detected patterns |
| `/api/signals` | GET | Trade signals |
| `/api/matrix` | GET | Pattern matrix |
| `/api/scan/run` | POST | Trigger manual scan |

---

## Testing

```bash
python -m pytest                    # All tests
python -m pytest --cov=app          # With coverage
```

---

## Project Structure

```
cryptolens/
├── app/
│   ├── routes/          # Web routes
│   ├── services/        # Business logic
│   │   └── patterns/    # FVG, OB, Sweep detectors
│   └── templates/       # HTML templates
├── scripts/
│   ├── fetch.py         # Real-time fetch + detection
│   ├── fetch_historical.py
│   └── cleanup_patterns.py
├── tests/               # 164 tests
└── run.py
```

---

## Disclaimer

This software is for educational purposes only. Trading cryptocurrencies involves significant risk of loss. Past pattern performance does not guarantee future results. Always use proper risk management.

## License

MIT
