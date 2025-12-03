# CryptoLens - Development Roadmap

> Last updated: 2025-12-03

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

### Pattern Improvements
- [ ] **Swing-based pattern invalidation** - Expire patterns when new swing forms beyond zone
- [ ] **ATR-based expiry** - More dynamic than static time-based
- [ ] **Pattern ML scoring** - Train on historical fill rates

### Real-time Features
- [ ] WebSocket for live price updates
- [ ] Real-time pattern notifications in UI
- [ ] Signal alerts without page refresh

### Multi-Exchange Support
- [ ] Abstract exchange interface
- [ ] Add Coinbase, Kraken, Bybit adapters
- [ ] Exchange selector in settings

### Other
- [ ] Custom alert rules (price alerts, volume spikes)
- [ ] Redis caching layer (pattern matrix, confluence scores)
- [ ] Gap detection in fetch_historical.py (currently only --force fills gaps)

---

## Completed

### Phase 6: Architecture (Dec 2025)
- Cron-based scheduling (replaced APScheduler)
- Async parallel fetch script (fetch.py)
- Pattern detection script (detect.py)
- Pattern expiry system (timeframe-based)
- Stats page optimization (390→10 queries)

### Phase 5: Code Quality
- Type hints in key services
- Configuration centralization
- DRY pattern detector refactoring

### Phase 4: Portfolio & Journal
- Portfolio management
- Trade logging with journal entries
- Performance analytics

### Phase 3: Testing
- 164 tests passing
- API, routes, services, patterns covered

### Phase 2: Performance
- N+1 query fixes
- Exchange instance caching
- Direct SQL to DataFrame

### Phase 1: Security
- API key authentication
- CSRF protection
- Input validation
- Notification retry logic

### Core Features
- Pattern detection (FVG, Order Block, Liquidity Sweep)
- Multi-timeframe aggregation
- Signal generation with confluence
- NTFY notifications
- Backtesting system

---

*164 tests passing*
