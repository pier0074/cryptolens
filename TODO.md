# CryptoLens - Remaining Issues & Future Enhancements

> **Last Updated**: December 15, 2025
> **Current Version**: v2.2.0

---

## Recently Completed

- [x] **Dashboard matrix optimization** - Reduced from 30 queries to 1
- [x] **API endpoint docstrings** - All endpoints documented
- [x] **Timestamp standardization** - All models now use BigInteger (ms)
- [x] **API key system redesign** - Per-key rate limits, IP rules, scopes

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
