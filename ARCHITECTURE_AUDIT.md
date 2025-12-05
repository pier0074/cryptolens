# CryptoLens Architecture Audit Report

**Date**: 2025-12-05
**Auditor**: Claude Code
**Codebase**: Flask 3.0 + SQLAlchemy 3.1 + SQLite

---

## SECTION A — CRITICAL ISSUES (Must-Fix)

### 1. **API Authentication is Optional** (`app/routes/api.py:18-23`)
```python
# CURRENT (BAD): API is completely open if no key is configured
api_key = Setting.get('api_key')
if not api_key:
    # No API key configured - allow access (for development)
    return f(*args, **kwargs)
```
**Impact**: Any external attacker can trigger scans, fetch data, start/stop scheduler.
**Fix**: Default to DENY, require explicit `ALLOW_UNAUTHENTICATED_API=true` env var for dev.

### 2. **No Input Validation/Sanitization** (`app/routes/portfolio.py:41-43`)
```python
# CURRENT (BAD): Direct float conversion, no bounds checking
initial_balance=float(data.get('initial_balance', 10000)),
entry_price=float(data.get('entry_price')),
```
**Impact**: ValueError crashes, potential for negative balances, scientific notation injection.
**Fix**: Use a validation library (WTForms or Marshmallow) with min/max bounds.

### 3. **No Rate Limiting on Any Endpoint**
The entire API is unprotected against abuse. A single client can:
- Exhaust database connections
- Trigger unlimited pattern scans
- DOS the application

**Fix**: Add `flask-limiter` with per-IP and per-endpoint limits.

### 4. **Settings Blueprint CSRF Exemption** (`app/__init__.py:129`)
```python
csrf.exempt(settings_bp)
```
**Impact**: Settings page (likely contains API key management) vulnerable to CSRF attacks.
**Fix**: Remove this exemption. Use AJAX with proper CSRF token handling.

### 5. **SQLite with 3.1GB Database - Single-Threaded Writes**
SQLite locks the entire database on writes. With 20M+ candles and continuous fetching, you will hit lock contention under load.

**Fix**: Migrate to PostgreSQL for production, or implement read replicas.

---

## SECTION B — HIGH-VALUE IMPROVEMENTS

### 1. **Missing Database Indexes** (`app/models.py`)
```python
# MISSING: Index for common queries
# Patterns page filters by status + orders by detected_at
# Current index: idx_pattern_active (symbol_id, timeframe, status)
# Missing: (status, detected_at DESC) for the patterns list page

# Add to Pattern model:
db.Index('idx_pattern_list', 'status', 'detected_at')
```

### 2. **Portfolio Routes Have N+1 Queries** (`app/routes/portfolio.py:109-111`)
```python
# CURRENT (BAD): Loads all closed trades, then iterates
closed_trades = portfolio.trades.filter_by(status='closed').all()
winning_trades = [t for t in closed_trades if t.pnl_amount and t.pnl_amount > 0]
```
**Fix**: Use SQL aggregation:
```python
from sqlalchemy import func, case
stats = db.session.query(
    func.count(Trade.id).label('total'),
    func.sum(case((Trade.pnl_amount > 0, 1), else_=0)).label('wins'),
    func.sum(Trade.pnl_amount).filter(Trade.pnl_amount > 0).label('gross_profit')
).filter(Trade.portfolio_id == portfolio_id, Trade.status == 'closed').first()
```

### 3. **Duplicate DataFrame Loading in Pattern Detectors**
Each detector calls `get_candles_df()` independently. When scanning all patterns for a symbol, the same DataFrame is loaded multiple times.

**Fix**: Pass DataFrame to detectors, don't let them fetch independently.

### 4. **Console Logging Instead of Proper Logging** (`app/__init__.py:103`)
```python
print(f"{color}[{elapsed_ms:7.1f}ms]{reset}...")  # BAD: stdout, not configurable
```
**Fix**: Use Python's `logging` module with structured output.

