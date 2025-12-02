# CryptoLens - Development Roadmap

> Last updated: 2025-12-02

---

## CRITICAL ISSUES (Security & Stability) ✅ COMPLETE

### Security
- [x] **Remove hardcoded SECRET_KEY fallback** - `config.py:8`
  - Require SECRET_KEY env var in production
  - Raise error if not set

- [x] **Add API authentication** - `api.py:113-176`
  - Add API key authentication for scheduler control endpoints
  - Create `@require_api_key` decorator
  - Store API key in Settings table

- [x] **Add CSRF protection** - `settings.py:31-46`
  - Install Flask-WTF
  - Add CSRF tokens to all forms
  - Protect POST endpoints

- [x] **Add input validation** - `settings.py:56-57`
  - Validate symbol format with regex (`^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$`)
  - Sanitize all user inputs

### Stability
- [x] **Fix silent logging failures** - `logger.py:75-77`
  - Log to stderr when DB logging fails
  - Don't silently swallow exceptions

- [x] **Add notification retry logic** - `notifier.py:29-45`
  - Implement exponential backoff (3 retries)
  - Only retry on server errors (5xx)

- [x] **Fix transaction rollback** - `signals.py:236-237`
  - Add try/except around db.session.commit()
  - Rollback on failure and log error

---

## HIGH PRIORITY (Performance) ✅ COMPLETE

### N+1 Query Fixes
- [x] **Fix signals endpoint N+1** - `api.py:79-84`
  - Use `joinedload(Signal.symbol)`
  - Single query instead of N+1

- [x] **Fix pattern matrix N+1** - `api.py:96-108`
  - Previously 180 queries (30 symbols × 6 timeframes)
  - Now uses single query with subquery groupby

- [x] **Cache exchange instance** - `data_fetcher.py:45`
  - Singleton pattern for ccxt exchange
  - Avoid recreating on every call

### Memory Optimization
- [x] **Direct SQL to DataFrame** - `aggregator.py:54-70`
  - Use `pd.read_sql()` instead of loading to list first
  - Reduce memory footprint by 50%

### Caching Layer
- [ ] **Add Redis caching** (optional, future)
  - Cache pattern matrix (invalidate on new patterns)
  - Cache confluence scores
  - Cache symbol list

---

## MEDIUM PRIORITY (Code Quality) ✅ MOSTLY COMPLETE

### Type Hints ✅ COMPLETE
- [x] Add comprehensive type hints to key functions
  - `data_fetcher.py` - Tuple, List, Dict, Any, Optional, Callable
  - Pattern detectors - List, Dict, Any

### Constants & Configuration ✅ COMPLETE
- [x] **Extract magic numbers to config** - `config.py`
  - `MIN_ZONE_PERCENT = 0.15`
  - `ORDER_BLOCK_STRENGTH_MULTIPLIER = 1.5`
  - `OVERLAP_THRESHOLDS` per timeframe
  - `BATCH_SIZE = 1000`
  - `RATE_LIMIT_DELAY = 0.1`
  - `TIMEFRAME_MS` mapping

### DRY Refactoring ✅ COMPLETE
- [x] **Move shared methods to base class** - `patterns/base.py`
  - `save_pattern()` - common pattern saving logic
  - `check_fill()` - check if pattern zone filled
  - `update_pattern_status()` - update all patterns for symbol
  - `is_zone_tradeable()` - uses Config.MIN_ZONE_PERCENT
  - `has_overlapping_pattern()` - deduplication

### Architecture (Remaining)
- [ ] **Add database migrations**
  - Install Flask-Migrate
  - Initialize Alembic
  - Create initial migration

- [ ] **Replace generic exceptions** - `scheduler.py`
  - Catch specific exceptions (NetworkError, ExchangeError, SQLAlchemyError)

---

## TEST COVERAGE ✅ COMPLETE

### Critical Tests (Pattern Detection)
- [x] `tests/test_patterns.py`
  - Test bullish imbalance detection
  - Test bearish imbalance detection
  - Test zone size filter (< 0.15% rejected)
  - Test pattern fill tracking
  - Test edge cases (no data, insufficient candles)
  - Test no duplicate patterns

### Critical Tests (Signals)
- [x] `tests/test_signals.py`
  - Test ATR calculation (sufficient data, empty, insufficient, unknown symbol)
  - Test confluence calculation (single direction, mixed, neutral)
  - Test signal cooldown (4-hour)
  - Test entry/SL/TP calculations (long & short)
  - Test minimum risk enforcement (0.5%)
  - Test R:R ratio validation
  - Test HTF requirement filtering
  - Test highest timeframe pattern selection

### API Tests
- [x] `tests/test_api.py`
  - Test all endpoints return valid JSON
  - Test 404 on unknown symbol
  - Test query parameter filtering
  - Test API key authentication
  - Test symbols, candles, patterns, signals, matrix endpoints
  - Test scheduler endpoints

### Test Infrastructure
- [x] Create `tests/conftest.py` with fixtures
  - Test database setup/teardown
  - Sample candle data fixtures (bullish/bearish FVG, no FVG, small FVG)
  - Sample pattern and signal fixtures

