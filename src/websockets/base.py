"""Base WebSocket manager with common functionality"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Callable, List, TYPE_CHECKING
from dataclasses import dataclass
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

if TYPE_CHECKING:
    from websockets.client import WebSocketClientProtocol


class WebSocketEventType(str, Enum):
    """WebSocket event types"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    MESSAGE = "message"
    ORDERBOOK_UPDATE = "orderbook_update"
    TRADE = "trade"
    MARKET_UPDATE = "market_update"


@dataclass
class WebSocketEvent:
    """WebSocket event"""
    event_type: WebSocketEventType
    data: Dict[str, Any]
    timestamp: datetime
    market_id: Optional[str] = None


class BaseWebSocketManager(ABC):
    """Base class for WebSocket managers"""
    
    def __init__(
        self,
        url: str,
        reconnect_interval: float = 5.0,
        max_reconnect_attempts: int = 10,
        ping_interval: float = 20.0
    ):
        """Initialize WebSocket manager"""
        self.url = url
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.ping_interval = ping_interval
        
        self.websocket: Optional[Any] = None  # websockets.WebSocketClientProtocol
        self.is_connected = False
        self.is_running = False
        self.reconnect_attempts = 0
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        
        # Event callbacks
        self.event_callbacks: Dict[WebSocketEventType, List[Callable]] = {
            event_type: [] for event_type in WebSocketEventType
        }
        
        # Subscriptions
        self.subscriptions: set = set()
    
    def register_callback(
        self,
        event_type: WebSocketEventType,
        callback: Callable[[WebSocketEvent], None]
    ):
        """Register a callback for a specific event type"""
        if callback not in self.event_callbacks[event_type]:
            self.event_callbacks[event_type].append(callback)
    
    def unregister_callback(
        self,
        event_type: WebSocketEventType,
        callback: Callable[[WebSocketEvent], None]
    ):
        """Unregister a callback"""
        if callback in self.event_callbacks[event_type]:
            self.event_callbacks[event_type].remove(callback)
    
    def _emit_event(self, event: WebSocketEvent):
        """Emit an event to all registered callbacks"""
        callbacks = self.event_callbacks.get(event.event_type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                self.logger.error(f"Error in callback for {event.event_type}: {e}", exc_info=True)
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the WebSocket server. Returns True if successful."""
        pass
    
    @abstractmethod
    async def subscribe(self, channel: str, **kwargs) -> bool:
        """Subscribe to a channel. Returns True if successful."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, channel: str) -> bool:
        """Unsubscribe from a channel. Returns True if successful."""
        pass
    
    @abstractmethod
    def parse_message(self, message: str) -> Optional[WebSocketEvent]:
        """Parse incoming WebSocket message into a WebSocketEvent"""
        pass
    
    async def connect(self):
        """Connect to WebSocket server"""
        try:
            self.logger.info(f"Connecting to {self.url}")
            self.websocket = await websockets.connect(
                self.url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_interval * 2
            )
            self.is_connected = True
            self.reconnect_attempts = 0
            
            # Authenticate if needed
            auth_success = await self.authenticate()
            if not auth_success:
                self.logger.warning("Authentication failed, but connection established")
            
            # Re-subscribe to previous subscriptions
            for channel in self.subscriptions.copy():
                await self.subscribe(channel)
            
            event = WebSocketEvent(
                event_type=WebSocketEventType.CONNECTED,
                data={"url": self.url},
                timestamp=datetime.utcnow()
            )
            self._emit_event(event)
            self.logger.info("WebSocket connected successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}", exc_info=True)
            self.is_connected = False
            raise
    
    async def disconnect(self):
        """Disconnect from WebSocket server"""
        self.is_running = False
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
            finally:
                self.websocket = None
                self.is_connected = False
                
                event = WebSocketEvent(
                    event_type=WebSocketEventType.DISCONNECTED,
                    data={},
                    timestamp=datetime.utcnow()
                )
                self._emit_event(event)
                self.logger.info("WebSocket disconnected")
    
    async def send_message(self, message: Dict[str, Any]):
        """Send a message to the WebSocket server"""
        if not self.is_connected or not self.websocket:
            raise ConnectionError("WebSocket is not connected")
        
        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}", exc_info=True)
            raise
    
    async def _receive_loop(self):
        """Main receive loop"""
        while self.is_running and self.is_connected:
            try:
                if not self.websocket:
                    break
                
                message = await self.websocket.recv()
                event = self.parse_message(message)
                
                if event:
                    self._emit_event(event)
                    
            except ConnectionClosed:
                self.logger.warning("WebSocket connection closed")
                self.is_connected = False
                break
            except WebSocketException as e:
                self.logger.error(f"WebSocket error: {e}", exc_info=True)
                self.is_connected = False
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in receive loop: {e}", exc_info=True)
                error_event = WebSocketEvent(
                    event_type=WebSocketEventType.ERROR,
                    data={"error": str(e)},
                    timestamp=datetime.utcnow()
                )
                self._emit_event(error_event)
    
    async def _reconnect_loop(self):
        """Reconnection loop"""
        while self.is_running:
            if not self.is_connected:
                if self.reconnect_attempts >= self.max_reconnect_attempts:
                    self.logger.error("Max reconnect attempts reached")
                    break
                
                self.reconnect_attempts += 1
                self.logger.info(f"Attempting to reconnect ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
                
                try:
                    await self.connect()
                except Exception as e:
                    self.logger.error(f"Reconnection failed: {e}")
                    if self.is_running:
                        await asyncio.sleep(self.reconnect_interval)
            else:
                await asyncio.sleep(1)
    
    async def start(self):
        """Start the WebSocket manager"""
        self.is_running = True
        
        # Start connection
        await self.connect()
        
        # Start receive loop
        receive_task = asyncio.create_task(self._receive_loop())
        
        # Start reconnect loop
        reconnect_task = asyncio.create_task(self._reconnect_loop())
        
        try:
            await asyncio.gather(receive_task, reconnect_task)
        except asyncio.CancelledError:
            self.logger.info("WebSocket manager stopped")
        finally:
            await self.disconnect()
    
    async def stop(self):
        """Stop the WebSocket manager"""
        self.is_running = False
        await self.disconnect()
