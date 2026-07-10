"""Paper trading simulator"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from .base import BaseSimulator, SimulatorMode
from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, OrderSide, OrderType, OrderStatus, Platform, PositionSide
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.websockets.schwab import SchwabSpxStream
from src.config import get_settings
from src.utils.logger import get_logger


class PaperTradingSimulator(BaseSimulator):
    """Simulator that trades on live data with simulated execution"""

    def __init__(
        self,
        markets: Optional[List[str]] = None,
        duration_minutes: Optional[float] = None,
        bounds_file: Optional[str] = None,
        use_schwab_spx: Optional[bool] = None,
    ):
        """Initialize paper trading simulator.
        markets: optional list of market/asset IDs to subscribe to (Kalshi + Polymarket).
        duration_minutes: if set, run for this many minutes then stop and report.
        bounds_file: JSON with lower/upper/eod bounds for configured markets.
        use_schwab_spx: override settings.simulator.use_schwab_spx when set.
        """
        super().__init__(mode=SimulatorMode.PAPER)
        self.settings = get_settings()
        ib = float(self.settings.simulator.initial_balance)
        self.initial_balance = ib
        self.current_balance = ib
        self.logger = get_logger("PaperTradingSimulator")
        self.storage = get_storage()
        self.markets: List[str] = list(markets) if markets else []
        self.duration_minutes: Optional[float] = duration_minutes
        self.bounds_file = bounds_file or self.settings.simulator.bounds_file
        self.use_schwab_spx = (
            self.settings.simulator.use_schwab_spx
            if use_schwab_spx is None
            else use_schwab_spx
        )

        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
        self._schwab: Optional[SchwabSpxStream] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Market state
        self.market_state: Dict[str, Dict[str, Any]] = {}  # market_id -> state
        self._market_bounds: Dict[str, Dict[str, Any]] = self._load_bounds()
        self._bounds_injected: Set[str] = set()
        self._latest_spx: Optional[float] = None
        self._latest_spx_at: Optional[datetime] = None

        # Pending orders
        self.pending_orders: Dict[str, Order] = {}
        self._fill_lock = asyncio.Lock()

        # Set to True if run() exited early due to WebSocket connection failure
        self.websocket_connection_failed: bool = False

    def _load_bounds(self) -> Dict[str, Dict[str, Any]]:
        """Load Kalshi band metadata keyed by market ticker."""
        path = Path(self.bounds_file).expanduser().resolve()
        if not path.is_file():
            self.logger.warning("Bounds file not found: %s", path)
            return {}

        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Could not read bounds file %s: %s", path, exc)
            return {}

        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            self.logger.warning("Bounds file %s has no rows list", path)
            return {}

        bounds: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("has_bounds"):
                continue
            ticker = row.get("ticker")
            lower = row.get("lower_bound")
            upper = row.get("upper_bound")
            if not ticker or lower is None or upper is None:
                continue
            try:
                bounds[str(ticker)] = {
                    "lower_bound": float(lower),
                    "upper_bound": float(upper),
                    "eod_timestamp": float(row["eod_timestamp"])
                    if row.get("eod_timestamp") is not None
                    else None,
                }
            except (TypeError, ValueError):
                continue

        if bounds:
            self.logger.info("Loaded bounds for %d market(s) from %s", len(bounds), path.name)
        else:
            self.logger.warning("No usable bounds rows in %s", path)
        return bounds

    async def _maybe_inject_bounds(self, market_id: str) -> None:
        """Inject one-time band metadata for a market from the bounds file."""
        if market_id in self._bounds_injected:
            return
        bounds = self._market_bounds.get(market_id)
        if bounds is None:
            return

        event = WebSocketEvent(
            event_type=WebSocketEventType.MARKET_UPDATE,
            data={
                "market_id": market_id,
                "lower_bound": bounds["lower_bound"],
                "upper_bound": bounds["upper_bound"],
                "eod_timestamp": bounds.get("eod_timestamp"),
            },
            timestamp=datetime.utcnow(),
            market_id=market_id,
        )
        for strategy in self.strategies:
            await strategy.on_market_event(event)
        self._bounds_injected.add(market_id)
        self.logger.info(
            "Injected band bounds for %s (lower=%s upper=%s)",
            market_id,
            bounds["lower_bound"],
            bounds["upper_bound"],
        )

    def _on_spx_price_thread(self, price: float, ts: datetime) -> None:
        """Bridge Schwab worker thread back into the asyncio event loop."""
        if self._loop is None or not self.is_running:
            return
        asyncio.run_coroutine_threadsafe(self._on_spx_price(price, ts), self._loop)

    async def _on_spx_price(self, price: float, ts: datetime) -> None:
        """Forward live SPX spot updates to strategies as underlying_price events."""
        if not self.is_running:
            return
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self._latest_spx = price
        self._latest_spx_at = ts

        event = WebSocketEvent(
            event_type=WebSocketEventType.MARKET_UPDATE,
            data={
                "update_type": "underlying_price",
                "symbol": self.settings.simulator.schwab_symbol,
                "price": price,
                "timestamp": ts.isoformat(),
                "source": "schwab_stream",
            },
            timestamp=ts,
            market_id=None,
        )
        for strategy in self.strategies:
            await strategy.on_market_event(event)
        await self._process_strategy_signals()

    def _start_spx_feed(self) -> None:
        """Start Schwab SPX stream/poll feed in a background thread."""
        if not self.use_schwab_spx:
            return
        try:
            self._schwab = SchwabSpxStream(
                symbol=self.settings.simulator.schwab_symbol,
                poll_interval_seconds=self.settings.simulator.spx_poll_interval_seconds,
                use_stream=self.settings.simulator.schwab_spx_use_stream,
            )
            self._schwab.start(self._on_spx_price_thread)
            self.logger.info(
                "Started Schwab SPX feed for %s",
                self.settings.simulator.schwab_symbol,
            )
        except Exception as exc:
            self.logger.error("Failed to start Schwab SPX feed: %s", exc, exc_info=True)
            self._schwab = None

    def _stop_spx_feed(self) -> None:
        if self._schwab is not None:
            try:
                self._schwab.stop()
            except Exception as exc:
                self.logger.debug("Error stopping Schwab SPX feed: %s", exc)
            self._schwab = None

    def _log_spx_staleness(self) -> None:
        """Warn if the SPX feed has gone quiet."""
        if not self.use_schwab_spx or self._latest_spx_at is None:
            return
        age = (datetime.now(timezone.utc) - self._latest_spx_at).total_seconds()
        stale_after = float(self.settings.simulator.spx_stale_seconds)
        if age > stale_after:
            self.logger.warning(
                "SPX feed stale for %.0fs (last=%s)",
                age,
                self._latest_spx,
            )
    
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
        if self.market_state[market_id]["mid_price"] is not None:
            self._mark_position_to_market(market_id, self.market_state[market_id]["mid_price"])
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_orderbook_update(orderbook)

        await self._maybe_inject_bounds(market_id)
        
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
            if order.market_id != market_id or order.status not in (
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            ):
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
        """Fill an order (serialized to avoid duplicate fills / KeyError on pending_orders)."""
        async with self._fill_lock:
            order_id = order.order_id
            from_pending = order.order_type == OrderType.LIMIT

            if from_pending:
                live = self.pending_orders.get(order_id)
                if live is None or live.status not in (
                    OrderStatus.OPEN,
                    OrderStatus.PARTIALLY_FILLED,
                ):
                    return
                order = live

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

            fill_sz = self._allowed_fill_size(
                order.market_id, order.platform, order.side, order.size
            )
            if fill_sz <= 0:
                return

            # Simulate latency
            await asyncio.sleep(self.settings.simulator.latency_ms / 1000.0)

            if from_pending:
                live = self.pending_orders.get(order_id)
                if live is None or live.status not in (
                    OrderStatus.OPEN,
                    OrderStatus.PARTIALLY_FILLED,
                ):
                    return
                order = live
                fill_sz = min(
                    fill_sz,
                    self._allowed_fill_size(
                        order.market_id, order.platform, order.side, order.size
                    ),
                )
                if fill_sz <= 0:
                    return

            # Create trade
            trade = Trade(
                trade_id=str(uuid.uuid4()),
                market_id=order.market_id,
                platform=order.platform,
                side=order.side,
                price=execution_price,
                size=fill_sz,
                timestamp=datetime.utcnow(),
                order_id=order.order_id,
                strategy_id=order.strategy_id,
                fees=execution_price * fill_sz * 0.001  # 0.1% fee
            )

            # Update balance
            cost = execution_price * fill_sz
            if order.side == OrderSide.BUY:
                self.current_balance -= cost + trade.fees
            else:
                self.current_balance += cost - trade.fees

            # Store trade
            self.trades.append(trade)
            self.storage.save_trade(trade)

            # Update position
            await self._update_position(trade)
            await self._notify_fill(trade)

            order.filled_size = (order.filled_size or 0.0) + fill_sz
            remaining = float(order.size) - fill_sz
            if remaining > 1e-12:
                order.size = remaining
                order.status = OrderStatus.PARTIALLY_FILLED
                order.updated_at = datetime.utcnow()
                self.storage.save_order(order)
                self.logger.info(
                    f"Partial fill {order.order_id} {fill_sz}/{remaining + fill_sz} at {execution_price:.4f}"
                )
                return

            order.status = OrderStatus.FILLED
            order.size = order.filled_size
            order.updated_at = datetime.utcnow()
            self.storage.save_order(order)
            self.pending_orders.pop(order_id, None)
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
        if signal.order_type == "limit" and signal.size <= 0:
            cancel_ids = [
                oid
                for oid, pending in self.pending_orders.items()
                if pending.market_id == signal.market_id
                and pending.side == OrderSide(signal.side)
                and pending.status == OrderStatus.OPEN
            ]
            for oid in cancel_ids:
                del self.pending_orders[oid]
            return None

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
                fill_sz = self._allowed_fill_size(
                    signal.market_id, signal.platform, signal.side, order.size
                )
                if fill_sz <= 0:
                    order.status = OrderStatus.CANCELLED
                    return None
                execution_price = signal.price or 0.5
                slippage = self.settings.simulator.slippage
                if order.side == OrderSide.BUY:
                    execution_price *= (1 + slippage)
                else:
                    execution_price *= (1 - slippage)
                
                trade = Trade(
                    trade_id=str(uuid.uuid4()),
                    market_id=signal.market_id,
                    platform=order.platform,
                    side=order.side,
                    price=execution_price,
                    size=fill_sz,
                    timestamp=datetime.utcnow(),
                    order_id=order.order_id,
                    strategy_id=order.strategy_id,
                    fees=execution_price * fill_sz * 0.001,
                )
                
                order.status = OrderStatus.FILLED
                order.filled_size = fill_sz
                
                cost = execution_price * fill_sz
                if order.side == OrderSide.BUY:
                    self.current_balance -= cost + trade.fees
                else:
                    self.current_balance += cost - trade.fees
                
                await self._update_position(trade)
                await self._notify_fill(trade)
                return trade
        else:
            # Cancel/replace: one open limit per (market_id, side).
            cancel_ids = [
                oid
                for oid, pending in self.pending_orders.items()
                if pending.market_id == signal.market_id
                and pending.side == OrderSide(signal.side)
                and pending.status == OrderStatus.OPEN
            ]
            for oid in cancel_ids:
                del self.pending_orders[oid]

            self.pending_orders[order.order_id] = order
        
        return None

    async def _notify_fill(self, trade: Trade):
        """Notify strategies about their own fills so they can track inventory."""
        for strategy in self.strategies:
            await strategy.on_fill(trade)
    
    async def _update_position(self, trade: Trade):
        """Update position based on trade"""
        position_key = f"{trade.market_id}_{trade.platform.value}"
        
        if position_key not in self.positions:
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
            if position.side == PositionSide.LONG:
                if trade.side == OrderSide.BUY:
                    total_cost = position.average_price * position.size + trade.price * trade.size
                    total_size = position.size + trade.size
                    position.average_price = total_cost / total_size if total_size > 0 else position.average_price
                    position.size = total_size
                else:
                    if trade.size < position.size:
                        position.size -= trade.size
                    elif trade.size == position.size:
                        position.size = 0.0
                        position.closed_at = trade.timestamp
                    else:
                        position.side = PositionSide.SHORT
                        position.size = trade.size - position.size
                        position.average_price = trade.price
                        position.opened_at = trade.timestamp
                        position.closed_at = None
            else:
                if trade.side == OrderSide.SELL:
                    total_cost = position.average_price * position.size + trade.price * trade.size
                    total_size = position.size + trade.size
                    position.average_price = total_cost / total_size if total_size > 0 else position.average_price
                    position.size = total_size
                else:
                    if trade.size < position.size:
                        position.size -= trade.size
                    elif trade.size == position.size:
                        position.size = 0.0
                        position.closed_at = trade.timestamp
                    else:
                        position.side = PositionSide.LONG
                        position.size = trade.size - position.size
                        position.average_price = trade.price
                        position.opened_at = trade.timestamp
                        position.closed_at = None

            position.current_price = trade.price if position.current_price is None else position.current_price

    def _mark_position_to_market(self, market_id: str, mark_price: float):
        """Refresh current mark for any open position in the market."""
        for position in self.positions.values():
            if position.market_id == market_id and position.size > 0:
                position.current_price = mark_price
    
    async def run(self):
        """Run paper trading simulator"""
        self.is_running = True
        self.start_time = datetime.utcnow()
        self._loop = asyncio.get_running_loop()
        
        self.logger.info("Starting paper trading simulator")
        
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

        # Start strategies first so they can run discovery (e.g. market_making discovers markets)
        for strategy in self.strategies:
            await strategy.start()

        self._start_spx_feed()

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
            if kalshi_ok and self.kalshi_ws:
                for market_id in all_market_ids:
                    try:
                        await self.kalshi_ws.subscribe_market(market_id)
                    except Exception as e:
                        self.logger.warning(f"Kalshi subscribe {market_id}: {e}")
            if poly_ok and self.polymarket_ws:
                try:
                    await self.polymarket_ws.subscribe_assets(all_market_ids)
                except Exception as e:
                    self.logger.warning(f"Polymarket subscribe assets: {e}")
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
                self._log_spx_staleness()

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

            self._stop_spx_feed()
            
            # Stop WebSockets
            if self.kalshi_ws:
                await self.kalshi_ws.stop()
            if self.polymarket_ws:
                await self.polymarket_ws.stop()
            
            # Calculate final metrics
            self.metrics = self._calculate_metrics()
            
            self.logger.info("Paper trading simulator stopped")
