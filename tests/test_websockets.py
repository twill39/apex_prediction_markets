"""Tests for WebSocket clients"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.websockets.base import BaseWebSocketManager, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket


@pytest.mark.asyncio
async def test_base_websocket_manager():
    """A dropped receive loop must be recreated after reconnect."""

    class ReconnectingManager(BaseWebSocketManager):
        def __init__(self):
            super().__init__("wss://example.invalid", reconnect_interval=0.001)
            self.connect_count = 0
            self.receive_count = 0

        async def connect(self):
            self.connect_count += 1
            self.is_connected = True
            self.reconnect_attempts = 0

        async def authenticate(self):
            return True

        async def subscribe(self, channel: str, **kwargs):
            return True

        async def unsubscribe(self, channel: str):
            return True

        def parse_message(self, message: str):
            return None

        async def _receive_loop(self):
            self.receive_count += 1
            self.is_connected = False
            if self.receive_count >= 2:
                self.is_running = False
            await asyncio.sleep(0)

    ws = ReconnectingManager()
    await asyncio.wait_for(ws.start(), timeout=1.0)

    assert ws.connect_count == 2
    assert ws.receive_count == 2


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
async def test_kalshi_subscribes_on_unified_yes_price_scale():
    ws = KalshiWebSocket()
    ws.send_message = AsyncMock()

    assert await ws.subscribe_orderbook_delta(["KXTEST"])

    message = ws.send_message.await_args.args[0]
    assert message["params"]["use_yes_price"] is True


def test_kalshi_snapshot_and_delta_use_yes_price_scale_and_sequence():
    ws = KalshiWebSocket()
    snapshot = {
        "type": "orderbook_snapshot",
        "sid": 1,
        "seq": 10,
        "msg": {
            "market_ticker": "KXTEST",
            "yes_dollars_fp": [["0.42", "12.00"]],
            # use_yes_price=true means this is already the implied YES ask.
            "no_dollars_fp": [["0.58", "9.00"]],
            "ts_ms": 1_700_000_000_000,
        },
    }

    event = ws.parse_message(json.dumps(snapshot))
    orderbook = event.data["orderbook"]
    assert orderbook["bids"][0]["price"] == pytest.approx(0.42)
    assert orderbook["asks"][0]["price"] == pytest.approx(0.58)
    assert orderbook["timestamp"] == datetime.fromtimestamp(
        1_700_000_000, tz=timezone.utc
    )

    delta = {
        "type": "orderbook_delta",
        "sid": 1,
        "seq": 11,
        "msg": {
            "market_ticker": "KXTEST",
            "side": "no",
            "price_dollars": "0.57",
            "delta_fp": "4.00",
            "ts_ms": 1_700_000_001_000,
        },
    }
    event = ws.parse_message(json.dumps(delta))
    asks = {level["price"]: level["size"] for level in event.data["orderbook"]["asks"]}
    assert asks == {0.57: 4.0, 0.58: 9.0}


def test_kalshi_rejects_sequence_gap_until_new_snapshot():
    ws = KalshiWebSocket()
    errors = []
    ws.register_callback(WebSocketEventType.ERROR, errors.append)
    snapshot = {
        "type": "orderbook_snapshot",
        "seq": 3,
        "msg": {
            "market_ticker": "KXTEST",
            "yes_dollars_fp": [["0.40", "2.00"]],
            "no_dollars_fp": [["0.60", "2.00"]],
        },
    }
    assert ws.parse_message(json.dumps(snapshot)) is not None

    gap = {
        "type": "orderbook_delta",
        "seq": 5,
        "msg": {
            "market_ticker": "KXTEST",
            "side": "yes",
            "price_dollars": "0.41",
            "delta_fp": "1.00",
        },
    }
    assert ws.parse_message(json.dumps(gap)) is None
    assert ws._orderbook_state["KXTEST"] == {"bids": {}, "asks": {}}
    assert errors[0].data["reason"] == "orderbook_sequence_gap"


def test_kalshi_trade_parses_current_msg_envelope():
    ws = KalshiWebSocket()
    payload = {
        "type": "trade",
        "sid": 11,
        "msg": {
            "trade_id": "trade-1",
            "market_ticker": "KXTEST",
            "yes_price_dollars": "0.360",
            "no_price_dollars": "0.640",
            "count_fp": "136.00",
            "taker_side": "no",
            "ts_ms": 1_669_149_841_000,
        },
    }

    event = ws.parse_message(json.dumps(payload))
    trade = event.data["trade"]
    assert event.market_id == "KXTEST"
    assert trade["trade_id"] == "trade-1"
    assert trade["price"] == pytest.approx(0.36)
    assert trade["size"] == pytest.approx(136.0)
    assert trade["side"] == "sell"
    assert trade["timestamp"] == datetime.fromtimestamp(
        1_669_149_841, tz=timezone.utc
    )


@pytest.mark.asyncio
async def test_polymarket_websocket_parse_message():
    """Test Polymarket message parsing"""
    ws = PolymarketWebSocket()
    
    # Test orderbook message
    orderbook_msg = '{"type": "orderbook", "market": "test", "bids": [[0.5, 100]], "asks": [[0.51, 100]]}'
    event = ws.parse_message(orderbook_msg)
    
    assert event is not None
    assert event.event_type == WebSocketEventType.ORDERBOOK_UPDATE