### 5. **No Connection Pooling Configuration**
SQLAlchemy defaults are not optimized for production.
```python
# Add to config:
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 300,
    'pool_pre_ping': True,
}
```

---

## SECTION C — RECOMMENDED ARCHITECTURE

### Current Architecture (Acceptable for MVP)
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Cron      │────▶│   Flask     │────▶│   SQLite    │
│   Scripts   │     │   (Werkzeug)│     │   (3.1GB)   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   CCXT      │
                    │   (Binance) │
                    └─────────────┘
```

### Recommended Architecture (Production)
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Redis     │◀───▶│   Gunicorn  │────▶│  PostgreSQL │
│   (Cache)   │     │   (4 workers)│    │  (TimescaleDB)│
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │
       │            ┌──────┴──────┐
       │            ▼             ▼
       │     ┌───────────┐  ┌───────────┐
       └────▶│  Celery   │  │   Nginx   │
             │  (Queue)  │  │  (Reverse)│
             └───────────┘  └───────────┘
```

**Key Changes:**
1. **PostgreSQL + TimescaleDB**: Purpose-built for time-series data (candles)
2. **Redis**: Session storage, rate limiting, cache invalidation
3. **Celery**: Move scan/fetch jobs off cron into a proper task queue
4. **Nginx**: Static files, SSL termination, rate limiting at edge

---

## SECTION D — CODE REWRITES (Explicit)

### D1. Fix API Authentication Default
```python
# app/routes/api.py - REPLACE lines 14-34

import hmac
import os

def require_api_key(f):
    """Decorator to require API key for sensitive endpoints"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if auth is explicitly disabled (dev only)
        if os.getenv('ALLOW_UNAUTHENTICATED_API', 'false').lower() == 'true':
            return f(*args, **kwargs)

        api_key = Setting.get('api_key')
        if not api_key:
            return jsonify({'error': 'API not configured. Set api_key in settings.'}), 503

        provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not provided_key or not hmac.compare_digest(provided_key, api_key):
            return jsonify({'error': 'Unauthorized'}), 401

        return f(*args, **kwargs)
    return decorated
```

### D2. Add Input Validation to Portfolio
```python
# app/routes/portfolio.py - ADD after imports

from wtforms import Form, FloatField, StringField, validators

class TradeForm(Form):
    symbol = StringField('Symbol', [validators.Length(min=3, max=20)])
    entry_price = FloatField('Entry Price', [validators.NumberRange(min=0.00000001)])
    entry_quantity = FloatField('Quantity', [validators.NumberRange(min=0.00000001)])
    stop_loss = FloatField('Stop Loss', [validators.Optional(), validators.NumberRange(min=0)])

# THEN in new_trade():
form = TradeForm(request.form)
if not form.validate():
    return render_template('portfolio/trade_form.html', errors=form.errors, ...)
```

### D3. Add Rate Limiting
```python
# app/__init__.py - ADD after imports

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])

# In create_app():
limiter.init_app(app)

# app/routes/api.py - ADD to expensive endpoints
@api_bp.route('/scan', methods=['POST'])
@limiter.limit("1 per minute")
@require_api_key
def trigger_scan():
    ...
```

### D4. Replace print() with logging
```python
# app/__init__.py - REPLACE request timing middleware

import logging

def create_app(config_name=None):
    # ... existing code ...

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler()]
    )
    logger = logging.getLogger(__name__)

    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            elapsed_ms = (time.time() - g.start_time) * 1000
            logger.info(f"{request.method} {request.path} {response.status_code} {elapsed_ms:.1f}ms")
        return response
```

### D5. Add Health Check Endpoint
```python
# app/routes/api.py - ADD new endpoint

@api_bp.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Test database connection
        db.session.execute(db.text('SELECT 1'))
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': int(time.time() * 1000)
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 503
```

---

## SECTION E — PERFORMANCE GAINS

