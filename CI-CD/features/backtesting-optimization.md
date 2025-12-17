# Feature: Backtesting Parameter Optimization System

**Status**: Complete
**Priority**: High
**Estimated Effort**: Large (3 phases)
**Created**: 2024-12-17
**Last Updated**: 2024-12-17

## Implementation Progress

- [x] **Phase 1**: Unified pattern detection (commit `062f7c1`)
- [x] **Phase 2**: Parameter optimization system (commit `ab90793`)
- [x] **Phase 3**: Auto-tuning & parameter comparison (commit `532f842`)

## Summary of What's Implemented

### Phase 1 - Unified Detection
- Added `detect_historical()` to all pattern detectors (FVG, Order Block, Liquidity Sweep)
- Refactored backtester to use production detectors
- 22 backtester tests passing

### Phase 2 - Optimization System
- OptimizationJob and OptimizationRun database models
- ParameterOptimizer service with grid search
- CLI script `scripts/run_optimization.py`
- Admin UI at `/admin/optimization`

### Phase 3 - Auto-Tuning & Comparison
- Extended UserSymbolPreference with custom trading parameters
- AutoTuner service for applying best params
- Parameter comparison heatmap at `/admin/optimization/compare`
- Copy-to-preferences feature (premium/admin only)
- API endpoints for parameter management

---

## Problem Statement

The current backtesting system has significant differences from production pattern detection:

1. **Detection logic mismatch** - Backtesting uses simplified inline functions, not production detectors
2. **No parameter optimization** - Can't systematically find best SL%, TP%, RR settings
3. **No results comparison** - Can't compare different parameter combinations
4. **Potential duplicates** - No overlap detection in backtesting creates unrealistic results

### Current Differences: Backtesting vs Production

| Aspect | Production | Backtesting |
|--------|-----------|-------------|
| Detection | `FVGDetector`, `OrderBlockDetector`, `LiquiditySweepDetector` classes | Inline simplified functions |
| Overlap check | 70% threshold to avoid duplicates | None - creates duplicates |
| Zone validation | MIN_ZONE_PERCENT = 0.15% | None |
| Trading levels | 3 TPs (TP1, TP2, TP3) with ATR/swing targeting | Single TP at fixed RR |
| Entry | Zone edge + ATR buffer | Zone edge only |
| Stop loss | Beyond zone + ATR buffer | Zone edge - 10% buffer |

---

## Goals

1. **Align backtesting with production** - Same detection logic, same trading levels
2. **Automated parameter optimization** - Test combinations of SL%, TP%, RR, etc.
3. **Results database** - Store all optimization runs for analysis
4. **Dashboard** - Visualize best parameters per symbol/pattern/timeframe
5. **Auto-tuning** - Optionally apply best parameters to production

---

## Implementation Plan

### Phase 1: Align Backtesting with Production (Foundation)

**Goal**: Make backtesting use the exact same detection logic as production

#### Files to Create
- `app/services/backtester_v2.py` - New backtester using production detectors

#### Files to Modify
- `app/services/patterns/base.py` - Add `detect_historical()` method that doesn't save to DB
- `app/services/patterns/fair_value_gap.py` - Implement `detect_historical()`
- `app/services/patterns/order_block.py` - Implement `detect_historical()`
- `app/services/patterns/liquidity.py` - Implement `detect_historical()`

#### Key Changes

1. Add `detect_historical(df, skip_overlap=False)` to each detector:
```python
def detect_historical(
    self,
    df: pd.DataFrame,
    skip_overlap: bool = False
) -> List[Dict[str, Any]]:
    """
    Detect patterns in historical data without database interaction.

    Args:
        df: DataFrame with OHLCV data
        skip_overlap: If True, skip overlap detection (faster but may have duplicates)

    Returns:
        List of detected patterns (not saved to DB)
    """
```

2. Update backtester to call production detectors instead of inline functions

3. Add configurable parameters:
```python
def run_backtest_v2(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    pattern_type: str = 'imbalance',
    rr_target: float = 2.0,
    sl_buffer_pct: float = 10.0,
    entry_method: str = 'zone_edge',  # or 'zone_mid', 'atr_buffer'
    tp_method: str = 'fixed_rr',  # or 'swing_target', 'atr_multiple'
    min_zone_pct: float = 0.15,
    use_overlap_detection: bool = True
) -> Dict:
```

---

### Phase 2: Parameter Optimization System

**Goal**: Create automated parameter sweep with database storage

#### New Database Models

