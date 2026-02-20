"""Trading strategies"""

from .base import BaseStrategy, StrategySignal, StrategyState
from .copy_trading import CopyTradingStrategy
from .market_making import MarketMakingStrategy
from .alt_data import AltDataStrategy

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "StrategyState",
    "CopyTradingStrategy",
    "MarketMakingStrategy",
    "AltDataStrategy"
]
