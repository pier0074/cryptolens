# CryptoLens Action Plan (Post-Audit)

Generated from Security & Architecture Audit on December 6, 2025.

---

## PHASE 1: CRITICAL SECURITY FIXES (Before Any Production Use)

### P1.1 Session Security [BLOCKING] ✅ DONE
- [x] Add secure session configuration to `app/__init__.py`
  ```python
  SESSION_COOKIE_SECURE=True  # HTTPS only
  SESSION_COOKIE_HTTPONLY=True  # No JS access
  SESSION_COOKIE_SAMESITE='Lax'
  PERMANENT_SESSION_LIFETIME=timedelta(days=7)
  ```
- [ ] Regenerate session ID after successful login (session fixation prevention)
- [ ] Add session timeout/inactivity logout

**Files:** `app/__init__.py`

---

### P1.2 Password Reset Validation [HIGH] ✅ DONE
- [x] Fix password reset to use `validate_password()` instead of length check only
- [x] Import and call auth service validation in reset route

**Files:** `app/routes/auth.py:394-416`

---

### P1.3 Hash API Keys [HIGH] ✅ DONE
- [x] Create `hash_api_key()` and `verify_api_key()` functions
- [x] Modify Setting storage to use `api_key_hash` instead of `api_key`
- [x] Update API key verification in `app/routes/api.py`
- [ ] Add migration to hash existing API keys (not needed - new keys are hashed on save)

**Files:** `app/services/auth.py`, `app/routes/api.py`, `app/routes/settings.py`

---

### P1.4 Account Lockout [MEDIUM] ✅ DONE
- [x] Add `failed_attempts` and `locked_until` columns to User model
- [x] Create `app/services/lockout.py` with:
  - `record_failed_attempt(email)`
  - `is_locked(email)`
  - `clear_lockout(user)`
- [x] Integrate into login route
- [ ] Add admin UI to unlock accounts (optional enhancement)

**Files:** `app/models.py`, `app/services/lockout.py`, `app/routes/auth.py`

---

### P1.5 Encrypt TOTP Secrets [MEDIUM] ✅ DONE
- [x] Add `cryptography` to requirements.txt
- [x] Create encryption utilities for at-rest encryption (`app/services/encryption.py`)
- [x] Encrypt TOTP secrets before storage
- [x] Decrypt on verification (with legacy fallback)
- [x] Add migration to encrypt existing secrets

**Files:** `app/models.py`, `app/services/encryption.py`, `requirements.txt`

---

### P1.6 Fix CSRF Exemptions [MEDIUM] ✅ DONE
- [x] Remove blanket CSRF exemption from payments blueprint
- [x] Only exempt webhook endpoints (using @csrf.exempt decorator)
- [x] Test checkout flows still work (321 tests pass)

**Files:** `app/__init__.py`, `app/routes/payments.py`

---

## PHASE 2: INFRASTRUCTURE IMPROVEMENTS ✅ COMPLETE

### P2.1 PostgreSQL Migration [BLOCKING for Scale] ✅ DONE
- [x] Add PostgreSQL to requirements.txt (`psycopg2-binary`)
- [x] Update config to warn if SQLite used in production
- [x] Connection pooling already configured (pool_size=10, max_overflow=20)
- [ ] Create Alembic migrations for schema (optional - using migrate_all.py)
- [ ] Update README with PostgreSQL setup instructions

**Files:** `requirements.txt`, `app/config.py`

---

### P2.2 Redis Caching Layer ✅ DONE
- [x] Add `redis` and `flask-caching` to requirements.txt
- [x] Create cache configuration (falls back to SimpleCache if no Redis)
- [x] Cache pattern matrix (1 minute TTL)
- [ ] Cache stats/analytics (5 minute TTL) - future enhancement
- [ ] Cache user tier info - future enhancement

**Files:** `requirements.txt`, `app/config.py`, `app/__init__.py`, `app/routes/api.py`

---

