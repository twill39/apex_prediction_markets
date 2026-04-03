"""Screener for the 'Fundamental Whale' strategy"""

from typing import Set
import asyncio

from src.data.models import Platform
from .base_screener import TraderScreener
from src.discovery.trader_discovery import (
    get_recent_trades, get_user_trades, get_closed_positions,
)
from src.config import get_settings

class WhaleConvictionTracker(TraderScreener):
    """
    Identifies addresses that take massive directional bets and wait for
    resolution. Filters for concentrated, profitable whales rather than
    high-volume scatter traders.
    """
    
    def __init__(self, platform: Platform = Platform.POLYMARKET):
        super().__init__(platform)
        settings = get_settings().copy_trading.screeners.whale
        self.min_trade_size_usd = settings.min_trade_size_usd
        self.min_days_to_resolution = settings.min_days_to_resolution
        self.max_unique_markets = settings.max_unique_markets
        self.min_total_pnl = settings.min_total_pnl
        self.min_win_rate = settings.min_win_rate
        self.min_closed_positions = settings.min_closed_positions
        
    async def get_tracked_traders(self) -> Set[str]:
        self.logger.info("Scanning for Fundamental Whales...")
        
        # Fetch recent global trades to find big prints
        loop = asyncio.get_event_loop()
        recent_trades = await loop.run_in_executor(None, get_recent_trades, 1000)
        candidates = set()
        
        for t in recent_trades:
            try:
                price = float(t.get('price', 0))
                size = float(t.get('size', 0))
            except (ValueError, TypeError):
                continue
                
            trade_value = price * size
            if trade_value >= self.min_trade_size_usd:
                proxy = t.get("proxyWallet")
                if proxy:
                    candidates.add(proxy)

        self.logger.info(f"Evaluating {len(candidates)} whale candidates concurrently...")
        tracked = await self.evaluate_candidates_concurrent(list(candidates))
                
        self.logger.info(f"Found {len(tracked)} Fundamental Whales")
        return tracked
        
    async def evaluate_trader(self, trader_id: str) -> bool:
        """Verify the trader trades huge sizes, is concentrated in few
        markets, and maintains profitability."""
        try:
            loop = asyncio.get_event_loop()
            trades = await loop.run_in_executor(None, get_user_trades, trader_id, 200)
            if not trades:
                return False
                
            # --- Whale size confirmation ---
            has_whale_trade = False
            unique_assets = set()
            for t in trades:
                try:
                    price = float(t.get('price', 0))
                    size = float(t.get('size', 0))
                except (ValueError, TypeError):
                    continue
                    
                if price * size >= self.min_trade_size_usd:
                    has_whale_trade = True

                asset = t.get('asset')
                if asset:
                    unique_assets.add(asset)
                    
            if not has_whale_trade:
                return False

            # --- Market concentration check ---
            # Insider whales tend to operate in very few markets.
            num_unique_markets = len(unique_assets)
            if num_unique_markets > self.max_unique_markets:
                self.logger.debug(
                    f"Trader {trader_id} rejected: too many markets ({num_unique_markets})"
                )
                return False

            # --- Profitability check via closed positions ---
            positions = await loop.run_in_executor(None, get_closed_positions, trader_id, 100)

            # Require minimum closed positions — no more "benefit of the doubt"
            if not positions or len(positions) < self.min_closed_positions:
                self.logger.debug(
                    f"Trader {trader_id} rejected: insufficient closed positions "
                    f"({len(positions) if positions else 0})"
                )
                return False
                
            winning = 0
            total_pnl = 0.0
            for pos in positions:
                pnl = pos.get("realizedPnl", 0)
                try:
                    pnl = float(pnl)
                except (ValueError, TypeError):
                    pnl = 0.0
                total_pnl += pnl
                if pnl > 0:
                    winning += 1

            win_rate = winning / len(positions)
            
            if win_rate < self.min_win_rate:
                return False

            if total_pnl < self.min_total_pnl:
                return False

            self.logger.info(
                f"Trader {trader_id} is a Whale "
                f"(Win Rate: {win_rate:.2%}, Markets: {num_unique_markets}, "
                f"Total PnL: ${total_pnl:.2f}, Positions: {len(positions)})"
            )
            return True
                
        except Exception as e:
            self.logger.warning(f"Error evaluating trader {trader_id}: {e}")
            
        return False
