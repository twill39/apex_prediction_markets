#!/usr/bin/env python3
"""Script to collect historical market data"""

import asyncio
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.utils.logger import setup_logger


class HistoricalDataCollector:
    """Collect historical market data"""
    
    def __init__(self, output_path: str):
        """Initialize collector"""
        self.output_path = output_path
        self.events: List[Dict[str, Any]] = []
        self.logger = setup_logger("HistoricalCollector")
    
    async def collect_kalshi(self, market_ids: List[str], duration_seconds: int = 60):
        """Collect data from Kalshi"""
        self.logger.info(f"Collecting Kalshi data for {len(market_ids)} markets")
        
        ws = KalshiWebSocket()
        
        # Register callback
        def on_event(event: WebSocketEvent):
            if event.event_type in [WebSocketEventType.ORDERBOOK_UPDATE, WebSocketEventType.TRADE]:
                self.events.append({
                    "type": event.event_type.value,
                    "market_id": event.market_id,
                    "platform": "kalshi",
                    "timestamp": event.timestamp.isoformat(),
                    "data": event.data
                })
        
        ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, on_event)
        ws.register_callback(WebSocketEventType.TRADE, on_event)
        
        # Start WebSocket
        asyncio.create_task(ws.start())
        await asyncio.sleep(2)  # Wait for connection
        
        # Subscribe to markets
        for market_id in market_ids:
            await ws.subscribe_market(market_id)
        
        # Collect for specified duration
        await asyncio.sleep(duration_seconds)
        
        # Stop
        await ws.stop()
        
        self.logger.info(f"Collected {len(self.events)} events from Kalshi")
    
    async def collect_polymarket(self, market_ids: List[str], duration_seconds: int = 60):
        """Collect data from Polymarket"""
        self.logger.info(f"Collecting Polymarket data for {len(market_ids)} markets")
        
        ws = PolymarketWebSocket()
        
        # Register callback
        def on_event(event: WebSocketEvent):
            if event.event_type in [WebSocketEventType.ORDERBOOK_UPDATE, WebSocketEventType.TRADE]:
                self.events.append({
                    "type": event.event_type.value,
                    "market_id": event.market_id,
                    "platform": "polymarket",
                    "timestamp": event.timestamp.isoformat(),
                    "data": event.data
                })
        
        ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, on_event)
        ws.register_callback(WebSocketEventType.TRADE, on_event)
        
        # Start WebSocket
        asyncio.create_task(ws.start())
        await asyncio.sleep(2)  # Wait for connection
        
        # Subscribe to markets
        for market_id in market_ids:
            await ws.subscribe_market(market_id)
        
        # Collect for specified duration
        await asyncio.sleep(duration_seconds)
        
        # Stop
        await ws.stop()
        
        self.logger.info(f"Collected {len(self.events)} events from Polymarket")
    
    def save(self):
        """Save collected data"""
        output = {
            "collected_at": datetime.utcnow().isoformat(),
            "total_events": len(self.events),
            "events": self.events
        }
        
        with open(self.output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        self.logger.info(f"Saved {len(self.events)} events to {self.output_path}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Collect historical market data")
    parser.add_argument("--platform", choices=["kalshi", "polymarket"], required=True)
    parser.add_argument("--markets", nargs="+", required=True, help="Market IDs to collect")
    parser.add_argument("--duration", type=int, default=60, help="Collection duration in seconds")
    parser.add_argument("--output", required=True, help="Output file path")
    
    args = parser.parse_args()
    
    collector = HistoricalDataCollector(args.output)
    
    if args.platform == "kalshi":
        await collector.collect_kalshi(args.markets, args.duration)
    else:
        await collector.collect_polymarket(args.markets, args.duration)
    
    collector.save()


if __name__ == "__main__":
    asyncio.run(main())
