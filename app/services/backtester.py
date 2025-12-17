"""
Backtesting Service
Historical pattern detection and trade simulation

Uses production pattern detectors for consistency between live and backtest.
"""
import json
from datetime import datetime, timezone
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

# Minimum candles required for meaningful backtest
MIN_CANDLES_REQUIRED = 10

# Lookback periods by timeframe (higher timeframes need longer lookback)
LOOKBACK_BY_TIMEFRAME = {
    '5m': 200,   # ~16 hours
    '15m': 150,  # ~37 hours
    '30m': 120,  # ~60 hours
    '1h': 100,   # ~4 days
    '2h': 80,    # ~6 days
    '4h': 60,    # ~10 days
    '1d': 30,    # ~30 days
}
DEFAULT_LOOKBACK = 100


def run_backtest(symbol: str, timeframe: str, start_date: str, end_date: str,
                 pattern_type: str = 'imbalance', rr_target: float = 2.0,
                 sl_buffer_pct: float = 10.0, slippage_pct: float = 0.0,
                 page: int = 1, per_page: int = 50) -> Dict:
    """
    Run a backtest for a specific pattern strategy

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        pattern_type: Pattern type to test ('imbalance', 'order_block', 'liquidity_sweep')
        rr_target: Target risk/reward ratio (must be > 0)
        sl_buffer_pct: Stop loss buffer as percentage of zone size (default 10%)
        slippage_pct: Slippage as percentage of entry price (default 0%)
        page: Page number for trade results (default: 1)
        per_page: Trades per page (default: 50, use -1 for all)

    Returns:
        Backtest results with paginated trades
    """
    from app.services.aggregator import get_candles_as_dataframe

    # Validate pattern type
    valid_types = ['imbalance', 'order_block', 'liquidity_sweep']
    if pattern_type not in valid_types:
        return {'error': f'Invalid pattern type. Must be one of: {valid_types}'}

    # Validate dates early (before fetching data)
    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        # End of day for end_date
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
    except ValueError as e:
        log_backtest(
            f"Backtest failed: Invalid date format - {e}",
            symbol=symbol,
            timeframe=timeframe,
            level='ERROR'
        )
        return {'error': f'Invalid date format: {e}. Use YYYY-MM-DD'}

    log_backtest(
        f"Starting backtest: {pattern_type} strategy, RR={rr_target}, slippage={slippage_pct}%",
        symbol=symbol,
        timeframe=timeframe,
        details={
            'start_date': start_date,
            'end_date': end_date,
            'pattern_type': pattern_type,
            'rr_target': rr_target,
            'slippage_pct': slippage_pct
        }
    )

    # Get historical data (no limit - date range filtering handles boundaries)
    df = get_candles_as_dataframe(symbol, timeframe)

    if df.empty:
        log_backtest(
            "Backtest failed: No data available",
            symbol=symbol,
            timeframe=timeframe,
            level='WARNING'
        )
        return {'error': 'No data available for backtesting'}

    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] <= end_ts)]

    if len(df) < MIN_CANDLES_REQUIRED:
        log_backtest(
            f"Backtest failed: Insufficient data ({len(df)} candles, need {MIN_CANDLES_REQUIRED})",
            symbol=symbol,
            timeframe=timeframe,
            level='WARNING'
        )
        return {'error': f'Insufficient data for backtesting (got {len(df)} candles, need at least {MIN_CANDLES_REQUIRED})'}

    log_backtest(
        f"Processing {len(df)} candles for backtest",
        symbol=symbol,
        timeframe=timeframe
    )

    # Get lookback period for this timeframe
    lookback = LOOKBACK_BY_TIMEFRAME.get(timeframe, DEFAULT_LOOKBACK)

    # Run pattern detection and simulation with slippage
    trades = simulate_trades(df, pattern_type, rr_target, sl_buffer_pct, slippage_pct, timeframe)

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
            'max_drawdown': stats['max_drawdown'],
            'inconclusive_trades': stats['inconclusive_trades']
        }
    )

    # Pagination for trades
    total_trades_count = len(trades)
    if per_page == -1:
        # Return all trades
        paginated_trades = trades
    else:
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_trades = trades[start_idx:end_idx]

    return {
        'id': backtest.id,
        **stats,
        'trades': paginated_trades,
        'pagination': {
            'page': page,
            'per_page': per_page if per_page != -1 else total_trades_count,
            'total_trades': total_trades_count,
            'total_pages': (total_trades_count + per_page - 1) // per_page if per_page > 0 else 1
        }
    }


