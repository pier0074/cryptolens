"""
Base Pattern Detector
Abstract base class for all pattern detectors
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd


class PatternDetector(ABC):
    """Abstract base class for pattern detection"""

    @property
    @abstractmethod
    def pattern_type(self) -> str:
        """Return the pattern type name"""
        pass

    @abstractmethod
    def detect(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Detect patterns in the given symbol/timeframe

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h')
            limit: Number of candles to analyze

        Returns:
            List of detected patterns
        """
        pass

    @abstractmethod
    def check_fill(self, pattern: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Check if a pattern has been filled

        Args:
            pattern: The pattern to check
            current_price: Current market price

        Returns:
            Updated pattern with fill status
        """
        pass

    def get_candles_df(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Get candles as DataFrame"""
        from app.services.aggregator import get_candles_as_dataframe
        return get_candles_as_dataframe(symbol, timeframe, limit)
