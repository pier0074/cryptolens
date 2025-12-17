# Code Review: Backtesting System

**Date**: 2025-12-17
**Reviewer**: Claude Code
**Files Reviewed**:
- `app/services/backtester.py`
- `app/routes/backtest.py`
- `tests/test_backtester.py`
- `app/services/patterns/base.py`
- `app/services/patterns/fair_value_gap.py`

---

## Summary

The backtesting system is well-structured with good separation of concerns and comprehensive test coverage. However, there are several correctness issues in trade simulation logic and some security/reliability concerns in the routes that require attention.

---

## Critical Issues

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| Missing input validation | `backtest.py:31-36` | No validation on `symbol`, `timeframe`, `start_date`, `end_date` before passing to `run_backtest()` | Could cause crashes or unexpected behavior with malformed input |
| Missing authorization on detail route | `backtest.py:60-66` | `detail()` endpoint lacks `@login_required` and `@feature_required` decorators | Anyone can view backtest results without authentication |

---

## High Priority Issues

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| Same-candle SL/TP hit ambiguity | `backtester.py:228-281` | When both SL and TP could be hit in the same candle, code assumes SL hits first for longs (checks `low` before `high`) | Biases backtest results - may report losses when trade actually won |
| Unrealistic entry assumption | `backtester.py:217-224` | Entry triggers when price touches zone (`candle['low'] <= entry` for long) but uses zone edge as entry price | Slippage not modeled - real entries would likely be worse |
| Incomplete pattern types | `backtester.py:149-156` | Unknown pattern type silently defaults to FVG instead of raising error | User may unknowingly test wrong strategy |
| Date parsing without error handling | `backtester.py:65-66` | `datetime.strptime()` will raise `ValueError` on invalid dates | Server crash on malformed date input |

---

## Medium Priority Issues

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| Hardcoded 5000 candle limit | `backtester.py:53` | Fixed `limit=5000` regardless of date range | May miss data for long backtests or fetch unnecessary data for short ones |
| Magic number 100 for lookback | `backtester.py:212` | Hardcoded 100-candle max trade duration | Arbitrary limit may miss valid trade completions on higher timeframes |
| Magic number 10 for min candles | `backtester.py:70` | Minimum 10 candles required | May be too few for meaningful patterns, too many for short tests |
| No timezone handling | `backtester.py:65-66` | Dates parsed as naive datetime, compared to UTC timestamps | Could cause off-by-one-day issues depending on server timezone |
| Trades truncated in response | `backtester.py:130` | Returns first 50 trades only (`trades[:50]`) | Users can't see full trade history for analysis |

---

## Low Priority Issues

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| Singleton pattern detectors | `backtester.py:20-22` | Module-level singleton instances | Thread-safety concern if instance state is modified |
| Hardcoded overlap threshold | `fair_value_gap.py:201` | `0.7` threshold in historical detection | Should use `Config` value for consistency |
| Redundant zero division check | `backtester.py:311,314,330` | Multiple `if total_trades > 0` checks | Minor code duplication |

---

## Positive Observations

- Good use of production pattern detectors in backtesting for consistency
- Comprehensive logging with `log_backtest()` at key points
- Proper numpy type conversion in `simulate_single_trade()` (lines 190-193)
- Good test coverage with edge cases (empty trades, all wins, all losses, mixed)
- Clean separation between route, service, and pattern detection layers
- Proper use of decorators for authentication/authorization on main routes
- Backtest results saved to database for historical analysis
- Well-documented functions with clear docstrings

---

## Execution Trace - Potential Bug

```
Input: bullish pattern, zone_high=100, zone_low=98, rr_target=2.0, sl_buffer=10%

-> Line 192: zone_size = 100 - 98 = 2
-> Line 193: buffer = 2 * 0.1 = 0.2
-> Line 196: entry = 100 (zone_high)
-> Line 197: stop_loss = 98 - 0.2 = 97.8
-> Line 198: risk = 100 - 97.8 = 2.2
-> Line 199: take_profit = 100 + (2.2 * 2.0) = 104.4

-> Line 217-218: Entry triggers when candle low <= 100
   BUG: Assumes we get filled at exactly 100, but price went lower

-> Line 228-229: If candle has low=97 and high=105
   - Checks low <= 97.8 (SL) FIRST -> returns loss
   - Never checks if high >= 104.4 (TP) was hit
   RESULT: Reports loss when trade might have won
```

---

## Edge Cases Analysis

| Input | Expected | Actual | Status |
|-------|----------|--------|--------|
| Invalid date format | Error message | Server crash | FAIL - `strptime` raises unhandled exception |
| Empty symbol string | Validation error | Proceeds to query | FAIL - No validation |
| Negative `rr_target` | Error/clamp | Inverted TP/SL logic | FAIL - No validation |
| `sl_buffer_pct=0` | Tight stops | Works but risky | WARN - May want minimum |
| Future `end_date` | Handle gracefully | Returns recent data | PASS |
| Very short date range | Few/no trades | Returns error if <10 candles | PASS |
| `None` JSON body | Error message | AttributeError crash | FAIL - No null check |

---

## Recommendations

### Must Fix
1. Add `@login_required` and `@feature_required('backtest')` to `detail()` route at line 60
2. Add input validation for date formats and required fields in route
3. Add try/except around date parsing with proper error response

### Should Fix
4. Handle same-candle SL/TP ambiguity (conservative approach: mark as inconclusive)
5. Validate pattern_type and return error for unknown types
6. Add null check for `request.get_json()` result

### Consider
7. Make lookback period (100) configurable based on timeframe
8. Add slippage modeling option for more realistic results
9. Add pagination or full export option for trade results
10. Use UTC-aware datetime parsing

---

## Testing Suggestions

### Security Tests
- [ ] Test `detail` route without authentication
- [ ] Test with SQL injection payloads in symbol field
- [ ] Test with XSS payloads in pattern_type

### Input Validation Tests
- [ ] Test with invalid date format (e.g., "01-01-2023" instead of "2023-01-01")
- [ ] Test with `pattern_type='invalid'`
- [ ] Test with empty/null required fields
- [ ] Test with `rr_target=0` and negative values

### Edge Case Tests
- [ ] Test candles where both SL and TP would be hit in same bar
- [ ] Test with very large date ranges (>5000 candles)
- [ ] Test with date range returning exactly 10 candles

### Performance Tests
- [ ] Test with maximum date range
- [ ] Test concurrent backtest requests

---

## Files for Detailed Issues

- `CI-CD/issues/001-missing-auth-backtest-detail.md`
- `CI-CD/issues/002-missing-input-validation.md`
- `CI-CD/issues/003-same-candle-sl-tp-ambiguity.md`

---

## Conclusion

The backtesting system has a solid foundation with good architecture and test coverage. The critical issues around authentication and input validation should be addressed immediately before production use. The trade simulation logic bugs (same-candle ambiguity) will affect result accuracy but not system stability.

**Overall Assessment**: Needs work before production-ready
