"""Alt Data Trading Strategy - Use alternative data sources"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from .base import BaseStrategy, StrategySignal, StrategyState
from src.data.models import Platform, Trade, OrderBook, Market
from src.data.collectors import DataCollector, TwitterCollector
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.config import get_settings
from src.utils.logger import get_logger


class AltDataStrategy(BaseStrategy):
    """Strategy that uses alternative data sources for trading signals"""
    
    def __init__(self):
        """Initialize alt data strategy"""
        super().__init__(
            strategy_id="alt_data",
            name="Alt Data Trading Strategy"
        )
        self.settings = get_settings()
        self.logger = get_logger("AltDataStrategy")
        self.storage = get_storage()
        
        # Data collectors
        self.collectors: Dict[str, DataCollector] = {}
        
        # Fair value models
        self.models: Dict[str, Any] = {}  # market_id -> model
        
        # Market data
        self.market_data: Dict[str, Dict[str, Any]] = {}  # market_id -> data
        
        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
    
    async def initialize(self):
        """Initialize the strategy"""
        self.logger.info("Initializing alt data strategy")
        
        # Initialize data collectors
        await self._initialize_collectors()
        
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
        
        self.logger.info("Alt data strategy initialized")
    
    async def _initialize_collectors(self):
        """Initialize data collectors"""
        # Twitter collector
        if self.settings.alt_data.twitter_bearer_token:
            try:
                twitter_collector = TwitterCollector(
                    bearer_token=self.settings.alt_data.twitter_bearer_token
                )
                self.collectors["twitter"] = twitter_collector
                self.logger.info("Twitter collector initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Twitter collector: {e}")
        
        # Add other collectors as needed (satellite imagery, etc.)
    
    async def _collect_alt_data(self, market_id: str, keywords: List[str]) -> Dict[str, Any]:
        """Collect alternative data for a market"""
        alt_data = {}
        
        # Collect from all available collectors
        for name, collector in self.collectors.items():
            try:
                data = await collector.collect(keywords)
                alt_data[name] = data
            except Exception as e:
                self.logger.error(f"Error collecting data from {name}: {e}")
        
        return alt_data
    
    def _build_fair_value_model(self, market_id: str, alt_data: Dict[str, Any], historical_prices: List[float]) -> Optional[Any]:
        """Build a fair value model using alt data"""
        # Extract features from alt data
        features = []
        
        # Twitter sentiment
        if "twitter" in alt_data:
            twitter_data = alt_data["twitter"]
            features.extend([
                twitter_data.get("sentiment_score", 0.0),
                twitter_data.get("mention_count", 0),
                twitter_data.get("engagement_score", 0.0)
            ])
        
        # Add more features from other data sources
        
        if not features:
            return None
        
        # Simple linear model (can be extended to more sophisticated models)
        X = np.array(features).reshape(1, -1)
        
        # For now, return a simple model structure
        # In production, this would train on historical data
        model = {
            "features": features,
            "weights": np.random.randn(len(features)),  # Placeholder
            "bias": 0.0,
            "trained_at": datetime.utcnow()
        }
        
        return model
    
    def _predict_fair_value(self, market_id: str, alt_data: Dict[str, Any]) -> Optional[float]:
        """Predict fair value using alt data model"""
        model = self.models.get(market_id)
        if not model:
            return None
        
        # Extract features
        features = []
        if "twitter" in alt_data:
            twitter_data = alt_data["twitter"]
            features.extend([
                twitter_data.get("sentiment_score", 0.0),
                twitter_data.get("mention_count", 0),
                twitter_data.get("engagement_score", 0.0)
            ])
        
        if len(features) != len(model["weights"]):
            return None
        
        # Simple linear prediction
        prediction = np.dot(features, model["weights"]) + model["bias"]
        
        # Normalize to 0-1 range (probability)
        prediction = max(0.0, min(1.0, prediction))
        
        return prediction
    
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
            # Extract keywords from market title/description
            title = data.get("title", "")
            keywords = self._extract_keywords(title)
            
            # Collect alt data
            alt_data = await self._collect_alt_data(market_id, keywords)
            
            # Build or update model
            if market_id not in self.models:
                # Build initial model
                model = self._build_fair_value_model(market_id, alt_data, [])
                if model:
                    self.models[market_id] = model
            
            # Store alt data
            if market_id not in self.market_data:
                self.market_data[market_id] = {}
            self.market_data[market_id]["alt_data"] = alt_data
            self.market_data[market_id]["last_updated"] = datetime.utcnow()
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text"""
        # Simple keyword extraction (can be improved with NLP)
        words = text.lower().split()
        # Remove common words
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return keywords[:10]  # Top 10 keywords
    
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update"""
        market_id = orderbook.market_id
        
        # Get current market price
        mid_price = orderbook.get_mid_price()
        if not mid_price:
            return
        
        # Get alt data
        alt_data = self.market_data.get(market_id, {}).get("alt_data", {})
        if not alt_data:
            return
        
        # Predict fair value
        predicted_fair_value = self._predict_fair_value(market_id, alt_data)
        if not predicted_fair_value:
            return
        
        # Store prediction
        if market_id not in self.market_data:
            self.market_data[market_id] = {}
        self.market_data[market_id]["predicted_fair_value"] = predicted_fair_value
        self.market_data[market_id]["current_price"] = mid_price
        self.market_data[market_id]["orderbook"] = orderbook
    
    async def on_trade(self, trade: Trade):
        """Handle trade event"""
        # Update models with actual outcomes
        pass
    
    async def generate_signals(self) -> List[StrategySignal]:
        """Generate trading signals based on alt data"""
        if self.state != StrategyState.RUNNING:
            return []
        
        signals = []
        confidence_threshold = self.settings.alt_data.confidence_threshold
        
        for market_id, data in self.market_data.items():
            predicted_fv = data.get("predicted_fair_value")
            current_price = data.get("current_price")
            orderbook = data.get("orderbook")
            
            if not predicted_fv or not current_price or not orderbook:
                continue
            
            # Calculate deviation from fair value
            deviation = abs(predicted_fv - current_price)
            confidence = min(deviation * 2, 1.0)  # Higher deviation = higher confidence
            
            if confidence < confidence_threshold:
                continue
            
            platform = orderbook.platform
            
            # Generate signal if price deviates significantly from fair value
            if current_price < predicted_fv * 0.95:  # Price is 5% below fair value
                # Buy signal
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="buy",
                    size=100.0,  # Fixed size for now
                    order_type="limit",
                    price=current_price * 1.01,  # Slightly above current
                    confidence=confidence,
                    reason=f"Price {current_price:.4f} below predicted fair value {predicted_fv:.4f}",
                    timestamp=datetime.utcnow()
                ))
            
            elif current_price > predicted_fv * 1.05:  # Price is 5% above fair value
                # Sell signal
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="sell",
                    size=100.0,  # Fixed size for now
                    order_type="limit",
                    price=current_price * 0.99,  # Slightly below current
                    confidence=confidence,
                    reason=f"Price {current_price:.4f} above predicted fair value {predicted_fv:.4f}",
                    timestamp=datetime.utcnow()
                ))
        
        return signals
