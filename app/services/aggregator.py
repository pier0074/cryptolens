"""
Timeframe Aggregator Service
Aggregates 1m candles into higher timeframes (5m, 15m, 30m, 1h, 2h, 4h, 1d)

Smart aggregation approach:
1. Find last aggregated timestamp for target timeframe
2. Load only source candles AFTER that timestamp
3. Create all possible complete target candles
4. Skip the current incomplete period
"""
import logging
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import Symbol, Candle

logger = logging.getLogger(__name__)


# Single source of truth for timeframe configuration
# Timeframes to aggregate from 1m (excludes 1m itself)
AGGREGATION_TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']

# Pandas resample rules for each timeframe
RESAMPLE_RULES = {
    '5m': '5min',
    '15m': '15min',
    '30m': '30min',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '1d': '1D'
}

# Timeframe multipliers (in minutes)
TIMEFRAME_MINUTES = {
    '1m': 1,
    '5m': 5,
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '4h': 240,
    '1d': 1440
}


def aggregate_new_candles(symbol: str, from_tf: str = '1m', to_tf: str = '5m') -> int:
    """
    Smart aggregation - only processes candles that haven't been aggregated yet.

    How it works:
    1. Find the last aggregated candle's timestamp for target timeframe
    2. Load source candles AFTER that timestamp (+ buffer for alignment)
    3. Resample into target candles
    4. Exclude the current incomplete period (can't aggregate a candle still forming)
    5. Save only NEW candles (skip existing)

    This ONE function handles all cases:
    - Normal fetch (1-2 new 1m candles): loads few, creates 0-1 target
    - Gap fill (100 new 1m candles): loads 100, creates multiple targets
    - Historical backfill (no existing): loads all, creates all

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

    tf_minutes = TIMEFRAME_MINUTES.get(to_tf, 5)
    tf_ms = tf_minutes * 60 * 1000

    # 1. Find last aggregated candle for this target timeframe
    last_target = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=to_tf
    ).order_by(Candle.timestamp.desc()).first()

    if last_target:
        # Start from the BEGINNING of the last target candle's period
        # (in case we need to look at adjacent source candles for alignment)
        start_from = last_target.timestamp
    else:
        # No aggregated candles yet - need full historical
        start_from = 0

    # 2. Load source candles AFTER start_from
    # Add buffer for period alignment (need full period of source candles)
    query = text("""
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol_id = :symbol_id
          AND timeframe = :timeframe
          AND timestamp >= :start_from
        ORDER BY timestamp ASC
    """)

    df = pd.read_sql(
        query,
        db.engine,
        params={
            'symbol_id': sym.id,
            'timeframe': from_tf,
            'start_from': start_from
        }
    )

    if df.empty:
        return 0

    # Need at least enough candles for one complete period
    if len(df) < tf_minutes:
        return 0

    # 3. Resample into target timeframe
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)

    rule = RESAMPLE_RULES.get(to_tf)
    if not rule:
        return 0

    agg_df = df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    if agg_df.empty:
        return 0

    # 4. Exclude current incomplete period
    # A period is incomplete if we don't have all source candles for it yet
    # Current time floored to period start = incomplete period
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    current_period_start_ms = (now_ms // tf_ms) * tf_ms

    # Filter out the current (incomplete) period
    timestamps = []
    for idx in agg_df.index:
        ts_ms = int(idx.timestamp() * 1000)
        if ts_ms < current_period_start_ms:
            timestamps.append(ts_ms)

    if not timestamps:
        return 0

    # 5. Check which candles already exist (batch query)
    existing_ts = set(
        c.timestamp for c in Candle.query.filter(
            Candle.symbol_id == sym.id,
            Candle.timeframe == to_tf,
            Candle.timestamp.in_(timestamps)
        ).all()
    )

    # 6. Save only NEW candles
    created = 0
    for idx, row in agg_df.iterrows():
        timestamp = int(idx.timestamp() * 1000)

        # Skip incomplete current period
        if timestamp >= current_period_start_ms:
            continue

        # Skip existing
        if timestamp in existing_ts:
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
        created += 1

    if created > 0:
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            logger.warning(f"Some candles already existed for {symbol}/{to_tf}")
            return 0

    return created


def aggregate_all_timeframes(symbol: str, progress_callback=None) -> dict:
    """
    Aggregate 1m candles to all higher timeframes using smart aggregation.

    Args:
        symbol: Trading pair
        progress_callback: Optional callback(tf, created) for progress

    Returns:
        Dict with timeframe -> candles_created count
    """
    results = {}

    for tf in AGGREGATION_TIMEFRAMES:
        count = aggregate_new_candles(symbol, '1m', tf)
        results[tf] = count
        if progress_callback:
            progress_callback(tf, count)

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


# =============================================================================
# Legacy functions - kept for backward compatibility with backfill scripts
# =============================================================================

def aggregate_candles(symbol: str, from_tf: str = '1m', to_tf: str = '5m',
                      progress_callback=None) -> int:
    """
    FULL aggregation - loads ALL candles. Use only for historical backfill.

    For normal use, prefer aggregate_new_candles() which only processes
    what's needed.

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

    if progress_callback:
        progress_callback('loading', 0, source_count)

    # Direct SQL to DataFrame - 50% less memory than ORM + list comprehension
    query = text("""
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol_id = :symbol_id AND timeframe = :timeframe
        ORDER BY timestamp ASC
    """)

    df = pd.read_sql(
        query,
        db.engine,
        params={'symbol_id': sym.id, 'timeframe': from_tf}
    )

    if progress_callback:
        progress_callback('loading', source_count, source_count)

    if df.empty:
        return 0

    if progress_callback:
        progress_callback('resampling', 0, 1)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)

    rule = RESAMPLE_RULES.get(to_tf)
    if not rule:
        return 0

    agg_df = df.resample(rule).agg({
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

    # Save aggregated candles in batches with proper error handling
    count = 0
    batch_count = 0
    COMMIT_BATCH = 1000

    for idx, (period_start, row) in enumerate(agg_df.iterrows()):
        timestamp = int(period_start.timestamp() * 1000)

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

        if batch_count >= COMMIT_BATCH:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                existing_timestamps = set(
                    c.timestamp for c in Candle.query.filter_by(
                        symbol_id=sym.id,
                        timeframe=to_tf
                    ).with_entities(Candle.timestamp).all()
                )
            batch_count = 0

        if progress_callback and idx % 500 == 0:
            progress_callback('saving', idx, total_rows)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logger.warning(f"Some candles already existed for {symbol}/{to_tf}")

    if progress_callback:
        progress_callback('saving', total_rows, total_rows)

    return count


# Backward compatibility aliases
aggregate_candles_realtime = aggregate_new_candles
aggregate_candles_windowed = aggregate_new_candles


def get_candles_as_dataframe(
    symbol: str,
    timeframe: str,
    limit: int = 500,
    verified_only: bool = False
) -> pd.DataFrame:
    """
    Get candles as a pandas DataFrame for analysis (optimized: direct SQL to DataFrame)

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        timeframe: Candle timeframe (e.g., '1h', '4h')
        limit: Maximum number of candles to return
        verified_only: If True, only return verified candles (recommended for backtesting)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return pd.DataFrame()

    if verified_only:
        query = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol_id = :symbol_id AND timeframe = :timeframe
              AND verified_at IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT :limit
        """)
    else:
        query = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol_id = :symbol_id AND timeframe = :timeframe
            ORDER BY timestamp DESC
            LIMIT :limit
        """)

    df = pd.read_sql(
        query,
        db.engine,
        params={'symbol_id': sym.id, 'timeframe': timeframe, 'limit': limit}
    )

    if df.empty:
        return pd.DataFrame()

    # Reverse to chronological order and add datetime
    df = df.iloc[::-1].reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df
