# Issue #002: Missing Input Validation on Backtest Run Endpoint

## Severity: Critical

## Location
`app/routes/backtest.py:31-36`

## Description
The `/run` endpoint extracts user input without validating required fields or formats before passing to the backtest service.

## Current Code
```python
data = request.get_json()

symbol = data.get('symbol')
timeframe = data.get('timeframe')
start_date = data.get('start_date')
end_date = data.get('end_date')
pattern_type = data.get('pattern_type', 'imbalance')
```

## Issues
1. `symbol` could be `None` or empty string
2. `timeframe` could be `None` or invalid value
3. `start_date` and `end_date` not validated for format (YYYY-MM-DD)
4. No check if `end_date` is after `start_date`
5. No check if `data` itself is `None` (malformed JSON)

## Impact
- Server crashes on malformed input
- `datetime.strptime()` raises unhandled `ValueError` on invalid dates
- Confusing error messages for users

## Recommended Fix
```python
data = request.get_json()
if not data:
    return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

symbol = data.get('symbol')
timeframe = data.get('timeframe')
start_date = data.get('start_date')
end_date = data.get('end_date')

# Validate required fields
if not all([symbol, timeframe, start_date, end_date]):
    return jsonify({
        'success': False,
        'error': 'Missing required fields: symbol, timeframe, start_date, end_date'
    }), 400

# Validate date format
try:
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
except ValueError:
    return jsonify({
        'success': False,
        'error': 'Invalid date format. Use YYYY-MM-DD'
    }), 400

if end_dt <= start_dt:
    return jsonify({
        'success': False,
        'error': 'end_date must be after start_date'
    }), 400

# Validate timeframe
if timeframe not in Config.TIMEFRAMES:
    return jsonify({
        'success': False,
        'error': f'Invalid timeframe. Must be one of: {Config.TIMEFRAMES}'
    }), 400
```
