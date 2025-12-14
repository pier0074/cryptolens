"""
Shared retry and error handling utilities for fetch scripts.

Usage:
    from scripts.utils.retry import async_retry, is_rate_limit_error, is_timeout_error

    # As a decorator
    @async_retry(max_retries=3, context="BTC/USDT")
    async def fetch_data():
        return await exchange.fetch_ohlcv(...)

    # Or manually
    result = await async_retry_call(
        exchange.fetch_ohlcv, symbol, '1m', since=since,
        context=symbol, verbose=True
    )
"""
import asyncio
import logging
import re
from functools import wraps
from typing import Callable, Any, Optional

import ccxt

# Configure module logger
logger = logging.getLogger('fetch')

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
DEFAULT_RATE_LIMIT_COOLOFF_SECONDS = 30
TIMEOUT_RETRY_DELAY_SECONDS = 10


def is_timeout_error(error: Exception) -> bool:
    """Check if error is a timeout error."""
    if isinstance(error, (ccxt.RequestTimeout, ccxt.NetworkError)):
        error_str = str(error).lower()
        if 'timeout' in error_str or 'timed out' in error_str:
            return True
    error_str = str(error).lower()
    return any(x in error_str for x in ['timeout', 'timed out', 'read timed out', 'connect timed out'])


def get_error_summary(error: Exception) -> str:
    """Extract a concise error summary from ccxt exceptions."""
    error_type = type(error).__name__

    # Check for common ccxt error types
    if isinstance(error, ccxt.RateLimitExceeded):
        return "Rate limit exceeded"
    elif isinstance(error, ccxt.DDoSProtection):
        return "DDoS protection triggered"
    elif isinstance(error, ccxt.RequestTimeout):
        return "Request timeout"
    elif isinstance(error, ccxt.NetworkError):
        return "Network error"
    elif isinstance(error, ccxt.ExchangeError):
        # Try to extract Binance error code
        error_str = str(error)
        if '-1021' in error_str:
            return "Timestamp out of recvWindow (check system time)"
        elif '-1003' in error_str:
            return "Too many requests (IP banned temporarily)"
        elif '-1015' in error_str:
            return "Too many orders"
        elif '-1001' in error_str:
            return "Internal error"
        return f"Exchange error: {error_str[:100]}"

    # Fallback to first 80 chars of error
    error_str = str(error)
    if len(error_str) > 80:
        return f"{error_type}: {error_str[:77]}..."
    return f"{error_type}: {error_str}"


def is_rate_limit_error(error: Exception) -> bool:
    """Check if error is a rate limit error."""
    if isinstance(error, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
        return True
    error_str = str(error).lower()
    return any(x in error_str for x in ['rate limit', 'ratelimit', '429', 'too many requests'])


def extract_rate_limit_wait_time(error: Exception) -> int:
    """
    Extract wait time from rate limit error message.

    Returns:
        Wait time in seconds (default 30s, max 300s/5min)
    """
    error_str = str(error).lower()
    patterns = [
        r'retry[- ]?after[:\s]+(\d+)',       # 'retry after 10', 'Retry-After: 60'
        r'after\s+(\d+)\s*s',                 # 'after 30s'
        r'in\s+(\d+)\s*sec',                  # 'in 5 seconds'
        r'wait\s+(\d+)',                      # 'wait 45 seconds'
        r'(\d+)\s*seconds?\s*(cool|wait|delay)',  # '10 seconds cooldown'
    ]
    for pattern in patterns:
        match = re.search(pattern, error_str)
        if match:
            wait_time = int(match.group(1))
            return min(wait_time, 300)  # Cap at 5 minutes
    return DEFAULT_RATE_LIMIT_COOLOFF_SECONDS


async def async_retry_call(
    func: Callable,
    *args,
    context: str = "",
    verbose: bool = False,
    max_retries: int = MAX_RETRIES,
    on_retry: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Call an async function with retry logic for rate limits, timeouts, and errors.

    Args:
        func: Async function to call
        *args: Positional arguments for func
        context: Context string for logging (e.g., symbol name)
        verbose: Print retry messages to stdout
        max_retries: Maximum number of retry attempts
        on_retry: Optional callback(attempt, error, wait_time) called before each retry
        **kwargs: Keyword arguments for func

    Returns:
        Result of func, or None if all retries exhausted

    Example:
        result = await async_retry_call(
            exchange.fetch_ohlcv, 'BTC/USDT', '1m', since=since,
            context='BTC/USDT', verbose=True
        )
    """
    last_error = None
    ctx = f"{context}: " if context else ""

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)

        except Exception as e:
            last_error = e
            attempts_left = max_retries - attempt - 1

            if is_rate_limit_error(e):
                wait_time = extract_rate_limit_wait_time(e)
                logger.warning(f"{ctx}Rate limit, cooling off {wait_time}s (attempt {attempt + 1}/{max_retries})")
                if verbose:
                    print(f"  {ctx}Rate limit, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                if on_retry:
                    on_retry(attempt, e, wait_time)
                if attempts_left > 0:
                    await asyncio.sleep(wait_time)

            elif is_timeout_error(e):
                wait_time = TIMEOUT_RETRY_DELAY_SECONDS
                logger.warning(f"{ctx}Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                if verbose:
                    print(f"  {ctx}Timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                if on_retry:
                    on_retry(attempt, e, wait_time)
                if attempts_left > 0:
                    await asyncio.sleep(wait_time)

            else:
                wait_time = RETRY_DELAY_SECONDS
                error_summary = get_error_summary(e)
                logger.error(f"{ctx}{error_summary} (attempt {attempt + 1}/{max_retries})")
                if verbose:
                    print(f"  {ctx}{error_summary}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                if on_retry:
                    on_retry(attempt, e, wait_time)
                if attempts_left > 0:
                    await asyncio.sleep(wait_time)

    # All retries exhausted
    error_summary = get_error_summary(last_error) if last_error else "Unknown error"
    logger.error(f"{ctx}Failed after {max_retries} retries: {error_summary}")
    if verbose:
        print(f"  {ctx}Failed after {max_retries} retries: {error_summary}")
    return None


def async_retry(
    max_retries: int = MAX_RETRIES,
    context: str = "",
    verbose: bool = False
):
    """
    Decorator for async functions with retry logic.

    Args:
        max_retries: Maximum retry attempts
        context: Context for logging
        verbose: Print to stdout

    Example:
        @async_retry(max_retries=3, context="fetch_candles")
        async def fetch_candles(symbol):
            return await exchange.fetch_ohlcv(symbol, '1m')
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await async_retry_call(
                func, *args,
                context=context,
                verbose=verbose,
                max_retries=max_retries,
                **kwargs
            )
        return wrapper
    return decorator


class RetryConfig:
    """Configuration class for retry behavior."""

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        retry_delay: float = RETRY_DELAY_SECONDS,
        rate_limit_cooloff: float = DEFAULT_RATE_LIMIT_COOLOFF_SECONDS,
        timeout_delay: float = TIMEOUT_RETRY_DELAY_SECONDS
    ):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.rate_limit_cooloff = rate_limit_cooloff
        self.timeout_delay = timeout_delay


# Default configuration
default_config = RetryConfig()
