"""Base interface for trader screeners"""

import abc
from typing import Dict, List, Set

from src.data.models import TraderPerformance, Platform
from src.utils.logger import get_logger

class TraderScreener(abc.ABC):
    """Base class for all trader identification strategies"""
    
    def __init__(self, platform: Platform = Platform.POLYMARKET):
        self.platform = platform
        self.logger = get_logger(self.__class__.__name__)
        
    @abc.abstractmethod
    async def get_tracked_traders(self) -> Set[str]:
        """
        Identify and return a set of trader addresses/IDs that match 
        this screener's specific criteria.
        """
        pass
        
    @abc.abstractmethod
    async def evaluate_trader(self, trader_id: str) -> bool:
        """
        Evaluate if a specific trader still meets the criteria.
        Returns True if they should be copied, False otherwise.
        """
        pass
