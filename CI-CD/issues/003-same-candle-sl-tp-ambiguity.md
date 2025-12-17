# Issue #003: Same-Candle Stop Loss / Take Profit Ambiguity

## Severity: High

## Location
`app/services/backtester.py:228-281`

## Description
When simulating trades, the code checks if stop loss is hit before checking take profit. This creates a bias where trades are marked as losses when both SL and TP levels are crossed within the same candle.

## Current Logic
```python
if direction == 'long':
    if candle['low'] <= stop_loss:      # Checked FIRST
        return {..., 'result': 'loss'}
    elif candle['high'] >= take_profit:  # Checked SECOND
        return {..., 'result': 'win'}
```

## Problem Scenario
Consider a candle with:
- Low: 97
- High: 105
- Stop Loss: 98
- Take Profit: 104

Both conditions are true:
- `97 <= 98` (SL hit) ✓
- `105 >= 104` (TP hit) ✓

Current code returns **loss**, but the trade might have actually **won** if price hit TP before SL.

## Impact
- Backtest results are pessimistically biased
- Win rate may be artificially lower than real trading
- Users may reject profitable strategies based on inaccurate data

## Possible Solutions

### Option A: Conservative (Mark as Inconclusive)
```python
if candle['low'] <= stop_loss and candle['high'] >= take_profit:
    return {
        ...,
        'result': 'inconclusive',
        'rr_achieved': 0,
        'note': 'Both SL and TP hit in same candle'
    }
```

### Option B: Use OHLC Order Heuristic
Assume candle follows Open → High/Low → Close path based on candle color:
- Bullish candle (close > open): Open → Low → High → Close
- Bearish candle (close < open): Open → High → Low → Close

### Option C: Split the Difference
Count as 50% win rate contribution to statistics.

## Recommended Fix
Option A is the safest - mark these trades as inconclusive and let users decide how to interpret them.
