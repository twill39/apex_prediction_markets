"""Historical replay simulator"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

from .base import BaseSimulator, SimulatorMode
from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, OrderSide, OrderType, OrderStatus, Platform
from src.data.storage import get_storage
from src.config import get_settings
from src.utils.logger import get_logger


class HistoricalSimulator(BaseSimulator):
    """Simulator that replays historical market data"""
    
    def __init__(self, data_path: Optional[str] = None):
        """Initialize historical simulator"""
        super().__init__(mode=SimulatorMode.HISTORICAL)
        self.settings = get_settings()
        self.logger = get_logger("HistoricalSimulator")
        self.storage = get_storage()
        
        # Historical data
        self.data_path = data_path or "./data/historical"
        self.events: List[Dict[str, Any]] = []
        self.current_event_index = 0
        
        # Market state (order books, prices)
        self.market_state: Dict[str, Dict[str, Any]] = {}  # market_id -> state
    
    def load_historical_data(self, file_path: str):
        """Load historical data from file"""
        self.logger.info(f"Loading historical data from {file_path}")
        
        try:
            # Support JSON and CSV formats
            if file_path.endswith('.json'):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.events = data.get("events", [])
            elif file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
                # Convert DataFrame to events
                self.events = df.to_dict('records')
            else:
                raise ValueError(f"Unsupported file format: {file_path}")
            
            # Sort events by timestamp
            self.events.sort(key=lambda x: self._get_event_timestamp(x))
            
            self.logger.info(f"Loaded {len(self.events)} historical events")
            
        except Exception as e:
            self.logger.error(f"Failed to load historical data: {e}", exc_info=True)
            raise
    
    def _get_event_timestamp(self, event: Dict[str, Any]) -> datetime:
        """Extract timestamp from event"""
        timestamp_str = event.get("timestamp") or event.get("time")
        if isinstance(timestamp_str, str):
            try:
                return datetime.fromisoformat(timestamp_str)
            except:
                return datetime.utcnow()
        return datetime.utcnow()
    
    async def run(self):
        """Run historical replay"""
        if not self.events:
            self.logger.error("No historical data loaded")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        self.logger.info(f"Starting historical replay with {len(self.events)} events")
        
        # Initialize strategies
        for strategy in self.strategies:
            await strategy.start()
        
        # Replay events chronologically
        for i, event in enumerate(self.events):
            if not self.is_running:
                break
            
            self.current_event_index = i
            await self._process_event(event)
            
            # Small delay to prevent overwhelming
            await asyncio.sleep(0.001)
        
        self.end_time = datetime.utcnow()
        self.logger.info("Historical replay completed")
        
        # Stop strategies
        for strategy in self.strategies:
            await strategy.stop()
        
        # Calculate final metrics
        self.metrics = self._calculate_metrics()
    
    async def _process_event(self, event: Dict[str, Any]):
        """Process a single historical event"""
        event_type = event.get("type") or event.get("event_type")
        
        if event_type == "orderbook_update":
            await self._process_orderbook_update(event)
        elif event_type == "trade":
            await self._process_trade(event)
        elif event_type == "market_update":
            await self._process_market_update(event)
    
    async def _process_orderbook_update(self, event: Dict[str, Any]):
        """Process order book update event"""
        from src.data.models import OrderBook, OrderBookLevel
        
        market_id = event.get("market_id")
        if not market_id:
            return
        
        # Update market state
        if market_id not in self.market_state:
            self.market_state[market_id] = {}
        
        # Create order book from event
        bids = [OrderBookLevel(price=b[0], size=b[1]) for b in event.get("bids", [])]
        asks = [OrderBookLevel(price=a[0], size=a[1]) for a in event.get("asks", [])]
        
        orderbook = OrderBook(
            market_id=market_id,
            platform=Platform(event.get("platform", "kalshi")),
            timestamp=self._get_event_timestamp(event),
            bids=bids,
            asks=asks
        )
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_orderbook_update(orderbook)
        
        # Generate and execute signals
        await self._process_strategy_signals()
    
    async def _process_trade(self, event: Dict[str, Any]):
        """Process trade event"""
        from src.data.models import Trade
        
        trade = Trade(
            trade_id=event.get("trade_id", f"hist_{self.current_event_index}"),
            market_id=event.get("market_id"),
            platform=Platform(event.get("platform", "kalshi")),
            side=OrderSide(event.get("side", "buy")),
            price=float(event.get("price", 0)),
            size=float(event.get("size", 0)),
            timestamp=self._get_event_timestamp(event)
        )
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_trade(trade)
        
        # Generate and execute signals
        await self._process_strategy_signals()
    
    async def _process_market_update(self, event: Dict[str, Any]):
        """Process market update event"""
        # Update market state
        market_id = event.get("market_id")
        if market_id:
            if market_id not in self.market_state:
                self.market_state[market_id] = {}
            self.market_state[market_id].update(event.get("data", {}))
    
    async def _process_strategy_signals(self):
        """Process signals from strategies"""
        for strategy in self.strategies:
            signals = await strategy.generate_signals()
            for signal in signals:
                trade = await self.execute_signal(signal)
                if trade:
                    self.trades.append(trade)
                    self.storage.save_trade(trade)
    
    async def execute_signal(self, signal: StrategySignal) -> Optional[Trade]:
        """Execute a trading signal in historical context"""
        # Get current market price from market state
        market_id = signal.market_id
        market_state = self.market_state.get(market_id, {})
        
        # Determine execution price
        if signal.order_type == "market":
            # Use mid price or last trade price
            execution_price = market_state.get("mid_price") or market_state.get("last_price") or signal.price or 0.5
        else:
            # Limit order - check if price is acceptable
            execution_price = signal.price or 0.5
        
        if execution_price <= 0:
            return None
        
        # Apply slippage
        slippage = self.settings.simulator.slippage
        if signal.side == "buy":
            execution_price *= (1 + slippage)
        else:
            execution_price *= (1 - slippage)
        
        # Create trade
        trade = Trade(
            trade_id=f"hist_{len(self.trades)}_{datetime.utcnow().timestamp()}",
            market_id=signal.market_id,
            platform=signal.platform,
            side=OrderSide(signal.side),
            price=execution_price,
            size=signal.size,
            timestamp=datetime.utcnow(),
            strategy_id=signal.market_id,  # Using market_id as placeholder
            fees=execution_price * signal.size * 0.001  # 0.1% fee
        )
        
        # Update balance
        cost = execution_price * signal.size
        if signal.side == "buy":
            self.current_balance -= cost
        else:
            self.current_balance += cost
        
        # Update position
        await self._update_position(trade)
        
        return trade
    
    async def _update_position(self, trade: Trade):
        """Update position based on trade"""
        position_key = f"{trade.market_id}_{trade.platform.value}"
        
        if position_key not in self.positions:
            # Create new position
            position = Position(
                position_id=position_key,
                market_id=trade.market_id,
                platform=trade.platform,
                side=PositionSide.LONG if trade.side == OrderSide.BUY else PositionSide.SHORT,
                size=trade.size,
                average_price=trade.price,
                opened_at=trade.timestamp
            )
            self.positions[position_key] = position
        else:
            # Update existing position
            position = self.positions[position_key]
            # Simplified position update
            total_cost = position.average_price * position.size + trade.price * trade.size
            total_size = position.size + trade.size
            position.average_price = total_cost / total_size if total_size > 0 else position.average_price
            position.size = total_size