def simulate_trades(df: pd.DataFrame, pattern_type: str, rr_target: float,
                    sl_buffer_pct: float = 10.0, slippage_pct: float = 0.0,
                    timeframe: str = '1h') -> List[Dict]:
    """
    Simulate trades based on detected patterns using production detectors.

    Args:
        df: DataFrame with OHLCV data
        pattern_type: 'imbalance', 'order_block', or 'liquidity_sweep'
        rr_target: Target risk/reward ratio
        sl_buffer_pct: Stop loss buffer as percentage of zone size (default 10%)
        slippage_pct: Slippage as percentage of entry price (default 0%)
        timeframe: Timeframe for lookback calculation (default '1h')

    Returns:
        List of simulated trades
    """
    # Select the appropriate detector - raise error for invalid types
    if pattern_type == 'imbalance':
        detector = _fvg_detector
    elif pattern_type == 'order_block':
        detector = _ob_detector
    elif pattern_type == 'liquidity_sweep':
        detector = _sweep_detector
    else:
        raise ValueError(f"Invalid pattern type: {pattern_type}. Must be 'imbalance', 'order_block', or 'liquidity_sweep'")

    # Get lookback period for this timeframe
    lookback = LOOKBACK_BY_TIMEFRAME.get(timeframe, DEFAULT_LOOKBACK)

    # Detect patterns using production logic (no DB interaction)
    patterns = detector.detect_historical(df, skip_overlap=True)

    # Simulate trades for each detected pattern
    trades = []
    for pattern in patterns:
        trade = simulate_single_trade(
            df, pattern['detected_at'], pattern, rr_target, sl_buffer_pct,
            slippage_pct, lookback
        )
        if trade:
            trade['pattern_type'] = pattern_type
            trades.append(trade)

    return trades


