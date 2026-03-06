"""Kalshi WebSocket client"""

import asyncio
import json
import base64
import time
from pathlib import Path
from datetime import datetime
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
    
    async def subscribe(self, channel: str, **kwargs) -> bool:
        """Subscribe to a Kalshi channel"""
        try:
            # Kalshi subscription format
            subscribe_message = {
                "action": "subscribe",
                "channel": channel,
                **kwargs
            }
            
            await self.send_message(subscribe_message)
            self.subscriptions.add(channel)
            self.logger.info(f"Subscribed to channel: {channel}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to subscribe to {channel}: {e}", exc_info=True)
            return False
    
    async def subscribe_market(self, market_id: str, subscribe_orderbook: bool = True, subscribe_trades: bool = True):
        """Subscribe to market data for a specific market"""
        subscriptions = []
        
        if subscribe_orderbook:
            await self.subscribe(f"orderbook.{market_id}")
            subscriptions.append(f"orderbook.{market_id}")
        
        if subscribe_trades:
            await self.subscribe(f"trades.{market_id}")
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
        """Parse Kalshi WebSocket message"""
        try:
            data = json.loads(message)
            
            # Handle different message types
            if "type" in data:
                msg_type = data["type"]
                
                # Order book update
                if msg_type == "orderbook" or "orderbook" in data.get("channel", ""):
                    return self._parse_orderbook(data)
                
                # Trade update
                elif msg_type == "trade" or "trades" in data.get("channel", ""):
                    return self._parse_trade(data)
                
                # Market update
                elif msg_type == "market":
                    return self._parse_market_update(data)
                
                # Status/error messages
                elif msg_type in ["status", "error"]:
                    self.logger.debug(f"Status message: {data}")
                    return None
            
            # Default: generic message
            return WebSocketEvent(
                event_type=WebSocketEventType.MESSAGE,
                data=data,
                timestamp=datetime.utcnow(),
                market_id=data.get("market_id")
            )
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing message: {e}", exc_info=True)
            return None
    
    def _parse_orderbook(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Parse order book update"""
        market_id = data.get("market_id") or data.get("channel", "").split(".")[-1]
        
        # Extract bid/ask levels
        bids = []
        asks = []
        
        if "bids" in data:
            for bid in data["bids"]:
                bids.append(OrderBookLevel(
                    price=float(bid.get("price", 0)),
                    size=float(bid.get("size", 0)),
                    orders=bid.get("orders", 1)
                ))
        
        if "asks" in data:
            for ask in data["asks"]:
                asks.append(OrderBookLevel(
                    price=float(ask.get("price", 0)),
                    size=float(ask.get("size", 0)),
                    orders=ask.get("orders", 1)
                ))
        
        orderbook = OrderBook(
            market_id=market_id,
            platform=Platform.KALSHI,
            timestamp=datetime.utcnow(),
            bids=bids,
            asks=asks
        )
        
        return WebSocketEvent(
            event_type=WebSocketEventType.ORDERBOOK_UPDATE,
            data={"orderbook": orderbook.model_dump()},
            timestamp=datetime.utcnow(),
            market_id=market_id
        )
    
    def _parse_trade(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Parse trade update"""
        market_id = data.get("market_id") or data.get("channel", "").split(".")[-1]
        
        trade = Trade(
            trade_id=data.get("trade_id", ""),
            market_id=market_id,
            platform=Platform.KALSHI,
            side=OrderSide.BUY if data.get("side") == "buy" else OrderSide.SELL,
            price=float(data.get("price", 0)),
            size=float(data.get("size", 0)),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
            fees=float(data.get("fees", 0))
        )
        
        return WebSocketEvent(
            event_type=WebSocketEventType.TRADE,
            data={"trade": trade.model_dump()},
            timestamp=datetime.utcnow(),
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
