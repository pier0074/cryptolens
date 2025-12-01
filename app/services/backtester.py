"""
Backtesting Service
Historical pattern detection and trade simulation
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from app.models import Symbol, Backtest
from app.config import Config
from app import db


def run_backtest(symbol: str, timeframe: str, start_date: str, end_date: str,
                 pattern_type: str = 'imbalance', rr_target: float = 2.0) -> Dict:
    """
    Run a backtest for a specific pattern strategy

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        pattern_type: Pattern type to test
        rr_target: Target risk/reward ratio

    Returns:
        Backtest results
    """
    from app.services.aggregator import get_candles_as_dataframe

    # Get historical data
    df = get_candles_as_dataframe(symbol, timeframe, limit=5000)

    if df.empty:
        return {'error': 'No data available for backtesting'}

    # Filter by date range
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

    df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] <= end_ts)]

    if len(df) < 10:
        return {'error': 'Insufficient data for backtesting'}

    # Run pattern detection and simulation
    trades = simulate_trades(df, pattern_type, rr_target)

    # Calculate statistics
    stats = calculate_statistics(trades)

    # Save backtest result
    backtest = Backtest(
        name=f"{symbol} {timeframe} {pattern_type}",
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        pattern_type=pattern_type,
        total_trades=stats['total_trades'],
        winning_trades=stats['winning_trades'],
        losing_trades=stats['losing_trades'],
        win_rate=stats['win_rate'],
        avg_rr=stats['avg_rr'],
        total_profit_pct=stats['total_profit_pct'],
        max_drawdown=stats['max_drawdown'],
        results_json=json.dumps(trades)
    )
    db.session.add(backtest)
    db.session.commit()

    return {
        'id': backtest.id,
        **stats,
        'trades': trades[:50]  # Return first 50 trades for display
    }


def simulate_trades(df: pd.DataFrame, pattern_type: str, rr_target: float) -> List[Dict]:
    """
    Simulate trades based on detected patterns

    Returns:
        List of simulated trades
    """
    trades = []

    for i in range(2, len(df) - 10):  # Leave room for trade to play out
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]

        pattern = None

        # Detect bullish imbalance
        if c1['high'] < c3['low']:
            pattern = {
                'direction': 'bullish',
                'zone_high': c3['low'],
                'zone_low': c1['high'],
                'detected_at': i
            }

        # Detect bearish imbalance
        elif c1['low'] > c3['high']:
            pattern = {
                'direction': 'bearish',
                'zone_high': c1['low'],
                'zone_low': c3['high'],
                'detected_at': i
            }

        if pattern:
            # Simulate the trade
            trade = simulate_single_trade(df, i, pattern, rr_target)
            if trade:
                trades.append(trade)

    return trades


def simulate_single_trade(df: pd.DataFrame, entry_idx: int, pattern: Dict,
                          rr_target: float) -> Optional[Dict]:
    """
    Simulate a single trade from pattern detection to outcome

    Returns:
        Trade result or None
    """
    zone_high = pattern['zone_high']
    zone_low = pattern['zone_low']
    zone_size = zone_high - zone_low
    buffer = zone_size * 0.1

    if pattern['direction'] == 'bullish':
        entry = zone_high
        stop_loss = zone_low - buffer
        risk = entry - stop_loss
        take_profit = entry + (risk * rr_target)
        direction = 'long'
    else:
        entry = zone_low
        stop_loss = zone_high + buffer
        risk = stop_loss - entry
        take_profit = entry - (risk * rr_target)
        direction = 'short'

    # Look for entry trigger and outcome
    entry_triggered = False
    entry_candle = None

    for j in range(entry_idx + 1, min(entry_idx + 100, len(df))):
        candle = df.iloc[j]

        if not entry_triggered:
            # Check if price enters the zone (entry triggered)
            if direction == 'long':
                if candle['low'] <= entry:
                    entry_triggered = True
                    entry_candle = j
            else:  # short
                if candle['high'] >= entry:
                    entry_triggered = True
                    entry_candle = j

        else:
            # Trade is active, check for SL or TP
            if direction == 'long':
                if candle['low'] <= stop_loss:
                    # Stop loss hit
                    return {
                        'entry_price': entry,
                        'exit_price': stop_loss,
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1,
                        'profit_pct': -abs((stop_loss - entry) / entry * 100),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': j - entry_candle
                    }
                elif candle['high'] >= take_profit:
                    # Take profit hit
                    return {
                        'entry_price': entry,
                        'exit_price': take_profit,
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': rr_target,
                        'profit_pct': abs((take_profit - entry) / entry * 100),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': j - entry_candle
                    }
            else:  # short
                if candle['high'] >= stop_loss:
                    # Stop loss hit
                    return {
                        'entry_price': entry,
                        'exit_price': stop_loss,
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1,
                        'profit_pct': -abs((stop_loss - entry) / entry * 100),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': j - entry_candle
                    }
                elif candle['low'] <= take_profit:
                    # Take profit hit
                    return {
                        'entry_price': entry,
                        'exit_price': take_profit,
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': rr_target,
                        'profit_pct': abs((take_profit - entry) / entry * 100),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': j - entry_candle
                    }

    return None  # Trade didn't complete in the lookback period


def calculate_statistics(trades: List[Dict]) -> Dict:
    """
    Calculate performance statistics from trades

    Returns:
        Statistics dict
    """
    if not trades:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'avg_rr': 0,
            'total_profit_pct': 0,
            'max_drawdown': 0,
            'avg_duration': 0
        }

    winning = [t for t in trades if t['result'] == 'win']
    losing = [t for t in trades if t['result'] == 'loss']

    total_trades = len(trades)
    winning_trades = len(winning)
    losing_trades = len(losing)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    # Average R:R
    avg_rr = sum(t['rr_achieved'] for t in trades) / total_trades if total_trades > 0 else 0

    # Total profit
    total_profit_pct = sum(t['profit_pct'] for t in trades)

    # Max drawdown (simplified)
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cumulative += t['profit_pct']
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    # Average duration
    avg_duration = sum(t['duration_candles'] for t in trades) / total_trades if total_trades > 0 else 0

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': round(win_rate, 2),
        'avg_rr': round(avg_rr, 2),
        'total_profit_pct': round(total_profit_pct, 2),
        'max_drawdown': round(max_dd, 2),
        'avg_duration': round(avg_duration, 1)
    }
