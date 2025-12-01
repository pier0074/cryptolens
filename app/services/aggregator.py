"""
Timeframe Aggregator Service
Aggregates 1m candles into higher timeframes (5m, 15m, 1h, 4h, 1d)
"""
import pandas as pd
from app import db
from app.models import Symbol, Candle


# Timeframe multipliers (in minutes)
TIMEFRAME_MINUTES = {
    '1m': 1,
    '5m': 5,
    '15m': 15,
    '1h': 60,
    '4h': 240,
    '1d': 1440
}


def aggregate_candles(symbol: str, from_tf: str = '1m', to_tf: str = '5m') -> int:
    """
    Aggregate candles from one timeframe to another

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        from_tf: Source timeframe (usually '1m')
        to_tf: Target timeframe (e.g., '5m', '1h')

    Returns:
        Number of candles created
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return 0

    # Get source candles
    source_candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=from_tf
    ).order_by(Candle.timestamp.asc()).all()

    if not source_candles:
        return 0

    # Convert to pandas DataFrame
    df = pd.DataFrame([{
        'timestamp': c.timestamp,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'volume': c.volume
    } for c in source_candles])

    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)

    # Resample rule mapping
    resample_rules = {
        '5m': '5min',
        '15m': '15min',
        '1h': '1h',
        '4h': '4h',
        '1d': '1D'
    }

    rule = resample_rules.get(to_tf)
    if not rule:
        return 0

    # Aggregate
    agg_df = df.resample(rule).agg({
        'timestamp': 'first',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    # Save aggregated candles
    count = 0
    for _, row in agg_df.iterrows():
        timestamp = int(row['timestamp'])

        # Check if exists
        existing = Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe=to_tf,
            timestamp=timestamp
        ).first()

        if not existing:
            candle = Candle(
                symbol_id=sym.id,
                timeframe=to_tf,
                timestamp=timestamp,
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row['volume']
            )
            db.session.add(candle)
            count += 1

    db.session.commit()
    return count


def aggregate_all_timeframes(symbol: str) -> dict:
    """
    Aggregate 1m candles to all higher timeframes

    Returns:
        Dict with timeframe -> candles_created count
    """
    results = {}
    higher_tfs = ['5m', '15m', '1h', '4h', '1d']

    for tf in higher_tfs:
        count = aggregate_candles(symbol, '1m', tf)
        results[tf] = count

    return results


def update_aggregations_for_all_symbols() -> dict:
    """
    Update all aggregations for all active symbols

    Returns:
        Dict with symbol -> {timeframe -> count}
    """
    symbols = Symbol.query.filter_by(is_active=True).all()
    results = {}

    for symbol in symbols:
        results[symbol.symbol] = aggregate_all_timeframes(symbol.symbol)

    return results


def get_candles_as_dataframe(symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
    """
    Get candles as a pandas DataFrame for analysis

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return pd.DataFrame()

    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame([{
        'timestamp': c.timestamp,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'volume': c.volume
    } for c in reversed(candles)])

    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df
