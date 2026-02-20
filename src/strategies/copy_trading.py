"""Copy Trading Strategy - Copy profitable traders"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import numpy as np

from .base import BaseStrategy, StrategySignal, StrategyState
from src.data.models import (
    Platform, Trade, OrderBook, OrderSide, Position, TraderPerformance
)
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.config import get_settings
from src.utils.logger import get_logger
from src.strategies.screeners import (
    ConsistentGrinderScreener,
    WhaleConvictionTracker,
    TrendsetterScreener
)

class CopyTradingStrategy(BaseStrategy):
    """Strategy that copies profitable traders"""
    
    def __init__(self, use_kalshi: Optional[bool] = None):
        """Initialize copy trading strategy"""
        super().__init__(
            strategy_id="copy_trading",
            name="Copy Trading Strategy"
        )
        self.settings = get_settings()
        self.use_kalshi = use_kalshi if use_kalshi is not None else self.settings.copy_trading.use_kalshi
        self.logger = get_logger("CopyTradingStrategy")
        self.storage = get_storage()
        
        # Tracked traders
        self.tracked_traders: Set[str] = set()
        self.trader_performance: Dict[str, TraderPerformance] = {}
        
        # Market mapping between platforms
        self.market_mapping: Dict[str, Dict[Platform, str]] = {}
        
        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
        
        # Screeners
        self.screeners = [
            ConsistentGrinderScreener(),
            WhaleConvictionTracker(),
            TrendsetterScreener()
        ]
        
        # Trader activity tracking
        self.trader_positions: Dict[str, Dict[str, Position]] = {}  # trader_id -> {market_id: position}
        self.trader_trades: Dict[str, List[Trade]] = {}  # trader_id -> [trades]
    
    async def initialize(self):
        """Initialize the strategy"""
        self.logger.info("Initializing copy trading strategy")
        
        # Initialize WebSocket clients
        try:
            self.polymarket_ws = PolymarketWebSocket()
            self.polymarket_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
            self.polymarket_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
        except Exception as e:
            self.logger.error(f"Failed to initialize Polymarket WebSocket client (required): {e}", exc_info=True)
            self.state = StrategyState.ERROR
            return
            
        if self.use_kalshi:
            try:
                self.kalshi_ws = KalshiWebSocket()
                self.kalshi_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
                self.kalshi_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
            except Exception as e:
                self.logger.warning(f"Failed to initialize Kalshi WebSocket client (optional): {e}", exc_info=True)
        
        # Load top traders
        await self._load_top_traders()
        
        self.logger.info(f"Initialized with {len(self.tracked_traders)} tracked traders")
    
    async def _load_top_traders(self):
        """Load top profitable traders from Polymarket using screeners"""
        self.logger.info("loading top traders from screeners...")
        
        # Gather tracked traders from all screeners
        for screener in self.screeners:
            try:
                screener_traders = await screener.get_tracked_traders()
                self.tracked_traders.update(screener_traders)
            except Exception as e:
                self.logger.error(f"Error fetching from screener {screener.__class__.__name__}: {e}")
                
        self.logger.info(f"Loaded {len(self.tracked_traders)} base target traders")
    
    def _calculate_trader_metrics(self, trader_id: str, platform: Platform) -> TraderPerformance:
        """Calculate performance metrics for a trader"""
        trades = self.trader_trades.get(trader_id, [])
        platform_trades = [t for t in trades if t.platform == platform]
        
        if not platform_trades:
            return TraderPerformance(
                trader_id=trader_id,
                platform=platform,
                last_updated=datetime.utcnow()
            )
            
        # Optional: HFT Bot Filtering
        # If they traded thousands of times in a day, they're an HFT bot.
        # Check trade rate: count / timeframe
        if len(platform_trades) > 100:
            dt = platform_trades[-1].timestamp - platform_trades[0].timestamp
            if dt.total_seconds() > 0:
                trades_per_sec = len(platform_trades) / dt.total_seconds()
                if trades_per_sec > 1.0: # simplistic HFT heuristic
                    self.logger.debug(f"{trader_id} exhibits HFT behavior ({trades_per_sec:.2f} t/s). Ignoring.")
                    # return empty/zeroed performance
                    return TraderPerformance(trader_id=trader_id, platform=platform, win_rate=0.0)
        
        # Calculate metrics
        winning = sum(1 for t in platform_trades if t.price > 0)  # Simplified
        losing = len(platform_trades) - winning
        win_rate = winning / len(platform_trades) if platform_trades else 0.0
        
        # Calculate PnL (simplified - would need position tracking)
        total_pnl = sum([t.size * t.price for t in platform_trades])  # Very simplified
        
        # Calculate Sharpe ratio (simplified)
        returns = [t.price / 0.5 - 1 for t in platform_trades]  # Conceptual proxy
        sharpe = None
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
        
        return TraderPerformance(
            trader_id=trader_id,
            platform=platform,
            total_trades=len(platform_trades),
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe,
            average_trade_size=np.mean([t.size for t in platform_trades]) if platform_trades else 0.0,
            last_updated=datetime.utcnow()
        )
    
    async def _identify_profitable_traders(self) -> List[str]:
        """Identify most profitable traders to copy"""
        # Calculate metrics for all tracked traders
        for trader_id in self.tracked_traders:
            for platform in [Platform.POLYMARKET, Platform.KALSHI]:
                performance = self._calculate_trader_metrics(trader_id, platform)
                self.trader_performance[f"{trader_id}_{platform.value}"] = performance
        
        # Sort by performance (e.g., Sharpe ratio, win rate, ROI)
        sorted_traders = sorted(
            self.trader_performance.items(),
            key=lambda x: (
                x[1].sharpe_ratio or 0,
                x[1].win_rate,
                x[1].total_pnl
            ),
            reverse=True
        )
        
        # Return top N traders
        max_traders = self.settings.copy_trading.max_traders
        top_traders = [t[0].split("_")[0] for t in sorted_traders[:max_traders]]
        
        return list(set(top_traders))  # Remove duplicates
    
    async def _on_websocket_event(self, event: WebSocketEvent):
        """Handle WebSocket events"""
        if self.state != StrategyState.RUNNING:
            return
        
        await self.on_market_event(event)
    
    async def on_market_event(self, event: WebSocketEvent):
        """Handle market event"""
        if event.event_type == WebSocketEventType.TRADE:
            trade_data = event.data.get("trade")
            if trade_data:
                trade = Trade(**trade_data)
                await self.on_trade(trade)
        
        elif event.event_type == WebSocketEventType.ORDERBOOK_UPDATE:
            orderbook_data = event.data.get("orderbook")
            if orderbook_data:
                orderbook = OrderBook(**orderbook_data)
                await self.on_orderbook_update(orderbook)
    
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update"""
        # Store order book data for analysis
        pass
    
    async def on_trade(self, trade: Trade):
        """Handle trade event"""
        # Track trader activity
        trader_id = trade.metadata.get("trader_id")
        if trader_id:
            if trader_id not in self.tracked_traders:
                self.tracked_traders.add(trader_id)
                self.trader_trades[trader_id] = []
                self.trader_positions[trader_id] = {}
            
            self.trader_trades[trader_id].append(trade)
            
            # Update performance metrics
            performance = self._calculate_trader_metrics(trader_id, trade.platform)
            self.trader_performance[f"{trader_id}_{trade.platform.value}"] = performance
            self.storage.save_trader_performance(performance)
    
    async def _copy_trader_trade(self, trader_id: str, trade: Trade) -> Optional[StrategySignal]:
        """Generate signal to copy a trader's trade"""
        # Check if trader is in top performers or tracked pool
        if trader_id not in self.tracked_traders:
            return None
        
        # Ask screeners if they consider this trader still viable
        is_viable = False
        for screener in self.screeners:
            if await screener.evaluate_trader(trader_id):
                is_viable = True
                break
                
        if not is_viable:
            return None
            
        # Get trader performance
        performance_key = f"{trader_id}_{trade.platform.value}"
        performance = self.trader_performance.get(performance_key)
        
        if not performance or performance.win_rate < 0.5:
            return None  # Only copy profitable traders
            
        # Slippage Check / Limit
        # Determine current best available price from our local orderbook cache
        # If it's more than 2-5% worse than the trade.price, abort to avoid MEV.
        # Note: Need mock or actual orderbook lookups here.
        # Assuming we had an orderbook cache `self.orderbooks[trade.market_id]` here.
        max_slippage = 0.02
        acceptable_price = trade.price * (1 + max_slippage) if trade.side == OrderSide.BUY else trade.price * (1 - max_slippage)
        # Placeholder for slippage abort:
        # if current_best_price > acceptable_price:
        #    return None
        
        # Generate copy signal and proportional sizing
        # Instead of max_size, we might use a percentage of our portfolio
        # For this implementation plan, we stick to fixed size config or max
        max_size = self.settings.copy_trading.max_position_size
        # Sizing proportional up to max_size, e.g., if trade size is $10,000 we cap to $50.
        size = min(trade.size, max_size)
        
        # Map to other platform if needed
        target_platform = trade.platform
        target_market_id = trade.market_id
        
        # Check if market exists on other platform
        if trade.platform == Platform.POLYMARKET:
            # Try to find equivalent market on Kalshi
            mapped_market = self.market_mapping.get(trade.market_id, {}).get(Platform.KALSHI)
            if mapped_market:
                target_platform = Platform.KALSHI
                target_market_id = mapped_market
        
        return StrategySignal(
            market_id=target_market_id,
            platform=target_platform,
            side=trade.side.value,
            size=size,
            order_type="limit", # Use limit orders to enforce slippage
            price=acceptable_price, # Set the limit price
            confidence=performance.win_rate,
            reason=f"Copying trader {trader_id} (win_rate: {performance.win_rate:.2%})",
            timestamp=datetime.utcnow()
        )
    
    async def generate_signals(self) -> List[StrategySignal]:
        """Generate trading signals"""
        if self.state != StrategyState.RUNNING:
            return []
        
        signals = []
        
        # Process recent trades from tracked traders
        for trader_id, trades in self.trader_trades.items():
            # Get most recent trades (last hour)
            recent_trades = [
                t for t in trades
                if (datetime.utcnow() - t.timestamp).total_seconds() < 3600
            ]
            
            for trade in recent_trades[-5:]:  # Last 5 trades per trader
                signal = await self._copy_trader_trade(trader_id, trade)
                if signal:
                    signals.append(signal)
        
        return signals
