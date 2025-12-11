"""
Tests for the aggregator service.

These tests ensure timeframe configuration consistency across the codebase
to prevent bugs where some timeframes are missing from aggregation.
"""
import pytest
from app.config import Config
from app.services.aggregator import (
    AGGREGATION_TIMEFRAMES,
    RESAMPLE_RULES,
    TIMEFRAME_MINUTES,
    aggregate_candles,
    aggregate_all_timeframes
)


class TestTimeframeConsistency:
    """Tests to ensure timeframe lists stay in sync across the codebase."""

    def test_aggregation_timeframes_have_resample_rules(self):
        """Every timeframe in AGGREGATION_TIMEFRAMES must have a resample rule."""
        for tf in AGGREGATION_TIMEFRAMES:
            assert tf in RESAMPLE_RULES, (
                f"Timeframe '{tf}' is in AGGREGATION_TIMEFRAMES but missing from RESAMPLE_RULES. "
                f"Add '{tf}' to RESAMPLE_RULES in aggregator.py"
            )

    def test_resample_rules_match_aggregation_timeframes(self):
        """RESAMPLE_RULES should only contain aggregatable timeframes."""
        for tf in RESAMPLE_RULES:
            assert tf in AGGREGATION_TIMEFRAMES, (
                f"Timeframe '{tf}' is in RESAMPLE_RULES but not in AGGREGATION_TIMEFRAMES. "
                f"Either add it to AGGREGATION_TIMEFRAMES or remove from RESAMPLE_RULES"
            )

    def test_aggregation_timeframes_have_minutes(self):
        """Every aggregation timeframe must have a minute multiplier."""
        for tf in AGGREGATION_TIMEFRAMES:
            assert tf in TIMEFRAME_MINUTES, (
                f"Timeframe '{tf}' is in AGGREGATION_TIMEFRAMES but missing from TIMEFRAME_MINUTES. "
                f"Add '{tf}' to TIMEFRAME_MINUTES in aggregator.py"
            )

    def test_config_pattern_timeframes_are_aggregatable(self):
        """All Config.PATTERN_TIMEFRAMES must be in AGGREGATION_TIMEFRAMES (except 1m)."""
        for tf in Config.PATTERN_TIMEFRAMES:
            if tf != '1m':
                assert tf in AGGREGATION_TIMEFRAMES, (
                    f"Config.PATTERN_TIMEFRAMES contains '{tf}' but it's not in AGGREGATION_TIMEFRAMES. "
                    f"Add '{tf}' to AGGREGATION_TIMEFRAMES in aggregator.py"
                )

    def test_config_timeframes_are_known(self):
        """All Config.TIMEFRAMES must be either 1m or in AGGREGATION_TIMEFRAMES."""
        for tf in Config.TIMEFRAMES:
            if tf != '1m':
                assert tf in AGGREGATION_TIMEFRAMES, (
                    f"Config.TIMEFRAMES contains '{tf}' but it's not in AGGREGATION_TIMEFRAMES. "
                    f"Add '{tf}' to AGGREGATION_TIMEFRAMES in aggregator.py"
                )

    def test_aggregation_order_is_ascending(self):
        """AGGREGATION_TIMEFRAMES should be in ascending order (smallest to largest)."""
        minutes = [TIMEFRAME_MINUTES[tf] for tf in AGGREGATION_TIMEFRAMES]
        assert minutes == sorted(minutes), (
            f"AGGREGATION_TIMEFRAMES is not in ascending order. "
            f"Current: {AGGREGATION_TIMEFRAMES}, should be sorted by duration"
        )

    def test_no_duplicate_timeframes(self):
        """No duplicate timeframes in any list."""
        assert len(AGGREGATION_TIMEFRAMES) == len(set(AGGREGATION_TIMEFRAMES)), (
            "AGGREGATION_TIMEFRAMES contains duplicates"
        )
        assert len(Config.TIMEFRAMES) == len(set(Config.TIMEFRAMES)), (
            "Config.TIMEFRAMES contains duplicates"
        )
        assert len(Config.PATTERN_TIMEFRAMES) == len(set(Config.PATTERN_TIMEFRAMES)), (
            "Config.PATTERN_TIMEFRAMES contains duplicates"
        )


class TestResampleRulesValid:
    """Tests that resample rules produce valid pandas rules."""

    @pytest.mark.parametrize("tf,rule", RESAMPLE_RULES.items())
    def test_resample_rule_format(self, tf, rule):
        """Each resample rule should be a valid pandas offset alias."""
        import pandas as pd
        # This will raise if the rule is invalid
        try:
            pd.Timedelta(rule)
        except ValueError:
            # Some rules like '1D' need different validation
            try:
                pd.tseries.frequencies.to_offset(rule)
            except ValueError:
                pytest.fail(f"Invalid resample rule '{rule}' for timeframe '{tf}'")


class TestAggregatorFunctions:
    """Tests for aggregator function behavior."""

    def test_aggregate_candles_returns_zero_for_unknown_timeframe(self, app):
        """aggregate_candles should return 0 for unknown timeframes."""
        with app.app_context():
            result = aggregate_candles('BTC/USDT', '1m', 'unknown_tf')
            assert result == 0

    def test_aggregate_candles_returns_zero_for_missing_symbol(self, app):
        """aggregate_candles should return 0 for non-existent symbols."""
        with app.app_context():
            result = aggregate_candles('NONEXISTENT/USDT', '1m', '5m')
            assert result == 0

    def test_aggregate_all_timeframes_returns_dict(self, app):
        """aggregate_all_timeframes should return a dict with all timeframes."""
        with app.app_context():
            result = aggregate_all_timeframes('BTC/USDT')
            assert isinstance(result, dict)
            # Should have entry for each aggregation timeframe
            for tf in AGGREGATION_TIMEFRAMES:
                assert tf in result, f"Missing timeframe '{tf}' in result"


class TestExpectedTimeframes:
    """Tests documenting expected timeframe configuration."""

    def test_expected_aggregation_timeframes(self):
        """Document and verify expected aggregation timeframes."""
        expected = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
        assert AGGREGATION_TIMEFRAMES == expected, (
            f"AGGREGATION_TIMEFRAMES changed unexpectedly. "
            f"Expected: {expected}, Got: {AGGREGATION_TIMEFRAMES}. "
            f"If intentional, update this test."
        )

    def test_expected_config_timeframes(self):
        """Document and verify expected Config.TIMEFRAMES."""
        # Note: 1m removed as it's too noisy for reliable pattern detection
        expected = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
        assert Config.TIMEFRAMES == expected, (
            f"Config.TIMEFRAMES changed unexpectedly. "
            f"Expected: {expected}, Got: {Config.TIMEFRAMES}. "
            f"If intentional, update this test."
        )

    def test_expected_pattern_timeframes(self):
        """Document and verify expected Config.PATTERN_TIMEFRAMES."""
        expected = ['5m', '15m', '30m', '1h', '2h', '4h', '1d']
        assert Config.PATTERN_TIMEFRAMES == expected, (
            f"Config.PATTERN_TIMEFRAMES changed unexpectedly. "
            f"Expected: {expected}, Got: {Config.PATTERN_TIMEFRAMES}. "
            f"If intentional, update this test."
        )
