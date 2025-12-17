# CI/CD Todo List

## High Priority

- [ ] Add input validation to backtest route endpoints
- [ ] Fix missing authentication on backtest detail route
- [ ] Handle same-candle SL/TP ambiguity in trade simulation
- [ ] Add try/except around date parsing with proper error responses
- [ ] Set up automated test pipeline

## Medium Priority

- [ ] Make trade lookback period configurable based on timeframe
- [ ] Add timezone handling for date inputs
- [ ] Implement slippage modeling option
- [ ] Add pagination for trade results (currently truncated to 50)
- [ ] Configure dynamic candle limit based on date range

## Low Priority

- [ ] Extract hardcoded constants to configuration
- [ ] Add thread-safety review for singleton pattern detectors
- [ ] Align historical detection overlap threshold with Config value
- [ ] Reduce code duplication in statistics calculation

## Infrastructure

- [ ] Set up GitHub Actions workflow
- [ ] Configure test coverage reporting
- [ ] Add pre-commit hooks for linting
- [ ] Set up staging environment
- [ ] Configure deployment automation

## Documentation

- [ ] Document API endpoints
- [ ] Add developer setup guide
- [ ] Create troubleshooting guide
- [ ] Document pattern detection algorithms
