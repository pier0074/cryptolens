"""
Signal Generation Service
Generates trade signals from detected patterns
"""
import json
from typing import Optional, Dict, List
from app.models import Symbol, Pattern, Signal, Setting
from app.config import Config
from app import db


def calculate_atr(symbol: str, timeframe: str, period: int = 14) -> float:
    """
    Calculate Average True Range for position sizing

    Returns:
        ATR value
    """
    from app.services.aggregator import get_candles_as_dataframe

    df = get_candles_as_dataframe(symbol, timeframe, limit=period + 1)

    if df.empty or len(df) < period:
        return 0.0

    # Calculate True Range
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['prev_close'])
    df['tr3'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

    # ATR is the average of True Range
    atr = df['tr'].tail(period).mean()

    return atr if atr else 0.0


def generate_signal_from_pattern(pattern: Pattern, current_price: float = None) -> Optional[Signal]:
    """
    Generate a trade signal from a detected pattern

    Args:
        pattern: The pattern to generate signal from
        current_price: Current market price (optional, used for validation)

    Returns:
        Signal object or None
    """
    symbol = db.session.get(Symbol, pattern.symbol_id)
    if not symbol:
        return None

    # Get risk parameters from settings
    default_rr = float(Setting.get('default_rr', '3.0'))
    min_risk_pct = float(Setting.get('min_risk_pct', '0.5'))  # Minimum 0.5% risk

    # Calculate ATR for buffer
    atr = calculate_atr(symbol.symbol, pattern.timeframe)

    # Use ATR-based buffer or minimum 0.5% of zone midpoint
    zone_mid = (pattern.zone_high + pattern.zone_low) / 2
    min_buffer = zone_mid * (min_risk_pct / 100)
    buffer = max(atr * 0.5, min_buffer) if atr > 0 else min_buffer

    if pattern.direction == 'bullish':
        # Long signal
        entry = pattern.zone_high  # Enter at top of imbalance
        stop_loss = pattern.zone_low - buffer  # SL below zone
        risk = entry - stop_loss

        # Ensure minimum risk percentage
        risk_pct = (risk / entry) * 100 if entry > 0 else 0
        if risk_pct < min_risk_pct:
            # Adjust stop loss to meet minimum risk
            risk = entry * (min_risk_pct / 100)
            stop_loss = entry - risk

        take_profit_1 = entry + risk  # 1:1
        take_profit_2 = entry + (risk * 2)  # 1:2
        take_profit_3 = entry + (risk * default_rr)  # 1:RR

        direction = 'long'

    else:  # bearish
        # Short signal
        entry = pattern.zone_low  # Enter at bottom of imbalance
        stop_loss = pattern.zone_high + buffer  # SL above zone
        risk = stop_loss - entry

        # Ensure minimum risk percentage
        risk_pct = (risk / entry) * 100 if entry > 0 else 0
        if risk_pct < min_risk_pct:
            # Adjust stop loss to meet minimum risk
            risk = entry * (min_risk_pct / 100)
            stop_loss = entry + risk

        take_profit_1 = entry - risk  # 1:1
        take_profit_2 = entry - (risk * 2)  # 1:2
        take_profit_3 = entry - (risk * default_rr)  # 1:RR

        direction = 'short'

    # Create signal
    signal = Signal(
        symbol_id=pattern.symbol_id,
        direction=direction,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        take_profit_3=take_profit_3,
        risk_reward=default_rr,
        confluence_score=1,
        pattern_id=pattern.id,
        status='pending'
    )

    return signal


def check_confluence(symbol: str) -> Dict:
    """
    Check for confluence across timeframes

    Returns:
        Dict with confluence info
    """
    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return {'bullish': [], 'bearish': [], 'score': 0}

    bullish_tfs = []
    bearish_tfs = []

    for tf in Config.TIMEFRAMES:
        # Get most recent active pattern
        pattern = Pattern.query.filter_by(
            symbol_id=sym.id,
            timeframe=tf,
            status='active'
        ).order_by(Pattern.detected_at.desc()).first()

        if pattern:
            if pattern.direction == 'bullish':
                bullish_tfs.append(tf)
            else:
                bearish_tfs.append(tf)

    # Determine dominant direction
    if len(bullish_tfs) > len(bearish_tfs):
        dominant = 'bullish'
        score = len(bullish_tfs)
        aligned = bullish_tfs
    elif len(bearish_tfs) > len(bullish_tfs):
        dominant = 'bearish'
        score = len(bearish_tfs)
        aligned = bearish_tfs
    else:
        dominant = 'neutral'
        score = 0
        aligned = []

    return {
        'bullish': bullish_tfs,
        'bearish': bearish_tfs,
        'dominant': dominant,
        'score': score,
        'aligned_timeframes': aligned
    }


def generate_confluence_signal(symbol: str) -> Optional[Signal]:
    """
    Generate a signal based on multi-timeframe confluence

    Returns:
        Signal if confluence threshold met, else None
    """
    from datetime import datetime, timedelta, timezone

    # Settings for relaxed trading
    min_confluence = int(Setting.get('min_confluence', '3'))  # Require 3+ timeframes
    cooldown_hours = int(Setting.get('signal_cooldown_hours', '4'))  # 4 hour cooldown per symbol/direction
    require_htf = Setting.get('require_htf', 'true') == 'true'  # Require higher timeframe (4h or 1d)

    confluence = check_confluence(symbol)

    if confluence['score'] < min_confluence:
        return None

    sym = Symbol.query.filter_by(symbol=symbol).first()
    if not sym:
        return None

    # Check if higher timeframe is aligned (for relaxed trading)
    htf_aligned = any(tf in confluence['aligned_timeframes'] for tf in ['4h', '1d'])
    if require_htf and not htf_aligned:
        return None  # Skip if no higher timeframe confirmation

    # Check for recent signal on same symbol/direction (cooldown)
    cooldown_time = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
    recent_signal = Signal.query.filter(
        Signal.symbol_id == sym.id,
        Signal.direction == ('long' if confluence['dominant'] == 'bullish' else 'short'),
        Signal.created_at >= cooldown_time
    ).first()

    if recent_signal:
        return None  # Already notified recently, skip

    # Get the pattern from the highest timeframe in alignment
    tf_priority = ['1d', '4h', '1h', '15m', '5m', '1m']

    pattern = None
    for tf in tf_priority:
        if tf in confluence['aligned_timeframes']:
            pattern = Pattern.query.filter_by(
                symbol_id=sym.id,
                timeframe=tf,
                direction=confluence['dominant'],
                status='active'
            ).order_by(Pattern.detected_at.desc()).first()
            if pattern:
                break

    if not pattern:
        return None

    # Generate signal from the highest TF pattern
    signal = generate_signal_from_pattern(pattern)
    if signal:
        signal.confluence_score = confluence['score']
        signal.timeframes_aligned = json.dumps(confluence['aligned_timeframes'])

        try:
            db.session.add(signal)
            db.session.commit()

            # Get current price for notification
            from app.services.aggregator import get_candles_as_dataframe
            df = get_candles_as_dataframe(symbol, '1m', limit=1)
            current_price = float(df['close'].iloc[-1]) if not df.empty else None

            # Notify for high-quality signals (if notifications enabled for this symbol)
            if sym.notify_enabled:
                from app.services.notifier import notify_signal
                notify_signal(signal, current_price=current_price)
        except Exception as e:
            db.session.rollback()
            from app.services.logger import log_error
            log_error(f"Failed to save signal: {e}", symbol=symbol)
            return None

    return signal


def scan_and_generate_signals() -> Dict:
    """
    Scan all symbols and generate signals where confluence exists

    Returns:
        Results dict
    """
    symbols = Symbol.query.filter_by(is_active=True).all()

    results = {
        'signals_generated': 0,
        'notifications_sent': 0,
        'symbols_scanned': len(symbols)
    }

    for symbol in symbols:
        signal = generate_confluence_signal(symbol.symbol)
        if signal:
            results['signals_generated'] += 1
            if signal.status == 'notified':
                results['notifications_sent'] += 1

    return results
