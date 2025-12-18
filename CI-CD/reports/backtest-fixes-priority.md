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

## Phase 2: Production Parity - IN PROGRESS

### 2.1 Liquidity Sweep Detection Mismatch 🟠

**Status**: Pending
**Files**: `liquidity.py:156` (production) vs `liquidity.py:364` (backtest)
**Effort**: 2 hours | **Impact**: High

**Problem**:
The production `detect()` method only scans the **last 10 candles** for liquidity sweeps:
```python
# Production (detect) - line 156
for i in range(len(df) - 10, len(df)):  # Only last 10 candles
```

But the backtest `detect_historical()` scans **ALL candles from index 10 onwards**:
```python
# Backtest (detect_historical) - line 364
for i in range(10, n):  # All candles!
```

**Impact**:
- Backtest finds **significantly more patterns** than production would ever detect
- A pattern from 1000 candles ago would be backtested but never triggered in live
- Results are overly optimistic because backtest includes patterns that wouldn't exist

**Fix**:
Modify `detect_historical()` to only scan the last N candles per symbol/timeframe chunk, simulating the rolling 10-candle window that production uses.

---

### 2.2 FVG/OB Pattern Detection Overlap Checking 🟠

**Status**: Pending
**Files**: `detect()` vs `detect_historical()` in `fair_value_gap.py`, `order_block.py`
**Effort**: 4 hours | **Impact**: High

**Problem**:
Production and backtest use different overlap detection mechanisms:

**Production** (`detect()`):
- Queries the database for existing active patterns
- Uses `has_overlapping_pattern()` which checks `Pattern` table
- Respects patterns that were saved in previous runs
- Can skip patterns that overlap with DB-persisted ones

**Backtest** (`detect_historical()`):
- Uses in-memory lists (`seen_bullish_lows`, `seen_bearish_highs`)
- Starts fresh each run - no memory of previously detected patterns
- Only checks overlap within the current detection run
- May accept patterns that production would reject (due to DB overlap)

**Impact**:
- Pattern counts differ between backtest and live
- Backtest may trade patterns that production would skip
- Historical simulation doesn't accurately represent what live would do

**Fix**:
Either:
1. Make `detect_historical()` maintain persistent overlap state across chunks
2. Or make both use the same overlap-checking logic (in-memory for both)

---

### 2.3 Missing Auth on Backtest Detail Route 🟠

**Status**: Pending
**File**: `app/routes/backtest.py:60-66`
**Effort**: 5 minutes | **Impact**: High (Security)

**Problem**:
The `detail()` route in `backtest.py` lacks authentication decorators:
```python
@backtest_bp.route('/detail/<int:pattern_id>')
def detail(pattern_id):  # No @login_required or @feature_required!
    ...
```

**Impact**:
- Unauthenticated users can access backtest details
- Potential information disclosure
- Inconsistent with other protected routes

**Fix**:
Add decorators:
```python
@backtest_bp.route('/detail/<int:pattern_id>')
@login_required
@feature_required('backtesting')
def detail(pattern_id):
```

---

### 2.4 Worker Trade Simulation Duplication 🟠

**Status**: Pending
**File**: `optimizer.py:131-280`
**Effort**: 1.5 hours | **Impact**: Medium (Maintainability)

**Problem**:
`_simulate_trades_worker()` is a **complete copy** of `_simulate_trades_fast()` (~150 lines):
```python
def _simulate_trades_worker(ohlcv, patterns, params):
    """
    Trade simulation for worker process.
    MUST produce identical results to ParameterOptimizer._simulate_trades_fast().
    ...
    """
    # 150 lines of duplicated logic
```

The comment even acknowledges they must be identical! This is a DRY violation.

**Impact**:
- Changes to one function may not propagate to the other
- Bug fixes need to be applied twice
- Already diverged slightly: worker doesn't have drill-down capability for same-candle conflicts
- Maintenance burden increases over time

**Fix**:
Extract shared logic to a standalone function that both can call:
```python
def _simulate_trades_core(ohlcv, patterns, params, resolve_conflict_fn=None):
    # Shared implementation
    ...

def _simulate_trades_worker(ohlcv, patterns, params):
    return _simulate_trades_core(ohlcv, patterns, params, resolve_conflict_fn=lambda: 'loss')

def _simulate_trades_fast(self, ohlcv, patterns, params, timeframe=None, data_cache=None, symbol=None):
    def resolve_fn():
        return self._resolve_same_candle_conflict(...)
    return _simulate_trades_core(ohlcv, patterns, params, resolve_conflict_fn=resolve_fn)
```

---

### 2.5 Worker Statistics Duplication 🟠

**Status**: Pending
**File**: `optimizer.py:283-350`
**Effort**: 30 minutes | **Impact**: Medium (Maintainability)

**Problem**:
`_calculate_statistics_worker()` duplicates `_calculate_statistics()` (~70 lines):
```python
def _calculate_statistics_worker(trades):
    """
    Calculate statistics for worker process.
    MUST produce identical results to ParameterOptimizer._calculate_statistics().
    """
    # 70 lines of duplicated logic
```

Same issue as 2.4 - explicit comment saying they must match, yet maintained separately.

**Impact**:
- Same as 2.4: changes may not propagate, bugs fixed twice
- Statistics could silently diverge between parallel and sequential runs

**Fix**:
Extract to standalone function:
```python
def calculate_trade_statistics(trades: List[Dict]) -> Dict:
    """Shared statistics calculation - used by both worker and main optimizer."""
    ...

# Then both call:
stats = calculate_trade_statistics(trades)
```

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
| Phase 2 | 2.1 - 2.5 | 🔄 In Progress | ~8 hours remaining |
| Phase 3 | 3.1 - 3.4 | Pending | ~2 hours |
| Phase 4 | 4.1 - 4.2 | Pending | ~0.5 hours |

---

## Recommended Next Steps

1. **Quick win**: 2.3 (5 min) - Add auth decorator
2. **Biggest impact**: 2.1 (2h) - Fix liquidity sweep detection
3. **Code quality**: 2.4 + 2.5 (2h) - Refactor duplicated worker code

---

*Last updated: 2025-12-18*
