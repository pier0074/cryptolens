"""
Data Fetcher Service
Fetches OHLC candles via CCXT (Binance by default - 1000 candles/request)
"""
import ccxt
import time
import logging
from datetime import datetime, timedelta, timezone
from app import db
from app.models import Symbol, Candle
from app.config import Config

logger = logging.getLogger(__name__)

# Binance allows 1000 candles per request (vs Kucoin's 500)
BATCH_SIZE = 1000

# Singleton exchange instance cache
_exchange_instance = None
_exchange_id = None


def get_exchange():
    """Get configured exchange instance (singleton pattern)"""
    global _exchange_instance, _exchange_id

    exchange_id = getattr(Config, 'EXCHANGE', 'binance')

    # Return cached instance if same exchange
    if _exchange_instance is not None and _exchange_id == exchange_id:
        return _exchange_instance

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


def fetch_candles(symbol: str, timeframe: str, limit: int = BATCH_SIZE, since: int = None) -> tuple:
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
    import sys
    exchange = get_exchange()

    # Calculate start timestamp (timezone-aware)
    now_dt = datetime.now(timezone.utc)
    start_time = now_dt - timedelta(days=days)
    since = int(start_time.timestamp() * 1000)
    now = int(now_dt.timestamp() * 1000)

    # Timeframe to milliseconds mapping
    tf_ms = {
        '1m': 60 * 1000,
        '5m': 5 * 60 * 1000,
        '15m': 15 * 60 * 1000,
        '1h': 60 * 60 * 1000,
        '4h': 4 * 60 * 60 * 1000,
        '1d': 24 * 60 * 60 * 1000
    }

    candle_duration = tf_ms.get(timeframe, 60 * 1000)

    # Calculate total batches needed (using BATCH_SIZE)
    total_candles_needed = (now - since) // candle_duration
    total_batches = max(1, (total_candles_needed // BATCH_SIZE) + 1)

    if verbose:
        print(f"    📊 {symbol} - Fetching ~{total_candles_needed:,} candles in {total_batches} batches...")
        sys.stdout.flush()

    total_new = 0
    total_api = 0
    current_since = since
    batch_num = 0
    last_progress = 0
    empty_batches = 0

    while current_since < now:
        batch_num += 1

        try:
            new_count, api_count = fetch_candles(symbol, timeframe, limit=BATCH_SIZE, since=current_since)
            total_new += new_count
            total_api += api_count

            # Track empty API responses (means we've caught up)
            if api_count == 0:
                empty_batches += 1
                if empty_batches >= 3:
                    if verbose:
                        print(f"    ℹ️  {symbol}: No more data from API, stopping early")
                        sys.stdout.flush()
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
                    print(f"    📈 {symbol}: {batch_num}/{total_batches} ({pct}%) [{status}]")
                    sys.stdout.flush()

            # Move to next batch
            current_since += BATCH_SIZE * candle_duration

            # Rate limiting (Binance is faster)
            time.sleep(max(exchange.rateLimit / 1000, 0.1))

        except Exception as e:
            logger.warning(f"{symbol} batch {batch_num}: {e}")
            time.sleep(1)
            continue

    if verbose:
        print(f"    ✅ {symbol}: Done! {total_new:,} new candles ({total_api:,} from API)")
        sys.stdout.flush()

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
