"""Market Making Strategy - Provide liquidity on niche markets"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np

from .base import BaseStrategy, StrategySignal, StrategyState
from src.data.models import (
    Platform, Trade, OrderBook, OrderSide, OrderType, Market
)
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.config import get_credentials, get_settings
from src.discovery import discover_markets_for_making
from src.utils.logger import get_logger


class MarketMakingStrategy(BaseStrategy):
    """Strategy that provides liquidity on niche markets"""
    
    def __init__(self):
        """Initialize market making strategy"""
        super().__init__(
            strategy_id="market_making",
            name="Market Making Strategy"
        )
        self.settings = get_settings()
        self.logger = get_logger("MarketMakingStrategy")
        self.storage = get_storage()
        
        # Active market making markets
        self.active_markets: Dict[str, Dict[str, any]] = {}  # market_id -> market data
        
        # Order book snapshots
        self.orderbooks: Dict[str, OrderBook] = {}  # market_id -> orderbook
        
        # Fair value estimates
        self.fair_values: Dict[str, float] = {}  # market_id -> fair_value

        # Discovered markets (from discovery API)
        self.discovered_market_ids: List[str] = []

        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
    
    async def initialize(self):
        """Initialize the strategy"""
        self.logger.info("Initializing market making strategy")
        
        # Initialize WebSocket clients
        try:
            self.kalshi_ws = KalshiWebSocket()
            self.polymarket_ws = PolymarketWebSocket()
            
            # Register callbacks
            self.kalshi_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
            self.kalshi_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
            self.polymarket_ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, self._on_websocket_event)
            self.polymarket_ws.register_callback(WebSocketEventType.MARKET_UPDATE, self._on_websocket_event)
            
        except Exception as e:
            self.logger.error(f"Failed to initialize WebSocket clients: {e}", exc_info=True)
            self.state = StrategyState.ERROR
            return
        
        # Identify markets to market make on
        await self._identify_markets()
        
        self.logger.info(f"Initialized with {len(self.active_markets)} active markets")
    
    async def _identify_markets(self):
        """Discover markets with high spread and decent liquidity for market making."""
        mm = self.settings.market_making
        kalshi_base = DEFAULT_KALSHI_BASE
        try:
            creds = get_credentials()
            if creds and creds.kalshi:
                kalshi_base = creds.kalshi.base_url
        except Exception:
            pass
        try:
            discovered = discover_markets_for_making(
                min_liquidity_poly=mm.discovery_min_liquidity,
                min_spread_pct=mm.discovery_min_spread_pct,
                min_volume_24h_kalshi=mm.discovery_min_volume_24h_kalshi,
                max_poly=mm.discovery_max_markets,
                max_kalshi=mm.discovery_max_markets,
                kalshi_base_url=kalshi_base,
            )
            self.discovered_market_ids = [m["market_id"] for m in discovered]
            if self.discovered_market_ids:
                self.logger.info(f"Discovered {len(self.discovered_market_ids)} markets for market making")
            else:
                self.logger.info("No markets met discovery criteria; will use markets from order book stream")
        except Exception as e:
            self.logger.warning(f"Market discovery failed: {e}; will use order book stream")

    def get_discovered_market_ids(self) -> List[str]:
        """Return market IDs discovered for market making (for simulator subscription)."""
        return list(self.discovered_market_ids)
    
    def _calculate_fair_value(self, market_id: str, orderbook: OrderBook) -> Optional[float]:
        """Calculate fair value for a market"""
        if not orderbook.bids or not orderbook.asks:
            return None
        
        # Simple mid-price as fair value
        best_bid = max(level.price for level in orderbook.bids)
        best_ask = min(level.price for level in orderbook.asks)
        
        if best_bid >= best_ask:
            return None
        
        # Weighted mid-price (by size)
        bid_size = sum(level.size for level in orderbook.bids if level.price == best_bid)
        ask_size = sum(level.size for level in orderbook.asks if level.price == best_ask)
        total_size = bid_size + ask_size
        
        if total_size == 0:
            return (best_bid + best_ask) / 2.0
        
        # Size-weighted mid
        fair_value = (best_bid * ask_size + best_ask * bid_size) / total_size
        return fair_value
    
    def _is_market_suitable(self, market_id: str, orderbook: OrderBook) -> bool:
        """Check if market is suitable for market making"""
        # Check spread
        spread = orderbook.get_spread()
        if spread is None:
            return False
        
        mid_price = orderbook.get_mid_price()
        if mid_price is None or mid_price == 0:
            return False
        
        spread_pct = spread / mid_price
        
        # Check if spread is within acceptable range
        if spread_pct > self.settings.market_making.max_spread:
            return False
        
        # Check volume (would need historical data)
        # For now, we'll accept any market with acceptable spread
        
        return True
    
    async def _on_websocket_event(self, event: WebSocketEvent):
        """Handle WebSocket events"""
        if self.state != StrategyState.RUNNING:
            return
        
        await self.on_market_event(event)
    
    async def on_market_event(self, event: WebSocketEvent):
        """Handle market event"""
        if event.event_type == WebSocketEventType.ORDERBOOK_UPDATE:
            orderbook_data = event.data.get("orderbook")
            if orderbook_data:
                orderbook = OrderBook(**orderbook_data)
                await self.on_orderbook_update(orderbook)
        
        elif event.event_type == WebSocketEventType.MARKET_UPDATE:
            await self._process_market_update(event.data)
    
    async def _process_market_update(self, data: Dict):
        """Process market update"""
        market_id = data.get("market_id")
        if market_id:
            # Update market information
            if market_id not in self.active_markets:
                # Check if we should start market making
                pass
    
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update"""
        market_id = orderbook.market_id
        
        # Store order book
        self.orderbooks[market_id] = orderbook
        
        # Calculate fair value
        fair_value = self._calculate_fair_value(market_id, orderbook)
        if fair_value:
            self.fair_values[market_id] = fair_value
        
        # Check if market is suitable
        if market_id not in self.active_markets:
            if self._is_market_suitable(market_id, orderbook):
                self.active_markets[market_id] = {
                    "platform": orderbook.platform,
                    "started_at": datetime.utcnow()
                }
                self.logger.info(f"Started market making on {market_id}")
        
        # Update quotes if market is active
        if market_id in self.active_markets:
            await self._update_quotes(market_id, orderbook)
    
    async def _update_quotes(self, market_id: str, orderbook: OrderBook):
        """Update market making quotes"""
        # This would place/cancel orders to maintain quotes
        # For now, we'll generate signals for quote updates
        
        fair_value = self.fair_values.get(market_id)
        if not fair_value:
            return
        
        # Calculate quote prices (fair value ± small spread)
        quote_spread = 0.01  # 1% spread
        bid_price = fair_value * (1 - quote_spread / 2)
        ask_price = fair_value * (1 + quote_spread / 2)
        
        # Store quote information
        if market_id not in self.active_markets:
            self.active_markets[market_id] = {}
        
        self.active_markets[market_id]["bid_price"] = bid_price
        self.active_markets[market_id]["ask_price"] = ask_price
        self.active_markets[market_id]["fair_value"] = fair_value
    
    async def on_trade(self, trade: Trade):
        """Handle trade event"""
        # Update fair value based on recent trades
        pass
    
    async def generate_signals(self) -> List[StrategySignal]:
        """Generate trading signals for market making"""
        if self.state != StrategyState.RUNNING:
            return []
        
        signals = []
        
        # Generate signals to maintain quotes on active markets
        for market_id, market_data in self.active_markets.items():
            orderbook = self.orderbooks.get(market_id)
            if not orderbook:
                continue
            
            fair_value = self.fair_values.get(market_id)
            if not fair_value:
                continue
            
            platform = market_data.get("platform", orderbook.platform)
            bid_price = market_data.get("bid_price")
            ask_price = market_data.get("ask_price")
            
            if not bid_price or not ask_price:
                continue
            
            # Check current best bid/ask
            best_bid = orderbook.get_best_bid()
            best_ask = orderbook.get_best_ask()
            
            # Place bid if our bid is better or missing
            if best_bid is None or bid_price > best_bid:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="buy",
                    size=self.settings.market_making.max_position / 10,  # Small size
                    price=bid_price,
                    order_type="limit",
                    confidence=0.8,
                    reason=f"Market making bid at {bid_price:.4f}",
                    timestamp=datetime.utcnow()
                ))
            
            # Place ask if our ask is better or missing
            if best_ask is None or ask_price < best_ask:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="sell",
                    size=self.settings.market_making.max_position / 10,  # Small size
                    price=ask_price,
                    order_type="limit",
                    confidence=0.8,
                    reason=f"Market making ask at {ask_price:.4f}",
                    timestamp=datetime.utcnow()
                ))
        
        return signals
