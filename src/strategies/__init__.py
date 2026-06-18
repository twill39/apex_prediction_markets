"""Trading strategies"""

from .base import BaseStrategy, StrategySignal, StrategyState
from .copy_trading import CopyTradingStrategy
from .market_making import MarketMakingStrategy
from .market_making_as import MarketMakingStrategy as MarketMakingAsStrategy
from .alt_data import AltDataStrategy

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "StrategyState",
    "CopyTradingStrategy",
    "MarketMakingStrategy",
    "MarketMakingAsStrategy",
    "AltDataStrategy"
]
