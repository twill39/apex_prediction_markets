"""Polymarket WebSocket client"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from .base import BaseWebSocketManager, WebSocketEvent, WebSocketEventType
from src.config import get_credentials
from src.data.models import Platform, OrderBook, OrderBookLevel, Trade, OrderSide
from src.utils.logger import get_logger


class PolymarketWebSocket(BaseWebSocketManager):
    """Polymarket WebSocket client.

    Per Polymarket docs:
    - Market channel (/ws/market): no authentication; public orderbook/trades.
    - User channel (/ws/user): requires auth object { apiKey, secret, passphrase } in subscribe.
    """

    # Market channel: public data, no auth. User channel would be /ws/user.
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self):
        """Initialize Polymarket WebSocket client"""
        credentials = get_credentials()
        if not credentials.polymarket:
            raise ValueError("Polymarket credentials not configured")

        super().__init__(url=self.WS_URL)
        self.api_key = getattr(credentials.polymarket, "api_key", None)
        self.secret = getattr(credentials.polymarket, "secret", None)
        self.passphrase = getattr(credentials.polymarket, "passphrase", None)
        self.logger = get_logger("PolymarketWebSocket")

        # Market subscriptions
        self.market_subscriptions: Dict[str, Dict[str, Any]] = {}

    def _is_market_channel(self) -> bool:
        """True if connected to the public market channel (no auth)."""
        return "/ws/market" in self.url

    async def authenticate(self) -> bool:
        """Authenticate per Polymarket model.
        Market channel: no auth (server does not expect or support it).
        User channel: auth is sent inside the subscribe message, not here.
        """
        if self._is_market_channel():
            # Market channel has no authentication (per Polymarket docs).
            self.logger.debug("Polymarket market channel: no authentication required")
            return True
        # User channel: auth is done via auth object in subscribe(), not a separate message.
        self.logger.debug("Polymarket user channel: auth is sent with subscription")
        return True
    
    async def subscribe(self, channel: str, **kwargs) -> bool:
        """Subscribe to a Polymarket channel.
        User channel requires auth object: { apiKey, secret, passphrase } in the message.
        """
        try:
            subscribe_message = {"type": "subscribe", "channel": channel, **kwargs}
            if not self._is_market_channel() and self.api_key and self.secret and self.passphrase:
                subscribe_message["auth"] = {
                    "apiKey": self.api_key,
                    "secret": self.secret,
                    "passphrase": self.passphrase,
                }
            await self.send_message(subscribe_message)
            self.subscriptions.add(channel)
            self.logger.info(f"Subscribed to channel: {channel}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to subscribe to {channel}: {e}", exc_info=True)
            return False
    
    async def subscribe_assets(self, assets_ids: List[str], custom_feature_enabled: bool = True) -> bool:
        """Subscribe to market channel for the given asset IDs (Polymarket market-channel format)."""
        if not assets_ids:
            return True
        try:
            msg = {
                "assets_ids": assets_ids,
                "type": "market",
                "custom_feature_enabled": custom_feature_enabled,
            }
            await self.send_message(msg)
            for aid in assets_ids:
                self.market_subscriptions[aid] = {"orderbook": True, "trades": True}
            self.logger.info(f"Subscribed to {len(assets_ids)} Polymarket assets")
            return True
        except Exception as e:
            self.logger.error(f"Failed to subscribe to Polymarket assets: {e}", exc_info=True)
            return False

    async def subscribe_market(self, market_id: str, subscribe_orderbook: bool = True, subscribe_trades: bool = True):
        """Subscribe to a single market (convenience; for multiple use subscribe_assets)."""
        return await self.subscribe_assets([market_id])
    
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
