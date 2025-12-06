#!/usr/bin/env python
"""
Real-time Candle Fetcher with Pattern Detection

Simple, consistent flow:
1. Check last candle timestamp in DB
2. Fetch all candles from there to now
3. Save new candles
4. Aggregate ALL higher timeframes
5. Detect patterns on all fetched candles
6. Update pattern status
7. Generate signals
8. Expire old patterns
9. Notify
10. Log run to database

Cron setup:
  * * * * * cd /path && venv/bin/python scripts/fetch.py
"""
import sys
import os
import asyncio
import time
import traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt_async
from datetime import datetime, timezone

# All timeframes to aggregate (always, regardless of current time)
ALL_TIMEFRAMES = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']


def get_last_candle_timestamp(app, symbol_name):
    """Get the timestamp of the last 1m candle for a symbol."""
    from app.models import Symbol, Candle
    from sqlalchemy import func

    with app.app_context():
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            return None
        return Candle.query.filter_by(
            symbol_id=sym.id,
            timeframe='1m'
        ).with_entities(func.max(Candle.timestamp)).scalar()


def process_symbol(symbol_name, ohlcv, app, verbose=False):
    """
    Process a single symbol after fetch:
    1. Save candles to DB
    2. Aggregate ALL higher timeframes
    3. Detect patterns on all fetched candles
    4. Update pattern status
    """
    import time as _time
    from app.models import Symbol, Candle
    from app.services.aggregator import aggregate_candles_realtime
    from app.services.patterns import get_all_detectors
    from app import db

    _t0 = _time.time()
    with app.app_context():
        # Get symbol
        sym = Symbol.query.filter_by(symbol=symbol_name).first()
        if not sym:
            return {'symbol': symbol_name, 'new': 0, 'patterns': 0}

        # 1. Save new candles
        timestamps = [c[0] for c in ohlcv]
        existing = set(
            c.timestamp for c in Candle.query.filter(
                Candle.symbol_id == sym.id,
                Candle.timeframe == '1m',
                Candle.timestamp.in_(timestamps)
            ).all()
        )

        new_count = 0
        for candle in ohlcv:
            ts, o, h, l, c, v = candle
            if ts in existing:
                continue
            db.session.add(Candle(
                symbol_id=sym.id,
                timeframe='1m',
                timestamp=ts,
                open=o, high=h, low=l, close=c,
                volume=v or 0
            ))
            new_count += 1

        if new_count > 0:
            db.session.commit()

        # 2. Aggregate ALL higher timeframes (always)
        for tf in ALL_TIMEFRAMES:
            try:
                aggregate_candles_realtime(symbol_name, '1m', tf)
            except Exception:
                pass

        # 3. Detect patterns on all timeframes
        # Scan limit = number of candles fetched + context buffer
        patterns_found = 0
        if new_count > 0:
            detectors = get_all_detectors()
            scan_limit = len(ohlcv) + 50  # Fetched candles + context

            for tf in ['1m'] + ALL_TIMEFRAMES:
                # Scale limit for higher timeframes
                tf_multiplier = {
                    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
                    '1h': 60, '2h': 120, '4h': 240, '1d': 1440
                }.get(tf, 1)
                tf_limit = max(50, scan_limit // tf_multiplier + 10)

                for detector in detectors:
                    try:
                        patterns = detector.detect(symbol_name, tf, limit=tf_limit)
                        if patterns:
                            patterns_found += len(patterns)
                    except Exception:
                        pass

        # 4. Update pattern status with current price
        if ohlcv:
            current_price = ohlcv[-1][4]  # close price
            detectors = get_all_detectors()
            for detector in detectors:
                if hasattr(detector, 'update_pattern_status'):
                    for tf in ['1m'] + ALL_TIMEFRAMES:
                        try:
                            detector.update_pattern_status(symbol_name, tf, current_price)
                        except Exception:
                            pass

        _elapsed = _time.time() - _t0
        if verbose and (new_count > 0 or patterns_found > 0):
            print(f"  {symbol_name}: {new_count} candles, {patterns_found} patterns ({_elapsed:.1f}s)")

        return {
            'symbol': symbol_name,
            'new': new_count,
            'patterns': patterns_found,
            'time': _elapsed
        }


async def fetch_and_process(exchange, symbol, app, verbose=False):
    """Fetch candles from last timestamp to now, then process."""
    try:
        # Get last candle timestamp
        last_ts = get_last_candle_timestamp(app, symbol)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if last_ts:
            gap_minutes = (now_ms - last_ts) // 60000
            if verbose and gap_minutes > 10:
                print(f"  {symbol}: Fetching {gap_minutes} min gap...")

            # Fetch in batches of 1000 (Binance max) until caught up
            all_ohlcv = []
            since = last_ts + 60000  # Start from next minute

            while since < now_ms:
                batch = await exchange.fetch_ohlcv(symbol, '1m', since=since, limit=1000)
                if not batch:
                    break
                all_ohlcv.extend(batch)
                # Move to next batch (last candle timestamp + 1 min)
                since = batch[-1][0] + 60000
                # Small delay to respect rate limits on large gaps
                if len(batch) == 1000:
                    await asyncio.sleep(0.1)

            ohlcv = all_ohlcv
        else:
            # No data yet - fetch initial history
            ohlcv = await exchange.fetch_ohlcv(symbol, '1m', limit=500)
            if verbose:
                print(f"  {symbol}: Initial fetch (500 candles)...")

        if ohlcv:
            return process_symbol(symbol, ohlcv, app, verbose)
        return {'symbol': symbol, 'new': 0, 'patterns': 0}

    except Exception as e:
        if verbose:
            print(f"  {symbol}: ERROR - {e}")
        return {'symbol': symbol, 'new': 0, 'patterns': 0, 'error': str(e)}


async def run_fetch_cycle(symbols, app, verbose=False):
    """Run a complete fetch cycle with parallel fetching."""
    exchange = ccxt_async.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })

    try:
        tasks = [fetch_and_process(exchange, s, app, verbose) for s in symbols]
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
        return results
    finally:
        await exchange.close()


