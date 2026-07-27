"""Paper trading simulator"""

import asyncio
import json
import time
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
        self._websocket_tasks: Dict[str, asyncio.Task] = {}
        self._feed_unhealthy_since: Dict[str, float] = {}
        self._last_orderbook_monotonic: Dict[str, float] = {}
        self._subscribed_market_ids: Set[str] = set()
        self._market_unready_since: Dict[str, float] = {}
        self._run_started_monotonic: Optional[float] = None
        self.feed_failure_reason: Optional[str] = None
        self.startup_failure_reason: Optional[str] = None
        self._cleanup_done = False

        # Market state
        self.market_state: Dict[str, Dict[str, Any]] = {}  # market_id -> state
        self._market_bounds: Dict[str, Dict[str, Any]] = self._load_bounds()
        self._bounds_injected: Set[str] = set()
        self._latest_spx: Optional[float] = None
        self._latest_spx_at: Optional[datetime] = None
        self._last_spx_stale_log_monotonic: Optional[float] = None

        # Pending orders
        self.pending_orders: Dict[str, Order] = {}
        self._fill_lock = asyncio.Lock()
        self._signal_lock = asyncio.Lock()
        self._event_lock = asyncio.Lock()
        self._filling_order_ids: Set[str] = set()

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
            timestamp=datetime.now(timezone.utc),
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
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._on_spx_price(price, ts), self._loop
            )
            future.add_done_callback(self._log_spx_callback_result)
        except RuntimeError as exc:
            self.logger.debug("Dropped SPX update while event loop closed: %s", exc)

    def _log_spx_callback_result(self, future) -> None:
        try:
            future.result()
        except Exception as exc:
            self.logger.error("SPX event callback failed: %s", exc, exc_info=True)

    async def _on_spx_price(self, price: float, ts: datetime) -> None:
        """Forward live SPX spot updates to strategies as underlying_price events."""
        if not self.is_running:
            return
        async with self._event_lock:
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

    def _start_spx_feed(self) -> bool:
        """Start Schwab SPX stream/poll feed in a background thread."""
        if not self.use_schwab_spx:
            return True
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
            return True
        except Exception as exc:
            self.logger.error("Failed to start Schwab SPX feed: %s", exc, exc_info=True)
            self._schwab = None
            return False

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
            now = time.monotonic()
            if (
                self._last_spx_stale_log_monotonic is not None
                and now - self._last_spx_stale_log_monotonic < 60.0
            ):
                return
            self._last_spx_stale_log_monotonic = now
            self.logger.warning(
                "SPX feed stale for %.0fs (last=%s)",
                age,
                self._latest_spx,
            )

    async def _wait_for_initial_connection(self) -> bool:
        """Wait for the feed required by each explicitly configured market."""
        timeout = max(
            float(self.settings.simulator.feed_startup_grace_seconds), 1.0
        )
        deadline = time.monotonic() + timeout
        needs_kalshi = any(
            market_id.upper().startswith("KX") for market_id in self.markets
        )
        needs_polymarket = any(
            not market_id.upper().startswith("KX") for market_id in self.markets
        )
        while time.monotonic() < deadline:
            kalshi_ready = (
                self.kalshi_ws is not None and self.kalshi_ws.is_connected
            )
            polymarket_ready = (
                self.polymarket_ws is not None and self.polymarket_ws.is_connected
            )
            if self.markets:
                ready = (
                    (not needs_kalshi or kalshi_ready)
                    and (not needs_polymarket or polymarket_ready)
                )
            else:
                ready = kalshi_ready or polymarket_ready
            if ready:
                return True
            if self._websocket_tasks and all(
                task.done() for task in self._websocket_tasks.values()
            ):
                return False
            await asyncio.sleep(0.1)
        return False

    def _feed_health_error(self) -> Optional[str]:
        """Return a fatal paper-feed error after configured grace periods."""
        now = time.monotonic()
        clients = {
            "kalshi": self.kalshi_ws,
            "polymarket": self.polymarket_ws,
        }
        for name, client in clients.items():
            if client is None:
                continue
            if (
                self._subscribed_market_ids
                and not self._markets_for_feed(name)
            ):
                continue
            task = self._websocket_tasks.get(name)
            if task is not None and task.done():
                if task.cancelled():
                    detail = "task was cancelled"
                else:
                    exc = task.exception()
                    detail = str(exc) if exc else "task exited"
                return f"{name} WebSocket stopped: {detail}"
            if client.is_connected:
                self._feed_unhealthy_since.pop(name, None)
                continue
            since = self._feed_unhealthy_since.setdefault(name, now)
            reconnect_budget = float(client.reconnect_interval) * (
                int(client.max_reconnect_attempts) + 1
            )
            disconnect_grace = max(
                float(self.settings.simulator.feed_disconnect_grace_seconds),
                reconnect_budget,
                1.0,
            )
            if now - since > disconnect_grace:
                return (
                    f"{name} WebSocket disconnected for "
                    f"{now - since:.0f}s"
                )

        if self._run_started_monotonic is None:
            return None
        startup_grace = max(
            float(self.settings.simulator.feed_startup_grace_seconds), 1.0
        )
        if now - self._run_started_monotonic <= startup_grace:
            return None
        if self.use_schwab_spx and self._latest_spx_at is None:
            return "SPX feed produced no initial price"

        recovery_grace = max(
            float(self.settings.simulator.market_data_stale_seconds), 1.0
        )
        for market_id, since in self._market_unready_since.items():
            age = now - since
            if age > recovery_grace:
                return (
                    f"no fresh orderbook snapshot for {market_id} "
                    f"after {age:.0f}s"
                )
        return None

    async def _stop_websocket_tasks(self) -> None:
        """Stop clients and retrieve all background task results."""
        if self.kalshi_ws:
            await self.kalshi_ws.stop()
        if self.polymarket_ws:
            await self.polymarket_ws.stop()
        tasks = list(self._websocket_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._websocket_tasks.clear()

    def _markets_for_feed(self, feed_name: str) -> Set[str]:
        if feed_name == "kalshi":
            return {
                market_id
                for market_id in self._subscribed_market_ids
                if market_id.upper().startswith("KX")
            }
        return {
            market_id
            for market_id in self._subscribed_market_ids
            if not market_id.upper().startswith("KX")
        }

    async def _on_feed_status(
        self, feed_name: str, event: WebSocketEvent
    ) -> None:
        """Invalidate cached books until a fresh post-reconnect snapshot arrives."""
        async with self._event_lock:
            await self._dispatch_feed_status(feed_name, event)

    async def _dispatch_feed_status(
        self, feed_name: str, event: WebSocketEvent
    ) -> None:
        if event.event_type not in (
            WebSocketEventType.DISCONNECTED,
            WebSocketEventType.ERROR,
        ):
            return
        now = time.monotonic()
        market_id = event.market_id or event.data.get("market_id")
        markets = {market_id} if market_id else self._markets_for_feed(feed_name)
        for configured_market in markets:
            self._market_unready_since[configured_market] = now
            self.market_state.pop(configured_market, None)
        if markets:
            await self._cancel_all_pending_orders(
                reason=f"{feed_name}_{event.event_type.value}"
            )

    async def _on_kalshi_status(self, event: WebSocketEvent) -> None:
        await self._on_feed_status("kalshi", event)

    async def _on_polymarket_status(self, event: WebSocketEvent) -> None:
        await self._on_feed_status("polymarket", event)
    
    async def initialize_websockets(self):
        """Initialize WebSocket connections"""
        try:
            if self.settings.simulator.use_polymarket:
                try:
                    self.polymarket_ws = PolymarketWebSocket()
                    self.polymarket_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
                    self.polymarket_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
                    self.polymarket_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
                    self.polymarket_ws.register_callback(WebSocketEventType.DISCONNECTED, self._on_polymarket_status)
                    self.polymarket_ws.register_callback(WebSocketEventType.ERROR, self._on_polymarket_status)
                    self._websocket_tasks["polymarket"] = asyncio.create_task(
                        self.polymarket_ws.start(), name="polymarket-websocket"
                    )
                except Exception as e:
                    self.logger.error(f"Failed to initialize Polymarket WebSocket: {e}", exc_info=True)
            
            if self.settings.simulator.use_kalshi:
                try:
                    self.kalshi_ws = KalshiWebSocket()
                    self.kalshi_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
                    self.kalshi_ws.register_callback(WebSocketEventType.TRADE, self._on_websocket_event)
                    self.kalshi_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
                    self.kalshi_ws.register_callback(WebSocketEventType.DISCONNECTED, self._on_kalshi_status)
                    self.kalshi_ws.register_callback(WebSocketEventType.ERROR, self._on_kalshi_status)
                    self._websocket_tasks["kalshi"] = asyncio.create_task(
                        self.kalshi_ws.start(), name="kalshi-websocket"
                    )
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
        async with self._event_lock:
            await self._dispatch_websocket_event(event)

    async def _dispatch_websocket_event(self, event: WebSocketEvent):
        """Process one market event in arrival order."""
        
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
        self._last_orderbook_monotonic[market_id] = time.monotonic()
        self._market_unready_since.pop(market_id, None)
        
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

        # Public trades can fill resting passive quotes even when the book does
        # not cross their limit.
        await self._check_trade_fills(trade)
        
        # Generate and process signals
        await self._process_strategy_signals()
    
    async def _check_order_fills(self, market_id: str, orderbook):
        """Check if pending orders should be filled"""
        async with self._fill_lock:
            pending = list(self.pending_orders.values())

        orders_to_fill = []
        best_bid = orderbook.get_best_bid()
        best_ask = orderbook.get_best_ask()
        for order in pending:
            if order.market_id != market_id or order.status not in (
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            ):
                continue
            if order.order_type != OrderType.LIMIT:
                continue
            if (
                order.side == OrderSide.BUY
                and best_ask is not None
                and order.price >= best_ask
            ):
                orders_to_fill.append((order, best_ask))
            elif (
                order.side == OrderSide.SELL
                and best_bid is not None
                and order.price <= best_bid
            ):
                orders_to_fill.append((order, best_bid))

        for order, touch_price in orders_to_fill:
            await self._fill_order(
                order, orderbook, execution_price_override=touch_price
            )

    async def _check_trade_fills(self, trade: Trade) -> None:
        """Fill passive limits touched by an opposite-side public trade."""
        async with self._fill_lock:
            pending = list(self.pending_orders.values())

        for order in pending:
            if order.market_id != trade.market_id or order.order_type != OrderType.LIMIT:
                continue
            if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
                continue
            buy_touched = (
                order.side == OrderSide.BUY
                and trade.side == OrderSide.SELL
                and trade.price <= order.price
            )
            sell_touched = (
                order.side == OrderSide.SELL
                and trade.side == OrderSide.BUY
                and trade.price >= order.price
            )
            if buy_touched or sell_touched:
                await self._fill_order(
                    order,
                    self.market_state.get(trade.market_id, {}).get("orderbook"),
                    execution_price_override=trade.price,
                    max_fill_size=trade.size,
                )

    async def _fill_order(
        self,
        order: Order,
        orderbook,
        execution_price_override: Optional[float] = None,
        max_fill_size: Optional[float] = None,
    ) -> Optional[Trade]:
        """Commit one linearizable simulated fill after cancellable latency."""
        order_id = order.order_id
        from_pending = order.order_type == OrderType.LIMIT

        async with self._fill_lock:
            if order_id in self._filling_order_ids:
                return None
            if from_pending:
                live = self.pending_orders.get(order_id)
                if live is None or live.status not in (
                    OrderStatus.OPEN,
                    OrderStatus.PARTIALLY_FILLED,
                ):
                    return None
            self._filling_order_ids.add(order_id)

        try:
            await asyncio.sleep(self.settings.simulator.latency_ms / 1000.0)

            async with self._fill_lock:
                if from_pending:
                    live = self.pending_orders.get(order_id)
                    if live is None or live.status not in (
                        OrderStatus.OPEN,
                        OrderStatus.PARTIALLY_FILLED,
                    ):
                        return None
                    order = live

                if execution_price_override is not None:
                    execution_price = float(execution_price_override)
                elif order.order_type == OrderType.MARKET:
                    if orderbook is None:
                        return None
                    if order.side == OrderSide.BUY:
                        execution_price = orderbook.get_best_ask()
                    else:
                        execution_price = orderbook.get_best_bid()
                    if execution_price is None:
                        return None
                else:
                    execution_price = float(order.price)

                # Slippage applies only to market orders. A limit fill must never
                # execute outside its limit.
                if order.order_type == OrderType.MARKET:
                    slippage = self.settings.simulator.slippage
                    if order.side == OrderSide.BUY:
                        execution_price *= 1 + slippage
                    else:
                        execution_price *= 1 - slippage

                requested = float(order.size)
                if max_fill_size is not None:
                    requested = min(requested, max(0.0, float(max_fill_size)))
                fill_sz = self._allowed_fill_size(
                    order.market_id, order.platform, order.side, requested
                )
                if order.side == OrderSide.BUY and execution_price > 0:
                    affordable = self.current_balance / (execution_price * 1.001)
                    fill_sz = min(fill_sz, max(0.0, affordable))
                if fill_sz <= 1e-12:
                    return None

                trade = Trade(
                    trade_id=str(uuid.uuid4()),
                    market_id=order.market_id,
                    platform=order.platform,
                    side=order.side,
                    price=execution_price,
                    size=fill_sz,
                    timestamp=datetime.now(timezone.utc),
                    order_id=order.order_id,
                    strategy_id=order.strategy_id,
                    fees=execution_price * fill_sz * 0.001,
                )

                cost = execution_price * fill_sz
                if order.side == OrderSide.BUY:
                    self.current_balance -= cost + trade.fees
                else:
                    self.current_balance += cost - trade.fees

                self.trades.append(trade)
                self.storage.save_trade(trade)
                await self._update_position(trade)

                order.filled_size = (order.filled_size or 0.0) + fill_sz
                remaining = float(order.size) - fill_sz
                order.updated_at = datetime.now(timezone.utc)
                if remaining > 1e-12:
                    order.size = remaining
                    order.status = OrderStatus.PARTIALLY_FILLED
                    self.storage.save_order(order)
                    self.logger.info(
                        "Partial fill %s %.4f/%.4f at %.4f",
                        order.order_id,
                        fill_sz,
                        remaining + fill_sz,
                        execution_price,
                    )
                else:
                    order.status = OrderStatus.FILLED
                    order.size = order.filled_size
                    self.storage.save_order(order)
                    self.pending_orders.pop(order_id, None)
                    self.logger.info(
                        "Filled order %s at %.4f", order.order_id, execution_price
                    )
        finally:
            async with self._fill_lock:
                self._filling_order_ids.discard(order_id)

        await self._notify_fill(trade)
        return trade
    
    def _cancel_matching_orders_locked(
        self,
        market_id: Optional[str] = None,
        side: Optional[OrderSide] = None,
        reason: str = "cancelled",
    ) -> int:
        """Cancel and persist matching live orders while holding _fill_lock."""
        cancel_ids = [
            oid
            for oid, pending in self.pending_orders.items()
            if (market_id is None or pending.market_id == market_id)
            and (side is None or pending.side == side)
            and pending.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)
        ]
        for oid in cancel_ids:
            pending = self.pending_orders.pop(oid)
            pending.status = OrderStatus.CANCELLED
            pending.updated_at = datetime.now(timezone.utc)
            pending.metadata["cancel_reason"] = reason
            self.storage.save_order(pending)
        return len(cancel_ids)

    async def _cancel_all_pending_orders(self, reason: str) -> int:
        async with self._fill_lock:
            count = self._cancel_matching_orders_locked(reason=reason)
        if count:
            self.logger.info("Cancelled %d pending order(s): %s", count, reason)
        return count

    async def _process_strategy_signals(self):
        """Serialize signal generation and order-state mutations."""
        if self.use_schwab_spx and self._latest_spx_at is None:
            return
        if any(
            market_id in self._market_unready_since
            for market_id in self._subscribed_market_ids
        ):
            return
        async with self._signal_lock:
            for strategy in self.strategies:
                signals = await strategy.generate_signals()
                strategy_id = getattr(strategy, "strategy_id", None)
                for signal in signals:
                    await self.execute_signal(signal, strategy_id=strategy_id)
    
    async def execute_signal(
        self, signal: StrategySignal, strategy_id: Optional[str] = None
    ) -> Optional[Trade]:
        """Execute a trading signal with simulated execution"""
        order_side = OrderSide(signal.side)
        if signal.order_type == "limit" and signal.size <= 0:
            async with self._fill_lock:
                self._cancel_matching_orders_locked(
                    market_id=signal.market_id,
                    side=order_side,
                    reason="strategy_zero_size",
                )
            return None

        # Create order
        order = Order(
            order_id=str(uuid.uuid4()),
            market_id=signal.market_id,
            platform=signal.platform,
            side=order_side,
            order_type=OrderType(signal.order_type),
            price=signal.price,
            size=signal.size,
            status=OrderStatus.OPEN,
            strategy_id=strategy_id or signal.market_id,
        )

        # Get current market state
        market_state = self.market_state.get(signal.market_id, {})
        orderbook = market_state.get("orderbook")

        if not orderbook:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(timezone.utc)
            order.metadata["cancel_reason"] = "no_live_orderbook"
            async with self._fill_lock:
                self.orders[order.order_id] = order
                self.storage.save_order(order)
            self.logger.warning(
                "Rejected %s order for %s: no live orderbook",
                order.order_type.value,
                order.market_id,
            )
            return None

        # For market orders, fill immediately
        if order.order_type == OrderType.MARKET:
            async with self._fill_lock:
                self.orders[order.order_id] = order
                self.storage.save_order(order)
            trade = await self._fill_order(order, orderbook)
            if trade is None and order.status == OrderStatus.OPEN:
                async with self._fill_lock:
                    order.status = OrderStatus.CANCELLED
                    order.updated_at = datetime.now(timezone.utc)
                    order.metadata["cancel_reason"] = "unfillable_market_order"
                    self.storage.save_order(order)
            return trade
        else:
            # Cancel/replace: one open limit per (market_id, side).
            async with self._fill_lock:
                self._cancel_matching_orders_locked(
                    market_id=signal.market_id,
                    side=order_side,
                    reason="replaced",
                )
                self.orders[order.order_id] = order
                self.pending_orders[order.order_id] = order
                self.storage.save_order(order)
        
        return None

    async def _notify_fill(self, trade: Trade):
        """Notify strategies about their own fills so they can track inventory."""
        for strategy in self.strategies:
            try:
                await strategy.on_fill(trade)
            except Exception as exc:
                self.logger.error(
                    "Strategy %s failed to process fill %s: %s",
                    getattr(strategy, "strategy_id", type(strategy).__name__),
                    trade.trade_id,
                    exc,
                    exc_info=True,
                )
    
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

    async def stop(self):
        """Idempotently stop feeds, cancel orders, and finalize metrics."""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self.is_running = False
        self.end_time = datetime.now(timezone.utc)

        await self._cancel_all_pending_orders(reason="simulator_shutdown")
        self._stop_spx_feed()
        await self._stop_websocket_tasks()

        for strategy in self.strategies:
            try:
                await strategy.stop()
            except Exception as exc:
                self.logger.error(
                    "Failed to stop strategy %s: %s",
                    getattr(strategy, "strategy_id", type(strategy).__name__),
                    exc,
                    exc_info=True,
                )
        self.metrics = self._calculate_metrics()
    
    async def run(self):
        """Run paper trading simulator"""
        self.is_running = True
        self.start_time = datetime.now(timezone.utc)
        self._loop = asyncio.get_running_loop()
        self._run_started_monotonic = time.monotonic()
        
        self.logger.info("Starting paper trading simulator")
        
        # Initialize WebSockets
        await self.initialize_websockets()
        
        # Wait for connections to establish (or fail).
        await self._wait_for_initial_connection()
        
        # Require at least one WebSocket to be connected
        kalshi_ok = self.kalshi_ws is not None and self.kalshi_ws.is_connected
        poly_ok = self.polymarket_ws is not None and self.polymarket_ws.is_connected
        needs_kalshi = any(
            market_id.upper().startswith("KX") for market_id in self.markets
        )
        needs_polymarket = any(
            not market_id.upper().startswith("KX") for market_id in self.markets
        )
        required_feed_missing = (
            (needs_kalshi and not kalshi_ok)
            or (needs_polymarket and not poly_ok)
            or (not self.markets and not kalshi_ok and not poly_ok)
        )
        if required_feed_missing:
            self.websocket_connection_failed = True
            msg = "Could not load simulator because of bad websocket connection."
            self.logger.error(msg)
            print(f"\n{msg}\nCheck credentials, network, and logs above for details.\n")
            await self.stop()
            return

        # Start strategies first so they can run discovery (e.g. market_making discovers markets)
        for strategy in self.strategies:
            await strategy.start()

        if not self._start_spx_feed():
            self.startup_failure_reason = "Could not start required Schwab SPX feed"
            self.logger.critical(self.startup_failure_reason)
            await self.stop()
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
            self._subscribed_market_ids = set(all_market_ids)
            snapshot_deadline_started = time.monotonic()
            self._market_unready_since = {
                market_id: snapshot_deadline_started
                for market_id in all_market_ids
            }
            for market_id in all_market_ids:
                await self._maybe_inject_bounds(market_id)
            if kalshi_ok and self.kalshi_ws:
                kalshi_market_ids = [
                    market_id
                    for market_id in all_market_ids
                    if market_id.upper().startswith("KX")
                ]
                for market_id in kalshi_market_ids:
                    try:
                        await self.kalshi_ws.subscribe_market(market_id)
                    except Exception as e:
                        self.logger.warning(f"Kalshi subscribe {market_id}: {e}")
            if poly_ok and self.polymarket_ws:
                polymarket_asset_ids = [
                    market_id
                    for market_id in all_market_ids
                    if not market_id.upper().startswith("KX")
                ]
                if polymarket_asset_ids:
                    try:
                        await self.polymarket_ws.subscribe_assets(
                            polymarket_asset_ids
                        )
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
                feed_error = self._feed_health_error()
                if feed_error is not None:
                    self.feed_failure_reason = feed_error
                    self.logger.critical(
                        "Stopping paper trading because live data is unsafe: %s",
                        feed_error,
                    )
                    await self._cancel_all_pending_orders(
                        reason=f"feed_failure:{feed_error}"
                    )
                    self.is_running = False
                    break

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
            await self.stop()
            self.logger.info("Paper trading simulator stopped")