### P2.3 Connection Pooling ✅ DONE (Already Configured)
- [x] SQLAlchemy pool settings for PostgreSQL already in config.py
- [x] pool_size=10, pool_recycle=300, max_overflow=20
- [x] pool_pre_ping=True for connection validation

**Files:** `app/config.py`

---

### P2.4 Circuit Breakers ✅ DONE
- [x] Add `pybreaker` to requirements.txt
- [x] Wrap NTFY notification calls with circuit breaker
- [ ] Wrap CCXT exchange calls - future enhancement
- [ ] Wrap payment provider calls - future enhancement

**Files:** `requirements.txt`, `app/services/notifier.py`

---

## PHASE 3: CODE QUALITY REFACTORING

### P3.1 Split models.py (1417 lines → 4 files)
- [ ] Create `app/models/__init__.py` (exports all models)
- [ ] Create `app/models/user.py`:
  - User
  - Subscription
  - UserNotification
- [ ] Create `app/models/trading.py`:
  - Symbol
  - Candle
  - Pattern
  - Signal
  - Notification
- [ ] Create `app/models/portfolio.py`:
  - Portfolio
  - Trade
  - TradeTag
  - JournalEntry
- [ ] Create `app/models/system.py`:
  - Setting
  - Log
  - StatsCache
  - CronJob
  - CronRun
  - Payment
  - Backtest
- [ ] Update all imports across codebase
- [ ] Run tests to verify no regressions

**Files:** `app/models/`

---

### P3.2 Remove Duplicate Code ✅ DONE
- [x] Remove duplicate `login_required` from `app/routes/payments.py`
- [x] Use central `app/decorators.py` version everywhere
- [x] Consolidate `get_current_user()` implementations:
  - `app/decorators.py` (canonical version)
  - `app/routes/main.py` (removed, now imports from decorators)
  - `app/routes/payments.py` (removed, now imports from decorators)
  - `app/routes/auth.py` (already using services/auth version)

**Files:** `app/routes/payments.py`, `app/routes/main.py`

---

### P3.3 Standardize Error Handling
- [ ] Create `app/exceptions.py` with domain exceptions:
  - `AuthenticationError`
  - `AuthorizationError`
  - `ValidationError`
  - `NotFoundError`
- [ ] Create error handlers in `app/__init__.py`
- [ ] Convert services to raise domain exceptions
- [ ] Remove mixed return types (tuple vs exception)

**Files:** `app/exceptions.py`, `app/__init__.py`, `app/services/`

---

### P3.4 Replace Print with Logging
- [ ] Search for all `print(` statements
- [ ] Replace with `logger.debug/info/warning/error`
- [ ] Add context (symbol, timeframe, etc.) to log messages
- [ ] Ensure structured logging format

**Files:** `app/services/`, `scripts/`

---

### P3.5 Extract Magic Numbers
- [ ] Create `app/constants.py` for:
  - Rate limits
  - Timeouts
  - Thresholds
  - Retry counts
- [ ] Replace hardcoded values across codebase
- [ ] Document each constant

**Files:** `app/constants.py`, various

---

## PHASE 4: PERFORMANCE OPTIMIZATION ✅ COMPLETE

### P4.1 Fix N+1 Queries ✅ DONE
- [x] Add `joinedload` to pattern queries in `app/routes/api.py` (done in Phase 2)
- [x] Optimize eligible subscribers query in `app/services/notifier.py` and `app/services/auth.py`
- [ ] Add query logging in development - future enhancement
- [ ] Profile endpoints with SQLAlchemy profiler - future enhancement

**Files:** `app/routes/api.py`, `app/services/notifier.py`, `app/services/auth.py`

---

### P4.2 Optimize Context Processor ✅ DONE
- [x] Cache `last_data_update` using Flask-Caching (60s TTL)
- [x] Avoids DB query on every request
- [ ] AJAX lazy-load - future enhancement

**Files:** `app/__init__.py`

---

