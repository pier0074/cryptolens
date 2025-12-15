# CryptoLens - Remaining Issues & Future Enhancements

> **Last Updated**: December 15, 2025
> **Current Version**: v2.1.0

---

## LOW SEVERITY (Nice to Have)

### Performance

- [ ] **Dashboard matrix building** - `app/routes/dashboard.py:43-57`
  - 30 queries (5 symbols × 6 timeframes)
  - Consider batch query with single JOIN (low priority)

### Documentation

- [ ] **Add docstrings to undocumented endpoints**
  - `app/routes/api.py` - 5 GET endpoints
  - `app/routes/patterns.py` - chart endpoint
  - `app/routes/dashboard.py` - analytics endpoint

### Code Quality

- [ ] **Timestamp field inconsistency**
  - `Candle.timestamp` - BigInteger (ms)
  - `Pattern.detected_at` - BigInteger (ms)
  - `Signal.created_at` - DateTime object
  - Consider standardizing (low priority)

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

# Security scan
pip install bandit && bandit -r app/

# Type checking
pip install mypy && mypy app/
```
