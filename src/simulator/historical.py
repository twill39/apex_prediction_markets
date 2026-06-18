"""Historical replay simulator"""

import asyncio
import json
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
from zoneinfo import ZoneInfo

from .base import BaseSimulator, SimulatorMode
from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, OrderSide, OrderType, OrderStatus, Platform, PositionSide
from src.data.storage import get_storage
from src.config import get_settings
from src.utils.logger import get_logger
from src.websockets.base import WebSocketEvent, WebSocketEventType


class HistoricalSimulator(BaseSimulator):
    """Simulator that replays historical market data"""

    def __init__(
        self,
        data_path: Optional[str] = None,
        markets: Optional[List[str]] = None,
        underlying_path: Optional[str] = None,
        underlying_symbol: str = "$SPX",
        historical_rth_only: Optional[bool] = None,
    ):
        """Initialize historical simulator.
        markets: optional list of market IDs; if set, only events for these markets are replayed.
        """
        super().__init__(mode=SimulatorMode.HISTORICAL)
        self.settings = get_settings()
        ib = float(self.settings.simulator.initial_balance)
        self.initial_balance = ib
        self.current_balance = ib
        self.logger = get_logger("HistoricalSimulator")
        self.storage = get_storage()
        self.markets: List[str] = list(markets) if markets else []

        # Historical data
        self.data_path = data_path or "./data/historical"
        self.underlying_path = underlying_path
        self.underlying_symbol = underlying_symbol
        self.historical_rth_only = (
            self.settings.simulator.historical_rth_only
            if historical_rth_only is None
            else historical_rth_only
        )
        self.trading_timezone = self.settings.simulator.trading_timezone
        self.session_start = self._parse_hhmm(self.settings.simulator.regular_session_start, time(9, 30))
        self.session_end = self._parse_hhmm(self.settings.simulator.regular_session_end, time(16, 0))
        self._market_tz = ZoneInfo(self.trading_timezone)
        self.events: List[Dict[str, Any]] = []
        self.current_event_index = 0

        # Market state (order books, prices)
        self.market_state: Dict[str, Dict[str, Any]] = {}  # market_id -> state

        # Checking unfillled orders
        self.pending_orders: List[Dict] = []  # unfilled limit orders

    @staticmethod
    def _parse_hhmm(value: str, fallback: time) -> time:
        """Parse HH:MM session time strings with safe fallback."""
        if not value:
            return fallback
        try:
            parts = value.split(":")
            if len(parts) != 2:
                return fallback
            hh = int(parts[0])
            mm = int(parts[1])
            return time(hh, mm)
        except (TypeError, ValueError):
            return fallback

    def _is_in_regular_session(self, event: Dict[str, Any]) -> bool:
        """Return True if event timestamp is inside configured regular hours."""
        ts = self._get_event_timestamp(event)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local_ts = ts.astimezone(self._market_tz)
        local_time = local_ts.timetz().replace(tzinfo=None)
        return self.session_start <= local_time <= self.session_end
    
    def load_historical_data(self, file_path: str):
        """Load historical data from file"""
        self.logger.info(f"Loading historical data from {file_path}")
        
        try:
            # Support JSON and CSV formats
            if file_path.endswith('.json'):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.events = data.get("events", []) or data.get("candlesticks", [])
            elif file_path.endswith('.jsonl'):
                with open(file_path, 'r') as f:
                    first_line = json.loads(f.readline())
                print(f"bids[:3]={first_line['bids'][:3]}")
                print(f"asks[:3]={first_line['asks'][:3]}")
                print(f"best bid={max(b[0] for b in first_line['bids'])}")
                print(f"asks above best bid={[a for a in first_line['asks'] if a[0] > max(b[0] for b in first_line['bids'])][:3]}")



                with open(file_path, 'r') as f:
                    raw = [json.loads(line) for line in f if line.strip()]
                ticker = Path(file_path).parent.name  # infer ticker from folder name
                self.events = [
                    {
                        "type": "orderbook_update",
                        "market_id": ticker,
                        "timestamp": datetime.fromtimestamp(e["t"], tz=timezone.utc).isoformat(),
                        "bids": e.get("bids", []),
                        "asks": [[round(1 - a[0], 2), a[1]] for a in e.get("asks", [])],
                    }
                    for e in raw
                ]
            elif file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
                # Convert DataFrame to events
                self.events = df.to_dict('records')
            else:
                raise ValueError(f"Unsupported file format: {file_path}")
            
            if self.underlying_path:
                underlying_events = self._load_underlying_events(
                    self.underlying_path,
                    symbol=self.underlying_symbol,
                )
                self.events.extend(underlying_events)
                self.logger.info(
                    f"Merged {len(underlying_events)} underlying events from {self.underlying_path}"
                )

            # Sort events by timestamp
            self.events.sort(key=lambda x: self._get_event_timestamp(x))
            
            self.logger.info(f"Loaded {len(self.events)} historical events")
            
        except Exception as e:
            self.logger.error(f"Failed to load historical data: {e}", exc_info=True)
            raise

    def _load_underlying_events(self, file_path: str, symbol: str) -> List[Dict[str, Any]]:
        """Load minute underlying observations and convert to MARKET_UPDATE events."""
        if not file_path.endswith(".csv"):
            raise ValueError(f"Unsupported underlying format: {file_path}")

        df = pd.read_csv(file_path)
        if df.empty:
            return []

        ts_col = None
        for candidate in ("timestamp_et", "timestamp_utc", "timestamp", "time"):
            if candidate in df.columns:
                ts_col = candidate
                break
        if ts_col is None:
            raise ValueError(
                f"Could not find timestamp column in underlying CSV. Columns: {list(df.columns)}"
            )

        price_col = None
        for candidate in ("close", "price", "last", "spot"):
            if candidate in df.columns:
                price_col = candidate
                break
        if price_col is None:
            raise ValueError(
                f"Could not find price column in underlying CSV. Columns: {list(df.columns)}"
            )

        events: List[Dict[str, Any]] = []
        for row in df.to_dict("records"):
            raw_ts = row.get(ts_col)
            if raw_ts is None:
                continue
            ts = pd.to_datetime(raw_ts, utc=True, errors="coerce")
            if pd.isna(ts):
                continue

            raw_price = row.get(price_col)
            if raw_price is None:
                continue
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                continue

            metadata = {
                k: v
                for k, v in row.items()
                if k not in {ts_col, price_col}
            }
            events.append(
                {
                    "type": "market_update",
                    "timestamp": ts.to_pydatetime().isoformat(),
                    "data": {
                        "update_type": "underlying_price",
                        "symbol": symbol,
                        "price": price,
                        "timestamp": ts.to_pydatetime().isoformat(),
                        "source": "historical_underlying_csv",
                        "metadata": metadata,
                    },
                }
            )

        return events
    
    def _get_event_timestamp(self, event: Dict[str, Any]) -> datetime:
        """Extract timestamp from event"""
        # handle unix timestamp from websocket (key "t")
        t = event.get("t")
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t, tz=timezone.utc)
        
        # fallback for ISO string format
        timestamp_str = event.get("timestamp") or event.get("time")
        if isinstance(timestamp_str, str):
            try:
                parsed = datetime.fromisoformat(timestamp_str)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except Exception:
                return datetime.now(timezone.utc)
        
        return datetime.now(timezone.utc)
    
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
        
        # Replay events chronologically (optionally filter by market)
        for i, event in enumerate(self.events):
            if not self.is_running:
                break
            if self.historical_rth_only and not self._is_in_regular_session(event):
                continue
            if self.markets:
                mid = event.get("market_id") or event.get("market") or event.get("data", {}).get("market_id")
                if mid is not None and mid not in self.markets:
                    continue
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

        # store best bid/ask for fill checks
        bids = event.get("bids", [])
        asks = event.get("asks", [])
        if bids:
            self.market_state[market_id]["best_bid"] = max(b[0] for b in bids)
        if asks:
            self.market_state[market_id]["best_ask"] = min(a[0] for a in asks)
        self.market_state[market_id]["timestamp"] = self._get_event_timestamp(event)
        mid = None
        if bids and asks:
            mid = (self.market_state[market_id]["best_bid"] + self.market_state[market_id]["best_ask"]) / 2
            self.market_state[market_id]["mid_price"] = mid
            self._mark_position_to_market(market_id, mid)

        # check pending orders before processing strategies
        await self._check_pending_orders(market_id)
        
        payload = event.get("data") or {}
        # Newer format (from `scripts/collect_historical.py`):
        #   event["data"]["orderbook"] = OrderBook.model_dump()
        orderbook_data = payload.get("orderbook") or event.get("orderbook")
        if orderbook_data:
            # Let the model validate/parse where possible.
            orderbook = OrderBook(**orderbook_data)
        else:
            # Back-compat: older format with top-level `bids`/`asks` as [[price,size], ...]
            bids = [OrderBookLevel(price=b[0], size=b[1]) for b in event.get("bids", [])]
            asks = [OrderBookLevel(price=a[0], size=a[1]) for a in event.get("asks", [])]
            orderbook = OrderBook(
                market_id=market_id,
                platform=Platform(event.get("platform", "kalshi")),
                timestamp=self._get_event_timestamp(event),
                bids=bids,
                asks=asks,
            )
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_orderbook_update(orderbook)
        
        # Generate and execute signals
        await self._process_strategy_signals()
    
    async def _process_trade(self, event: Dict[str, Any]):
        """Process trade event"""
        from src.data.models import Trade

        payload = event.get("data") or {}
        trade_data = payload.get("trade") or event.get("trade")
        if trade_data:
            trade = Trade(**trade_data)
        else:
            # Back-compat: older format with flat keys.
            trade = Trade(
                trade_id=event.get("trade_id", f"hist_{self.current_event_index}"),
                market_id=event.get("market_id"),
                platform=Platform(event.get("platform", "kalshi")),
                side=OrderSide(event.get("side", "buy")),
                price=float(event.get("price", 0)),
                size=float(event.get("size", 0)),
                timestamp=self._get_event_timestamp(event),
            )
        
        # Notify strategies
        for strategy in self.strategies:
            await strategy.on_trade(trade)
        
        # Generate and execute signals
        await self._process_strategy_signals()
    
    async def _process_market_update(self, event: Dict[str, Any]):
        """Process market update event"""
        # Update market state
        market_id = event.get("market_id") or (event.get("data") or {}).get("market_id")
        if market_id:
            if market_id not in self.market_state:
                self.market_state[market_id] = {}
            self.market_state[market_id].update(event.get("data", {}))

        # Notify strategies (alt_data relies on MARKET_UPDATE via on_market_event)
        payload = event.get("data") or {}
        ws_event = WebSocketEvent(
            event_type=WebSocketEventType.MARKET_UPDATE,
            data=payload,
            timestamp=self._get_event_timestamp(event),
            market_id=market_id,
        )
        for strategy in self.strategies:
            await strategy.on_market_event(ws_event)

        # Generate and process signals
        await self._process_strategy_signals()
    
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
        """Queue limit orders for realistic fill simulation."""
        market_state = self.market_state.get(signal.market_id, {})
        event_time = market_state.get("timestamp") or signal.timestamp or datetime.utcnow()
        if signal.order_type == "market":
            # Market orders fill immediately at mid
            execution_price = market_state.get("mid_price") or signal.price or 0.5
            return await self._fill_order(signal, execution_price, execution_time=event_time)
        else:
            if signal.size <= 0:
                self.pending_orders = [
                    o
                    for o in self.pending_orders
                    if not (
                        o["signal"].market_id == signal.market_id
                        and o["signal"].side == signal.side
                    )
                ]
                return None
            # Cancel/replace: one live limit order per (market_id, side).
            self.pending_orders = [
                o
                for o in self.pending_orders
                if not (
                    o["signal"].market_id == signal.market_id
                    and o["signal"].side == signal.side
                )
            ]
            self.pending_orders.append({
                "signal": signal,
                "queued_at": event_time,
                "expires_at": event_time + timedelta(seconds=30),  # order TTL in event time
            })
            return None
        
    async def _fill_order(self, signal: StrategySignal, execution_price: float, execution_time: Optional[datetime] = None) -> Optional[Trade]:
        """Actually fill an order and update balance/position."""
        if execution_price <= 0:
            return None
        trade_time = execution_time or signal.timestamp or datetime.utcnow()

        fill_sz = self._allowed_fill_size(signal.market_id, signal.platform, signal.side, signal.size)
        if fill_sz <= 0:
            return None

        slippage = self.settings.simulator.slippage
        if signal.side == "buy":
            execution_price *= (1 + slippage)
        else:
            execution_price *= (1 - slippage)

        trade = Trade(
            trade_id=f"hist_{len(self.trades)}_{datetime.utcnow().timestamp()}",
            market_id=signal.market_id,
            platform=signal.platform,
            side=OrderSide(signal.side),
            price=execution_price,
            size=fill_sz,
            timestamp=trade_time,
            strategy_id=signal.market_id,
            fees=execution_price * fill_sz * 0.001,
        )

        cost = execution_price * fill_sz
        if signal.side == "buy":
            self.current_balance -= cost + trade.fees
        else:
            self.current_balance += cost - trade.fees

        await self._update_position(trade)
        await self._notify_fill(trade)
        return trade

    async def _notify_fill(self, trade: Trade):
        """Notify strategies about their own fills so they can track inventory."""
        for strategy in self.strategies:
            await strategy.on_fill(trade)
    
    async def _check_pending_orders(self, market_id: str):
        """Check if any pending limit orders can be filled given current market state."""
        if not self.pending_orders:
            return

        market_state = self.market_state.get(market_id, {})
        best_bid = market_state.get("best_bid")
        best_ask = market_state.get("best_ask")
        now = market_state.get("timestamp") or datetime.utcnow()

        still_pending = []
        for order in self.pending_orders:
            signal = order["signal"]

            # Skip orders for other markets
            if signal.market_id != market_id:
                still_pending.append(order)
                continue

            # Expire stale orders
            if now > order["expires_at"]:
                self.logger.debug(f"Order expired: {signal.side} {signal.market_id} @ {signal.price}")
                continue

            orig_size = float(signal.size)
            trade: Optional[Trade] = None
            # Buy fills if best ask drops to or below our bid price
            if signal.side == "buy" and best_ask is not None and best_ask <= signal.price:
                trade = await self._fill_order(signal, best_ask, execution_time=now)
                if trade:
                    self.trades.append(trade)
                    self.storage.save_trade(trade)
                    rem = orig_size - trade.size
                    if rem > 1e-12:
                        order["signal"] = signal.model_copy(update={"size": rem})
                        still_pending.append(order)

            # Sell fills if best bid rises to or above our ask price
            elif signal.side == "sell" and best_bid is not None and best_bid >= signal.price:
                trade = await self._fill_order(signal, best_bid, execution_time=now)
                if trade:
                    self.trades.append(trade)
                    self.storage.save_trade(trade)
                    rem = orig_size - trade.size
                    if rem > 1e-12:
                        order["signal"] = signal.model_copy(update={"size": rem})
                        still_pending.append(order)
            else:
                still_pending.append(order)

        self.pending_orders = still_pending

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
