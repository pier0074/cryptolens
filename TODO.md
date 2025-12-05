# CryptoLens v2.0 - Development Roadmap

> **Current Version**: v2.0.0 (Released 2025-12-05)
> **Status**: All core phases complete, Phase 5 contains optional enhancements

---

## v2.0 Roadmap

| Version | Focus | Status |
|---------|-------|--------|
| v2.0.0 | API Auth + Rate Limiting | **Done** |
| v2.1.0 | Input Validation + CSRF Fix | **Done** |
| v2.2.0 | Health Check + Logging | **Done** |
| v2.3.0 | Gunicorn + Connection Pooling | **Done** |
| v2.4.0 | Performance (DB Index, Query Opt) | **Done** |
| v2.5.0 | Code Quality (Coverage, Types) | **Done** |

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

### Symbol/Currency Management (Settings)
- [ ] Add symbols management page in Settings
- [ ] **File**: `app/routes/settings.py` - Add symbol CRUD endpoints
- [ ] **File**: `app/templates/settings.html` - Add symbol selector UI:
  - List all symbols with active/inactive toggle
  - Search bar to find symbols from exchange
  - Add new symbol button (fetches from Binance)
  - Delete symbol (with confirmation)
- [ ] Symbol model already has `is_active` field - use it
- [ ] Update `fetch.py` to only fetch active symbols

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

## Progress Summary

All phases 1-4 complete. Test coverage at 68%.

| Phase | Focus | Tasks |
|-------|-------|-------|
| 1 | Security | API Auth, Rate Limiting, Input Validation, CSRF |
| 2 | Production | Health Check, Logging, Gunicorn, Connection Pool |
| 3 | Performance | DB Index, Portfolio Query, DataFrame Optimization |
| 4 | Quality | Test Coverage (68%), Type Hints |
| 5 | Future | Optional enhancements (see above) |

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
