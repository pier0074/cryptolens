# Code Review: Backtesting & Optimization System

**Date**: 2025-12-18
**Reviewer**: Claude Code
**Files Reviewed**:
- `app/services/optimizer.py` (primary focus)
- `app/services/backtester.py`
- `app/services/patterns/base.py`
- `app/services/patterns/fair_value_gap.py`
- `app/services/patterns/order_block.py`
- `app/services/patterns/liquidity.py`
- `app/models/optimization.py`

---

## Executive Summary

The backtesting system is well-engineered with excellent performance optimizations (vectorized numpy operations achieving 3.7x speedup). **However, there are critical realism issues that make backtest results unreliable for live trading decisions.** The system properly handles open trades across incremental runs, but the core trade simulation has fundamental flaws.

**Key Finding**: The backtest overstates profitability by ignoring fees (~0.1-0.3% per trade), slippage, and spread. A strategy showing 97% total profit could realistically yield 50-70% less in live trading.

---

## Open Trades Handling in Incremental Mode

### How It Works

The system **correctly persists and resolves open trades** across incremental runs:

1. **Storage**: Open trades stored in `open_trades_json` column (`optimizer.py:2334`, `models/optimization.py:183`)
2. **Retrieval**: `existing.open_trades` property deserializes JSON (`models/optimization.py:211-213`)
3. **Resolution**: `_resolve_open_trades_fast()` checks new candles for SL/TP hits (`optimizer.py:2721-2818`)
4. **Merge**: Resolved trades added to `all_closed_trades`, unresolved stay in `all_open_trades` (`optimizer.py:2404-2406`)

### Code Flow (Incremental Update)

```
run_incremental()
  └─> _run_incremental_single_fast()
        └─> Check existing.last_candle_timestamp vs new data
        └─> existing.open_trades  # Retrieve from DB
        └─> _resolve_open_trades_fast(ohlcv, open_trades, after_timestamp)
              └─> For each open trade:
                    └─> Find candles after entry_time (binary search)
                    └─> Check SL/TP hit on each candle
                    └─> Return (resolved, still_open)
        └─> Detect new patterns in new data only
        └─> _simulate_trades_with_open_fast() for new patterns
        └─> Merge: all_closed = existing.results + resolved + new_trades
        └─> Merge: all_open = still_open + new_open
        └─> Update existing run with merged data
```

### Open Trades Analysis

| Aspect | Status | Notes |
|--------|--------|-------|
| Persistence | ✅ Good | Stored as JSON in `open_trades_json` column |
| Retrieval | ✅ Good | Property with JSON deserialization |
| Resolution logic | ⚠️ Has bug | Same-candle SL/TP assumes SL first (biased) |
| Merge logic | ✅ Good | Properly combines old + resolved + new |
| Timestamp tracking | ✅ Good | `last_candle_timestamp` prevents duplicate processing |
| Overlap handling | ✅ Good | 100-candle overlap window for continuity |

### Bug in Open Trade Resolution

`_resolve_open_trades_fast()` at lines 2756-2813:

```python
if direction == 'long':
    if lows[idx] <= stop_loss:  # Checks SL first
        # Returns loss
    elif highs[idx] >= take_profit:  # Only checks TP if SL not hit
        # Returns win
```

**Issue**: On candles where both SL and TP are touched, SL always wins. Should be indeterminate or use conservative assumption.

---

## Critical Issues 🔴

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| **No slippage/fees** | `optimizer.py:1162-1310` | Trade simulation assumes perfect fills at exact SL/TP prices with zero fees | **Overstates profits by ~0.1-0.3% per trade**. Binance fees 0.1% round-trip. A strategy with 200 trades loses ~20-60% to fees alone |
| **Same-candle SL/TP bias** | `optimizer.py:1266-1283`, `2756-2813` | When both SL and TP are hit on same candle, assumes index order determines winner (`if sl_idx <= tp_idx`) | **Systematically biased results** - within a single candle, we can't know which was hit first |
| **No spread consideration** | Entry logic at `optimizer.py:1201-1212` | Long entries at `zone_high`, short at `zone_low` without bid-ask spread | Real entries would be worse by spread (0.01-0.05%) |
| **Production pattern detection differs** | `detect()` vs `detect_historical()` | Production uses DB overlap checks, backtest uses in-memory overlap | **Results won't match live** - production may skip patterns that backtest accepts |

---

## High Priority Issues 🟠

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| **Liquidity sweep lookback differs** | `liquidity.py:156` vs `liquidity.py:364` | Production: last 10 candles. Backtest: all candles from index 10+ | Backtest detects **far more patterns** than production would |
| **Worker function duplication** | `optimizer.py:106-253` | `_simulate_trades_worker()` duplicates `_simulate_trades_fast()` | Maintenance risk - changes to one may not propagate |
| **Unverified candles fallback** | `optimizer.py:389-393` | Falls back to unverified candles silently (just logs `[unverified!]`) | Backtest may use unverified data that differs from production |
| **Missing authorization** | `backtest.py:60-66` | `detail()` endpoint lacks `@login_required` decorator | Security vulnerability |

---

## Medium Priority Issues 🟡

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| **MAX_TRADE_DURATION=1000 hardcoded** | `optimizer.py:1185` | Trades unresolved after 1000 candles dropped | On 1m TF = 16.6 hours (restrictive); on 1d = 2.7 years (fine) |
| **Sharpe ratio not annualized** | `optimizer.py:1736-1741` | Simplified Sharpe without standard annualization | Not comparable to industry-standard Sharpe ratios |
| **Overlap threshold inconsistency** | Pattern detectors | Production uses DB checks; backtest uses fresh in-memory tracking | Subtle pattern count differences |
| **No position sizing** | Trade simulation | All trades treated equally | Can't assess realistic account growth |
| **Results JSON truncated** | `optimizer.py:1497` | Only stores last 100 trades | Can't analyze full trade history |

