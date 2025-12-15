# CryptoLens - Audit Findings & Future Enhancements

> **Audit Date**: December 15, 2025
> **Current Version**: v2.1.0
> **Issues Found**: 85+

---

## CRITICAL SEVERITY (Fix Immediately)

### Security: Authentication & Authorization

- [x] **Missing `@login_required` on portfolio routes** - `app/routes/portfolio.py` ✅ FIXED
  - Added `@login_required` decorator to all 7 endpoints
  - Added ownership validation (`portfolio.user_id != user.id`)

- [x] **Unauthenticated signal status modification** - `app/routes/signals.py:73` ✅ FIXED
  - Added `@login_required` decorator
  - Added status whitelist validation

- [x] **Unauthenticated test notification** - `app/routes/settings.py:138` ✅ FIXED
  - Added `@login_required` decorator

- [ ] **Unauthenticated data endpoints** - `app/routes/api.py`
  - Line 160: `/symbols` - no auth
  - Line 171: `/candles/<symbol>/<timeframe>` - no auth
  - Line 188: `/patterns` - no auth
  - Line 213: `/signals` - no auth
  - Line 239: `/matrix` - no auth
  - Consider adding `@login_required` or API key requirement

### Security: Cryptography

- [x] **Hardcoded encryption salt** - `app/services/encryption.py` ✅ FIXED
  - Now reads from `ENCRYPTION_SALT` environment variable
  - Raises `EncryptionConfigError` in production if not set
  - Development fallback only for testing

- [x] **Insecure encryption key fallback** - `app/services/encryption.py` ✅ FIXED
  - Now raises `EncryptionConfigError` in production if `SECRET_KEY` not set
  - Development fallback only for testing

### Security: Injection

- [x] **SQL injection in migration script** - `scripts/init_db.py` ✅ FIXED
  - Added `ALLOWED_TABLES` frozenset whitelist
  - Added `validate_table_name()` function

### Documentation: CLI Scripts

- [x] **fetch.py has no documented arguments** ✅ FIXED
  - Added Usage and Options sections documenting `--verbose` and `--gaps`

- [x] **init_db.py documentation** ✅ FIXED
  - Updated with proper usage examples

- [x] **compute_stats.py has no argparse** ✅ FIXED
  - Added argparse with `--verbose` option

- [x] **fetch_historical.py missing arguments** ✅ FIXED
  - Added all 8 options to documentation

- [x] **db_health.py missing arguments** ✅ FIXED
  - Added `--quiet` and `--clear-gaps` to documentation

---

## HIGH SEVERITY (Fix This Week)

### Security: HTTP & Webhooks

- [x] **Missing HTTP timeouts** - `app/services/payment.py` ✅ FIXED
  - Added `timeout=30` to all 3 `requests.*` calls
  - Fixed bare except clause in `get_available_cryptos()`

- [x] **Webhook validation bypass** - `app/services/payment.py:162` ✅ ALREADY FIXED
  - Already returns `False` when secret not configured

- [x] **Missing CSRF on key operations** - `app/routes/docs.py` ✅ ALREADY FIXED
  - CSRF tokens already in templates (`api/index.html`)
  - Blueprint not exempt from global CSRF protection

### Security: Input Validation

- [x] **Unvalidated date input** - `app/routes/admin.py` ✅ FIXED
  - Added `datetime.strptime()` validation for YYYY-MM-DD format

- [x] **Unvalidated status field** - `app/routes/signals.py` ✅ FIXED (CRITICAL)
  - Already fixed in critical fixes with `VALID_SIGNAL_STATUSES` whitelist

- [x] **Unvalidated pattern type** - `app/routes/backtest.py` ✅ FIXED
  - Added whitelist validation using `PATTERN_TYPES`

- [x] **Missing input length limits** - `app/routes/admin.py` ✅ FIXED
  - Added length validation to `create_template()` and `edit_template()`
  - Validates: name (100), template_type (20), title (200), message (10000), tags (100)

- [x] **Integer bounds not checked** - Multiple locations ✅ FIXED
  - `app/routes/api.py` - candles limit (1-2000), patterns limit (1-1000)
  - `app/routes/logs.py` - limit (1-1000), offset (>=0)
  - `app/routes/patterns.py` - limit (1-2000)

### Performance: N+1 Queries

- [x] **Dashboard analytics loop** - `app/routes/dashboard.py` ✅ FIXED
  - Replaced loop with single aggregation query using `group_by()`

- [x] **Signal enrichment loop** - `app/routes/signals.py` ✅ FIXED
  - Replaced N+1 with bulk fetch using `Symbol.id.in_()` and `Pattern.id.in_()`

- [x] **Pattern type statistics** - `app/routes/dashboard.py` ✅ FIXED
  - Replaced loop with single `group_by(Pattern.pattern_type)` query

- [ ] **Dashboard matrix building** - `app/routes/dashboard.py:43-57`
  - 30 queries (5 symbols × 6 timeframes)
  - Consider batch query with single JOIN (lower priority)

### Documentation: Missing CLI Arguments

- [x] **fetch_historical.py missing arguments** ✅ FIXED (CRITICAL)
  - All 8 options documented in docstring

- [x] **db_health.py missing arguments** ✅ FIXED (CRITICAL)
  - `--quiet` and `--clear-gaps` documented in docstring

---

## MEDIUM SEVERITY (Fix This Month)

### Error Handling: Bare Exceptions

