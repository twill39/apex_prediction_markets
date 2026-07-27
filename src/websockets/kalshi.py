"""Kalshi WebSocket client"""

import asyncio
import json
import base64
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from .base import BaseWebSocketManager, WebSocketEvent, WebSocketEventType
from src.config import get_credentials
from src.data.models import Platform, OrderBook, OrderBookLevel, Trade, OrderSide
from src.utils.logger import get_logger


class KalshiWebSocket(BaseWebSocketManager):
    """Kalshi WebSocket client (authenticates via PEM private key and connection headers)."""

    # Path to sign for WebSocket connection (per Kalshi docs)
    WS_SIGN_PATH = "/trade-api/ws/v2"
    
    def __init__(self):
        """Initialize Kalshi WebSocket client"""
        credentials = get_credentials()
        if not credentials.kalshi:
            raise ValueError("Kalshi credentials not configured (set KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH)")
        
        kalshi = credentials.kalshi
        super().__init__(url=kalshi.ws_url)
        self.api_key = kalshi.api_key
        self.private_key_path = Path(kalshi.private_key_path).expanduser().resolve()
        self.logger = get_logger("KalshiWebSocket")
        
        if not self.private_key_path.is_file():
            raise ValueError(f"Kalshi private key file not found: {self.private_key_path}")
        
        self._private_key = None  # Loaded lazily
        self.market_subscriptions: Dict[str, Dict[str, Any]] = {}
        self._msg_id = 0
        self._use_yes_price = True
        # Per-market orderbook state for orderbook_delta: market_id -> {bids: {price: size}, asks: {price: size}}
        self._orderbook_state: Dict[str, Dict[str, Dict[float, float]]] = {}
        self._orderbook_sequences: Dict[str, int] = {}
    
    def _load_private_key(self):
        """Load RSA private key from PEM file."""
        if self._private_key is None:
            with open(self.private_key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                )
        return self._private_key
    
    def _sign_message(self, message: str) -> str:
        """Sign message with RSA-PSS (SHA256) and return base64-encoded signature."""
        private_key = self._load_private_key()
        signature = private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")
    
    def get_connection_headers(self) -> Dict[str, str]:
        """Build Kalshi auth headers for WebSocket connection (timestamp in milliseconds, GET path)."""
        timestamp_ms = str(int(time.time() * 1000))
        message = timestamp_ms + "GET" + self.WS_SIGN_PATH
        signature = self._sign_message(message)
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }
    
    async def authenticate(self) -> bool:
        """Kalshi auth is done via headers on connect; no post-connect auth message."""
        self.logger.info("Kalshi authentication (via connection headers) successful")
        return True

    def _on_connection_lost(self) -> None:
        """Discard books that cannot safely be continued across a reconnect."""
        self._orderbook_state.clear()
        self._orderbook_sequences.clear()
    
    async def subscribe(self, channel: str, **kwargs) -> bool:
        """Subscribe to a Kalshi channel. For orderbook use subscribe_orderbook_delta instead (correct API format)."""
        try:
            # Kalshi uses cmd/params for orderbook_delta and trade; legacy action/channel for others
            if channel.startswith("orderbook."):
                market_id = channel.split(".", 1)[1]
                return await self.subscribe_orderbook_delta([market_id])
            if channel.startswith("trades.") or channel.startswith("trade."):
                market_id = channel.split(".", 1)[1]
                return await self.subscribe_trade([market_id])
            subscribe_message = {"action": "subscribe", "channel": channel, **kwargs}
            await self.send_message(subscribe_message)
            self.subscriptions.add(channel)
            self.logger.info(f"Subscribed to channel: {channel}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to subscribe to {channel}: {e}", exc_info=True)
            return False

    async def subscribe_orderbook_delta(self, market_tickers: list) -> bool:
        """Subscribe to orderbook_delta channel (Kalshi format: cmd/subscribe, params with channels + market_ticker(s))."""
        try:
            self._msg_id += 1
            params: Dict[str, Any] = {
                "channels": ["orderbook_delta"],
                # Keep YES bids and implied YES asks on one price scale. Without
                # this, Kalshi reports NO levels in NO-leg prices.
                "use_yes_price": self._use_yes_price,
            }
            if len(market_tickers) == 1:
                params["market_ticker"] = market_tickers[0]
            else:
                params["market_tickers"] = market_tickers
            subscribe_message = {"id": self._msg_id, "cmd": "subscribe", "params": params}
            await self.send_message(subscribe_message)
            for m in market_tickers:
                self.subscriptions.add(f"orderbook.{m}")
                self._orderbook_state.setdefault(m, {"bids": {}, "asks": {}})
            self.logger.info("Subscribed to orderbook_delta for %s", market_tickers)
            return True
        except Exception as e:
            self.logger.error("Failed to subscribe to orderbook_delta: %s", e, exc_info=True)
            return False

    async def subscribe_trade(self, market_tickers: list) -> bool:
        """Subscribe to trade channel (Kalshi format)."""
        try:
            self._msg_id += 1
            params: Dict[str, Any] = {"channels": ["trade"]}
            if len(market_tickers) == 1:
                params["market_ticker"] = market_tickers[0]
            else:
                params["market_tickers"] = market_tickers
            await self.send_message({"id": self._msg_id, "cmd": "subscribe", "params": params})
            for m in market_tickers:
                self.subscriptions.add(f"trades.{m}")
            self.logger.info("Subscribed to trade for %s", market_tickers)
            return True
        except Exception as e:
            self.logger.error("Failed to subscribe to trade: %s", e, exc_info=True)
            return False

    async def subscribe_market(self, market_id: str, subscribe_orderbook: bool = True, subscribe_trades: bool = True):
        """Subscribe to market data for a specific market"""
        subscriptions = []
        if subscribe_orderbook:
            ok = await self.subscribe_orderbook_delta([market_id])
            if ok:
                subscriptions.append(f"orderbook.{market_id}")
        if subscribe_trades:
            ok = await self.subscribe_trade([market_id])
            if ok:
                subscriptions.append(f"trades.{market_id}")
        
        self.market_subscriptions[market_id] = {
            "orderbook": subscribe_orderbook,
            "trades": subscribe_trades
        }
        
        return subscriptions
    
    async def unsubscribe(self, channel: str) -> bool:
        """Unsubscribe from a channel"""
        try:
            unsubscribe_message = {
                "action": "unsubscribe",
                "channel": channel
            }
            
            await self.send_message(unsubscribe_message)
            self.subscriptions.discard(channel)
            self.logger.info(f"Unsubscribed from channel: {channel}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to unsubscribe from {channel}: {e}", exc_info=True)
            return False
    
    def parse_message(self, message: str) -> Optional[WebSocketEvent]:
        """Parse Kalshi WebSocket message. Handles orderbook_snapshot, orderbook_delta (yes/no), trade, etc."""
        try:
            data = json.loads(message)
            if "type" not in data:
                return WebSocketEvent(
                    event_type=WebSocketEventType.MESSAGE,
                    data=data,
                    timestamp=datetime.utcnow(),
                    market_id=data.get("market_id"),
                )
            msg_type = data["type"]
            if msg_type == "orderbook_snapshot":
                return self._parse_orderbook_snapshot(data)
            if msg_type == "orderbook_delta":
                return self._parse_orderbook_delta(data)
            if msg_type == "orderbook" or "orderbook" in data.get("channel", ""):
                return self._parse_orderbook(data)
            if msg_type == "trade" or "trades" in data.get("channel", ""):
                return self._parse_trade(data)
            if msg_type == "market":
                return self._parse_market_update(data)
            if msg_type in ["status", "error", "subscribed"]:
                self.logger.debug("WS message: %s", msg_type)
                return None
            return WebSocketEvent(
                event_type=WebSocketEventType.MESSAGE,
                data=data,
                timestamp=datetime.utcnow(),
                market_id=data.get("market_id"),
            )
        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse message: %s", e)
            return None
        except Exception as e:
            self.logger.error("Error parsing message: %s", e, exc_info=True)
            return None

    @staticmethod
    def _message_timestamp(data: Dict[str, Any]) -> datetime:
        msg = data.get("msg") or {}
        ts_ms = msg.get("ts_ms") or data.get("ts_ms")
        if ts_ms is not None:
            try:
                return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        return datetime.now(timezone.utc)

    def _state_to_orderbook_event(
        self, market_id: str, timestamp: Optional[datetime] = None
    ) -> WebSocketEvent:
        """Build ORDERBOOK_UPDATE event from current _orderbook_state for market_id."""
        event_time = timestamp or datetime.now(timezone.utc)
        state = self._orderbook_state.get(market_id, {"bids": {}, "asks": {}})
        bids = [
            OrderBookLevel(price=p, size=s, orders=1)
            for p, s in sorted(state.get("bids", {}).items(), key=lambda x: -x[0])
            if s > 0
        ]
        asks = [
            OrderBookLevel(price=p, size=s, orders=1)
            for p, s in sorted(state.get("asks", {}).items(), key=lambda x: x[0])
            if s > 0
        ]
        orderbook = OrderBook(
            market_id=market_id,
            platform=Platform.KALSHI,
            timestamp=event_time,
            bids=bids,
            asks=asks,
        )
        return WebSocketEvent(
            event_type=WebSocketEventType.ORDERBOOK_UPDATE,
            data={"orderbook": orderbook.model_dump()},
            timestamp=event_time,
            market_id=market_id,
        )

    def _emit_orderbook_error(self, market_id: str, reason: str) -> None:
        event_time = datetime.now(timezone.utc)
        self._emit_event(
            WebSocketEvent(
                event_type=WebSocketEventType.ERROR,
                data={"reason": reason, "market_id": market_id},
                timestamp=event_time,
                market_id=market_id,
            )
        )

    def _parse_orderbook_snapshot(self, data: Dict[str, Any]) -> Optional[WebSocketEvent]:
        """Kalshi orderbook_snapshot.

        Current Kalshi payload (per docs):
          - msg.yes_dollars_fp: [[price_in_dollars, contract_count_fp], ...]
          - msg.no_dollars_fp:  [[price_in_dollars, contract_count_fp], ...]

        Back-compat:
          - msg.yes / msg.no might appear as [[price_cents, size], ...]
        """
        msg = data.get("msg") or {}
        market_id = (msg.get("market_ticker") or msg.get("market_id") or "").strip()
        if not market_id:
            return None
        state = self._orderbook_state.setdefault(market_id, {"bids": {}, "asks": {}})
        state["bids"] = {}
        state["asks"] = {}
        seq = data.get("seq")
        try:
            self._orderbook_sequences[market_id] = int(seq)
        except (TypeError, ValueError):
            self.logger.error(
                "Ignoring Kalshi snapshot with invalid sequence for %s: %r",
                market_id,
                seq,
            )
            self._orderbook_sequences.pop(market_id, None)
            self._emit_orderbook_error(market_id, "invalid_snapshot_sequence")
            return None

        # Prefer the documented keys (yes_dollars_fp/no_dollars_fp).
        # Some payloads place depth fields at the top-level instead of under `msg`.
        yes_dollars = msg.get("yes_dollars_fp") if "yes_dollars_fp" in msg else data.get("yes_dollars_fp")
        no_dollars = msg.get("no_dollars_fp") if "no_dollars_fp" in msg else data.get("no_dollars_fp")

        if yes_dollars is not None or no_dollars is not None:
            yes_levels = yes_dollars or []
            no_levels = no_dollars or []
            for level in yes_levels:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    p = float(level[0])
                    s = float(level[1])
                    if s > 0:
                        state["bids"][p] = s
            for level in no_levels:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    p = float(level[0])
                    s = float(level[1])
                    if s > 0:
                        state["asks"][p] = s
        else:
            # Back-compat: older payload used yes/no in cents.
            yes_levels = msg.get("yes") if "yes" in msg else data.get("yes")
            no_levels = msg.get("no") if "no" in msg else data.get("no")
            for level in yes_levels or []:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    p = float(level[0]) / 100.0
                    s = float(level[1])
                    if s > 0:
                        state["bids"][p] = s
            for level in no_levels or []:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    p = float(level[0]) / 100.0
                    s = float(level[1])
                    if s > 0:
                        state["asks"][p] = s

        return self._state_to_orderbook_event(
            market_id, timestamp=self._message_timestamp(data)
        )

    def _parse_orderbook_delta(self, data: Dict[str, Any]) -> Optional[WebSocketEvent]:
        """Kalshi orderbook_delta.

        Current Kalshi payload (per docs):
          - msg.price_dollars (string)
          - msg.delta_fp (string, fixed-point)
          - msg.side in {"yes","no"}

        Back-compat:
          - msg.price (cents), msg.delta (int-ish), msg.side in {"yes","no"}
        """
        msg = data.get("msg") or {}
        market_id = (msg.get("market_ticker") or msg.get("market_id") or "").strip()
        if not market_id:
            return None
        state = self._orderbook_state.setdefault(market_id, {"bids": {}, "asks": {}})
        seq = data.get("seq")
        try:
            seq_int = int(seq)
        except (TypeError, ValueError):
            self.logger.error("Ignoring invalid Kalshi sequence for %s: %r", market_id, seq)
            self._emit_orderbook_error(market_id, "invalid_delta_sequence")
            return None
        previous = self._orderbook_sequences.get(market_id)
        if previous is None:
            self.logger.warning(
                "Ignoring Kalshi delta for %s before snapshot", market_id
            )
            self._emit_orderbook_error(market_id, "delta_before_snapshot")
            return None
        if seq_int != previous + 1:
            self.logger.error(
                "Kalshi orderbook sequence gap for %s: expected %s, got %s; waiting for snapshot",
                market_id,
                previous + 1,
                seq_int,
            )
            self._orderbook_state[market_id] = {"bids": {}, "asks": {}}
            self._orderbook_sequences.pop(market_id, None)
            self._emit_orderbook_error(market_id, "orderbook_sequence_gap")
            return None
        self._orderbook_sequences[market_id] = seq_int
        side = (msg.get("side") or data.get("side") or "").strip().lower()
        if side not in {"yes", "no"}:
            self.logger.warning("Ignoring Kalshi delta with invalid side %r", side)
            return None
        side_key = "bids" if side == "yes" else "asks"

        price_dollars = msg.get("price_dollars") if "price_dollars" in msg else data.get("price_dollars")
        delta_fp = msg.get("delta_fp") if "delta_fp" in msg else data.get("delta_fp")
        if price_dollars is not None or delta_fp is not None:
            price = float(price_dollars or 0)
            delta = float(delta_fp or 0)
        else:
            price = float(msg.get("price", data.get("price", 0)) or 0) / 100.0
            delta = float(msg.get("delta", data.get("delta", 0)) or 0)

        book = state[side_key]
        current = book.get(price, 0.0) + delta
        if current <= 0:
            book.pop(price, None)
        else:
            book[price] = current
        return self._state_to_orderbook_event(
            market_id, timestamp=self._message_timestamp(data)
        )

    def _parse_orderbook(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Legacy: parse order book with top-level bids/asks (if API ever sends that)."""
        market_id = data.get("market_id") or (data.get("channel") or "").split(".")[-1]
        bids = []
        asks = []
        if "bids" in data:
            for bid in data["bids"]:
                bids.append(
                    OrderBookLevel(
                        price=float(bid.get("price", 0)),
                        size=float(bid.get("size", 0)),
                        orders=bid.get("orders", 1),
                    )
                )
        if "asks" in data:
            for ask in data["asks"]:
                asks.append(
                    OrderBookLevel(
                        price=float(ask.get("price", 0)),
                        size=float(ask.get("size", 0)),
                        orders=ask.get("orders", 1),
                    )
                )
        orderbook = OrderBook(
            market_id=market_id,
            platform=Platform.KALSHI,
            timestamp=datetime.now(timezone.utc),
            bids=bids,
            asks=asks,
        )
        return WebSocketEvent(
            event_type=WebSocketEventType.ORDERBOOK_UPDATE,
            data={"orderbook": orderbook.model_dump()},
            timestamp=datetime.now(timezone.utc),
            market_id=market_id,
        )
    
    def _parse_trade(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Parse trade update"""
        msg = data.get("msg") or data
        market_id = (
            msg.get("market_ticker")
            or msg.get("market_id")
            or data.get("market_id")
            or data.get("channel", "").split(".")[-1]
        )
        ts_ms = msg.get("ts_ms")
        if ts_ms is not None:
            timestamp = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        elif msg.get("ts") is not None:
            ts_value = float(msg["ts"])
            if ts_value > 10_000_000_000:
                ts_value /= 1000.0
            timestamp = datetime.fromtimestamp(ts_value, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        taker_side = str(
            msg.get("taker_outcome_side") or msg.get("taker_side") or ""
        ).lower()
        taker_book_side = str(msg.get("taker_book_side") or "").lower()
        is_yes_taker = taker_side == "yes" or taker_book_side == "bid"
        
        if msg.get("yes_price_dollars") is not None:
            trade_price = float(msg["yes_price_dollars"])
        else:
            trade_price = float(msg.get("price", 0))
            if trade_price > 1.0:
                trade_price /= 100.0

        trade = Trade(
            trade_id=msg.get("trade_id", ""),
            market_id=market_id,
            platform=Platform.KALSHI,
            side=OrderSide.BUY if is_yes_taker else OrderSide.SELL,
            price=trade_price,
            size=float(msg.get("count_fp", msg.get("size", 0))),
            timestamp=timestamp,
            fees=float(msg.get("fees", 0)),
        )
        
        return WebSocketEvent(
            event_type=WebSocketEventType.TRADE,
            data={"trade": trade.model_dump()},
            timestamp=timestamp,
            market_id=market_id
        )
    
    def _parse_market_update(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Parse market update"""
        return WebSocketEvent(
            event_type=WebSocketEventType.MARKET_UPDATE,
            data=data,
            timestamp=datetime.utcnow(),
            market_id=data.get("market_id")
        )
