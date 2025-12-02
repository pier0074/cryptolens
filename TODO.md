# CryptoLens - Development Roadmap

> Generated from code review on 2025-12-02

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

## MEDIUM PRIORITY (Code Quality)

### Type Hints
- [ ] Add comprehensive type hints to all functions
  - `data_fetcher.py`
  - `signals.py`
  - `aggregator.py`
  - `notifier.py`
  - All pattern detectors

### Constants & Configuration
- [ ] **Extract magic numbers to config** - Multiple files
  - `MIN_ZONE_PCT = 0.15`
  - `ATR_BUFFER_MULTIPLIER = 0.5`
  - `MAX_TRADE_LOOKBACK = 100`
  - `AGGREGATION_BATCH_SIZE = 50000`
  - `SIGNAL_COOLDOWN_HOURS = 4`

### DRY Refactoring
- [ ] **Move update_pattern_status to base class** - `patterns/*.py`
  - Nearly identical code in all 3 detectors
  - Create single implementation in `PatternDetector` base

- [ ] **Fix hardcoded exchange name** - `run.py:25`, `settings.py:58`
  - Use `Config.EXCHANGE` consistently
  - Currently hardcoded as 'kucoin' in some places

### Architecture
- [ ] **Fix circular import risk** - `scheduler.py:16-19`
  - Pass app context properly instead of creating new instances
  - Use `current_app._get_current_object()`

- [ ] **Remove global scheduler state** - `scheduler.py:11`
  - Use Flask extension pattern
  - Store in `app.extensions['scheduler']`

- [ ] **Add database migrations**
  - Install Flask-Migrate
  - Initialize Alembic
  - Create initial migration

### Error Handling
- [ ] **Replace generic exceptions** - `scheduler.py:43, 81, 113`
  - Catch specific exceptions (NetworkError, ExchangeError, SQLAlchemyError)
  - Don't catch KeyboardInterrupt

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

---

## NEW FEATURES

### Portfolio & Trade Journal System
- [ ] **Create Portfolio model**
  ```
  Portfolio:
    - id, name, description
    - initial_balance, current_balance
    - created_at, updated_at
  ```

- [ ] **Create Trade model**
  ```
  Trade:
    - id, portfolio_id, signal_id (optional)
    - symbol, direction (long/short)
    - entry_price, entry_time, entry_quantity
    - exit_price, exit_time
    - stop_loss, take_profit
    - status (open/closed/cancelled)
    - pnl_amount, pnl_percent
    - fees
  ```

- [ ] **Create JournalEntry model**
  ```
  JournalEntry:
    - id, trade_id
    - entry_type (pre_trade/during/post_trade/lesson)
    - content (text)
    - mood (confident/neutral/fearful/greedy)
    - tags (JSON array)
    - screenshots (JSON array of paths)
    - created_at
  ```

- [ ] **Create TradeTag model**
  ```
  TradeTag:
    - id, name, color
    - description
  ```

- [ ] **Portfolio Routes**
  - `GET /portfolio/` - Portfolio dashboard
  - `GET /portfolio/trades` - Trade list with filters
  - `POST /portfolio/trades` - Log new trade
  - `PUT /portfolio/trades/<id>` - Update trade
  - `GET /portfolio/trades/<id>` - Trade detail + journal
  - `POST /portfolio/trades/<id>/close` - Close trade
  - `POST /portfolio/trades/<id>/journal` - Add journal entry

- [ ] **Portfolio UI**
  - Dashboard with equity curve
  - Open positions panel
  - Trade history table with sorting/filtering
  - Trade detail page with journal entries
  - Quick-add trade form
  - Import from signal button

- [ ] **Portfolio Analytics**
  - Win rate, profit factor, avg R:R
  - Best/worst trades
  - Performance by symbol
  - Performance by pattern type
  - Performance by time of day/week
  - Drawdown chart
  - Monthly/weekly P&L breakdown

- [ ] **Journal Features**
  - Pre-trade checklist (why entering?)
  - Post-trade review (what learned?)
  - Emotion tracking
  - Screenshot upload for chart markup
  - Tag system for filtering/analysis
  - Export journal to PDF/Markdown

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
- [x] Background scheduler
- [x] Backtesting system
- [x] Database statistics page
- [x] Scanner toggle in UI
- [x] Progress bar for aggregation
- [x] Minimum zone size filter (0.15%)
- [x] Smart price formatting for cheap coins
- [x] **Test suite** (101 tests, 54% coverage)
- [x] **Dynamic notification tags** (direction/symbol/pattern)
- [x] **Test mode notifications** ([TEST] prefix, `test` tag)
- [x] **Varied test notifications** (BTC/ETH/SOL, LONG/SHORT, FVG/OB/LS)
- [x] **European notification format** (timestamp, R:R percentage, confluence timeframes)

---

## Implementation Order (Suggested)

### Phase 1: Security & Stability ✅ COMPLETE
1. ~~SECRET_KEY validation~~
2. ~~API authentication~~
3. ~~CSRF protection~~
4. ~~Input validation~~
5. ~~Notification retry logic~~
6. ~~Silent logging failures fix~~
7. ~~Transaction rollback fix~~

### Phase 2: Performance ✅ COMPLETE
1. ~~Fix N+1 queries (signals + matrix)~~
2. ~~Exchange singleton~~
3. ~~Direct SQL to DataFrame~~

### Phase 3: Testing ✅ COMPLETE
1. ~~Test infrastructure setup (conftest.py)~~
2. ~~Pattern detection tests~~
   - test_patterns/test_imbalance.py (16 tests)
   - test_patterns/test_order_block.py (9 tests)
   - test_patterns/test_liquidity.py (10 tests)
3. ~~Signal generation tests (test_signals.py - 20 tests)~~
4. ~~API tests (test_api.py - 31 tests)~~
5. ~~Integration tests (test_integration.py - 14 tests)~~
   - **Total: 101 tests passing, 54% coverage**

### Phase 4: Portfolio & Journal
1. Database models
2. Basic CRUD routes
3. Portfolio dashboard UI
4. Trade logging
5. Journal system
6. Analytics

### Phase 5: Code Quality
1. Type hints
2. Extract magic numbers to config
3. DRY refactoring (pattern detectors)
4. Fix hardcoded exchange names

---

*Last updated: 2025-12-02 (Phase 3 Testing complete - 101 tests, 54% coverage)*