- [x] **Bare except handlers** - Multiple locations ✅ FIXED
  - `app/jobs/notifications.py:76` - Changed to specific exceptions
  - `app/services/notifier.py:184` - Changed to specific exceptions
  - `app/services/notifier.py:506` - Changed to specific exceptions

- [x] **Silent exception swallowing** - `scripts/fetch.py` ✅ FIXED
  - Added verbose logging for aggregation, pattern detection, and status update errors

### Database: Missing Indexes

- [x] **Add indexes to frequently queried fields** ✅ FIXED
  - Symbol: `idx_symbol_is_active`
  - Pattern: `idx_pattern_direction`, `idx_pattern_type`
  - User: `idx_user_admin`
  - Subscription: `idx_subscription_user_status`
  - Trade: `idx_trade_signal`

### Database: Transaction Issues

- [x] **Missing rollback in subscription operations** - `app/routes/admin.py` ✅ FIXED
  - Added try-except with `db.session.rollback()` for subscription operations

- [x] **Partial commits in bulk operations** - `app/routes/admin.py` ✅ FIXED
  - Added try-except with `db.session.rollback()` for bulk user actions

### API: Response Consistency

- [ ] **Standardize JSON response format** - All API routes
  - Current: Mix of `{data}`, `{success, data}`, `{error}`, `{success, error}`
  - Target: `{success: bool, data?: any, error?: string}`

### Security: Rate Limiting

- [x] **Missing rate limits on admin operations** - `app/routes/admin.py` ✅ FIXED
  - Added rate limits to: bulk-action, make-admin, revoke-admin, subscription, create-user, broadcast, bulk-symbols

### Security: Email Enumeration

- [ ] **Timing side-channel on auth endpoints** - `app/routes/auth.py`
  - Lines 415-417: `/resend-verification`
  - Lines 445-446: `/forgot-password`
  - Add consistent response delay (~500ms)

### Resource Management

- [ ] **Unclosed exchange singleton** - `app/services/data_fetcher.py:21-41`
  - Exchange instance never explicitly closed
  - Add cleanup method or use context manager

### Cascade Delete Gaps

- [ ] **Payment orphans on User delete** - `app/models/system.py:160`
  - No cascade defined for User → Payment relationship
  - Add `cascade='all, delete-orphan'`

- [ ] **Signal orphans on Pattern delete** - `app/models/trading.py:220`
  - No cascade defined for Pattern → Signal relationship
  - Add `cascade='all, delete-orphan'`

---

## LOW SEVERITY (Nice to Have)

### Documentation

- [ ] **Add docstrings to 40+ undocumented endpoints**
  - `app/routes/api.py` - 5 GET endpoints
  - `app/routes/patterns.py` - chart endpoint
  - `app/routes/dashboard.py` - analytics endpoint

### Code Quality

- [ ] **Timestamp field inconsistency**
  - `Candle.timestamp` - BigInteger (ms)
  - `Pattern.detected_at` - BigInteger (ms)
  - `Signal.created_at` - DateTime object
  - Consider standardizing

- [ ] **Duplicate relationship definition** - `app/models/trading.py`
  - Line 214: Pattern → Signal backref
  - Line 220: Signal → Pattern backref
  - Remove duplicate

---

## Automated Checks to Add

```yaml
# .github/workflows/security.yml
- name: Bandit Security Scan
  run: bandit -r app/ -ll

- name: Check for bare exceptions
  run: |
    if grep -rn "except:" app/ scripts/ --include="*.py" | grep -v "except.*:"; then
      echo "Found bare except clauses"
      exit 1
    fi

- name: Check for missing timeouts
  run: |
    if grep -rn "requests\.\(get\|post\)" app/ --include="*.py" | grep -v timeout; then
      echo "Found requests without timeout"
      exit 1
    fi

- name: Check for f-string SQL
  run: |
    if grep -rn 'execute(f"' scripts/ --include="*.py"; then
      echo "Found potential SQL injection"
      exit 1
    fi
```

---

## Future Enhancements

### Trading Features
- [ ] Breaker Block detection
- [ ] Mitigation Block detection
- [ ] Equal Highs/Lows detection
- [ ] ATR-based pattern expiry
- [ ] Pattern ML scoring

### Automatic Trading
- [ ] Exchange API connection (read-only first)
- [ ] Position sizing based on risk parameters
- [ ] Stop-loss and take-profit automation

### Infrastructure
- [ ] WebSocket for live price updates
- [ ] Real-time pattern notifications in UI
- [ ] Multi-exchange support (Coinbase, Kraken, Bybit)

### Mobile & Integrations
- [ ] iOS/Android app (React Native or Flutter)
- [ ] Discord bot
- [ ] Telegram bot

### SEO & Marketing
- [ ] Meta tags (description, keywords, OpenGraph)
- [ ] sitemap.xml
- [ ] robots.txt
- [ ] Structured data (JSON-LD)

---

## Commands Reference

```bash
# Run tests with coverage
pytest --cov=app --cov-report=html

# Find bare exceptions
grep -rn "except:" app/ scripts/ --include="*.py"

# Find missing timeouts
grep -rn "requests\.\(get\|post\|put\|delete\)" app/ --include="*.py" | grep -v timeout

# Find f-string SQL
grep -rn 'execute(f"' scripts/ --include="*.py"

# Check for hardcoded secrets
grep -rn "secret\|password\|api_key" app/ --include="*.py" | grep -v "get\|environ\|config"

# Security scan
pip install bandit && bandit -r app/

# Type checking
pip install mypy && mypy app/
```
