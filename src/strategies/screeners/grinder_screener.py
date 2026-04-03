"""Screener for the 'Consistent Grinder' strategy"""

from typing import Set
import asyncio

from src.data.models import Platform
from .base_screener import TraderScreener
from src.discovery.trader_discovery import discover_traders, get_closed_positions
from src.config import get_settings

class ConsistentGrinderScreener(TraderScreener):
    """
    Identifies traders with high volume and high win rate who also generate
    meaningful PnL per trade. Filters out noise traders who win often
    but on negligible amounts.
    """
    
    def __init__(self, platform: Platform = Platform.POLYMARKET):
        super().__init__(platform)
        settings = get_settings().copy_trading.screeners.grinder
        self.min_positions = settings.min_positions
        self.max_positions = settings.max_positions
        self.min_win_rate = settings.min_win_rate
        self.min_total_pnl = settings.min_total_pnl
        self.min_avg_pnl_per_trade = settings.min_avg_pnl_per_trade
        
    async def get_tracked_traders(self) -> Set[str]:
        self.logger.info("Scanning for Consistent Grinders...")
        
        # Fetch leaderboard top traders ordered by PnL to use as a base pool.
        loop = asyncio.get_event_loop()
        candidates = await loop.run_in_executor(None, discover_traders, 200)
        
        # Pre-filter by leaderboard PnL before hitting per-user API
        candidate_ids = []
        for candidate in candidates:
            proxy_wallet = candidate.get("proxyWallet")
            if not proxy_wallet:
                continue
            leaderboard_pnl = candidate.get("pnl")
            if leaderboard_pnl is not None and leaderboard_pnl < self.min_total_pnl:
                continue
            candidate_ids.append(proxy_wallet)

        self.logger.info(f"Evaluating {len(candidate_ids)} candidates concurrently...")
        tracked = await self.evaluate_candidates_concurrent(candidate_ids)
                
        self.logger.info(f"Found {len(tracked)} Consistent Grinders")
        return tracked
        
    async def evaluate_trader(self, trader_id: str) -> bool:
        """Evaluate if a trader has a high enough win rate, sufficient PnL,
        and meaningful per-trade profitability."""
        try:
            loop = asyncio.get_event_loop()
            positions = await loop.run_in_executor(None, get_closed_positions, trader_id, 200)
            if not positions:
                return False

            num_positions = len(positions)

            # Position count band: must be within [min, max]
            if num_positions < self.min_positions:
                return False
            if num_positions > self.max_positions:
                return False
                
            winning_trades = 0
            total_pnl = 0.0
            for pos in positions:
                pnl = pos.get("realizedPnl", 0)
                try:
                    pnl = float(pnl)
                except (ValueError, TypeError):
                    pnl = 0.0
                total_pnl += pnl
                if pnl > 0:
                    winning_trades += 1
                    
            win_rate = winning_trades / num_positions
            avg_pnl = total_pnl / num_positions
            
            if win_rate < self.min_win_rate:
                return False
            if total_pnl < self.min_total_pnl:
                return False
            if avg_pnl < self.min_avg_pnl_per_trade:
                return False

            self.logger.info(
                f"Trader {trader_id} is a Consistent Grinder "
                f"(Win Rate: {win_rate:.2%}, Trades: {num_positions}, "
                f"Total PnL: ${total_pnl:.2f}, Avg PnL/Trade: ${avg_pnl:.2f})"
            )
            return True
                
        except Exception as e:
            self.logger.warning(f"Error evaluating trader {trader_id}: {e}")
            
        return False
