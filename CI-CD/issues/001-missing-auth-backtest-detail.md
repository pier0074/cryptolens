# Issue #001: Missing Authentication on Backtest Detail Route

## Severity: Critical

## Location
`app/routes/backtest.py:60-66`

## Description
The `detail()` endpoint for viewing individual backtest results lacks both `@login_required` and `@feature_required('backtest')` decorators, unlike the other routes in the same file.

## Current Code
```python
@backtest_bp.route('/<int:backtest_id>')
def detail(backtest_id):
    """Backtest detail view"""
    backtest = db.session.get(Backtest, backtest_id)
    if backtest is None:
        abort(404)
    return render_template('backtest_detail.html', backtest=backtest)
```

## Expected Code
```python
@backtest_bp.route('/<int:backtest_id>')
@login_required
@feature_required('backtest')
def detail(backtest_id):
    """Backtest detail view"""
    backtest = db.session.get(Backtest, backtest_id)
    if backtest is None:
        abort(404)
    return render_template('backtest_detail.html', backtest=backtest)
```

## Impact
- Unauthenticated users can view any backtest result by ID
- Premium feature accessible without subscription
- Potential data exposure

## Steps to Reproduce
1. Log out of the application
2. Navigate to `/backtest/1` (or any valid backtest ID)
3. Observe that the page loads without authentication

## Recommended Fix
Add the missing decorators to match the other routes in the file.
