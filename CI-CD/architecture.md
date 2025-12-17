# CI/CD Architecture

## Overview

This document describes the continuous integration and continuous deployment architecture for the Cryptolens project.

## Project Structure

```
cryptolens/
├── app/
│   ├── models/          # Database models
│   ├── routes/          # Flask blueprints/endpoints
│   ├── services/        # Business logic
│   │   ├── patterns/    # Pattern detection (FVG, OB, Liquidity)
│   │   ├── backtester.py
│   │   ├── optimizer.py
│   │   └── aggregator.py
│   └── templates/       # Jinja2 templates
├── tests/               # Test suite
├── scripts/             # Utility scripts
└── CI-CD/               # CI/CD documentation
    ├── architecture.md
    ├── todo.md
    ├── features/
    ├── issues/
    └── reports/
```

## Key Components

### 1. Pattern Detection Layer
- **FVGDetector**: Fair Value Gap detection
- **OrderBlockDetector**: Order block identification
- **LiquiditySweepDetector**: Liquidity sweep patterns
- All inherit from `PatternDetector` base class

### 2. Backtesting Service
- Historical pattern detection
- Trade simulation engine
- Statistics calculation
- Database persistence

### 3. Optimization Service
- Parameter sweep functionality
- Incremental optimization support
- Results caching

## Data Flow

```
[Exchange API] → [Data Fetcher] → [Aggregator] → [Pattern Detectors]
                                       ↓
                              [Backtester Service]
                                       ↓
                              [Trade Simulation]
                                       ↓
                              [Statistics Engine]
                                       ↓
                              [Database Storage]
```

## Testing Strategy

### Unit Tests
- `test_backtester.py`: Backtesting logic
- `test_routes.py`: API endpoints
- `test_tiers.py`: Access control

### Integration Tests
- Full backtest workflow
- Database interactions
- Pattern detection accuracy

## Deployment Pipeline

1. **Code Push** → GitHub
2. **CI Trigger** → Run tests
3. **Code Review** → Manual approval
4. **Staging Deploy** → Test environment
5. **Production Deploy** → Live environment

## Environment Configuration

| Environment | Database | Debug | Features |
|-------------|----------|-------|----------|
| Development | SQLite | True | All |
| Testing | SQLite (memory) | True | All |
| Staging | PostgreSQL | False | All |
| Production | PostgreSQL | False | Tiered |