```python
# app/models/optimization.py

class OptimizationJob(db.Model):
    """Tracks a batch of optimization runs"""
    __tablename__ = 'optimization_jobs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # "BTC FVG Optimization"
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed

    # Scope
    symbols = db.Column(db.Text, nullable=False)  # JSON array: ["BTC/USDT", "ETH/USDT"]
    timeframes = db.Column(db.Text, nullable=False)  # JSON array: ["1h", "4h"]
    pattern_types = db.Column(db.Text, nullable=False)  # JSON array: ["imbalance", "order_block"]
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)

    # Parameter grid (JSON)
    parameter_grid = db.Column(db.Text, nullable=False)

    # Progress
    total_runs = db.Column(db.Integer, default=0)
    completed_runs = db.Column(db.Integer, default=0)
    failed_runs = db.Column(db.Integer, default=0)

    # Best results (JSON)
    best_params_json = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    runs = db.relationship('OptimizationRun', backref='job', lazy='dynamic')


class OptimizationRun(db.Model):
    """Individual backtest run with specific parameters"""
    __tablename__ = 'optimization_runs'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('optimization_jobs.id'), nullable=False)

    # Scope
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(5), nullable=False)
    pattern_type = db.Column(db.String(30), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)

    # Parameters tested
    rr_target = db.Column(db.Float, nullable=False)
    sl_buffer_pct = db.Column(db.Float, nullable=False)
    tp_method = db.Column(db.String(20), nullable=False)  # fixed_rr, swing, atr
    entry_method = db.Column(db.String(20), nullable=False)  # zone_edge, zone_mid
    min_zone_pct = db.Column(db.Float, nullable=False)
    use_overlap = db.Column(db.Boolean, default=True)

    # Results
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    avg_rr = db.Column(db.Float, default=0.0)
    total_profit_pct = db.Column(db.Float, default=0.0)
    max_drawdown = db.Column(db.Float, default=0.0)
    sharpe_ratio = db.Column(db.Float, default=0.0)
    profit_factor = db.Column(db.Float, default=0.0)
    avg_trade_duration = db.Column(db.Float, default=0.0)

    # Detailed results (JSON)
    results_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Indexes for fast queries
    __table_args__ = (
        db.Index('idx_opt_run_job', 'job_id'),
        db.Index('idx_opt_run_symbol_pattern', 'symbol', 'pattern_type'),
        db.Index('idx_opt_run_results', 'win_rate', 'total_profit_pct'),
    )
```

#### Parameter Grid Configuration

```python
# Default parameter grid for optimization
DEFAULT_PARAMETER_GRID = {
    'rr_target': [1.5, 2.0, 2.5, 3.0, 3.5],
    'sl_buffer_pct': [5, 10, 15, 20],
    'min_zone_pct': [0.1, 0.15, 0.2, 0.25],
    'tp_method': ['fixed_rr', 'swing_target', 'atr_multiple'],
    'entry_method': ['zone_edge', 'zone_mid'],
    'use_overlap': [True, False]
}

# Total combinations: 5 × 4 × 4 × 3 × 2 × 2 = 960 runs per symbol/timeframe/pattern
# For 5 symbols × 7 timeframes × 3 patterns = 105 combinations
# Total: 960 × 105 = 100,800 runs (full sweep)

# Recommended: Start with reduced grid
QUICK_PARAMETER_GRID = {
    'rr_target': [2.0, 2.5, 3.0],
    'sl_buffer_pct': [10, 15],
    'min_zone_pct': [0.15],
    'tp_method': ['fixed_rr'],
    'entry_method': ['zone_edge'],
    'use_overlap': [True]
}
# Total: 3 × 2 × 1 × 1 × 1 × 1 = 6 runs per symbol/timeframe/pattern
```

#### Files to Create

1. `app/models/optimization.py` - Database models
2. `app/services/optimizer.py` - Optimization engine
3. `scripts/run_optimization.py` - Cron script for background optimization
4. `app/routes/optimization.py` - Admin routes for managing jobs

#### Optimizer Service

```python
# app/services/optimizer.py

class ParameterOptimizer:
    """Automated parameter sweep for backtesting"""

    def __init__(self):
        self.job = None

    def create_job(
        self,
        name: str,
        symbols: List[str],
        timeframes: List[str],
        pattern_types: List[str],
        start_date: str,
        end_date: str,
        parameter_grid: Dict = None
    ) -> OptimizationJob:
        """Create a new optimization job"""
        pass

    def run_job(self, job_id: int) -> Dict:
        """Execute all runs for a job"""
        pass

    def get_best_params(
        self,
        symbol: str = None,
        pattern_type: str = None,
        metric: str = 'total_profit_pct'
    ) -> Dict:
        """Get best parameters from completed runs"""
        pass

    def compare_params(
        self,
        params_a: Dict,
        params_b: Dict,
        symbol: str,
        timeframe: str,
        pattern_type: str
    ) -> Dict:
        """Compare two parameter sets"""
        pass
```

#### Cron Script