---

## Low Priority Issues 🔵

| Issue | Location | Description | Impact |
|-------|----------|-------------|--------|
| Magic number `entry_idx + 10` | `optimizer.py:1192` | Why 10? | Minor - just skips patterns near data end |
| Timing logs in production | Pattern detectors | `if total_ms > 500: print(...)` | Log noise |
| Hardcoded 5000 candle limit | `backtester.py:53` | Fixed regardless of date range | May miss data or fetch too much |

---

## Factorization Analysis

| Area | Status | Notes |
|------|--------|-------|
| `run_job` vs `run_incremental` | ✅ **Good** | Both use `_process_symbol()` as single source of truth |
| `_run_sweep_phase()` | ✅ **Good** | Shared implementation for Phase 3 |
| `_simulate_trades_fast()` vs `_simulate_trades_worker()` | ❌ **Duplicated** | Worker has full copy (253 lines) instead of calling shared method |
| `_calculate_statistics()` vs `_calculate_statistics_worker()` | ❌ **Duplicated** | Same issue |
| Pattern `detect()` vs `detect_historical()` | ⚠️ **Different logic** | Not just DB-free version - actual detection differs |
| Open trade resolution | ✅ **Good** | Single `_resolve_open_trades_fast()` used everywhere |

---

## Pattern Detection Consistency (Prod vs Backtest)

| Pattern Type | Production `detect()` | Backtest `detect_historical()` | Gap |
|--------------|----------------------|-------------------------------|-----|
| **FVG** | DB overlap checks via `has_overlapping_pattern()` | In-memory numpy overlap tracking | Production respects existing DB patterns; backtest starts fresh |
| **Order Block** | 3-candle lookback, uses `_precomputed` ATR/swing | 3-candle lookback, no ATR/swing compute | Minor difference |
| **Liquidity Sweep** | **Last 10 candles only**, swing range [i-50, i-4] | **All candles from index 10+**, same swing range | **Major**: Backtest finds significantly more patterns |

---

## Positive Observations ✅

- Excellent vectorization with numpy - 3.7x Phase 3 speedup
- **Open trades properly persisted and resolved across incremental runs**
- Symbol-by-symbol processing prevents memory explosion
- Skip logic for unchanged data is smart optimization
- Good separation of phases (load → detect → sweep)
- Verified candles prioritized (verified_only=True first)
- Batch commits prevent DB bottlenecks
- Binary search for timestamp lookups (O(log n) vs O(n))
- Good test coverage with 24 passing tests

---

## Realism Assessment

| Aspect | Backtest | Real Trading | Gap |
|--------|----------|--------------|-----|
| **Entry price** | Exact zone edge | Zone edge + spread + slippage | 0.02-0.1% worse |
| **Exit price** | Exact SL/TP | SL/TP ± slippage | 0.01-0.05% worse |
| **Fees** | 0% | 0.1% round-trip (Binance) | 0.1% per trade |
| **Fill probability** | 100% | <100% (liquidity dependent) | Varies |
| **Pattern detection** | All historical patterns | Only patterns that would actually fire | May show more patterns |
| **Same-bar SL/TP** | Assumes deterministic order | Unknown which hit first | Biased results |

**Realistic Adjustment Factor**: Expect 30-50% lower returns in live trading compared to backtest results.

---

## Recommendations

### Must Fix (Affects Accuracy)
1. **Add fee calculation** - At minimum 0.1% round-trip
2. **Fix same-candle SL/TP logic** - Conservative: assume loss when both could hit
3. **Align `detect_historical()` with `detect()`** - Especially for liquidity sweep (10 candles vs all)

### Should Fix (Code Quality)
4. **Extract `_simulate_trades_worker()` to call shared method** - DRY principle
5. **Parameterize `MAX_TRADE_DURATION` by timeframe** - 1000 on 1m is too short
6. **Add slippage parameter** - Default 0.02-0.05%
7. **Add `@login_required` to backtest detail route**

### Consider (Future Improvement)
8. Add position sizing simulation for realistic equity curves
9. Make overlap checking consistent between prod/backtest
10. Store full trade history (not just last 100)
11. Add Monte Carlo simulation for confidence intervals

---

## Testing Suggestions

### Accuracy Verification
- [ ] Run backtest on known historical period, manually verify 10 random trades
- [ ] Compare `detect()` vs `detect_historical()` pattern counts on same data
- [ ] Run with 0%, 0.1%, 0.2% fee parameter to measure sensitivity

### Open Trades Verification
- [ ] Run incremental twice with gap, verify open trades resolved correctly
- [ ] Check `open_trades_json` contains proper SL/TP/entry data
- [ ] Test trade that spans 3+ incremental runs

### Edge Cases
- [ ] Same-candle SL/TP scenario - verify behavior
- [ ] Very short datasets (<50 candles)
- [ ] Data gaps in candle series
- [ ] Pattern at very end of data (near `entry_idx + 10` boundary)

---

## Conclusion

The backtesting system is **well-engineered from a performance standpoint** with proper incremental support and open trade handling. However, **the results are not realistic enough for production trading decisions** due to missing fees, slippage, and same-candle ambiguity.

**Actionable Summary**:
1. Add 0.1% fee deduction per trade - **immediate impact on accuracy**
2. Fix same-candle SL/TP to assume loss - **removes optimistic bias**
3. Align liquidity sweep detection with production - **ensures consistency**

**Risk Assessment**: Using current backtest results for live trading will likely result in 30-50% lower actual returns than predicted.

---

*Report generated by Claude Code on 2025-12-18*
