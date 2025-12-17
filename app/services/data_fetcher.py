"""
Data Fetcher Service
Fetches OHLC candles via CCXT (Binance by default - 1000 candles/request)
"""
from typing import Tuple
import ccxt
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from app import db
from app.models import Symbol, Candle
from app.config import Config

logger = logging.getLogger(__name__)

# Singleton exchange instance cache with thread safety
_exchange_instance = None
_exchange_id = None
_exchange_lock = threading.Lock()


def get_exchange():
    """Get configured exchange instance (thread-safe singleton pattern)"""
    global _exchange_instance, _exchange_id

    exchange_id = getattr(Config, 'EXCHANGE', 'binance')

    # Fast path: Return cached instance if same exchange (no lock needed for read)
    if _exchange_instance is not None and _exchange_id == exchange_id:
        return _exchange_instance

    # Slow path: Need to create or replace instance
    with _exchange_lock:
        # Double-check after acquiring lock (another thread may have created it)
        if _exchange_instance is not None and _exchange_id == exchange_id:
            return _exchange_instance

        # Clean up existing instance before creating new one
        if _exchange_instance is not None:
            _cleanup_exchange_unsafe()

        # Create new instance
        exchange_class = getattr(ccxt, exchange_id, ccxt.binance)
        _exchange_instance = exchange_class({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        _exchange_id = exchange_id

        return _exchange_instance


def _cleanup_exchange_unsafe():
    """Internal cleanup without lock - caller must hold _exchange_lock"""
    global _exchange_instance, _exchange_id

    if _exchange_instance is not None:
        try:
            if hasattr(_exchange_instance, 'close'):
                _exchange_instance.close()
        except Exception as e:
            logger.warning(f"Error closing exchange connection: {e}")
        finally:
            _exchange_instance = None
            _exchange_id = None


def cleanup_exchange():
    """
    Clean up the exchange singleton instance (thread-safe).
    Should be called during application shutdown or test teardown.
    """
    with _exchange_lock:
        _cleanup_exchange_unsafe()


def fetch_candles(symbol: str, timeframe: str, limit: int = None, since: int = None) -> Tuple[int, int]:
    """
    Fetch candles for a symbol/timeframe

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        timeframe: Candle timeframe (e.g., '1m', '5m', '1h')
        limit: Number of candles to fetch (max 1000 for Binance)
        since: Unix timestamp in ms to fetch from

    Returns:
        Tuple of (new_candles_saved, total_fetched_from_api)
    """
    if limit is None:
        limit = Config.BATCH_SIZE

    exchange = get_exchange()

    # Get or create symbol
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        sym = Symbol(symbol=symbol, exchange=Config.EXCHANGE)
        db.session.add(sym)
        db.session.commit()

    try:
        # Fetch OHLCV data
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

        if not ohlcv:
            return (0, 0)

        # Get existing timestamps in one query (batch check)
        timestamps = [c[0] for c in ohlcv]
        existing_timestamps = set(
            c.timestamp for c in Candle.query.filter(
                Candle.symbol_id == sym.id,
                Candle.timeframe == timeframe,
                Candle.timestamp.in_(timestamps)
            ).all()
        )

        count = 0
        for candle in ohlcv:
            timestamp, open_price, high, low, close, volume = candle

            # Skip if exists (using batch-queried set)
            if timestamp in existing_timestamps:
                continue

            # Validate OHLC data
            if high < low or open_price <= 0 or close <= 0:
                continue

            new_candle = Candle(
                symbol_id=sym.id,
                timeframe=timeframe,
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume
            )
            db.session.add(new_candle)
            count += 1

        # Commit after each batch
        db.session.commit()
        return (count, len(ohlcv))

    except ccxt.NetworkError as e:
        logger.error(f"Network error fetching {symbol} {timeframe}: {e}")
        db.session.rollback()
        return (0, 0)
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching {symbol} {timeframe}: {e}")
        db.session.rollback()
        return (0, 0)
    except Exception as e:
        logger.error(f"Error fetching {symbol} {timeframe}: {e}")
        db.session.rollback()
        return (0, 0)


def fetch_historical(symbol: str, timeframe: str, days: int = 30, progress_callback=None, verbose: bool = True) -> int:
    """
    Fetch historical candles for backtesting

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        days: Number of days of history to fetch
        progress_callback: Optional callback(batch_num, total_batches, candles_fetched)
        verbose: Print progress to stdout

    Returns:
        Total candles saved
    """
    exchange = get_exchange()

    # Calculate start timestamp (timezone-aware)
    now_dt = datetime.now(timezone.utc)
    start_time = now_dt - timedelta(days=days)
    since = int(start_time.timestamp() * 1000)
    now = int(now_dt.timestamp() * 1000)

    # Get candle duration from config
    candle_duration = Config.TIMEFRAME_MS.get(timeframe, 60 * 1000)

    # Calculate total batches needed
    batch_size = Config.BATCH_SIZE
    total_candles_needed = (now - since) // candle_duration
    total_batches = max(1, (total_candles_needed // batch_size) + 1)

    if verbose:
        logger.info(f"{symbol} - Fetching ~{total_candles_needed:,} candles in {total_batches} batches...")

    total_new = 0
    total_api = 0
    current_since = since
    batch_num = 0
    last_progress = 0
    empty_batches = 0

    while current_since < now:
        batch_num += 1

        try:
            new_count, api_count = fetch_candles(symbol, timeframe, limit=batch_size, since=current_since)
            total_new += new_count
            total_api += api_count

            # Track empty API responses (means we've caught up)
            if api_count == 0:
                empty_batches += 1
                if empty_batches >= 3:
                    if verbose:
                        logger.info(f"{symbol}: No more data from API, stopping early")
                    break
            else:
                empty_batches = 0

            # Progress callback
            if progress_callback:
                progress_callback(batch_num, total_batches, total_new)

            # Verbose progress (every 10% or 50 batches)
            if verbose:
                pct = int((batch_num / total_batches) * 100)
                if pct >= last_progress + 10 or batch_num % 50 == 0:
                    last_progress = pct
                    status = f"new: {total_new:,}" if new_count > 0 else "exists"
                    logger.info(f"{symbol}: {batch_num}/{total_batches} ({pct}%) [{status}]")

            # Move to next batch
            current_since += batch_size * candle_duration

            # Rate limiting
            time.sleep(max(exchange.rateLimit / 1000, Config.RATE_LIMIT_DELAY))

        except Exception as e:
            logger.warning(f"{symbol} batch {batch_num}: {e}")
            time.sleep(1)
            continue

    if verbose:
        logger.info(f"{symbol}: Done! {total_new:,} new candles ({total_api:,} from API)")

    return total_new


def fetch_all_symbols(timeframe: str = '1m', limit: int = 200) -> dict:
    """
    Fetch latest candles for all active symbols

    Returns:
        Dict with symbol -> candles_fetched count
    """
    symbols = Symbol.query.filter_by(is_active=True).all()
    results = {}

    for symbol in symbols:
        new_count, _ = fetch_candles(symbol.symbol, timeframe, limit=limit)
        results[symbol.symbol] = new_count
        time.sleep(0.05)  # Small delay between symbols

    return results


def get_latest_candles(symbol: str, timeframe: str, limit: int = 200) -> list:
    """
    Get latest candles from database, fetch if needed

    Returns:
        List of candle dicts
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return []

    candles = Candle.query.filter_by(
        symbol_id=sym.id,
        timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    # If no candles or stale, fetch fresh
    if not candles:
        fetch_candles(symbol, timeframe, limit=limit)
        candles = Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe=timeframe
        ).order_by(Candle.timestamp.desc()).limit(limit).all()

    return [c.to_dict() for c in reversed(candles)]
