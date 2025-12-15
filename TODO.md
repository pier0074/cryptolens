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
  - Using parameterized query for SQLite table existence check

### Documentation: CLI Scripts

- [x] **fetch.py has no documented arguments** ✅ FIXED
  - Added Usage and Options sections documenting `--verbose` and `--gaps`

- [x] **init_db.py --migrate missing path argument** ✅ FIXED
  - Updated to show: `python scripts/init_db.py --migrate /path/to/db.sqlite`

- [x] **compute_stats.py has no argparse** ✅ FIXED
  - Added argparse with `--verbose` option

- [x] **fetch_historical.py missing arguments** ✅ FIXED
  - Added all 8 options to documentation

- [x] **db_health.py missing arguments** ✅ FIXED
  - Added `--quiet` and `--clear-gaps` to documentation

---

## HIGH SEVERITY (Fix This Week)

### Security: HTTP & Webhooks

- [ ] **Missing HTTP timeouts** - `app/services/payment.py`
  - Line 77: LemonSqueezy checkout - no timeout
  - Line 275: NOWPayments invoice - no timeout
  - Line 549: NOWPayments currencies - no timeout + bare except
  - Add `timeout=30` to all `requests.*` calls

- [ ] **Webhook validation bypass** - `app/services/payment.py:162`
  ```python
  if not LEMONSQUEEZY_WEBHOOK_SECRET:
      log_system("WARNING...")
      # Missing return! Execution continues without validation
  ```
  - Add explicit `return {'success': False, 'error': '...'}`

- [ ] **Missing CSRF on key operations** - `app/routes/docs.py`
  - Line 117: `/generate-key` POST - no CSRF
  - Line 140: `/revoke-key` POST - no CSRF
  - Add CSRF token validation

### Security: Input Validation

- [ ] **Unvalidated date input** - `app/routes/admin.py:1327`
  ```python
  fetch_start_date = request.form.get('fetch_start_date', '2024-01-01')
  setting.value = fetch_start_date  # No validation!
  ```
  - Validate date format with `datetime.strptime()`

- [ ] **Unvalidated status field** - `app/routes/signals.py:82`
  ```python
  signal.status = data['status']  # Any string accepted!
  ```
  - Whitelist: `['active', 'filled', 'expired', 'cancelled']`

- [ ] **Unvalidated pattern type** - `app/routes/backtest.py:35`
  ```python
  pattern_type = data.get('pattern_type', 'imbalance')  # Not validated
  ```
  - Whitelist: `['imbalance', 'order_block', 'liquidity_sweep']`

- [ ] **Missing input length limits** - `app/routes/admin.py:747-751`
  - NotificationTemplate fields have no length validation
  - Add max length checks for `name`, `title`, `message`, `tags`

- [ ] **Integer bounds not checked** - Multiple locations
  - `app/routes/api.py:178` - `limit` parameter
  - `app/routes/logs.py:45` - `limit`, `offset` parameters
  - `app/routes/patterns.py:159` - `limit` parameter
  - Add `min()` bounds: `limit = min(int(request.args.get('limit', 200)), 1000)`

### Performance: N+1 Queries

- [ ] **Dashboard analytics loop** - `app/routes/dashboard.py:146-150`
  ```python
  for s in symbols:
      count = Pattern.query.filter_by(symbol_id=s.id, status='active').count()
  ```
  - 101 queries for 100 symbols
  - Use aggregation query with `func.count()` and `group_by()`

- [ ] **Signal enrichment loop** - `app/routes/signals.py:48-53`
  ```python
  for signal in signals:
      signal.symbol_obj = db.session.get(Symbol, signal.symbol_id)
  ```
  - Use `joinedload()` or eager loading

- [ ] **Dashboard matrix building** - `app/routes/dashboard.py:43-57`
  - 30 queries (5 symbols × 6 timeframes)
  - Batch query with single JOIN

- [ ] **Pattern type statistics** - `app/routes/dashboard.py:131-134`
  ```python
  for pt in PATTERN_TYPES:
      patterns_by_type[pt] = Pattern.query.filter_by(pattern_type=pt).count()
  ```
  - Use single query with `group_by(Pattern.pattern_type)`

### Documentation: Missing CLI Arguments

- [ ] **fetch_historical.py missing 4 arguments** - `scripts/fetch_historical.py:11-16`
  - Missing from docs: `--verbose`, `--no-aggregate`, `--full`, `--symbol`
  - Update docstring usage section

- [ ] **db_health.py missing 2 arguments** - `scripts/db_health.py:14-21`
  - Missing from docs: `--quiet`, `--clear-gaps`
  - Update docstring usage section

---

## MEDIUM SEVERITY (Fix This Month)

### Error Handling: Bare Exceptions

- [ ] **Bare except handlers** - Multiple locations
  - `app/jobs/notifications.py:76` - `except: pass`
  - `app/services/notifier.py:184` - `except: pass`
  - `app/services/notifier.py:506` - `except: pass`
  - Replace with `except (json.JSONDecodeError, TypeError, ValueError):`

- [ ] **Silent exception swallowing** - `scripts/fetch.py`
  - Lines 105-111: Aggregation errors silently ignored
  - Lines 129-134: Pattern detection errors silently ignored
  - Lines 142-146: Pattern status update errors silently ignored
  - Add logging: `logger.warning(f"Aggregation failed for {tf}: {e}")`

### Database: Missing Indexes

- [ ] **Add indexes to frequently queried fields**
  ```python
  # Symbol model
  db.Index('idx_symbol_is_active', 'is_active')

  # Pattern model
  db.Index('idx_pattern_direction', 'direction')
  db.Index('idx_pattern_type', 'pattern_type')

  # User model
  db.Index('idx_user_verified', 'is_verified')
  db.Index('idx_user_admin', 'is_admin')

  # Subscription model
  db.Index('idx_subscription_user_status', 'user_id', 'status')

  # Payment model
  db.Index('idx_payment_user_status', 'user_id', 'status')

  # Trade model
  db.Index('idx_trade_signal', 'signal_id')

  # Log model
  db.Index('idx_log_timestamp', 'timestamp')
  ```

### Database: Transaction Issues

- [ ] **Missing rollback in subscription operations** - `app/routes/admin.py:259-284`
  ```python
  cancel_subscription(user_id)   # Commits
  extend_subscription(user_id)   # May fail - no rollback!
  ```
  - Wrap in try-except with `db.session.rollback()`

- [ ] **Partial commits in bulk operations** - `app/routes/admin.py:183-210`
  - No transaction wrapping for bulk user updates
  - Add savepoints or single transaction

### API: Response Consistency

- [ ] **Standardize JSON response format** - All API routes
  - Current: Mix of `{data}`, `{success, data}`, `{error}`, `{success, error}`
  - Target: `{success: bool, data?: any, error?: string}`

### Security: Rate Limiting

- [ ] **Missing rate limits on admin operations** - `app/routes/admin.py`
  - Line 109: `/users/<id>/verify` - no rate limit
  - Line 120: `/users/<id>/unlock` - no rate limit
  - Add `@limiter.limit("10 per minute")`

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
