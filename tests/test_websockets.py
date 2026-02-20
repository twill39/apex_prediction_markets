"""Tests for WebSocket clients"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.websockets.base import BaseWebSocketManager, WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket


@pytest.mark.asyncio
async def test_base_websocket_manager():
    """Test base WebSocket manager"""
    # This would require mocking websockets library
    pass


@pytest.mark.asyncio
async def test_kalshi_websocket_parse_message():
    """Test Kalshi message parsing"""
    ws = KalshiWebSocket()
    
    # Test orderbook message
    orderbook_msg = '{"type": "orderbook", "market_id": "test", "bids": [{"price": 0.5, "size": 100}], "asks": [{"price": 0.51, "size": 100}]}'
    event = ws.parse_message(orderbook_msg)
    
    assert event is not None
    assert event.event_type == WebSocketEventType.ORDERBOOK_UPDATE
    assert event.market_id == "test"


@pytest.mark.asyncio
async def test_polymarket_websocket_parse_message():
    """Test Polymarket message parsing"""
    ws = PolymarketWebSocket()
    
    # Test orderbook message
    orderbook_msg = '{"type": "orderbook", "market": "test", "bids": [[0.5, 100]], "asks": [[0.51, 100]]}'
    event = ws.parse_message(orderbook_msg)
    
    assert event is not None
    assert event.event_type == WebSocketEventType.ORDERBOOK_UPDATE