| Issue | Current | After Fix | Improvement |
|-------|---------|-----------|-------------|
| Patterns page | 8.4s → 53ms (already fixed) | - | 158x |
| Portfolio stats | O(n) Python loops | SQL aggregation | ~10x |
| Pattern scanning | Duplicate DataFrame loads | Shared DataFrame | 2-3x |
| Index for pattern list | Full table scan | Index scan | 5-20x |
| Connection pooling | Default (5) | Configured (10+ping) | Reduces timeouts |

**Estimated Total Page Load Improvement**: Additional 30-50% reduction on data-heavy pages after SQL aggregation fixes.

---

## SECTION F — SECURITY EVALUATION SCORE

| Category | Score | Notes |
|----------|-------|-------|
| Authentication | 3/10 | API auth optional, no session expiry |
| Authorization | 5/10 | No role-based access, but single-user app |
| Input Validation | 3/10 | No validation library, raw float() casts |
| CSRF Protection | 6/10 | Present but exempted on settings |
| Rate Limiting | 0/10 | None |
| SQL Injection | 9/10 | ORM used correctly, no raw SQL in user paths |
| XSS | 7/10 | Jinja2 auto-escapes, but check custom filters |
| Secrets Management | 5/10 | SECRET_KEY generated, but stored in file |
| Dependencies | 7/10 | Modern Flask/SQLAlchemy versions |

**SECURITY SCORE: 5/10**

Critical gaps: Rate limiting, API auth defaults, input validation.

---

## SECTION G — PRODUCTION SCORE

| Category | Score | Notes |
|----------|-------|-------|
| Web Server | 3/10 | Werkzeug dev server, no gunicorn config |
| Database | 4/10 | SQLite works but doesn't scale |
| Caching | 7/10 | StatsCache implemented well |
| Logging | 3/10 | print() statements, no structured logging |
| Error Handling | 5/10 | Some try/except, no global handler |
| Health Checks | 0/10 | No /health endpoint |
| Monitoring | 0/10 | No metrics, no APM |
| Deployment | 4/10 | Manual scripts, no Docker |
| Configuration | 6/10 | Environment-based config exists |
| Documentation | 5/10 | Docstrings present but incomplete |

**PRODUCTION SCORE: 4/10**

Must-haves before production: Gunicorn, health check, structured logging, PostgreSQL.

---

## SECTION H — TESTING SCORE

| Category | Score | Notes |
|----------|-------|-------|
| Unit Tests | 7/10 | 164 tests, good service coverage |
| Integration Tests | 6/10 | Route tests present |
| E2E Tests | 0/10 | None |
| Test Isolation | 7/10 | Appears to use test DB |
| Fixtures | 6/10 | Basic fixtures present |
| Coverage | ?/10 | No coverage report configured |
| Mocking | 6/10 | CCXT calls should be mocked |

**TESTING SCORE: 5/10**

Good foundation. Add coverage reporting and E2E tests.

---

## SECTION I — FINAL ENGINEERING SUMMARY

### What's Done Well
1. **Clean Architecture**: App factory, blueprints, services layer - proper separation
2. **Pattern Abstraction**: `PatternDetector` base class is well-designed
3. **Recent Performance Work**: Pre-computed trading levels, StatsCache, pagination
4. **Domain Logic**: Trading calculations in `trading.py` are professionally implemented
5. **WAL Mode**: Correct SQLite configuration for concurrency

### Critical Path to Production
1. **Phase 1**: Add rate limiting, fix API auth defaults, add input validation
2. **Phase 2**: Add health check, replace print() with logging, add gunicorn config
3. **Phase 3**: Add coverage reporting to tests
4. **Phase 4+**: Migrate to PostgreSQL if scale requires it

### Technical Debt Estimate
- Security fixes: 2-3 days
- Logging/monitoring: 1-2 days
- PostgreSQL migration: 3-5 days (if needed)

### Verdict
This is a **competent MVP** with solid domain logic but significant security and operational gaps. The pattern detection and trading calculation code is production-quality. The infrastructure around it is development-quality.

**Not ready for production as-is.** With 1-2 weeks of focused work on the critical issues above, it can be deployed safely for a single-user or small-team scenario.
