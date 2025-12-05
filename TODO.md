# CryptoLens v2.0 - Improvement Plan

> **Current Version**: v2.0.0-dev (v1.0.0 released 2025-12-05)
> **Goal**: Security hardening, production readiness, performance optimization
> See: ARCHITECTURE_AUDIT.md for full details

---

## v2.0 Roadmap

| Version | Focus | Status |
|---------|-------|--------|
| v2.0.0 | API Auth + Rate Limiting | **Done** |
| v2.1.0 | Input Validation + CSRF Fix | **Done** |
| v2.2.0 | Health Check + Logging | Pending |
| v2.3.0 | Gunicorn + Connection Pooling | Pending |
| v2.4.0 | Performance (DB Index, Query Opt) | Pending |
| v2.5.0 | Code Quality (Coverage, Types) | Pending |

---

## Phase 1: Critical Security Fixes (v2.0.x - v2.1.x)

### 1.1 Fix API Authentication Default ✅
- [x] **File**: `app/routes/api.py`
- [x] Change `require_api_key` to deny by default
- [x] Add `ALLOW_UNAUTHENTICATED_API` env var for dev mode
- [x] Use `hmac.compare_digest()` for timing-safe comparison
- [x] Test: Verify API returns 503 when no key configured

### 1.2 Add Rate Limiting ✅
- [x] Install `flask-limiter`: `pip install flask-limiter`
- [x] **File**: `app/__init__.py` - Initialize limiter
- [x] **File**: `app/routes/api.py` - Add limits to expensive endpoints:
  - `/api/scan` - 1/minute
  - `/api/fetch` - 5/minute
  - `/api/scheduler/*` - 2/minute
- [x] Test: Verify rate limiting is active

### 1.3 Add Input Validation ✅
- [x] **File**: `app/routes/portfolio.py`
- [x] Add validation for `new_trade()`:
  - entry_price > 0
  - entry_quantity > 0
  - symbol length 3-20 chars
- [x] Add validation for `create()` portfolio:
  - initial_balance > 0, < 1_000_000_000
- [x] Return proper error messages on validation failure
- [x] Test: 14 new validation tests added

### 1.4 Fix CSRF Exemption on Settings ✅
- [x] **File**: `app/__init__.py`
- [x] Remove `csrf.exempt(settings_bp)`
- [x] **File**: `app/routes/settings.py` - CSRF tokens already in forms
- [x] **File**: `app/templates/settings.html` - Already has `{{ csrf_token() }}`
- [x] Test: All 6 settings tests pass

---

## Phase 2: Production Readiness

### 2.1 Add Health Check Endpoint ✅
- [x] **File**: `app/routes/api.py`
- [x] Add `/api/health` endpoint
- [x] Check database connectivity
- [x] Return JSON with status, db state, timestamp
- [x] Test: 5 new health check tests added

### 2.2 Replace print() with Logging ✅
- [x] **File**: `app/__init__.py`
- [x] Configure Python `logging` module with `setup_logging()` function
- [x] Replace `print()` in request timing middleware with logger.debug/info/warning
- [x] Add log level configuration via `LOG_LEVEL` env var (DEBUG/INFO/WARNING/ERROR)
- [x] Add `LOG_FORMAT` env var support (colored or json)

### 2.3 Add Gunicorn Configuration
- [ ] Create `gunicorn.conf.py`:
  - workers = 4
  - bind = "0.0.0.0:5000"
  - timeout = 120
- [ ] Update `requirements.txt` with gunicorn
- [ ] Create `start.sh` script for production

### 2.4 Add Connection Pooling Config
- [ ] **File**: `app/config.py`
- [ ] Add `SQLALCHEMY_ENGINE_OPTIONS` with:
  - pool_size: 10
  - pool_recycle: 300
  - pool_pre_ping: True

---

## Phase 3: Performance Improvements

### 3.1 Add Missing Database Index
- [ ] **File**: `app/models.py`
- [ ] Add index: `db.Index('idx_pattern_list', 'status', 'detected_at')`
- [ ] Create migration script
- [ ] Run migration
- [ ] Verify with `EXPLAIN ANALYZE`

### 3.2 Optimize Portfolio Stats Query
- [ ] **File**: `app/routes/portfolio.py`
- [ ] Replace Python loops with SQL aggregation in `detail()`
- [ ] Replace Python loops with SQL aggregation in `api_portfolio_stats()`
- [ ] Test: Compare response times before/after

