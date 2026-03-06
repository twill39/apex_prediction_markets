"""Data models for markets, orders, positions, and trades"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Platform(str, Enum):
    """Trading platform"""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class OrderSide(str, Enum):
    """Order side"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type"""
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    """Order status"""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(str, Enum):
    """Position side"""
    LONG = "long"
    SHORT = "short"


class Market(BaseModel):
    """Market information"""
    market_id: str = Field(..., description="Unique market identifier")
    platform: Platform = Field(..., description="Trading platform")
    title: str = Field(..., description="Market title")
    description: Optional[str] = Field(None, description="Market description")
    outcome_tokens: List[str] = Field(default_factory=list, description="Outcome tokens/sides")
    resolution_date: Optional[datetime] = Field(None, description="Market resolution date")
    created_at: Optional[datetime] = Field(None, description="Market creation date")
    volume: float = Field(default=0.0, description="Total volume")
    open_interest: float = Field(default=0.0, description="Open interest")
    is_active: bool = Field(default=True, description="Whether market is active")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class OrderBookLevel(BaseModel):
    """Single level in order book"""
    price: float = Field(..., description="Price level")
    size: float = Field(..., description="Size at this price level")
    orders: int = Field(default=1, description="Number of orders at this level")


class OrderBook(BaseModel):
    """Order book snapshot"""
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Snapshot timestamp")
    bids: List[OrderBookLevel] = Field(default_factory=list, description="Bid levels")
    asks: List[OrderBookLevel] = Field(default_factory=list, description="Ask levels")
    
    def get_best_bid(self) -> Optional[float]:
        """Get best bid price"""
        if not self.bids:
            return None
        return max(level.price for level in self.bids)
    
    def get_best_ask(self) -> Optional[float]:
        """Get best ask price"""
        if not self.asks:
            return None
        return min(level.price for level in self.asks)
    
    def get_spread(self) -> Optional[float]:
        """Calculate bid-ask spread"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return best_ask - best_bid
    
    def get_mid_price(self) -> Optional[float]:
        """Calculate mid price"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2.0


class Order(BaseModel):
    """Order information"""
    order_id: str = Field(..., description="Unique order identifier")
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    side: OrderSide = Field(..., description="Order side")
    order_type: OrderType = Field(..., description="Order type")
    price: Optional[float] = Field(None, description="Limit price (if limit order)")
    size: float = Field(..., description="Order size")
    filled_size: float = Field(default=0.0, description="Filled size")
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Order status")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Order creation time")
    updated_at: Optional[datetime] = Field(None, description="Last update time")
    strategy_id: Optional[str] = Field(None, description="Strategy that created this order")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class Position(BaseModel):
    """Position information"""
    position_id: str = Field(..., description="Unique position identifier")
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    side: PositionSide = Field(..., description="Position side")
    size: float = Field(..., description="Position size")
    average_price: float = Field(..., description="Average entry price")
    current_price: Optional[float] = Field(None, description="Current market price")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized P&L")
    realized_pnl: float = Field(default=0.0, description="Realized P&L")
    opened_at: datetime = Field(default_factory=datetime.utcnow, description="Position open time")
    closed_at: Optional[datetime] = Field(None, description="Position close time")
    strategy_id: Optional[str] = Field(None, description="Strategy that created this position")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class Trade(BaseModel):
    """Trade execution information"""
    trade_id: str = Field(..., description="Unique trade identifier")
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    side: OrderSide = Field(..., description="Trade side")
    price: float = Field(..., description="Execution price")
    size: float = Field(..., description="Trade size")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Trade timestamp")
    order_id: Optional[str] = Field(None, description="Associated order ID")
    strategy_id: Optional[str] = Field(None, description="Strategy that created this trade")
    fees: float = Field(default=0.0, description="Trading fees")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class MarketEvent(BaseModel):
    """Market event (trade, order book update, etc.)"""
    event_id: str = Field(..., description="Unique event identifier")
    market_id: str = Field(..., description="Market identifier")
    platform: Platform = Field(..., description="Trading platform")
    event_type: str = Field(..., description="Event type (trade, orderbook_update, etc.)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event data")


class TraderPerformance(BaseModel):
    """Trader performance metrics"""
    trader_id: str = Field(..., description="Trader identifier")
    platform: Platform = Field(..., description="Trading platform")
    total_trades: int = Field(default=0, description="Total number of trades")
    winning_trades: int = Field(default=0, description="Number of winning trades")
    losing_trades: int = Field(default=0, description="Number of losing trades")
    win_rate: float = Field(default=0.0, description="Win rate (0-1)")
    total_pnl: float = Field(default=0.0, description="Total P&L")
    roi: float = Field(default=0.0, description="Return on investment (%)")
    sharpe_ratio: Optional[float] = Field(None, description="Sharpe ratio")
    max_drawdown: float = Field(default=0.0, description="Maximum drawdown")
    average_trade_size: float = Field(default=0.0, description="Average trade size")
    last_updated: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
