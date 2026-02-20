"""Kalshi WebSocket client"""

import asyncio
import json
import logging
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from .base import BaseWebSocketManager, WebSocketEvent, WebSocketEventType
from src.config import get_credentials
from src.data.models import Platform, OrderBook, OrderBookLevel, Trade, OrderSide
from src.utils.logger import get_logger


class KalshiWebSocket(BaseWebSocketManager):
    """Kalshi WebSocket client"""
    
    # Kalshi WebSocket URL (based on their API documentation)
    WS_URL = "wss://api.kalshi.com/trade-api/ws/v2"
    
    def __init__(self):
        """Initialize Kalshi WebSocket client"""
        credentials = get_credentials()
        if not credentials.kalshi:
            raise ValueError("Kalshi credentials not configured")
        
        super().__init__(url=self.WS_URL)
        self.api_key = credentials.kalshi.api_key
        self.api_secret = credentials.kalshi.api_secret
        self.logger = get_logger("KalshiWebSocket")
        
        # Market subscriptions
        self.market_subscriptions: Dict[str, Dict[str, Any]] = {}
    
    def _generate_auth_signature(self, timestamp: str) -> str:
        """Generate authentication signature for Kalshi"""
        message = f"{self.api_key}{timestamp}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')
    
    async def authenticate(self) -> bool:
        """Authenticate with Kalshi WebSocket"""
        try:
            timestamp = str(int(datetime.utcnow().timestamp()))
            signature = self._generate_auth_signature(timestamp)
            
            auth_message = {
                "action": "auth",
                "api_key": self.api_key,
                "timestamp": timestamp,
                "signature": signature
            }
            
            await self.send_message(auth_message)
            
            # Wait for auth response
            response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
            response_data = json.loads(response)
            
            if response_data.get("status") == "ok":
                self.logger.info("Kalshi authentication successful")
                return True
            else:
                self.logger.error(f"Kalshi authentication failed: {response_data}")
                return False
                
        except Exception as e:
            self.logger.error(f"Authentication error: {e}", exc_info=True)
            return False
    
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
