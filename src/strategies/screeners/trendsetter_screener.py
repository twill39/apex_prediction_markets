"""Screener for the 'Early Trendsetter' strategy"""

from typing import Set
import asyncio

from src.data.models import Platform
from .base_screener import TraderScreener
from src.discovery.trader_discovery import get_recent_trades, get_user_trades
from src.config import get_settings

class TrendsetterScreener(TraderScreener):
    """
    Identifies traders who consistently capture large price movements
    via early entries and exits without necessarily holding to market resolution.
    Focus: Traders with large entry vs. exit margins on round trips,
    with meaningful trade sizes.
    """
    
    def __init__(self, platform: Platform = Platform.POLYMARKET):
        super().__init__(platform)
        settings = get_settings().copy_trading.screeners.trendsetter
        self.min_capture_margin = settings.min_capture_margin
        self.min_hold_time_hours = settings.min_hold_time_hours
        self.min_round_trips = settings.min_round_trips
        self.min_win_rate = settings.min_win_rate
        self.min_avg_trade_size = settings.min_avg_trade_size
        
    async def get_tracked_traders(self) -> Set[str]:
        self.logger.info("Scanning for Early Trendsetters...")
        
        # Fetch recent active traders from the global tape.
        loop = asyncio.get_event_loop()
        recent_trades = await loop.run_in_executor(None, get_recent_trades, 1000)
        candidates = set()
        for t in recent_trades:
            proxy = t.get("proxyWallet")
            if proxy:
                candidates.add(proxy)

        self.logger.info(f"Evaluating {len(candidates)} trendsetter candidates concurrently...")
        tracked = await self.evaluate_candidates_concurrent(list(candidates))
                
        self.logger.info(f"Found {len(tracked)} Early Trendsetters")
        return tracked
        
    async def evaluate_trader(self, trader_id: str) -> bool:
        """Evaluate if trader captures large margins on round trips with
        meaningful trade sizes."""
        try:
            loop = asyncio.get_event_loop()
            trades = await loop.run_in_executor(None, get_user_trades, trader_id, 1000)
            if not trades:
                return False
                
            # Sort trades oldest to newest for chronological simulation
            trades.sort(key=lambda x: int(x.get('timestamp', 0)))
            
            asset_positions = {}
            round_trips = []
            
            for t in trades:
                asset = t.get('asset')
                side = t.get('side')
                
                try:
                    price = float(t.get('price', 0))
                    size = float(t.get('size', 0))
                    ts = int(t.get('timestamp', 0))
                except (ValueError, TypeError):
                    continue
                
                if not asset or price <= 0 or size <= 0:
                    continue
                    
                if asset not in asset_positions:
                    asset_positions[asset] = {
                        'size': 0.0, 'cost': 0.0, 'first_buy_ts': 0
                    }
                    
                pos = asset_positions[asset]
                
                if side == 'BUY':
                    if pos['size'] == 0:
                        pos['first_buy_ts'] = ts
                    pos['size'] += size
                    pos['cost'] += size * price
                elif side == 'SELL':
                    if pos['size'] > 0:
                        # Selling part or all of the position
                        sell_size = min(size, pos['size'])
                        avg_buy_price = pos['cost'] / pos['size']
                        
                        margin = (
                            (price - avg_buy_price) / avg_buy_price
                            if avg_buy_price > 0 else 0
                        )
                        hold_time_hours = (ts - pos['first_buy_ts']) / 3600.0
                        trade_value = sell_size * price
                        
                        round_trips.append({
                            'margin': margin,
                            'hold_time': hold_time_hours,
                            'trade_value': trade_value,
                        })
                        
                        pos['size'] -= sell_size
                        pos['cost'] -= sell_size * avg_buy_price

                        # FIX: Reset first_buy_ts when position fully closes
                        # so the next buy starts a fresh hold-time window.
                        if pos['size'] <= 1e-9:
                            pos['size'] = 0.0
                            pos['cost'] = 0.0
                            pos['first_buy_ts'] = 0

            # Filter valid round trips by hold time
            valid_rt = [
                rt for rt in round_trips
                if rt['hold_time'] >= self.min_hold_time_hours
            ]
            
            if len(valid_rt) < self.min_round_trips:
                return False
                
            avg_margin = sum(rt['margin'] for rt in valid_rt) / len(valid_rt)
            win_rate = sum(1 for rt in valid_rt if rt['margin'] > 0) / len(valid_rt)
            avg_trade_size = (
                sum(rt['trade_value'] for rt in valid_rt) / len(valid_rt)
            )
            
            if avg_margin < self.min_capture_margin:
                return False
            if win_rate < self.min_win_rate:
                return False
            if avg_trade_size < self.min_avg_trade_size:
                return False

            self.logger.info(
                f"Trader {trader_id} is a Trendsetter "
                f"(Avg Margin: {avg_margin:.2%}, Win Rate: {win_rate:.2%}, "
                f"Round Trips: {len(valid_rt)}, Avg Size: ${avg_trade_size:.2f})"
            )
            return True
                
        except Exception as e:
            self.logger.warning(f"Error evaluating trader {trader_id}: {e}")
            
        return False
