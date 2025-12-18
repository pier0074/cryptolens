# Backtest Fixes - Priority List

**Date**: 2025-12-18 (Updated)
**Source**: Code Review Analysis

---

## Phase 1: Accuracy - COMPLETED

| Order | Status | Issue | Solution |
|-------|--------|-------|----------|
| **1.1** | ✅ Done | No trading fees | Moved to WebUI - fee input calculates net profit client-side. Formula: `Net = Gross - (Trades × 2 × Fee%)` |
| **1.2** | ✅ Done | Same-candle SL/TP bias | Implemented drill-down to smaller TF. When conflict on 4h candle, checks 1h data to determine which hit first. Falls back to 'loss' (conservative) at 1m or when no data. |
| **1.3** | ❌ Removed | No slippage modeling | Not needed - strategy uses limit orders only (zero slippage by definition) |
| **1.4** | ❌ Removed | No spread consideration | Not needed - limit orders are maker orders (no spread impact) |

---

## Phase 2: Production Parity - COMPLETED

### 2.1 Liquidity Sweep Detection Mismatch ✅

**Status**: Fixed
**Files**: `liquidity.py:156`

**Problem**:
The production `detect()` method only scanned the **last 10 candles** for liquidity sweeps (BUG).

**Solution**:
Fixed production to scan all candles like FVG/OB do:
```python
# Before (BUG)
for i in range(len(df) - 10, len(df)):  # Only last 10

# After (FIXED)
for i in range(10, len(df)):  # All candles - consistent with backtest
```

---

### 2.2 FVG/OB/LS Pattern Detection - Factorized ✅

**Status**: Fixed
**Files**: `fair_value_gap.py`, `order_block.py`, `liquidity.py`

**Problem**:
Production and backtest used different code for pattern detection, risking divergence.

**Solution**:
Refactored all pattern detectors so `detect()` now calls `detect_historical()`:
```python
def detect(self, symbol, timeframe, ...):
    # Use shared detection algorithm
    raw_patterns = self.detect_historical(df, skip_overlap=True)

    # Filter by DB overlap and save
    for raw in raw_patterns:
        if self.has_overlapping_pattern(...):
            continue
        self.save_pattern(...)
```

This ensures **identical pattern detection logic** for both prod and backtest.
The only difference is the overlap checking (DB vs in-memory) which is intentional.

---

### 2.3 Missing Auth on Backtest Detail Route ✅

**Status**: Already Fixed
**File**: `app/routes/backtest.py`

**Note**: The route already had auth decorators. The priority list was based on outdated analysis.
All backtest routes have `@login_required` and `@feature_required('backtest')`.

---

### 2.4 & 2.5 Worker Duplication - Removed ✅

**Status**: Fixed
**File**: `optimizer.py`

**Problem**:
`_simulate_trades_worker()` and `_calculate_statistics_worker()` were ~220 lines of duplicated code.

**Solution**:
Discovered these were **dead code** - never actually called! The parallel processing
uses `_process_symbol_worker()` which creates a full `ParameterOptimizer()` instance
and calls the class methods directly.

**Action**: Removed the unused functions (~225 lines of dead code removed).

---

## Remaining Phases (Lower Priority)

### Phase 3: Polish (Medium)
| Order | Issue | Description |
|-------|-------|-------------|
| 3.1 | MAX_TRADE_DURATION hardcoded | 1000 candles on 1m = 16.6 hours (too short). Parameterize by TF. |
| 3.2 | Sharpe ratio not annualized | Add annualization for industry-standard comparison |
| 3.3 | Results truncated to 100 | Store full trade history for analysis |
| 3.4 | Unverified candles fallback | Consider failing instead of silently using unverified data |

### Phase 4: Cleanup (Low)
| Order | Issue | Description |
|-------|-------|-------------|
| 4.1 | Magic numbers | Extract `entry_idx + 10` and others to named constants |
| 4.2 | Debug timing logs | Gate behind verbose flag or remove |

---

## Updated Time Estimates

| Phase | Items | Status | Time |
|-------|-------|--------|------|
| Phase 1 | 1.1 - 1.4 | ✅ Complete | Done |
| Phase 2 | 2.1 - 2.5 | ✅ Complete | Done |
| Phase 3 | 3.1 - 3.4 | Pending | ~2 hours |
| Phase 4 | 4.1 - 4.2 | Pending | ~0.5 hours |

---

## Summary of Changes

1. **Liquidity Sweep BUG Fix**: Production now scans all candles (was only last 10)
2. **Pattern Detection Factorization**: All detectors now share core logic via `detect_historical()`
3. **Dead Code Removal**: Removed ~225 lines of unused worker functions
4. **Test Updates**: Updated 1 test that referenced removed dead code

**All 84 related tests pass.**

---

*Last updated: 2025-12-18*