### P4.3 Async Notifications
- [ ] Use `asyncio.gather` for sending to multiple subscribers
- [ ] Add connection pooling for HTTP requests
- [ ] Consider background worker for notifications

**Files:** `app/services/notifier.py`

---

### P4.4 Background Job Queue
- [ ] Add Celery or RQ for background tasks
- [ ] Move pattern scanning to background
- [ ] Move notifications to background
- [ ] Add job monitoring/retry

**Files:** `workers/`, `requirements.txt`

---

## PHASE 5: OBSERVABILITY & OPERATIONS

### P5.1 Structured Logging
- [ ] Add JSON logging format for production
- [ ] Include request ID in all logs
- [ ] Add performance metrics logging
- [ ] Configure log aggregation (ELK/Datadog)

**Files:** `app/__init__.py`, `app/services/logger.py`

---

### P5.2 Metrics & Monitoring
- [ ] Add Prometheus metrics endpoint
- [ ] Track:
  - Request latency
  - Error rates
  - Pattern detection count
  - Active users
  - Database connection pool
- [ ] Add Grafana dashboards

**Files:** `app/routes/metrics.py`, `docker-compose.yml`

---

### P5.3 Health Checks ✅ DONE
- [x] Expand `/api/health` to check:
  - Database connectivity
  - Cache/Redis connectivity
  - Status: healthy/degraded/unhealthy
- [ ] Add Exchange API reachability check - future enhancement
- [ ] Add NTFY reachability check - future enhancement
- [ ] Add readiness vs liveness endpoints - future enhancement
- [ ] Add dependency health in response

**Files:** `app/routes/api.py`

---

### P5.4 Error Tracking
- [ ] Add Sentry integration
- [ ] Configure error grouping
- [ ] Add user context to errors
- [ ] Set up alerting for critical errors

**Files:** `app/__init__.py`, `requirements.txt`

---

## PHASE 6: DOCUMENTATION & TESTING

### P6.1 API Documentation
- [ ] Add OpenAPI/Swagger spec
- [ ] Document all endpoints
- [ ] Add request/response examples
- [ ] Generate API docs site

**Files:** `docs/api/`, `app/routes/`

---

### P6.2 Architecture Documentation
- [ ] Create architecture decision records (ADRs)
- [ ] Document data flow diagrams
- [ ] Document deployment architecture
- [ ] Create runbook for common operations

**Files:** `docs/architecture/`

---

### P6.3 Security Testing
- [ ] Add security-focused tests:
  - [ ] CSRF protection
  - [ ] Session security
  - [ ] Rate limiting
  - [ ] Auth bypass attempts
- [ ] Run OWASP ZAP scan
- [ ] Add to CI pipeline

**Files:** `tests/security/`

---

### P6.4 Load Testing
- [ ] Create Locust load test scripts
- [ ] Test concurrent user scenarios
- [ ] Test pattern detection under load
- [ ] Establish performance baselines

**Files:** `tests/load/`

---

## Priority Summary

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | Session Security | 2h | Critical |
| P0 | Password Reset Fix | 30m | Critical |
| P0 | API Key Hashing | 2h | High |
| P1 | Account Lockout | 3h | High |
| P1 | CSRF Fix | 1h | Medium |
| P1 | Credential Cleanup | 1h | High |
| P2 | PostgreSQL | 4h | Blocking |
| P2 | Redis Caching | 4h | High |
| P3 | Split models.py | 3h | Medium |
| P3 | Remove Duplicates | 2h | Medium |
| P4 | Fix N+1 | 2h | High |
| P5 | Monitoring | 8h | Medium |

---

## Definition of Done

Each task is complete when:
1. Code changes implemented
2. Unit tests added/updated
3. Integration tests pass
4. Security review (for P0/P1)
5. Documentation updated
6. Code review approved
7. Merged to main branch

---

## Notes

- All P0 tasks must be completed before any production deployment
- P1 tasks should be completed within first sprint
- P2/P3 can run in parallel
- P4/P5 are ongoing improvements
- Consider feature flags for gradual rollout