def generate_signals_batch(app, verbose=False):
    """Generate signals for all symbols (runs once after all fetches)."""
    from app.services.signals import scan_and_generate_signals

    with app.app_context():
        try:
            result = scan_and_generate_signals()
            if verbose and result['signals_generated'] > 0:
                print(f"  Generated {result['signals_generated']} signals")
            return result
        except Exception as e:
            if verbose:
                print(f"  Signal error: {e}")
            return {'signals_generated': 0}


def expire_old_patterns(app, verbose=False):
    """Mark expired patterns based on timeframe-specific expiry."""
    from app.models import Pattern
    from app.config import Config
    from app import db

    with app.app_context():
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        active_patterns = Pattern.query.filter_by(status='active').all()

        expired_count = 0
        for pattern in active_patterns:
            expiry_hours = Config.PATTERN_EXPIRY_HOURS.get(
                pattern.timeframe,
                Config.DEFAULT_PATTERN_EXPIRY_HOURS
            )
            expiry_ms = expiry_hours * 60 * 60 * 1000
            expires_at = pattern.detected_at + expiry_ms

            if now_ms > expires_at:
                pattern.status = 'expired'
                expired_count += 1

        if expired_count > 0:
            db.session.commit()
            if verbose:
                print(f"  Expired {expired_count} old patterns")

        return expired_count


def start_cron_run(app, job_name='fetch'):
    """Start tracking a cron run."""
    from app.models import CronJob, CronRun
    from app import db

    with app.app_context():
        # Get or create the job
        job = CronJob.query.filter_by(name=job_name).first()
        if not job:
            from app.models import CRON_JOB_TYPES
            config = CRON_JOB_TYPES.get(job_name, {})
            job = CronJob(
                name=job_name,
                description=config.get('description', ''),
                schedule=config.get('schedule', '* * * * *'),
                is_enabled=True
            )
            db.session.add(job)
            db.session.commit()

        # Check if job is enabled
        if not job.is_enabled:
            return None

        # Create a new run record
        run = CronRun(job_id=job.id)
        db.session.add(run)
        db.session.commit()
        return run.id


def complete_cron_run(app, run_id, success=True, error_message=None,
                      symbols_processed=0, candles_fetched=0, patterns_found=0,
                      signals_generated=0, notifications_sent=0):
    """Complete a cron run with results."""
    from app.models import CronRun
    from app import db

    if not run_id:
        return

    with app.app_context():
        run = CronRun.query.get(run_id)
        if run:
            run.ended_at = datetime.now(timezone.utc)
            run.duration_ms = int((run.ended_at - run.started_at).total_seconds() * 1000)
            run.success = success
            run.error_message = error_message
            run.symbols_processed = symbols_processed
            run.candles_fetched = candles_fetched
            run.patterns_found = patterns_found
            run.signals_generated = signals_generated
            run.notifications_sent = notifications_sent
            db.session.commit()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Candle fetcher with pattern detection')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--gaps', action='store_true', help='Fill data gaps (hourly job)')
    args = parser.parse_args()

    job_name = 'gaps' if args.gaps else 'fetch'

    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f"[{ts}] {'Filling gaps' if args.gaps else 'Fetching'}...", end=' ', flush=True)

    start_time = time.time()
    run_id = None
    error_msg = None

    from app import create_app
    from app.models import Symbol

    app = create_app()

    try:
        # Start tracking the run
        run_id = start_cron_run(app, job_name)
        if run_id is None:
            print("Job disabled, skipping")
            return

        with app.app_context():
            symbols = [s.symbol for s in Symbol.query.filter_by(is_active=True).all()]

        if not symbols:
            print("No active symbols found")
            complete_cron_run(app, run_id, success=True, symbols_processed=0)
            return

        if args.verbose:
            print(f"\n  {len(symbols)} symbols")

        # 1. Fetch and process all symbols (parallel)
        results = asyncio.run(run_fetch_cycle(symbols, app, args.verbose))

        # 2. Generate signals
        signal_result = generate_signals_batch(app, args.verbose)

        # 3. Expire old patterns
        expired = expire_old_patterns(app, args.verbose)

        elapsed = time.time() - start_time

        # Summary
        total_new = sum(r.get('new', 0) for r in results)
        total_patterns = sum(r.get('patterns', 0) for r in results)
        total_signals = signal_result.get('signals_generated', 0)
        errors = [r.get('error') for r in results if r.get('error')]

        # Log success (or partial success with errors)
        complete_cron_run(
            app, run_id,
            success=len(errors) == 0,
            error_message='; '.join(errors[:3]) if errors else None,
            symbols_processed=len(symbols),
            candles_fetched=total_new,
            patterns_found=total_patterns,
            signals_generated=total_signals,
            notifications_sent=0  # Updated by notification service if used
        )

        if args.verbose:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                  f"new={total_new} patterns={total_patterns} signals={total_signals} "
                  f"time={elapsed:.1f}s")
        else:
            print(f"done. {total_new} candles, {total_patterns} patterns, {total_signals} signals ({elapsed:.1f}s)")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"ERROR: {error_msg}")
        if args.verbose:
            traceback.print_exc()

        # Log failure
        complete_cron_run(
            app, run_id,
            success=False,
            error_message=error_msg
        )


if __name__ == '__main__':
    main()