```python
# scripts/run_optimization.py

"""
Run parameter optimization jobs in background.
Usage: python scripts/run_optimization.py [--job-id ID] [--new]

Cron: Run weekly on Sunday at 2 AM
0 2 * * 0 cd /path/to/cryptolens && python scripts/run_optimization.py --new
"""
```

---

### Phase 3: Results Dashboard & Auto-Tuning

**Goal**: Visualize optimization results and apply best parameters

#### Files to Create

1. `app/templates/admin/optimization.html` - Job list and management
2. `app/templates/admin/optimization_detail.html` - Single job results
3. `app/templates/admin/optimization_compare.html` - Parameter comparison

#### Dashboard Features

**1. Optimization Jobs List**
- Status badge (pending/running/completed/failed)
- Progress bar (completed_runs / total_runs)
- Best results summary
- Actions: View, Re-run, Delete

**2. Parameter Heatmap**
```
Win Rate by RR Target vs SL Buffer
         SL 5%   SL 10%  SL 15%  SL 20%
RR 1.5   45%     52%     48%     42%
RR 2.0   38%     55%*    51%     45%
RR 2.5   32%     48%     53%     49%
RR 3.0   28%     42%     47%     51%

* Best combination highlighted
```

**3. Best Parameters Table**

| Symbol | Pattern | Timeframe | RR | SL% | Win Rate | Profit | Current | Action |
|--------|---------|-----------|----|----|----------|--------|---------|--------|
| BTC/USDT | FVG | 1h | 2.5 | 10% | 55% | +23% | RR=2.0 | Apply |
| ETH/USDT | OB | 4h | 3.0 | 15% | 48% | +18% | RR=2.0 | Apply |

**4. Duplicate Pattern Analysis**
```sql
-- Query patterns with >70% overlap
SELECT
    p1.symbol_id,
    p1.timeframe,
    p1.pattern_type,
    COUNT(*) as overlap_count
FROM patterns p1
JOIN patterns p2 ON
    p1.symbol_id = p2.symbol_id
    AND p1.timeframe = p2.timeframe
    AND p1.pattern_type = p2.pattern_type
    AND p1.id < p2.id
    AND ABS(p1.zone_low - p2.zone_low) / p1.zone_low < 0.3
    AND ABS(p1.zone_high - p2.zone_high) / p1.zone_high < 0.3
GROUP BY p1.symbol_id, p1.timeframe, p1.pattern_type
HAVING COUNT(*) > 0;
```

#### Auto-Tuning (Optional)

```python
# app/services/auto_tuner.py

def apply_best_params(
    symbol: str = None,
    pattern_type: str = None,
    min_improvement_pct: float = 5.0,
    dry_run: bool = True
) -> Dict:
    """
    Apply best parameters from optimization to production settings.

    Args:
        symbol: Specific symbol or None for all
        pattern_type: Specific pattern or None for all
        min_improvement_pct: Only apply if improvement > this %
        dry_run: If True, don't actually apply changes

    Returns:
        Dict with changes made/proposed
    """
```

---

## Additional Improvements

### New Metrics to Add

1. **Sharpe Ratio** - Risk-adjusted returns
```python
sharpe = (avg_return - risk_free_rate) / std_dev_returns
```

2. **Profit Factor** - Gross wins / Gross losses
```python
profit_factor = sum(winning_profits) / abs(sum(losing_profits))
```

3. **Sortino Ratio** - Downside risk only
```python
sortino = (avg_return - risk_free_rate) / downside_std_dev
```

4. **Maximum Consecutive Losses** - Drawdown risk
5. **Average Trade Duration** - Time in market
6. **Win/Loss Ratio** - Average win size / Average loss size

### Commission/Slippage Modeling

```python
def apply_trading_costs(
    entry_price: float,
    exit_price: float,
    direction: str,
    commission_pct: float = 0.1,  # 0.1% per trade (0.2% round trip)
    slippage_pct: float = 0.05   # 0.05% slippage
) -> Tuple[float, float]:
    """Adjust prices for realistic trading costs"""
```

### Walk-Forward Analysis

```python
def walk_forward_validation(
    df: pd.DataFrame,
    train_pct: float = 0.7,
    test_pct: float = 0.3,
    n_splits: int = 5
) -> Dict:
    """
    Validate parameters using walk-forward analysis.
    Train on 70%, test on 30%, roll forward.
    """
```

### Monte Carlo Simulation

```python
def monte_carlo_simulation(
    trades: List[Dict],
    n_simulations: int = 1000,
    confidence_level: float = 0.95
) -> Dict:
    """
    Randomize trade order to test robustness.
    Returns confidence intervals for key metrics.
    """
```

---

## Database Migrations

