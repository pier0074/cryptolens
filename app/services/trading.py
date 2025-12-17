"""
Trading Calculations Service
Professional SMC/ICT-based SL/TP calculations for each pattern type
"""
from typing import Dict, Optional
from dataclasses import dataclass
import pandas as pd


@dataclass
class TradingLevels:
    """Trading levels for a pattern"""
    entry: float
    stop_loss: float
    take_profit_1: float  # Conservative TP (1:1 or structure)
    take_profit_2: float  # Standard TP (2:1 or next structure)
    take_profit_3: float  # Extended TP (3:1 or major structure)
    risk: float
    risk_reward_1: float
    risk_reward_2: float
    risk_reward_3: float


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Average True Range for volatility-based calculations.

    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (default 14)

    Returns:
        ATR value
    """
    if df.empty or len(df) < period:
        return 0.0

    df = df.copy()
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['prev_close'])
    df['tr3'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

    atr = df['tr'].tail(period).mean()
    return atr if pd.notna(atr) else 0.0


def find_swing_high(df: pd.DataFrame, start_idx: int, lookback: int = 50) -> Optional[float]:
    """Find the nearest swing high above a given index."""
    if df.empty:
        return None

    end_idx = max(0, start_idx - lookback)
    search_df = df.iloc[end_idx:start_idx]

    if search_df.empty:
        return None

    # Find local highs (higher than neighbors)
    swing_highs = []
    for i in range(2, len(search_df) - 2):
        if (search_df.iloc[i]['high'] > search_df.iloc[i-1]['high'] and
            search_df.iloc[i]['high'] > search_df.iloc[i-2]['high'] and
            search_df.iloc[i]['high'] > search_df.iloc[i+1]['high'] and
            search_df.iloc[i]['high'] > search_df.iloc[i+2]['high']):
            swing_highs.append(search_df.iloc[i]['high'])

    return max(swing_highs) if swing_highs else search_df['high'].max()


def find_swing_low(df: pd.DataFrame, start_idx: int, lookback: int = 50) -> Optional[float]:
    """Find the nearest swing low below a given index."""
    if df.empty:
        return None

    end_idx = max(0, start_idx - lookback)
    search_df = df.iloc[end_idx:start_idx]

    if search_df.empty:
        return None

    # Find local lows (lower than neighbors)
    swing_lows = []
    for i in range(2, len(search_df) - 2):
        if (search_df.iloc[i]['low'] < search_df.iloc[i-1]['low'] and
            search_df.iloc[i]['low'] < search_df.iloc[i-2]['low'] and
            search_df.iloc[i]['low'] < search_df.iloc[i+1]['low'] and
            search_df.iloc[i]['low'] < search_df.iloc[i+2]['low']):
            swing_lows.append(search_df.iloc[i]['low'])

    return min(swing_lows) if swing_lows else search_df['low'].min()


def calculate_fvg_levels(
    zone_low: float, zone_high: float, direction: str,
    atr: float = 0.0, swing_high: float = None, swing_low: float = None
) -> TradingLevels:
    """
    Calculate trading levels for Fair Value Gap (Imbalance) patterns.

    FVG Trading Logic (ICT/SMC):
    - Entry: At the edge of the FVG (zone_high for bullish, zone_low for bearish)
    - Stop Loss: Beyond the full FVG + ATR buffer (protects against sweep)
    - Take Profit: Target next liquidity (swing high/low) or use R:R multiples
    """
    zone_size = zone_high - zone_low

    # ATR buffer: use ATR if available, otherwise 50% of zone size
    buffer = atr * 0.5 if atr > 0 else zone_size * 0.5

    if direction == 'bullish':
        # Bullish FVG: Price should come down to fill, then bounce up
        entry = zone_high  # Enter at top of FVG (confirmation of support)
        stop_loss = zone_low - buffer  # Below full FVG with buffer

        risk = entry - stop_loss

        # Take profits: use swing high if available, otherwise R:R multiples
        if swing_high and swing_high > entry:
            tp1 = min(entry + risk, swing_high)  # 1:1 or swing, whichever is closer
            tp2 = swing_high  # Target swing high
            tp3 = swing_high + (swing_high - entry) * 0.5  # Extended beyond swing
        else:
            tp1 = entry + risk  # 1:1
            tp2 = entry + (risk * 2)  # 2:1
            tp3 = entry + (risk * 3)  # 3:1
    else:
        # Bearish FVG: Price should come up to fill, then drop
        entry = zone_low  # Enter at bottom of FVG (confirmation of resistance)
        stop_loss = zone_high + buffer  # Above full FVG with buffer

        risk = stop_loss - entry

        # Take profits: use swing low if available, otherwise R:R multiples
        if swing_low and swing_low < entry:
            tp1 = max(entry - risk, swing_low)  # 1:1 or swing, whichever is closer
            tp2 = swing_low  # Target swing low
            tp3 = swing_low - (entry - swing_low) * 0.5  # Extended beyond swing
        else:
            tp1 = entry - risk  # 1:1
            tp2 = entry - (risk * 2)  # 2:1
            tp3 = entry - (risk * 3)  # 3:1

    return TradingLevels(
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        risk=risk,
        risk_reward_1=abs(tp1 - entry) / risk if risk > 0 else 0,
        risk_reward_2=abs(tp2 - entry) / risk if risk > 0 else 0,
        risk_reward_3=abs(tp3 - entry) / risk if risk > 0 else 0,
    )


def calculate_order_block_levels(
    zone_low: float, zone_high: float, direction: str,
    atr: float = 0.0, swing_high: float = None, swing_low: float = None
) -> TradingLevels:
    """
    Calculate trading levels for Order Block patterns.

    Order Block Trading Logic (ICT/SMC):
    - Entry: At 50% of the OB body (optimal trade entry - OTE)
    - Stop Loss: Beyond the OB wick (the manipulation point)
    - Take Profit: Target opposing order block or equal highs/lows
    """
    zone_size = zone_high - zone_low
    zone_mid = (zone_high + zone_low) / 2

    # ATR buffer for stop loss
    buffer = atr * 0.3 if atr > 0 else zone_size * 0.3

    if direction == 'bullish':
        # Bullish OB: Last bearish candle before bullish move
        entry = zone_mid  # OTE at 50% of OB
        stop_loss = zone_low - buffer  # Below OB with buffer

        risk = entry - stop_loss

        # TPs: Target swing highs or equal highs (liquidity)
        if swing_high and swing_high > entry:
            tp1 = entry + risk  # 1:1 minimum
            tp2 = swing_high  # Target swing high
            tp3 = swing_high + risk  # Beyond swing high
        else:
            tp1 = entry + risk  # 1:1
            tp2 = entry + (risk * 2)  # 2:1
            tp3 = entry + (risk * 3)  # 3:1
    else:
        # Bearish OB: Last bullish candle before bearish move
        entry = zone_mid  # OTE at 50% of OB
        stop_loss = zone_high + buffer  # Above OB with buffer

        risk = stop_loss - entry

        # TPs: Target swing lows or equal lows (liquidity)
        if swing_low and swing_low < entry:
            tp1 = entry - risk  # 1:1 minimum
            tp2 = swing_low  # Target swing low
            tp3 = swing_low - risk  # Beyond swing low
        else:
            tp1 = entry - risk  # 1:1
            tp2 = entry - (risk * 2)  # 2:1
            tp3 = entry - (risk * 3)  # 3:1

    return TradingLevels(
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        risk=risk,
        risk_reward_1=abs(tp1 - entry) / risk if risk > 0 else 0,
        risk_reward_2=abs(tp2 - entry) / risk if risk > 0 else 0,
        risk_reward_3=abs(tp3 - entry) / risk if risk > 0 else 0,
    )


def calculate_liquidity_sweep_levels(
    zone_low: float, zone_high: float, direction: str,
    atr: float = 0.0, swing_high: float = None, swing_low: float = None
) -> TradingLevels:
    """
    Calculate trading levels for Liquidity Sweep patterns.

    Liquidity Sweep Trading Logic (ICT/SMC):
    - Entry: After sweep confirmation (close back inside range)
    - Stop Loss: Beyond the sweep wick (the liquidity grab point)
    - Take Profit: Target opposite liquidity (equal highs/lows on other side)
    """
    zone_size = zone_high - zone_low

    # Minimal buffer for sweeps (wick already represents the extreme)
    buffer = atr * 0.2 if atr > 0 else zone_size * 0.2

    if direction == 'bullish':
        # Bullish sweep: Price swept lows, now reversing up
        # zone_low = sweep wick, zone_high = previous low level
        entry = zone_high  # Enter after price reclaims the level
        stop_loss = zone_low - buffer  # Below the sweep wick

        risk = entry - stop_loss

        # Target: Opposite liquidity (swing highs / equal highs)
        if swing_high and swing_high > entry:
            tp1 = entry + risk * 1.5  # 1.5:1 minimum for sweeps
            tp2 = swing_high  # Target opposite liquidity
            tp3 = swing_high + (swing_high - entry) * 0.618  # Fib extension
        else:
            tp1 = entry + (risk * 1.5)  # 1.5:1
            tp2 = entry + (risk * 2.5)  # 2.5:1
            tp3 = entry + (risk * 4)    # 4:1 (sweeps often lead to big moves)
    else:
        # Bearish sweep: Price swept highs, now reversing down
        # zone_high = sweep wick, zone_low = previous high level
        entry = zone_low  # Enter after price loses the level
        stop_loss = zone_high + buffer  # Above the sweep wick

        risk = stop_loss - entry

        # Target: Opposite liquidity (swing lows / equal lows)
        if swing_low and swing_low < entry:
            tp1 = entry - risk * 1.5  # 1.5:1 minimum for sweeps
            tp2 = swing_low  # Target opposite liquidity
            tp3 = swing_low - (entry - swing_low) * 0.618  # Fib extension
        else:
            tp1 = entry - (risk * 1.5)  # 1.5:1
            tp2 = entry - (risk * 2.5)  # 2.5:1
            tp3 = entry - (risk * 4)    # 4:1 (sweeps often lead to big moves)

    return TradingLevels(
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        take_profit_3=tp3,
        risk=risk,
        risk_reward_1=abs(tp1 - entry) / risk if risk > 0 else 0,
        risk_reward_2=abs(tp2 - entry) / risk if risk > 0 else 0,
        risk_reward_3=abs(tp3 - entry) / risk if risk > 0 else 0,
    )


def calculate_trading_levels(
    pattern_type: str, zone_low: float, zone_high: float, direction: str,
    atr: float = 0.0, swing_high: float = None, swing_low: float = None
) -> TradingLevels:
    """
    Calculate trading levels based on pattern type.

    Args:
        pattern_type: 'imbalance', 'order_block', or 'liquidity_sweep'
        zone_low: Pattern zone low
        zone_high: Pattern zone high
        direction: 'bullish' or 'bearish'
        atr: Average True Range for volatility adjustment
        swing_high: Nearest swing high for TP targeting
        swing_low: Nearest swing low for TP targeting

    Returns:
        TradingLevels with entry, SL, and multiple TPs
    """
    calculators = {
        'imbalance': calculate_fvg_levels,
        'order_block': calculate_order_block_levels,
        'liquidity_sweep': calculate_liquidity_sweep_levels,
    }

    calculator = calculators.get(pattern_type, calculate_fvg_levels)
    return calculator(zone_low, zone_high, direction, atr, swing_high, swing_low)


def get_trading_levels_for_pattern(pattern, df: pd.DataFrame = None) -> Dict:
    """
    Get trading levels for a Pattern model object.

    Args:
        pattern: Pattern model instance
        df: Optional DataFrame with candle data for swing detection

    Returns:
        Dict with trading levels
    """
    atr = 0.0
    swing_high = None
    swing_low = None

    if df is not None and not df.empty:
        atr = calculate_atr(df)
        # Find swings looking back from the pattern
        swing_high = find_swing_high(df, len(df) - 1)
        swing_low = find_swing_low(df, len(df) - 1)

    levels = calculate_trading_levels(
        pattern_type=pattern.pattern_type,
        zone_low=pattern.zone_low,
        zone_high=pattern.zone_high,
        direction=pattern.direction,
        atr=atr,
        swing_high=swing_high,
        swing_low=swing_low
    )

    return {
        'entry': levels.entry,
        'stop_loss': levels.stop_loss,
        'take_profit_1': levels.take_profit_1,
        'take_profit_2': levels.take_profit_2,
        'take_profit_3': levels.take_profit_3,
        'risk': levels.risk,
        'risk_reward_1': round(levels.risk_reward_1, 2),
        'risk_reward_2': round(levels.risk_reward_2, 2),
        'risk_reward_3': round(levels.risk_reward_3, 2),
    }
