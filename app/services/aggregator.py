"""
Timeframe Aggregator Service
Aggregates 1m candles into higher timeframes (5m, 15m, 1h, 4h, 1d)
"""
import sys
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


def aggregate_candles(symbol: str, from_tf: str = '1m', to_tf: str = '5m',
                      progress_callback=None) -> int:
    """
    Aggregate candles from one timeframe to another

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        from_tf: Source timeframe (usually '1m')
        to_tf: Target timeframe (e.g., '5m', '1h')
        progress_callback: Optional callback(stage, current, total) for progress updates

    Returns:
        Number of candles created
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return 0

    if progress_callback:
        progress_callback('loading', 0, 0)

    # Get source candle count first for progress
    source_count = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=from_tf
    ).count()

    if source_count == 0:
        return 0

    # Load source candles in batches for memory efficiency
    BATCH_SIZE = 50000
    all_data = []

    for offset in range(0, source_count, BATCH_SIZE):
        batch = Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe=from_tf
        ).order_by(Candle.timestamp.asc()).offset(offset).limit(BATCH_SIZE).all()

        for c in batch:
            all_data.append({
                'timestamp': c.timestamp,
                'open': c.open,
                'high': c.high,
                'low': c.low,
                'close': c.close,
                'volume': c.volume
            })

        if progress_callback:
            progress_callback('loading', min(offset + BATCH_SIZE, source_count), source_count)

    if not all_data:
        return 0

    if progress_callback:
        progress_callback('resampling', 0, 1)

    # Convert to pandas DataFrame
    df = pd.DataFrame(all_data)
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

    if progress_callback:
        progress_callback('resampling', 1, 1)

    total_rows = len(agg_df)
    if total_rows == 0:
        return 0

    # Get all existing timestamps for this symbol/timeframe (batch check)
    if progress_callback:
        progress_callback('checking', 0, 1)

    existing_timestamps = set(
        c.timestamp for c in Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe=to_tf
        ).with_entities(Candle.timestamp).all()
    )

    if progress_callback:
        progress_callback('checking', 1, 1)

    # Save aggregated candles in batches
    count = 0
    batch_count = 0
    COMMIT_BATCH = 1000

    for idx, (_, row) in enumerate(agg_df.iterrows()):
        timestamp = int(row['timestamp'])

        # Skip if already exists
        if timestamp in existing_timestamps:
            continue

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
        batch_count += 1

        # Commit in batches for performance
        if batch_count >= COMMIT_BATCH:
            db.session.commit()
            batch_count = 0

        if progress_callback and idx % 500 == 0:
            progress_callback('saving', idx, total_rows)

    db.session.commit()

    if progress_callback:
        progress_callback('saving', total_rows, total_rows)

    return count


def aggregate_all_timeframes(symbol: str, progress_callback=None) -> dict:
    """
    Aggregate 1m candles to all higher timeframes

    Args:
        symbol: Trading pair
        progress_callback: Optional callback(tf, stage, current, total) for progress

    Returns:
        Dict with timeframe -> candles_created count
    """
    results = {}
    higher_tfs = ['5m', '15m', '1h', '4h', '1d']

    for i, tf in enumerate(higher_tfs):
        def tf_callback(stage, current, total, tf=tf):
            if progress_callback:
                progress_callback(tf, stage, current, total)

        count = aggregate_candles(symbol, '1m', tf, progress_callback=tf_callback)
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