### Additional Pattern Tests ✅ COMPLETE
- [x] `tests/test_patterns/test_order_block.py` (9 tests)
  - Bullish/bearish order block detection
  - Weak moves don't create blocks
  - Fill detection
- [x] `tests/test_patterns/test_liquidity.py` (10 tests)
  - Swing point detection
  - Bullish/bearish sweep detection
  - Fill/invalidation logic
- [x] `tests/test_integration.py` (14 tests)
  - Pattern detection pipeline
  - Confluence flow
  - Notification pipeline (BTC/ETH/SOL, LONG/SHORT, FVG/OB/LS)
  - Test mode notifications
  - Database integrity
  - Settings integration
- [x] `tests/test_routes.py` (37 tests)
  - Dashboard routes (4 tests)
  - Stats routes (4 tests)
  - Logs routes (6 tests)
  - Patterns routes (7 tests)
  - Signals routes (6 tests)
  - Backtest routes (3 tests)
  - Settings routes (6 tests)
- [x] `tests/test_services.py` (26 tests)
  - Aggregator service (8 tests)
  - Scheduler service (3 tests)
  - Logger service (10 tests)
  - Notifier service (5 tests)

---

## NEW FEATURES

### Portfolio & Trade Journal System ✅ COMPLETE

- [x] **Portfolio model** - `models.py`
  - id, name, description, initial_balance, current_balance
  - currency, is_active, created_at, updated_at
  - Properties: total_pnl, total_pnl_percent, open_trades_count

- [x] **Trade model** - `models.py`
  - Full trade tracking: symbol, direction, timeframe, pattern_type
  - Entry: price, time, quantity
  - Exit: price, time, notes
  - Risk: stop_loss, take_profit, risk_amount, risk_percent
  - Results: pnl_amount, pnl_percent, pnl_r, fees
  - Notes: setup_notes, exit_notes, lessons_learned
  - Methods: calculate_pnl(), close()

- [x] **JournalEntry model** - `models.py`
  - entry_type (pre_trade/during/post_trade/lesson)
  - content, mood tracking
  - screenshots (JSON array)

- [x] **TradeTag model** - `models.py`
  - Many-to-many with trades
  - Custom colors

- [x] **Portfolio Routes** - `routes/portfolio.py`
  - Full CRUD for portfolios
  - Trade management (create, edit, close, delete)
  - Journal entries (add, delete)
  - Tag management
  - API endpoints for stats

- [x] **Portfolio UI** - `templates/portfolio/`
  - index.html - Portfolio list with totals
  - detail.html - Portfolio detail with trades and stats
  - trade_form.html - Create/edit trade
  - trade_detail.html - Trade detail with journal
  - tags.html - Tag management
  - create.html, edit.html

- [x] **Portfolio Analytics**
  - Win rate, profit factor
  - Average win/loss
  - R-multiple tracking
  - Performance by symbol
  - API endpoint: /portfolio/api/portfolios/<id>/stats

### Additional Features
- [ ] **Health check endpoint** - `GET /api/health`
  - Database connectivity
  - Scheduler status
  - Last successful fetch timestamp

- [ ] **Rate limiting on API**
  - Install Flask-Limiter
  - Limit to 60 requests/minute per IP

- [ ] **WebSocket for real-time updates**
  - Live price updates on charts
  - Real-time pattern notifications
  - Signal alerts in UI

- [ ] **Multi-exchange support**
  - Abstract exchange interface
  - Add Coinbase, Kraken, Bybit
  - Exchange selector in settings

- [ ] **Custom alert rules**
  - User-defined conditions
  - Price alerts
  - Volume spike alerts
  - Pattern-specific notifications

- [ ] **Pattern ML scoring**
  - Train on historical fill rates
  - Score patterns by quality
  - Filter low-quality patterns

---

## COMPLETED
- [x] Initial Flask application structure
- [x] Pattern detection (Imbalance, Order Block, Liquidity Sweep)
- [x] Multi-timeframe aggregation
- [x] Signal generation with confluence
- [x] NTFY notifications
- [x] Smart background scheduler (5-min, timeframe-aware)
- [x] Backtesting system
- [x] Database statistics page
- [x] Scanner toggle in UI
- [x] Progress bar for aggregation
- [x] Minimum zone size filter (0.15%)
- [x] Smart price formatting for cheap coins
- [x] **Test suite** (164 tests)
- [x] **Dynamic notification tags** (direction/symbol/pattern)
- [x] **Portfolio & Trade Journal System**
- [x] **DRY pattern detector refactoring**
- [x] **Configuration centralization** (magic numbers to config)
- [x] **Type hints** in key services

---

## Implementation Order

### Phase 1: Security & Stability ✅ COMPLETE
### Phase 2: Performance ✅ COMPLETE
### Phase 3: Testing ✅ COMPLETE (164 tests)
### Phase 4: Portfolio & Journal ✅ COMPLETE
### Phase 5: Code Quality ✅ COMPLETE

### Phase 6: Future Enhancements
1. Database migrations (Flask-Migrate)
2. WebSocket real-time updates
3. Multi-exchange support
4. Health check endpoint
5. Rate limiting on API

---

*Last updated: 2025-12-02 (Phases 1-5 complete - 164 tests passing)*
