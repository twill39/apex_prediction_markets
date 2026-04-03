"""Paper trading simulator"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import random

from .base import BaseSimulator, SimulatorMode
from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, OrderSide, OrderType, OrderStatus, Platform
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.config import get_settings
from src.utils.logger import get_logger


class PaperTradingSimulator(BaseSimulator):
    """Simulator that trades on live data with simulated execution"""

    def __init__(self, markets: Optional[List[str]] = None, duration_minutes: Optional[float] = None):
        """Initialize paper trading simulator.
        markets: optional list of market/asset IDs to subscribe to (Kalshi + Polymarket).
        duration_minutes: if set, run for this many minutes then stop and report.
        """
        super().__init__(mode=SimulatorMode.PAPER)
        self.settings = get_settings()
        self.logger = get_logger("PaperTradingSimulator")
        self.storage = get_storage()
        self.markets: List[str] = list(markets) if markets else []
        self.duration_minutes: Optional[float] = duration_minutes

        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None

        # Market state
        self.market_state: Dict[str, Dict[str, Any]] = {}  # market_id -> state

        # Pending orders
        self.pending_orders: Dict[str, Order] = {}

        # Set to True if run() exited early due to WebSocket connection failure
        self.websocket_connection_failed: bool = False
    
    async def initialize_websockets(self):
        """Initialize WebSocket connections"""
        try:
            if self.settings.simulator.use_polymarket:
                try:
                    self.polymarket_ws = PolymarketWebSocket()
                    self.polymarket_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
                    self.polymarket_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
                    self.polymarket_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
                    asyncio.create_task(self.polymarket_ws.start())
                except Exception as e:
                    self.logger.error(f"Failed to initialize Polymarket WebSocket: {e}", exc_info=True)
            
            if self.settings.simulator.use_kalshi:
                try:
                    self.kalshi_ws = KalshiWebSocket()
                    self.kalshi_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
                    self.kalshi_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
                    self.kalshi_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
                    asyncio.create_task(self.kalshi_ws.start())
                except Exception as e:
                    self.logger.error(f"Failed to initialize Kalshi WebSocket: {e}", exc_info=True)
            
            self.logger.info("WebSocket connections initialization sequence completed")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize WebSockets sequence: {e}", exc_info=True)
            raise
    
    async def _on_websocket_event(self, event: WebSocketEvent):
        """Handle WebSocket events"""
        if not self.is_running:
            return
        
        # Process event and notify strategies
        if event.event_type == WebSocketEventType.ORDERBOOK_UPDATE:
            from src.data.models import OrderBook
            orderbook_data = event.data.get("orderbook")
            if orderbook_data:
                orderbook = OrderBook(**orderbook_data)
                await self._process_orderbook_update(orderbook)
        
        elif event.event_type == WebSocketEventType.TRADE:
            from src.data.models import Trade
            trade_data = event.data.get("trade")
            if trade_data:
                trade = Trade(**trade_data)
                await self._process_trade(trade)
        elif event.event_type == WebSocketEventType.MARKET_UPDATE:
            # Strategies (notably `alt_data`) rely on market updates via `on_market_event`.
            for strategy in self.strategies:
                await strategy.on_market_event(event)
            # Market updates can change fair-value inputs; allow strategies to react.
            await self._process_strategy_signals()
    
    async def _process_orderbook_update(self, orderbook):
        """Process order book update"""
        market_id = orderbook.market_id
        
        # Update market state
        if market_id not in self.market_state:
            self.market_state[market_id] = {}
        
        self.market_state[market_id]["orderbook"] = orderbook
        self.market_state[market_id]["mid_price"] = orderbook.get_mid_price()
        self.market_state[market_id]["best_bid"] = orderbook.get_best_bid()
        self.market_state[market_id]["best_ask"] = orderbook.get_best_ask()
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_orderbook_update(orderbook)
        
        # Check pending orders for fills
        await self._check_order_fills(market_id, orderbook)
        
        # Generate and process signals
        await self._process_strategy_signals()
    
    async def _process_trade(self, trade: Trade):
        """Process trade event"""
        market_id = trade.market_id
        
        # Update market state
        if market_id not in self.market_state:
            self.market_state[market_id] = {}
        self.market_state[market_id]["last_price"] = trade.price
        self.market_state[market_id]["last_trade"] = trade
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_trade(trade)
        
        # Generate and process signals
        await self._process_strategy_signals()
    
    async def _check_order_fills(self, market_id: str, orderbook):
        """Check if pending orders should be filled"""
        orders_to_fill = []
        
        for order_id, order in self.pending_orders.items():
            if order.market_id != market_id or order.status != OrderStatus.OPEN:
                continue
            
            # Check if limit order can be filled
            if order.order_type == OrderType.LIMIT:
                best_bid = orderbook.get_best_bid()
                best_ask = orderbook.get_best_ask()
                
                if order.side == OrderSide.BUY and best_ask and order.price >= best_ask:
                    orders_to_fill.append(order)
                elif order.side == OrderSide.SELL and best_bid and order.price <= best_bid:
                    orders_to_fill.append(order)
        
        # Fill orders
        for order in orders_to_fill:
            await self._fill_order(order, orderbook)
    
    async def _fill_order(self, order: Order, orderbook):
        """Fill an order"""
        # Determine execution price
        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BUY:
                execution_price = orderbook.get_best_ask() or order.price or 0.5
            else:
                execution_price = orderbook.get_best_bid() or order.price or 0.5
        else:
            execution_price = order.price
        
        # Apply slippage
        slippage = self.settings.simulator.slippage
        if order.side == OrderSide.BUY:
            execution_price *= (1 + slippage)
        else:
            execution_price *= (1 - slippage)
        
        # Simulate latency
        await asyncio.sleep(self.settings.simulator.latency_ms / 1000.0)
        
        # Create trade
        trade = Trade(
            trade_id=str(uuid.uuid4()),
            market_id=order.market_id,
            platform=order.platform,
            side=order.side,
            price=execution_price,
            size=order.size,
            timestamp=datetime.utcnow(),
            order_id=order.order_id,
            strategy_id=order.strategy_id,
            fees=execution_price * order.size * 0.001  # 0.1% fee
        )
        
        # Update order
        order.status = OrderStatus.FILLED
        order.filled_size = order.size
        order.updated_at = datetime.utcnow()
        
        # Update balance
        cost = execution_price * order.size
        if order.side == OrderSide.BUY:
            self.current_balance -= cost
        else:
            self.current_balance += cost
        
        # Store trade
        self.trades.append(trade)
        self.storage.save_trade(trade)
        self.storage.save_order(order)
        
        # Update position
        await self._update_position(trade)
        
        # Remove from pending
        del self.pending_orders[order.order_id]
        
        self.logger.info(f"Filled order {order.order_id} at {execution_price:.4f}")
    
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
        """Execute a trading signal with simulated execution"""
        # Create order
        order = Order(
            order_id=str(uuid.uuid4()),
            market_id=signal.market_id,
            platform=signal.platform,
            side=OrderSide(signal.side),
            order_type=OrderType(signal.order_type),
            price=signal.price,
            size=signal.size,
            status=OrderStatus.OPEN,
            strategy_id=signal.market_id  # Placeholder
        )
        
        self.orders[order.order_id] = order
        self.storage.save_order(order)
        
        # Get current market state
        market_state = self.market_state.get(signal.market_id, {})
        orderbook = market_state.get("orderbook")
        
        if not orderbook:
            # No order book available, use market order
            order.order_type = OrderType.MARKET
        
        # For market orders, fill immediately
        if order.order_type == OrderType.MARKET:
            if orderbook:
                await self._fill_order(order, orderbook)
            else:
                # No order book, use signal price with slippage
                execution_price = signal.price or 0.5
                slippage = self.settings.simulator.slippage
                if order.side == OrderSide.BUY:
                    execution_price *= (1 + slippage)
                else:
                    execution_price *= (1 - slippage)
                
                trade = Trade(
                    trade_id=str(uuid.uuid4()),
                    market_id=signal.market_id,
                    platform=signal.platform,
                    side=order.side,
                    price=execution_price,
                    size=order.size,
                    timestamp=datetime.utcnow(),
                    order_id=order.order_id,
                    strategy_id=order.strategy_id,
                    fees=execution_price * order.size * 0.001
                )
                
                order.status = OrderStatus.FILLED
                order.filled_size = order.size
                
                cost = execution_price * order.size
                if order.side == OrderSide.BUY:
                    self.current_balance -= cost
                else:
                    self.current_balance += cost
                
                await self._update_position(trade)
                return trade
        else:
            # Limit order - add to pending
            self.pending_orders[order.order_id] = order
        
        return None
    
    async def _update_position(self, trade: Trade):
        """Update position based on trade"""
        position_key = f"{trade.market_id}_{trade.platform.value}"
        
        if position_key not in self.positions:
            from src.data.models import PositionSide
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
            position = self.positions[position_key]
            total_cost = position.average_price * position.size + trade.price * trade.size
            total_size = position.size + trade.size
            position.average_price = total_cost / total_size if total_size > 0 else position.average_price
            position.size = total_size
    
    async def run(self):
        """Run paper trading simulator"""
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        self.logger.info("Starting paper trading simulator")
        
        # Start strategies first so they can run discovery (e.g. market_making discovers markets)
        # This must occur BEFORE websocket initialization because discovery may block the event loop
        # and cause websocket timeout if the websocket is already connected.
        for strategy in self.strategies:
            await strategy.start()

        # Initialize WebSockets
        await self.initialize_websockets()
        
        # Wait for connections to establish (or fail)
        await asyncio.sleep(3)
        
        # Require at least one WebSocket to be connected
        kalshi_ok = self.kalshi_ws is not None and self.kalshi_ws.is_connected
        poly_ok = self.polymarket_ws is not None and self.polymarket_ws.is_connected
        if not kalshi_ok and not poly_ok:
            self.websocket_connection_failed = True
            msg = "Could not load simulator because of bad websocket connection."
            self.logger.error(msg)
            print(f"\n{msg}\nCheck credentials, network, and logs above for details.\n")
            self.is_running = False
            if self.kalshi_ws:
                await self.kalshi_ws.stop()
            if self.polymarket_ws:
                await self.polymarket_ws.stop()
            self.end_time = datetime.utcnow()
            self.metrics = self._calculate_metrics()
            return

        # Build subscription list: CLI/file markets + any strategy-discovered markets
        all_market_ids = list(self.markets)
        for strategy in self.strategies:
            if hasattr(strategy, "get_discovered_market_ids") and callable(getattr(strategy, "get_discovered_market_ids")):
                discovered = strategy.get_discovered_market_ids()
                for mid in discovered:
                    if mid and mid not in all_market_ids:
                        all_market_ids.append(mid)
        if all_market_ids and all_market_ids != self.markets:
            self.logger.info(f"Subscribing to {len(all_market_ids)} market(s) (config + discovered)")
        elif all_market_ids:
            self.logger.info(f"Subscribing to {len(all_market_ids)} market(s): {all_market_ids[:5]}{'...' if len(all_market_ids) > 5 else ''}")
        if all_market_ids:
            # Wait for reconnect if WS dropped during strategy init
            poly_ok = self.polymarket_ws is not None and self.polymarket_ws.is_connected
            kalshi_ok = self.kalshi_ws is not None and self.kalshi_ws.is_connected
            if not poly_ok and self.polymarket_ws:
                self.logger.info("WebSocket disconnected — waiting for reconnect...")
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    if self.polymarket_ws.is_connected:
                        poly_ok = True
                        self.logger.info("WebSocket reconnected")
                        break
                if not poly_ok:
                    self.logger.warning("WebSocket did not reconnect in time")

            if kalshi_ok and self.kalshi_ws:
                for market_id in all_market_ids:
                    try:
                        await self.kalshi_ws.subscribe_market(market_id)
                    except Exception as e:
                        self.logger.warning(f"Kalshi subscribe {market_id}: {e}")
            if poly_ok and self.polymarket_ws:
                # Subscribe in batches to avoid overwhelming the server
                batch_size = 50
                for i in range(0, len(all_market_ids), batch_size):
                    batch = all_market_ids[i:i + batch_size]
                    try:
                        await self.polymarket_ws.subscribe_assets(batch)
                    except Exception as e:
                        self.logger.warning(f"Polymarket subscribe batch {i // batch_size}: {e}")
        else:
            self.logger.info("No markets to subscribe to; use --markets/--markets-file or run market_making for discovery.")

        # Optional: stop after duration_minutes
        duration_task: Optional[asyncio.Task] = None
        if self.duration_minutes is not None and self.duration_minutes > 0:
            duration_seconds = self.duration_minutes * 60.0
            self.logger.info(f"Paper run will stop after {self.duration_minutes} minute(s)")

            async def stop_after_duration():
                await asyncio.sleep(duration_seconds)
                if self.is_running:
                    self.logger.info("Duration reached; stopping paper run")
                    self.is_running = False

            duration_task = asyncio.create_task(stop_after_duration())

        # Main loop
        try:
            while self.is_running:
                # Process strategy signals periodically
                await self._process_strategy_signals()

                # Update metrics periodically
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("Stopped by user")
        finally:
            if duration_task is not None and not duration_task.done():
                duration_task.cancel()
                try:
                    await duration_task
                except asyncio.CancelledError:
                    pass
            self.end_time = datetime.utcnow()

            # Stop strategies
            for strategy in self.strategies:
                await strategy.stop()
            
            # Stop WebSockets
            if self.kalshi_ws:
                await self.kalshi_ws.stop()
            if self.polymarket_ws:
                await self.polymarket_ws.stop()
            
            # Calculate final metrics
            self.metrics = self._calculate_metrics()
            
            self.logger.info("Paper trading simulator stopped")
