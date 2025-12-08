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

    Args:
        df: DataFrame with OHLCV data
        pattern_type: 'imbalance', 'order_block', or 'liquidity_sweep'
        rr_target: Target risk/reward ratio

    Returns:
        List of simulated trades
    """
    if pattern_type == 'imbalance':
        return _detect_imbalance_trades(df, rr_target)
    elif pattern_type == 'order_block':
        return _detect_order_block_trades(df, rr_target)
    elif pattern_type == 'liquidity_sweep':
        return _detect_liquidity_sweep_trades(df, rr_target)
    else:
        # Default to imbalance for unknown types
        return _detect_imbalance_trades(df, rr_target)


def _detect_imbalance_trades(df: pd.DataFrame, rr_target: float) -> List[Dict]:
    """Detect and simulate FVG/Imbalance pattern trades"""
    trades = []

    for i in range(2, len(df) - 10):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]

        pattern = None

        # Bullish FVG: Gap between c1 high and c3 low
        if c1['high'] < c3['low']:
            pattern = {
                'direction': 'bullish',
                'zone_high': c3['low'],
                'zone_low': c1['high'],
                'detected_at': i,
                'pattern_type': 'imbalance'
            }

        # Bearish FVG: Gap between c1 low and c3 high
        elif c1['low'] > c3['high']:
            pattern = {
                'direction': 'bearish',
                'zone_high': c1['low'],
                'zone_low': c3['high'],
                'detected_at': i,
                'pattern_type': 'imbalance'
            }

        if pattern:
            trade = simulate_single_trade(df, i, pattern, rr_target)
            if trade:
                trade['pattern_type'] = 'imbalance'
                trades.append(trade)

    return trades


def _detect_order_block_trades(df: pd.DataFrame, rr_target: float) -> List[Dict]:
    """Detect and simulate Order Block pattern trades"""
    trades = []

    # Calculate candle body and move strength
    df = df.copy()
    df['body'] = df['close'] - df['open']
    df['body_size'] = abs(df['body'])
    df['is_bullish'] = df['body'] > 0
    df['is_bearish'] = df['body'] < 0

    # Calculate average body size for comparison
    avg_body = df['body_size'].rolling(20).mean()

    for i in range(3, len(df) - 10):
        current_body = df.iloc[i]['body_size']

        if pd.isna(avg_body.iloc[i]) or avg_body.iloc[i] == 0:
            continue

        # Check for strong move (body larger than 1.5x average)
        is_strong_move = current_body > (avg_body.iloc[i] * Config.ORDER_BLOCK_STRENGTH_MULTIPLIER)
        if not is_strong_move:
            continue

        pattern = None

        # Bullish OB: Last bearish candle before strong bullish move
        if df.iloc[i]['is_bullish']:
            # Look back for last bearish candle
            for j in range(i - 1, max(i - 4, 0), -1):
                if df.iloc[j]['is_bearish']:
                    zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                    zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])
                    pattern = {
                        'direction': 'bullish',
                        'zone_high': zone_high,
                        'zone_low': zone_low,
                        'detected_at': i,
                        'pattern_type': 'order_block'
                    }
                    break

        # Bearish OB: Last bullish candle before strong bearish move
        elif df.iloc[i]['is_bearish']:
            for j in range(i - 1, max(i - 4, 0), -1):
                if df.iloc[j]['is_bullish']:
                    zone_high = max(df.iloc[j]['open'], df.iloc[j]['close'])
                    zone_low = min(df.iloc[j]['open'], df.iloc[j]['close'])
                    pattern = {
                        'direction': 'bearish',
                        'zone_high': zone_high,
                        'zone_low': zone_low,
                        'detected_at': i,
                        'pattern_type': 'order_block'
                    }
                    break

        if pattern:
            trade = simulate_single_trade(df, i, pattern, rr_target)
            if trade:
                trade['pattern_type'] = 'order_block'
                trades.append(trade)

    return trades


def _find_swing_points(df: pd.DataFrame, lookback: int = 5) -> tuple:
    """Find swing highs and swing lows for liquidity sweep detection"""
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        # Check for swing high
        is_swing_high = True
        for j in range(1, lookback + 1):
            if df.iloc[i]['high'] <= df.iloc[i - j]['high'] or \
               df.iloc[i]['high'] <= df.iloc[i + j]['high']:
                is_swing_high = False
                break

        if is_swing_high:
            swing_highs.append({
                'index': i,
                'price': df.iloc[i]['high']
            })

        # Check for swing low
        is_swing_low = True
        for j in range(1, lookback + 1):
            if df.iloc[i]['low'] >= df.iloc[i - j]['low'] or \
               df.iloc[i]['low'] >= df.iloc[i + j]['low']:
                is_swing_low = False
                break

        if is_swing_low:
            swing_lows.append({
                'index': i,
                'price': df.iloc[i]['low']
            })

    return swing_highs, swing_lows


def _detect_liquidity_sweep_trades(df: pd.DataFrame, rr_target: float) -> List[Dict]:
    """Detect and simulate Liquidity Sweep pattern trades"""
    trades = []

    # Find swing points
    swing_highs, swing_lows = _find_swing_points(df, lookback=3)

    for i in range(10, len(df) - 10):
        current = df.iloc[i]
        pattern = None

        # Check for bullish sweep (sweep of lows)
        for swing_low in swing_lows:
            # Skip if swing is too recent or too old
            if swing_low['index'] >= i - 3 or swing_low['index'] < i - 50:
                continue

            # Check if current candle swept the low and reversed
            if current['low'] < swing_low['price'] and current['close'] > swing_low['price']:
                zone_low = current['low']
                zone_high = swing_low['price']

                # Ensure zone is valid
                if zone_high > zone_low:
                    pattern = {
                        'direction': 'bullish',
                        'zone_high': zone_high,
                        'zone_low': zone_low,
                        'detected_at': i,
                        'pattern_type': 'liquidity_sweep'
                    }
                    break

        # Check for bearish sweep (sweep of highs)
        if pattern is None:
            for swing_high in swing_highs:
                if swing_high['index'] >= i - 3 or swing_high['index'] < i - 50:
                    continue

                if current['high'] > swing_high['price'] and current['close'] < swing_high['price']:
                    zone_high = current['high']
                    zone_low = swing_high['price']

                    if zone_high > zone_low:
                        pattern = {
                            'direction': 'bearish',
                            'zone_high': zone_high,
                            'zone_low': zone_low,
                            'detected_at': i,
                            'pattern_type': 'liquidity_sweep'
                        }
                        break

        if pattern:
            trade = simulate_single_trade(df, i, pattern, rr_target)
            if trade:
                trade['pattern_type'] = 'liquidity_sweep'
                trades.append(trade)

    return trades


def simulate_single_trade(df: pd.DataFrame, entry_idx: int, pattern: Dict,
                          rr_target: float) -> Optional[Dict]:
    """
    Simulate a single trade from pattern detection to outcome

    Returns:
        Trade result or None
    """
    # Convert numpy types to native Python types
    zone_high = float(pattern['zone_high'])
    zone_low = float(pattern['zone_low'])
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
                        'entry_price': float(entry),
                        'exit_price': float(stop_loss),
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1.0,
                        'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
                elif candle['high'] >= take_profit:
                    # Take profit hit
                    return {
                        'entry_price': float(entry),
                        'exit_price': float(take_profit),
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': float(rr_target),
                        'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
            else:  # short
                if candle['high'] >= stop_loss:
                    # Stop loss hit
                    return {
                        'entry_price': float(entry),
                        'exit_price': float(stop_loss),
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1.0,
                        'profit_pct': float(-abs((stop_loss - entry) / entry * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
                elif candle['low'] <= take_profit:
                    # Take profit hit
                    return {
                        'entry_price': float(entry),
                        'exit_price': float(take_profit),
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': float(rr_target),
                        'profit_pct': float(abs((take_profit - entry) / entry * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
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
