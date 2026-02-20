"""Polymarket WebSocket client"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from .base import BaseWebSocketManager, WebSocketEvent, WebSocketEventType
from src.config import get_credentials
from src.data.models import Platform, OrderBook, OrderBookLevel, Trade, OrderSide
from src.utils.logger import get_logger


class PolymarketWebSocket(BaseWebSocketManager):
    """Polymarket WebSocket client"""
    
    # Polymarket WebSocket URL (based on their API documentation)
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self):
        """Initialize Polymarket WebSocket client"""
        credentials = get_credentials()
        if not credentials.polymarket:
            raise ValueError("Polymarket credentials not configured")
        
        super().__init__(url=self.WS_URL)
        self.api_key = credentials.polymarket.api_key
        self.logger = get_logger("PolymarketWebSocket")
        
        # Market subscriptions
        self.market_subscriptions: Dict[str, Dict[str, Any]] = {}
    
    async def authenticate(self) -> bool:
        """Authenticate with Polymarket WebSocket"""
        # Polymarket may not require authentication for public market data
        # If API key is provided, use it
        if self.api_key:
            try:
                auth_message = {
                    "type": "auth",
                    "api_key": self.api_key
                }
                
                await self.send_message(auth_message)
                
                # Wait for auth response
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                response_data = json.loads(response)
                
                if response_data.get("status") == "ok" or response_data.get("type") == "auth_success":
                    self.logger.info("Polymarket authentication successful")
                    return True
                else:
                    self.logger.warning(f"Polymarket authentication response: {response_data}")
                    # Continue anyway as public data may not require auth
                    return True
                    
            except Exception as e:
                self.logger.warning(f"Authentication attempt failed, continuing without auth: {e}")
                # Polymarket public data may not require authentication
                return True
        else:
            # No API key, assume public access
            self.logger.info("No API key provided, using public Polymarket data")
            return True
    
    async def subscribe(self, channel: str, **kwargs) -> bool:
        """Subscribe to a Polymarket channel"""
        try:
            # Polymarket subscription format
            subscribe_message = {
                "type": "subscribe",
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
            await self.subscribe(f"orderbook:{market_id}")
            subscriptions.append(f"orderbook:{market_id}")
        
        if subscribe_trades:
            await self.subscribe(f"trades:{market_id}")
            subscriptions.append(f"trades:{market_id}")
        
        self.market_subscriptions[market_id] = {
            "orderbook": subscribe_orderbook,
            "trades": subscribe_trades
        }
        
        return subscriptions
    
    async def unsubscribe(self, channel: str) -> bool:
        """Unsubscribe from a channel"""
        try:
            unsubscribe_message = {
                "type": "unsubscribe",
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
        """Parse Polymarket WebSocket message"""
        try:
            data = json.loads(message)
            
            # Handle different message types
            msg_type = data.get("type", "")
            
            # Order book update
            if msg_type == "orderbook" or "orderbook" in data.get("channel", ""):
                return self._parse_orderbook(data)
            
            # Trade update
            elif msg_type == "trade" or "trades" in data.get("channel", ""):
                return self._parse_trade(data)
            
            # Market update
            elif msg_type == "market" or msg_type == "market_update":
                return self._parse_market_update(data)
            
            # L2 order book snapshot
            elif msg_type == "l2_orderbook":
                return self._parse_orderbook(data)
            
            # Status/error messages
            elif msg_type in ["status", "error", "auth_success"]:
                self.logger.debug(f"Status message: {data}")
                return None
            
            # Default: generic message
            return WebSocketEvent(
                event_type=WebSocketEventType.MESSAGE,
                data=data,
                timestamp=datetime.utcnow(),
                market_id=data.get("market_id") or data.get("market")
            )
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing message: {e}", exc_info=True)
            return None
    
    def _parse_orderbook(self, data: Dict[str, Any]) -> WebSocketEvent:
        """Parse order book update"""
        market_id = data.get("market_id") or data.get("market") or data.get("channel", "").split(":")[-1]
        
        # Extract bid/ask levels
        bids = []
        asks = []
        
        # Polymarket format may vary, handle different structures
        if "bids" in data:
            for bid in data["bids"]:
                if isinstance(bid, list) and len(bid) >= 2:
                    # Format: [price, size]
                    bids.append(OrderBookLevel(
                        price=float(bid[0]),
                        size=float(bid[1]),
                        orders=1
                    ))
                elif isinstance(bid, dict):
                    bids.append(OrderBookLevel(
                        price=float(bid.get("price", 0)),
                        size=float(bid.get("size", 0)),
                        orders=bid.get("orders", 1)
                    ))
        
        if "asks" in data:
            for ask in data["asks"]:
                if isinstance(ask, list) and len(ask) >= 2:
                    # Format: [price, size]
                    asks.append(OrderBookLevel(
                        price=float(ask[0]),
                        size=float(ask[1]),
                        orders=1
                    ))
                elif isinstance(ask, dict):
                    asks.append(OrderBookLevel(
                        price=float(ask.get("price", 0)),
                        size=float(ask.get("size", 0)),
                        orders=ask.get("orders", 1)
                    ))
        
        orderbook = OrderBook(
            market_id=market_id,
            platform=Platform.POLYMARKET,
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
        market_id = data.get("market_id") or data.get("market") or data.get("channel", "").split(":")[-1]
        
        # Polymarket trade format
        side_str = data.get("side", "").lower()
        side = OrderSide.BUY if side_str in ["buy", "b"] else OrderSide.SELL
        
        # Extract trading addresses
        metadata = {}
        if "maker" in data:
            metadata["maker"] = data["maker"]
        if "taker" in data:
            metadata["taker"] = data["taker"]
        
        # We consider the taker as the primary trader executing directionally
        trader_id = data.get("taker") or data.get("maker")
        if trader_id:
            metadata["trader_id"] = trader_id

        trade = Trade(
            trade_id=data.get("trade_id") or data.get("id", ""),
            market_id=market_id,
            platform=Platform.POLYMARKET,
            side=side,
            price=float(data.get("price", 0)),
            size=float(data.get("size", 0)),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
            fees=float(data.get("fees", 0)),
            metadata=metadata
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
            market_id=data.get("market_id") or data.get("market")
        )
