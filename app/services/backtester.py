"""
Backtesting Service
Historical pattern detection and trade simulation

Uses production pattern detectors for consistency between live and backtest.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from app.models import Symbol, Backtest
from app.config import Config
from app import db
from app.services.logger import log_backtest
from app.services.patterns.fair_value_gap import FVGDetector
from app.services.patterns.order_block import OrderBlockDetector
from app.services.patterns.liquidity import LiquiditySweepDetector

# Singleton instances for backtesting (no DB interaction)
_fvg_detector = FVGDetector()
_ob_detector = OrderBlockDetector()
_sweep_detector = LiquiditySweepDetector()


def run_backtest(symbol: str, timeframe: str, start_date: str, end_date: str,
                 pattern_type: str = 'imbalance', rr_target: float = 2.0,
                 sl_buffer_pct: float = 10.0) -> Dict:
    """
    Run a backtest for a specific pattern strategy

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        pattern_type: Pattern type to test
        rr_target: Target risk/reward ratio
        sl_buffer_pct: Stop loss buffer as percentage of zone size (default 10%)

    Returns:
        Backtest results
    """
    from app.services.aggregator import get_candles_as_dataframe

    log_backtest(
        f"Starting backtest: {pattern_type} strategy, RR={rr_target}",
        symbol=symbol,
        timeframe=timeframe,
        details={'start_date': start_date, 'end_date': end_date, 'pattern_type': pattern_type, 'rr_target': rr_target}
    )

    # Get historical data
    df = get_candles_as_dataframe(symbol, timeframe, limit=5000)

    if df.empty:
        log_backtest(
            "Backtest failed: No data available",
            symbol=symbol,
            timeframe=timeframe,
            level='WARNING'
        )
        return {'error': 'No data available for backtesting'}

    # Filter by date range
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

    df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] <= end_ts)]

    if len(df) < 10:
        log_backtest(
            f"Backtest failed: Insufficient data ({len(df)} candles)",
            symbol=symbol,
            timeframe=timeframe,
            level='WARNING'
        )
        return {'error': 'Insufficient data for backtesting'}

    log_backtest(
        f"Processing {len(df)} candles for backtest",
        symbol=symbol,
        timeframe=timeframe
    )

    # Run pattern detection and simulation
    trades = simulate_trades(df, pattern_type, rr_target, sl_buffer_pct)

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

    log_backtest(
        f"Backtest complete: {stats['total_trades']} trades, {stats['win_rate']}% win rate, {stats['total_profit_pct']}% profit",
        symbol=symbol,
        timeframe=timeframe,
        details={
            'backtest_id': backtest.id,
            'total_trades': stats['total_trades'],
            'winning_trades': stats['winning_trades'],
            'losing_trades': stats['losing_trades'],
            'win_rate': stats['win_rate'],
            'avg_rr': stats['avg_rr'],
            'total_profit_pct': stats['total_profit_pct'],
            'max_drawdown': stats['max_drawdown']
        }
    )

    return {
        'id': backtest.id,
        **stats,
        'trades': trades[:50]  # Return first 50 trades for display
    }


def simulate_trades(df: pd.DataFrame, pattern_type: str, rr_target: float,
                    sl_buffer_pct: float = 10.0) -> List[Dict]:
    """
    Simulate trades based on detected patterns using production detectors.

    Args:
        df: DataFrame with OHLCV data
        pattern_type: 'imbalance', 'order_block', or 'liquidity_sweep'
        rr_target: Target risk/reward ratio
        sl_buffer_pct: Stop loss buffer as percentage of zone size (default 10%)

    Returns:
        List of simulated trades
    """
    # Select the appropriate detector
    if pattern_type == 'imbalance':
        detector = _fvg_detector
    elif pattern_type == 'order_block':
        detector = _ob_detector
    elif pattern_type == 'liquidity_sweep':
        detector = _sweep_detector
    else:
        detector = _fvg_detector  # Default

    # Detect patterns using production logic (no DB interaction)
    patterns = detector.detect_historical(df, skip_overlap=True)

    # Simulate trades for each detected pattern
    trades = []
    for pattern in patterns:
        trade = simulate_single_trade(df, pattern['detected_at'], pattern, rr_target, sl_buffer_pct)
        if trade:
            trade['pattern_type'] = pattern_type
            trades.append(trade)

    return trades


def simulate_single_trade(df: pd.DataFrame, entry_idx: int, pattern: Dict,
                          rr_target: float, sl_buffer_pct: float = 10.0) -> Optional[Dict]:
    """
    Simulate a single trade from pattern detection to outcome.

    This function uses the same logic as the optimizer for consistency.

    Args:
        df: DataFrame with OHLCV data
        entry_idx: Index where pattern was detected
        pattern: Pattern dict with zone_high, zone_low, direction
        rr_target: Target risk/reward ratio
        sl_buffer_pct: Stop loss buffer as percentage of zone size

    Returns:
        Trade result or None
    """
    # Convert numpy types to native Python types
    zone_high = float(pattern['zone_high'])
    zone_low = float(pattern['zone_low'])
    zone_size = zone_high - zone_low
    buffer = zone_size * (sl_buffer_pct / 100.0)

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
