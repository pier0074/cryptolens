"""
Scanner Background Jobs
Pattern scanning and signal processing via RQ
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger('cryptolens')


def scan_patterns_job(
    symbol_id: Optional[int] = None,
    timeframes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Background job to scan for patterns.

    Args:
        symbol_id: Optional specific symbol to scan (None = all active)
        timeframes: Optional list of timeframes to scan (None = all)

    Returns:
        Dict with scan results
    """
    from app import create_app, db
    from app.models import Symbol, Pattern
    from app.services.patterns import scan_all_patterns

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)

        # Get symbols to scan
        if symbol_id:
            symbols = [db.session.get(Symbol, symbol_id)]
            symbols = [s for s in symbols if s and s.is_active]
        else:
            symbols = Symbol.query.filter_by(is_active=True).all()

        if not symbols:
            return {'error': 'No active symbols to scan'}

        total_patterns = 0
        scan_results = []

        for symbol in symbols:
            try:
                # Scan patterns for this symbol
                patterns_found = scan_all_patterns(
                    symbol.id,
                    timeframes=timeframes
                )
                total_patterns += patterns_found
                scan_results.append({
                    'symbol': symbol.symbol,
                    'patterns_found': patterns_found
                })
            except Exception as e:
                logger.error(f"[JOB] Error scanning {symbol.symbol}: {e}")
                scan_results.append({
                    'symbol': symbol.symbol,
                    'error': str(e)
                })

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(
            f"[JOB] Pattern scan complete: {total_patterns} patterns found "
            f"across {len(symbols)} symbols in {elapsed:.2f}s"
        )

        return {
            'symbols_scanned': len(symbols),
            'patterns_found': total_patterns,
            'elapsed_seconds': elapsed,
            'results': scan_results
        }


def process_signals_job(
    min_confluence: int = 2,
    notify: bool = True
) -> Dict[str, Any]:
    """
    Background job to process patterns and generate signals.

    Args:
        min_confluence: Minimum confluence score required
        notify: Whether to send notifications for new signals

    Returns:
        Dict with processing results
    """
    from app import create_app, db
    from app.models import Symbol, Signal
    from app.services.signal_generator import generate_signals_for_symbol

    app = create_app()
    with app.app_context():
        start_time = datetime.now(timezone.utc)

        symbols = Symbol.query.filter_by(is_active=True).all()
        if not symbols:
            return {'error': 'No active symbols'}

        total_signals = 0
        signal_results = []

        for symbol in symbols:
            try:
                signals = generate_signals_for_symbol(
                    symbol.id,
                    min_confluence=min_confluence,
                    notify=notify
                )
                total_signals += len(signals)
                signal_results.append({
                    'symbol': symbol.symbol,
                    'signals_generated': len(signals)
                })
            except Exception as e:
                logger.error(f"[JOB] Error processing signals for {symbol.symbol}: {e}")
                signal_results.append({
                    'symbol': symbol.symbol,
                    'error': str(e)
                })

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(
            f"[JOB] Signal processing complete: {total_signals} signals generated "
            f"across {len(symbols)} symbols in {elapsed:.2f}s"
        )

        return {
            'symbols_processed': len(symbols),
            'signals_generated': total_signals,
            'elapsed_seconds': elapsed,
            'results': signal_results
        }