def simulate_single_trade(df: pd.DataFrame, entry_idx: int, pattern: Dict,
                          rr_target: float, sl_buffer_pct: float = 10.0,
                          slippage_pct: float = 0.0, lookback: int = 100) -> Optional[Dict]:
    """
    Simulate a single trade from pattern detection to outcome.

    Handles:
    - Slippage modeling: entry price adjusted by slippage percentage
    - Same-candle SL/TP ambiguity: marks as 'inconclusive' when both could be hit
    - Configurable lookback period per timeframe

    Args:
        df: DataFrame with OHLCV data
        entry_idx: Index where pattern was detected
        pattern: Pattern dict with zone_high, zone_low, direction
        rr_target: Target risk/reward ratio
        sl_buffer_pct: Stop loss buffer as percentage of zone size
        slippage_pct: Slippage as percentage of entry price (default 0%)
        lookback: Maximum candles to look ahead for trade completion

    Returns:
        Trade result dict or None if trade didn't trigger/complete
    """
    # Convert numpy types to native Python types
    zone_high = float(pattern['zone_high'])
    zone_low = float(pattern['zone_low'])
    zone_size = zone_high - zone_low
    buffer = zone_size * (sl_buffer_pct / 100.0)

    if pattern['direction'] == 'bullish':
        # For long: entry at zone high, with slippage we get worse price (higher)
        ideal_entry = zone_high
        slippage_amount = ideal_entry * (slippage_pct / 100.0)
        entry = ideal_entry + slippage_amount  # Worse entry for long
        stop_loss = zone_low - buffer
        risk = entry - stop_loss
        take_profit = entry + (risk * rr_target)
        direction = 'long'
    else:
        # For short: entry at zone low, with slippage we get worse price (lower)
        ideal_entry = zone_low
        slippage_amount = ideal_entry * (slippage_pct / 100.0)
        entry = ideal_entry - slippage_amount  # Worse entry for short
        stop_loss = zone_high + buffer
        risk = stop_loss - entry
        take_profit = entry - (risk * rr_target)
        direction = 'short'

    # Look for entry trigger and outcome
    entry_triggered = False
    entry_candle = None
    actual_entry_price = entry  # May be updated based on candle

    for j in range(entry_idx + 1, min(entry_idx + lookback, len(df))):
        candle = df.iloc[j]

        if not entry_triggered:
            # Check if price enters the zone (entry triggered)
            if direction == 'long':
                if candle['low'] <= ideal_entry:
                    entry_triggered = True
                    entry_candle = j
                    # More realistic: entry might be at open if gapped, or at zone edge
                    if candle['open'] <= ideal_entry:
                        actual_entry_price = candle['open'] + slippage_amount
                    else:
                        actual_entry_price = entry
            else:  # short
                if candle['high'] >= ideal_entry:
                    entry_triggered = True
                    entry_candle = j
                    if candle['open'] >= ideal_entry:
                        actual_entry_price = candle['open'] - slippage_amount
                    else:
                        actual_entry_price = entry

        else:
            # Trade is active, check for SL or TP
            # Recalculate TP based on actual entry
            if direction == 'long':
                actual_risk = actual_entry_price - stop_loss
                actual_tp = actual_entry_price + (actual_risk * rr_target)

                sl_hit = candle['low'] <= stop_loss
                tp_hit = candle['high'] >= actual_tp

                # Handle same-candle ambiguity
                if sl_hit and tp_hit:
                    # Both SL and TP could have been hit - mark as inconclusive
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(actual_entry_price),  # No P&L for inconclusive
                        'direction': direction,
                        'result': 'inconclusive',
                        'rr_achieved': 0.0,
                        'profit_pct': 0.0,
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle),
                        'note': 'Both SL and TP touched in same candle - outcome uncertain'
                    }
                elif sl_hit:
                    # Stop loss hit
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(stop_loss),
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1.0,
                        'profit_pct': float(-abs((stop_loss - actual_entry_price) / actual_entry_price * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
                elif tp_hit:
                    # Take profit hit
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(actual_tp),
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': float(rr_target),
                        'profit_pct': float(abs((actual_tp - actual_entry_price) / actual_entry_price * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
            else:  # short
                actual_risk = stop_loss - actual_entry_price
                actual_tp = actual_entry_price - (actual_risk * rr_target)

                sl_hit = candle['high'] >= stop_loss
                tp_hit = candle['low'] <= actual_tp

                # Handle same-candle ambiguity
                if sl_hit and tp_hit:
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(actual_entry_price),
                        'direction': direction,
                        'result': 'inconclusive',
                        'rr_achieved': 0.0,
                        'profit_pct': 0.0,
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle),
                        'note': 'Both SL and TP touched in same candle - outcome uncertain'
                    }
                elif sl_hit:
                    # Stop loss hit
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(stop_loss),
                        'direction': direction,
                        'result': 'loss',
                        'rr_achieved': -1.0,
                        'profit_pct': float(-abs((stop_loss - actual_entry_price) / actual_entry_price * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }
                elif tp_hit:
                    # Take profit hit
                    return {
                        'entry_price': float(actual_entry_price),
                        'exit_price': float(actual_tp),
                        'direction': direction,
                        'result': 'win',
                        'rr_achieved': float(rr_target),
                        'profit_pct': float(abs((actual_entry_price - actual_tp) / actual_entry_price * 100)),
                        'entry_time': int(df.iloc[entry_candle]['timestamp']),
                        'exit_time': int(candle['timestamp']),
                        'duration_candles': int(j - entry_candle)
                    }

    return None  # Trade didn't complete in the lookback period


def calculate_statistics(trades: List[Dict]) -> Dict:
    """
    Calculate performance statistics from trades

    Handles three trade outcomes:
    - win: Take profit hit
    - loss: Stop loss hit
    - inconclusive: Both SL and TP hit in same candle (not counted in win rate)

    Returns:
        Statistics dict with all metrics
    """
    if not trades:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'inconclusive_trades': 0,
            'win_rate': 0,
            'win_rate_excluding_inconclusive': 0,
            'avg_rr': 0,
            'total_profit_pct': 0,
            'max_drawdown': 0,
            'avg_duration': 0
        }

    winning = [t for t in trades if t['result'] == 'win']
    losing = [t for t in trades if t['result'] == 'loss']
    inconclusive = [t for t in trades if t['result'] == 'inconclusive']

    total_trades = len(trades)
    winning_trades = len(winning)
    losing_trades = len(losing)
    inconclusive_trades = len(inconclusive)
    conclusive_trades = winning_trades + losing_trades

    # Win rate including inconclusive (inconclusive = 0 contribution)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    # Win rate excluding inconclusive trades (more accurate)
    win_rate_excl = (winning_trades / conclusive_trades * 100) if conclusive_trades > 0 else 0

    # Average R:R (only from conclusive trades)
    conclusive_rr_sum = sum(t['rr_achieved'] for t in trades if t['result'] != 'inconclusive')
    avg_rr = conclusive_rr_sum / conclusive_trades if conclusive_trades > 0 else 0

    # Total profit (inconclusive trades contribute 0)
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
        'inconclusive_trades': inconclusive_trades,
        'win_rate': round(win_rate, 2),
        'win_rate_excluding_inconclusive': round(win_rate_excl, 2),
        'avg_rr': round(avg_rr, 2),
        'total_profit_pct': round(total_profit_pct, 2),
        'max_drawdown': round(max_dd, 2),
        'avg_duration': round(avg_duration, 1)
    }
