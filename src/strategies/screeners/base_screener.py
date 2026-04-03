"""Base interface for trader screeners"""

import abc
import asyncio
from typing import Dict, List, Set

from src.data.models import TraderPerformance, Platform
from src.utils.logger import get_logger

# Max concurrent API calls to Polymarket (avoid rate limiting)
DEFAULT_CONCURRENCY = 10


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

    async def evaluate_candidates_concurrent(
        self, candidates: List[str], concurrency: int = DEFAULT_CONCURRENCY
    ) -> Set[str]:
        """Evaluate a list of candidate trader IDs concurrently.

        Uses a semaphore to limit parallel API calls and avoid rate limits.
        ~10x faster than sequential evaluation with 0.1s sleeps.
        """
        semaphore = asyncio.Semaphore(concurrency)
        tracked: Set[str] = set()
        lock = asyncio.Lock()

        async def _eval(trader_id: str):
            async with semaphore:
                try:
                    if await self.evaluate_trader(trader_id):
                        async with lock:
                            tracked.add(trader_id)
                except Exception as e:
                    self.logger.warning(f"Error evaluating {trader_id}: {e}")

        await asyncio.gather(*[_eval(tid) for tid in candidates])
        return tracked