```python
# scripts/migrations/add_optimization_tables.py

def upgrade():
    """Add optimization tables"""
    db.session.execute(text('''
        CREATE TABLE IF NOT EXISTS optimization_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            symbols TEXT NOT NULL,
            timeframes TEXT NOT NULL,
            pattern_types TEXT NOT NULL,
            start_date VARCHAR(20) NOT NULL,
            end_date VARCHAR(20) NOT NULL,
            parameter_grid TEXT NOT NULL,
            total_runs INT DEFAULT 0,
            completed_runs INT DEFAULT 0,
            failed_runs INT DEFAULT 0,
            best_params_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME,
            completed_at DATETIME
        )
    '''))

    db.session.execute(text('''
        CREATE TABLE IF NOT EXISTS optimization_runs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            job_id INT NOT NULL,
            symbol VARCHAR(20) NOT NULL,
            timeframe VARCHAR(5) NOT NULL,
            pattern_type VARCHAR(30) NOT NULL,
            start_date VARCHAR(20) NOT NULL,
            end_date VARCHAR(20) NOT NULL,
            rr_target FLOAT NOT NULL,
            sl_buffer_pct FLOAT NOT NULL,
            tp_method VARCHAR(20) NOT NULL,
            entry_method VARCHAR(20) NOT NULL,
            min_zone_pct FLOAT NOT NULL,
            use_overlap BOOLEAN DEFAULT TRUE,
            status VARCHAR(20) DEFAULT 'pending',
            total_trades INT DEFAULT 0,
            winning_trades INT DEFAULT 0,
            losing_trades INT DEFAULT 0,
            win_rate FLOAT DEFAULT 0.0,
            avg_rr FLOAT DEFAULT 0.0,
            total_profit_pct FLOAT DEFAULT 0.0,
            max_drawdown FLOAT DEFAULT 0.0,
            sharpe_ratio FLOAT DEFAULT 0.0,
            profit_factor FLOAT DEFAULT 0.0,
            avg_trade_duration FLOAT DEFAULT 0.0,
            results_json TEXT,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES optimization_jobs(id),
            INDEX idx_opt_run_job (job_id),
            INDEX idx_opt_run_symbol_pattern (symbol, pattern_type),
            INDEX idx_opt_run_results (win_rate, total_profit_pct)
        )
    '''))
```

---

## Crontab Addition

```bash
# Run optimization weekly (Sunday 2 AM)
0 2 * * 0 cd /path/to/cryptolens && /path/to/venv/bin/python scripts/run_optimization.py --new >> /var/log/cryptolens/optimization.log 2>&1
```

---

## Testing Plan

### Unit Tests

```python
# tests/test_optimizer.py

class TestParameterOptimizer:
    def test_create_job(self):
        """Test job creation with parameter grid"""
        pass

    def test_run_single_optimization(self):
        """Test single parameter combination"""
        pass

    def test_get_best_params(self):
        """Test best parameter retrieval"""
        pass

    def test_parameter_grid_expansion(self):
        """Test grid generates correct combinations"""
        pass


class TestBacktesterV2:
    def test_uses_production_detectors(self):
        """Verify backtester uses production pattern detection"""
        pass

    def test_configurable_sl_buffer(self):
        """Test SL buffer parameter works"""
        pass

    def test_configurable_rr_target(self):
        """Test RR target parameter works"""
        pass
```

---

## Implementation Order

| Phase | Effort | Impact | Dependency |
|-------|--------|--------|------------|
| Phase 1 | Medium | High | None - fixes core issue |
| Phase 2 | Large | High | Phase 1 |
| Phase 3 | Medium | Medium | Phase 2 |

**Recommendation**: Start with Phase 1 to fix the production/backtest mismatch. This is the foundation - without it, optimization results won't match live performance.

---

## Files Summary

### New Files to Create
- `app/models/optimization.py`
- `app/services/backtester_v2.py`
- `app/services/optimizer.py`
- `app/services/auto_tuner.py`
- `app/routes/optimization.py`
- `app/templates/admin/optimization.html`
- `app/templates/admin/optimization_detail.html`
- `app/templates/admin/optimization_compare.html`
- `scripts/run_optimization.py`
- `scripts/migrations/add_optimization_tables.py`
- `tests/test_optimizer.py`

### Files to Modify
- `app/services/patterns/base.py` - Add `detect_historical()`
- `app/services/patterns/fair_value_gap.py` - Implement `detect_historical()`
- `app/services/patterns/order_block.py` - Implement `detect_historical()`
- `app/services/patterns/liquidity.py` - Implement `detect_historical()`
- `app/models/__init__.py` - Export new models
- `app/routes/__init__.py` - Register optimization blueprint
- `app/templates/admin/index.html` - Add optimization link
- `crontab.txt` - Add optimization cron job
