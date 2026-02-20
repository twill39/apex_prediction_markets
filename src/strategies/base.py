"""Base strategy interface"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from src.data.models import Order, Position, Trade, Market, OrderBook, Platform
from src.websockets.base import WebSocketEvent


class StrategyState(str, Enum):
    """Strategy state"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class StrategySignal(BaseModel):
    """Trading signal from strategy"""
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    side: str = Field(..., description="Trade side (buy/sell)")
    size: float = Field(..., description="Trade size")
    price: Optional[float] = Field(None, description="Limit price (if limit order)")
    order_type: str = Field(default="market", description="Order type (market/limit)")
    confidence: float = Field(default=0.5, description="Signal confidence (0-1)")
    reason: str = Field(default="", description="Reason for the signal")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Signal timestamp")


class BaseStrategy(ABC):
    """Base class for trading strategies"""
    
    def __init__(self, strategy_id: str, name: str):
        """Initialize strategy"""
        self.strategy_id = strategy_id
        self.name = name
        self.state = StrategyState.IDLE
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        
        # Active positions and orders
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        
        # Strategy-specific data
        self.data: Dict[str, Any] = {}
    
    @abstractmethod
    async def initialize(self):
        """Initialize the strategy"""
        pass
    
    @abstractmethod
    async def on_market_event(self, event: WebSocketEvent):
        """Handle market event"""
        pass
    
    @abstractmethod
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update"""
        pass
    
    @abstractmethod
    async def on_trade(self, trade: Trade):
        """Handle trade event"""
        pass
    
    @abstractmethod
    async def generate_signals(self) -> List[StrategySignal]:
        """Generate trading signals"""
        pass
    
    async def start(self):
        """Start the strategy"""
        self.state = StrategyState.RUNNING
        await self.initialize()
    
    async def stop(self):
        """Stop the strategy"""
        self.state = StrategyState.STOPPED
    
    async def pause(self):
        """Pause the strategy"""
        self.state = StrategyState.PAUSED
    
    async def resume(self):
        """Resume the strategy"""
        if self.state == StrategyState.PAUSED:
            self.state = StrategyState.RUNNING
    
    def update_position(self, position: Position):
        """Update position tracking"""
        self.positions[position.position_id] = position
    
    def update_order(self, order: Order):
        """Update order tracking"""
        self.orders[order.order_id] = order
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get strategy performance metrics"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "state": self.state.value,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "active_positions": len(self.positions),
            "active_orders": len(self.orders)
        }
