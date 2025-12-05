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

### 2.3 Add Gunicorn Configuration ✅
- [x] Create `gunicorn.conf.py`:
  - workers = min(cpu_count * 2 + 1, 4) (capped for SQLite)
  - bind = "0.0.0.0:5000"
  - timeout = 120
- [x] Update `requirements.txt` with gunicorn (already present)
- [x] Create `start.sh` script for production

### 2.4 Add Connection Pooling Config ✅
- [x] **File**: `app/config.py`
- [x] Add `get_engine_options()` method that detects database type:
  - SQLite: timeout=30, pool_pre_ping=True
  - PostgreSQL/MySQL: pool_size=10, pool_recycle=300, pool_pre_ping=True, max_overflow=20

---

## Phase 3: Performance Improvements

### 3.1 Add Missing Database Index ✅
- [x] **File**: `app/models.py`
- [x] Add index: `db.Index('idx_pattern_list', 'status', 'detected_at')`
- [x] Create migration script: `scripts/migrate_add_pattern_index.py`

### 3.2 Optimize Portfolio Stats Query ✅
- [x] **File**: `app/routes/portfolio.py`
- [x] Replace Python loops with SQL aggregation in `api_portfolio_stats()`
- [x] Uses COUNT, SUM, CASE WHEN, GROUP BY for 2 queries instead of loading all trades

### 3.3 Optimize Pattern Detector DataFrame Loading ✅
- [x] **File**: `app/services/patterns/__init__.py`
- [x] Modify `scan_all_patterns()` to load DataFrame once per symbol/timeframe
- [x] Pass DataFrame to each detector's `detect()` method
- [x] Update detector signatures to accept optional DataFrame
- [x] Updated base.py, imbalance.py, order_block.py, liquidity.py

---

## Phase 4: Code Quality

### 4.1 Add Test Coverage Reporting ✅
- [x] Install `pytest-cov`: already available
- [x] Add to pytest command: `--cov=app --cov-report=html`
- [x] Run tests and check coverage percentage
- [x] Current coverage: 68% (below 80% target due to untested backtester/portfolio routes)
- [x] Coverage HTML report generated in `htmlcov/`

### 4.2 Add Type Hints to Critical Files ✅
- [x] **File**: `app/services/patterns/base.py` - Type hints already present
- [x] **File**: `app/routes/api.py` - Added return type hints to all endpoints
- [x] Installed mypy for type checking
- [x] Note: Existing code has implicit Optional patterns (pre-existing, not blocking)

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

### Redis Integration (for scaling)
- [ ] Install `redis`: `pip install redis`
- [ ] Configure `REDIS_URL` env var (default: `redis://localhost:6379/0`)
- [ ] **File**: `app/__init__.py` - Update limiter storage backend:
  ```python
  from flask_limiter.util import get_remote_address
  limiter = Limiter(
      key_func=get_remote_address,
      storage_uri=os.getenv('REDIS_URL', 'memory://')
  )
  ```
- [ ] Add Redis for session storage (optional)
- [ ] Add Redis for caching pattern results (optional)
- [ ] Docker Compose service for Redis

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
| 2.3 | Gunicorn | **Done** | |
| 2.4 | Connection Pool | **Done** | |
| 3.1 | DB Index | **Done** | |
| 3.2 | Portfolio Query | **Done** | |
| 3.3 | DataFrame Opt | **Done** | |
| 4.1 | Test Coverage | **Done** | 68% coverage |
| 4.2 | Type Hints | **Done** | api.py typed |

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
