# CryptoLens - Development Roadmap

> Last updated: 2025-12-03

---

## Current Architecture

### Background Processing (Cron-based)
```bash
# Pattern scanning (every 5 minutes)
# Fetches fresh 1m candles, aggregates, detects patterns, sends notifications
*/5 * * * * cd /path/to/cryptolens && venv/bin/python scripts/scan.py

# Pattern cleanup (every 30 minutes)
# Marks expired patterns based on timeframe settings
*/30 * * * * cd /path/to/cryptolens && venv/bin/python scripts/cleanup_patterns.py

# Historical data backfill (daily at midnight, optional)
0 0 * * * cd /path/to/cryptolens && venv/bin/python scripts/fetch_historical.py --days 7
```

### Pattern Expiry (Timeframe-based)
| Timeframe | Expiry | Rationale |
|-----------|--------|-----------|
| 1m | 4h | LTF structure changes quickly |
| 5m | 12h | |
| 15m | 24h | |
| 30m | 48h | |
| 1h | 72h (3d) | MTF - stays relevant longer |
| 2h | 120h (5d) | |
| 4h | 168h (7d) | |
| 1d | 336h (14d) | HTF - most significant |

---

## Pending Tasks

### High Priority
- [ ] **Database migrations** - Flask-Migrate for schema changes
- [ ] **Health check endpoint** - `/api/health` with DB/exchange status

### Medium Priority
- [ ] **Rate limiting** - Flask-Limiter (60 req/min per IP)
- [ ] **Replace generic exceptions** - Catch specific errors (NetworkError, SQLAlchemyError)

---

## Future Enhancements (Optional)

### Real-time Features
- [ ] WebSocket for live price updates on charts
- [ ] Real-time pattern notifications in UI
- [ ] Signal alerts without page refresh

### Multi-Exchange Support
- [ ] Abstract exchange interface
- [ ] Add Coinbase, Kraken, Bybit adapters
- [ ] Exchange selector in settings

### Advanced Features
- [ ] Custom alert rules (price alerts, volume spikes)
- [ ] Pattern ML scoring (train on historical fill rates)
- [ ] Redis caching layer (pattern matrix, confluence scores)
- [ ] Swing-based pattern invalidation (more sophisticated than time-based)

---

## Completed (Phases 1-6)

- Pattern detection (FVG, Order Block, Liquidity Sweep)
- Multi-timeframe aggregation
- Signal generation with confluence
- NTFY notifications with dynamic tags
- Backtesting system
- Portfolio & Trade Journal
- Security (API keys, CSRF, input validation)
- Performance (N+1 fixes, batch queries, caching)
- Test suite (164 tests)
- Cron-based scheduling (replaced APScheduler)
- Pattern expiry system
- Optimized stats page (390→10 queries)

---

*164 tests passing*