### 3.3 Optimize Pattern Detector DataFrame Loading
- [ ] **File**: `app/services/patterns/__init__.py`
- [ ] Modify `scan_all_patterns()` to load DataFrame once per symbol
- [ ] Pass DataFrame to each detector's `detect()` method
- [ ] Update detector signatures to accept optional DataFrame

---

## Phase 4: Code Quality

### 4.1 Add Test Coverage Reporting
- [ ] Install `pytest-cov`: `pip install pytest-cov`
- [ ] Add to pytest command: `--cov=app --cov-report=html`
- [ ] Run tests and check coverage percentage
- [ ] Target: 80% coverage

### 4.2 Add Type Hints to Critical Files
- [ ] **File**: `app/services/patterns/base.py` - Add missing hints
- [ ] **File**: `app/routes/api.py` - Add return type hints
- [ ] Run `mypy app/` to check

---

## Phase 5: Future Enhancements (Optional)

### PostgreSQL Migration (if scale requires)
- [ ] Only if SQLite becomes a bottleneck
- [ ] Install `psycopg2-binary`
- [ ] Update `DATABASE_URL` in config
- [ ] Consider TimescaleDB for candles table

### Pattern Improvements
- [ ] Swing-based pattern invalidation
- [ ] ATR-based expiry (more dynamic than time-based)
- [ ] Pattern ML scoring (train on historical fill rates)

### Real-time Features
- [ ] WebSocket for live price updates
- [ ] Real-time pattern notifications in UI
- [ ] Signal alerts without page refresh

### Multi-Exchange Support
- [ ] Abstract exchange interface
- [ ] Add Coinbase, Kraken, Bybit adapters
- [ ] Exchange selector in settings

---

## Progress Tracking

| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| 1.1 | API Auth | **Done** | Critical |
| 1.2 | Rate Limiting | **Done** | Critical |
| 1.3 | Input Validation | **Done** | Critical |
| 1.4 | CSRF Fix | **Done** | Critical |
| 2.1 | Health Check | **Done** | |
| 2.2 | Logging | **Done** | |
| 2.3 | Gunicorn | Pending | |
| 2.4 | Connection Pool | Pending | |
| 3.1 | DB Index | Pending | |
| 3.2 | Portfolio Query | Pending | |
| 3.3 | DataFrame Opt | Pending | |
| 4.1 | Test Coverage | Pending | |
| 4.2 | Type Hints | Pending | |

---

## Completed (Previous Work)

### Phase 6: Architecture (Dec 2025)
- [x] Cron-based scheduling (replaced APScheduler)
- [x] Async parallel fetch script (fetch.py)
- [x] Pattern detection script (detect.py)
- [x] Pattern expiry system (timeframe-based)
- [x] Stats page optimization (390→10 queries)
- [x] Patterns page optimization (8.4s → 53ms)
- [x] Pre-computed trading levels

### Phase 5: Code Quality
- [x] Type hints in key services
- [x] Configuration centralization
- [x] DRY pattern detector refactoring

### Phase 4: Portfolio & Journal
- [x] Portfolio management
- [x] Trade logging with journal entries
- [x] Performance analytics

### Phase 3: Testing
- [x] 164 tests passing
- [x] API, routes, services, patterns covered

### Phase 2: Performance
- [x] N+1 query fixes
- [x] Exchange instance caching
- [x] Direct SQL to DataFrame

### Phase 1: Security (Partial)
- [x] API key authentication (needs hardening)
- [x] CSRF protection (needs fix for settings)
- [x] Notification retry logic

### Core Features
- [x] Pattern detection (FVG, Order Block, Liquidity Sweep)
- [x] Multi-timeframe aggregation
- [x] Signal generation with confluence
- [x] NTFY notifications
- [x] Backtesting system

---

## Commands Reference

```bash
# Run tests with coverage
pytest --cov=app --cov-report=html

# Start with gunicorn (production)
gunicorn -c gunicorn.conf.py "app:create_app()"

# Check for security issues
pip install bandit && bandit -r app/

# Type checking
pip install mypy && mypy app/

# Test rate limiting
for i in {1..10}; do curl -X POST http://localhost:5000/api/scan; done
```
