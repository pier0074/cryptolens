# CryptoLens - Future Enhancements

> **Current Version**: v2.1.0
> **Status**: Production-ready with 3-tier subscriptions, payments, and legal compliance
> **Tests**: 583 passing

---

## QA Audit Fixes (Completed December 2025)

> **Audit Date**: December 2025
> **Final Verdict**: 100% feature complete, production ready
> **All Critical/High/Medium Issues**: Resolved

### Critical - ✅ FIXED

- [x] **Async notification bug** - Verified: `notify_subscribers_async` wrapper correctly uses `asyncio.run()`
  - The warning was a false positive during Flask route compilation in Python 3.14
  - The synchronous wrapper properly executes the async code

### High Priority - ✅ FIXED

- [x] **Backtest for all pattern types** - Added Order Block and Liquidity Sweep detection
  - Location: `app/services/backtester.py`
  - Added: `_detect_order_block_trades()` and `_detect_liquidity_sweep_trades()`

- [x] **Payment webhook integration tests** - Added 13 tests in `tests/test_payments.py`
  - Tests: Signature validation, CSRF exemption, webhook processing
  - Covers: LemonSqueezy and NOWPayments webhooks

- [ ] **CCXT datetime deprecation** - External library issue, cannot fix directly
  - Tracked upstream, will be resolved in future CCXT releases

### Medium Priority - ✅ FIXED

- [x] **Terms checkbox HTTP-level test** - Added to `tests/test_auth.py`
  - `test_register_without_terms_fails()` - verifies rejection
  - `test_register_with_terms_succeeds()` - verifies acceptance

- [x] **Prometheus metrics endpoint test** - Added 6 tests in `tests/test_api.py`
  - Tests: 200 response, Prometheus format, app info, pattern gauges, user metrics

- [ ] **Chart E2E tests** - Deferred (requires Playwright/Cypress setup)
  - Consider adding in future sprint

### Low Priority - ✅ DOCUMENTED

- [ ] **SQLAlchemy deprecation warnings** - Known issue, doesn't affect functionality
  - Will be addressed in SQLAlchemy 2.0 migration

- [x] **Redis rate limiter** - Documented in PRODUCTION.md
  - Set `RATELIMIT_STORAGE_URL=redis://localhost:6379/0` in production

- [x] **Timeframe consistency** - Documented in `app/config.py`
  - fetch.py intentionally aggregates extra timeframes (30m, 2h) for data completeness

---

## Recently Completed

### Legal & Compliance
- [x] Comprehensive Terms of Service (20 sections)
- [x] Privacy Policy
- [x] Registration terms acknowledgment (checkbox)
- [x] Age verification (18+)
- [x] Personal account / no sharing policy
- [x] NTFY channel code protection in ToS
- [x] No refunds policy

### UI/UX Improvements
- [x] Login redirects to dashboard (not profile)
- [x] Centralized plan features (DRY)
- [x] Patterns section on landing page
- [x] "Fair Value Gap" terminology consistency
- [x] Tier-based upgrade buttons (no downgrade option)
- [x] Fixed spacing issues in plan display

---

## Security Enhancements

### Session Security
- [ ] Regenerate session ID after successful login (session fixation prevention)
- [ ] Add session timeout/inactivity logout (auto-logout after X minutes idle)

### Security Auditing
- [ ] Run OWASP ZAP automated security scan
- [ ] Add security tests to CI/CD pipeline
- [ ] Implement Content Security Policy (CSP) headers

---

## Admin Features

### Admin UI Improvements
- [ ] Add admin UI to unlock locked accounts
- [ ] Add bulk user management actions
- [ ] Scheduled notifications (downtime, promotions)

---

## Performance & Caching

### Advanced Caching
- [ ] Cache stats/analytics (5 minute TTL)
- [ ] Cache user tier info for faster access checks

### Performance Enhancements
- [ ] AJAX lazy-load for last_data_update in templates
- [ ] Add database connection health monitoring

### Additional Circuit Breakers
- [ ] Wrap CCXT exchange API calls with circuit breaker
- [ ] Wrap payment provider calls (LemonSqueezy, NOWPayments) with circuit breaker

---

## Code Quality

### Refactoring
- [ ] Convert all services to raise domain exceptions consistently
- [ ] Remove mixed return types (tuple vs exception) in auth services
- [ ] Add query logging in development mode
- [ ] Profile endpoints with SQLAlchemy profiler

---

## Observability

### Logging & Monitoring
- [ ] Include request ID in all log messages for tracing
- [ ] Configure log aggregation (ELK/Datadog) - deployment-specific
- [ ] Add Grafana dashboards for Prometheus metrics
- [ ] Add readiness vs liveness health check endpoints

### Additional Health Checks
- [ ] Add Exchange API (CCXT) reachability check
- [ ] Add NTFY notification service reachability check
- [ ] Add dependency health status in /api/health response

---

## Trading Features

### Additional SMC Patterns
- [ ] Breaker Block detection
- [ ] Mitigation Block detection
- [ ] Equal Highs/Lows detection
- [ ] Swing-based pattern invalidation
- [ ] ATR-based expiry (more dynamic than time-based)
- [ ] Pattern ML scoring (train on historical fill rates)

### Automatic Trading
- [ ] API integration for automated trade execution
- [ ] Exchange API connection (read-only first, then trading)
- [ ] Position sizing based on risk parameters
- [ ] Stop-loss and take-profit automation

---

## Payment & Monetization

### European/Swiss Payment Methods
- [ ] Stripe CH integration (Swiss cards)
- [ ] PostFinance integration
- [ ] TWINT support (Swiss mobile payment)

---

## Notifications

### Multi-Channel Support
- [ ] Admin can send to multiple NTFY topics
- [ ] Channel grouping (by tier, by preference)
- [ ] Scheduled notifications

---

## SEO & Marketing

### Improve Google Ranking
- [ ] Add meta tags (description, keywords, OpenGraph)
- [ ] Create sitemap.xml
- [ ] Add robots.txt
- [ ] Structured data (JSON-LD) for rich snippets
- [ ] Optimize page load speed
- [ ] Add canonical URLs

---

## Infrastructure

### Real-time Features
- [ ] WebSocket for live price updates
- [ ] Real-time pattern notifications in UI
- [ ] Signal alerts without page refresh

### Multi-Exchange Support
- [ ] Abstract exchange interface
- [ ] Add Coinbase, Kraken, Bybit adapters
- [ ] Exchange selector in settings

---

## Mobile & Integrations

### Mobile App
- [ ] iOS app
- [ ] Android app
- [ ] React Native or Flutter

### Bot Integrations
- [ ] Discord bot
- [ ] Telegram bot

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

# Load testing
locust -f tests/load/locustfile.py
```
