"""Market Making Strategy - Provide liquidity on niche markets"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from scipy.stats import cauchy

from .base import BaseStrategy, StrategySignal, StrategyState
from src.data.models import (
    Platform, Trade, OrderBook, OrderSide, OrderType, Market, PriceObservation, PriceHistory, UnderlyingPriceState
)
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.polymarket import PolymarketWebSocket
from src.config import get_credentials, get_settings
from src.discovery import discover_markets_for_making
from src.discovery.market_discovery import DEFAULT_KALSHI_BASE
from src.utils.logger import get_logger

# Regime stress ρ (reversal-bucket score). False = unwired: ρ=0 always (no gamma/size stress
# from local reversal frequency). Set True to restore previous behavior.
MM_AS_REGIME_SCORE_ENABLED = True

# Extra inventory discipline (skew, hard gate, EOD flatten, regime/inventory-sized lots).
# False = base A-S only: reservation price + optimal spread in `quotes()`, fixed small sizes.
MM_AS_INVENTORY_OVERLAYS_ENABLED = False

# When overlays are off: quote at most this many contracts per side each update (if room permits).
MM_AS_BASE_QUOTE_SIZE = 4.0


class MarketMakingStrategy(BaseStrategy):
    """Strategy that provides liquidity on niche markets"""
    
    def __init__(self):
        """Initialize market making strategy"""
        super().__init__(
            strategy_id="market_making_as",
            name="Market Making Strategy - Avellaneda & Stoikov"
        )
        self.settings = get_settings()
        self.logger = get_logger("MarketMakingAsStrategy")
        self.storage = get_storage()
        self.mm_as_settings = getattr(self.settings, "market_making_as", self.settings.market_making)

        # ADDED FIELDS
        self.current_quotes: Dict[str, Dict[str, float]] = {}  # market_id -> {bid, ask}
        self.last_quote_update: Dict[str, datetime] = {}  # market_id -> last update time
        self.quote_update_interval = timedelta(
            seconds=max(self.mm_as_settings.quote_update_interval_seconds, 0.0)
        )
        self.quote_reprice_threshold = self.mm_as_settings.quote_reprice_threshold
        
        # Active market making markets
        self.active_markets: Dict[str, Dict[str, any]] = {}  # market_id -> market data

        #Price history for rolling vol estimation (per market)
        self.price_histories: Dict[str, PriceHistory] = {}

        # Signed inventory per market for A-S reservation price.
        self.inventory: Dict[str, float] = {}
        
        # Order book snapshots
        self.orderbooks: Dict[str, OrderBook] = {}  # market_id -> orderbook
        
        # Fair value estimates
        self.fair_values: Dict[str, float] = {}  # market_id -> fair_value
        self.model_fair_values: Dict[str, float] = {}  # market_id -> model-based fair value
        self.underlying_state = UnderlyingPriceState(symbol="$SPX")

        # Discovered markets (from discovery API)
        self.discovered_market_ids: List[str] = []
        self.historical_market_metadata: Dict[str, Dict[str, float]] = {}

        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None

        # Quote sizing controls for regime/inventory-aware sizing.
        self.base_size_fraction = self.mm_as_settings.base_size_fraction
        self.regime_size_beta = self.mm_as_settings.regime_size_beta
        self.inventory_size_eta = self.mm_as_settings.inventory_size_eta
        self.min_size_fraction = self.mm_as_settings.min_size_fraction
        self.cauchy_x0 = self.mm_as_settings.cauchy_x0
        self.cauchy_gamma_base = self.mm_as_settings.cauchy_gamma_base
    

    # AVELLANEDA AND STOIKOV SPECIFIC CALCULATIONS

    # ── estimators ────────────────────────────────────────────────────────────────

    @staticmethod
    def rolling_realized_vol(price_history: PriceHistory) -> Optional[float]:
        """
        Compute realized volatility from a rolling window of mid prices.
        """
        
        prices = price_history.get_prices()
        
        if prices is None or len(prices) < 2:
            return None
        
        log_returns = np.log(prices[1:] / prices[:-1])
        
        return float(np.std(log_returns))


    @staticmethod
    def regime_score(
        prices: np.ndarray,
        historical_reversals: pd.DataFrame,
        n_buckets: int = 10
    ) -> float:
        if not MM_AS_REGIME_SCORE_ENABLED:
            return 0.0
        if prices is None:
            return 0.0
        prices_arr = np.asarray(prices, dtype=float)
        if prices_arr.size == 0:
            return 0.0

        current_price = float(prices_arr[-1])
        if not np.isfinite(current_price):
            return 0.0

        if historical_reversals is None or historical_reversals.empty:
            return 0.0

        if n_buckets < 2:
            n_buckets = 2

        df = historical_reversals.copy()

        price_col = next(
            (
                col
                for col in ("price", "mid_price", "level_price", "reversal_price")
                if col in df.columns
            ),
            None,
        )
        if price_col is None:
            return 0.0

        reversal_col = next(
            (
                col
                for col in ("is_reversal", "reversal", "reversed", "label")
                if col in df.columns
            ),
            None,
        )
        if reversal_col is None:
            # If the dataframe itself is a reversal event table, treat all rows as
            # positive reversal events.
            df["is_reversal"] = 1.0
            reversal_col = "is_reversal"

        px = pd.to_numeric(df[price_col], errors="coerce")
        rv = pd.to_numeric(df[reversal_col], errors="coerce")
        valid = px.notna() & rv.notna()
        if valid.sum() < 2:
            return 0.0

        work = pd.DataFrame(
            {"price": px[valid].astype(float), "is_reversal": (rv[valid] > 0).astype(float)}
        )

        # If historical prices are degenerate (all same), no bucket-specific signal exists.
        p_min = float(work["price"].min())
        p_max = float(work["price"].max())
        if not np.isfinite(p_min) or not np.isfinite(p_max) or p_min == p_max:
            return 0.0

        edges = np.linspace(p_min, p_max, n_buckets + 1)
        bucket_idx = np.searchsorted(edges, work["price"].to_numpy(), side="right") - 1
        bucket_idx = np.clip(bucket_idx, 0, n_buckets - 1)
        work["bucket"] = bucket_idx

        grouped = work.groupby("bucket")["is_reversal"].mean()
        if grouped.empty:
            return 0.0

        global_rate = float(work["is_reversal"].mean())
        if global_rate <= 0.0:
            return 0.0

        current_bucket = int(np.clip(np.searchsorted(edges, current_price, side="right") - 1, 0, n_buckets - 1))
        local_rate = float(grouped.get(current_bucket, global_rate))

        # Normalize local reversal intensity versus the highest observed bucket.
        max_rate = float(grouped.max())
        if max_rate <= 0.0:
            return 0.0

        rho = local_rate / max_rate
        return float(np.clip(rho, 0.0, 1.0))


    @staticmethod
    def adaptive_gamma(
        gamma_base: float,
        rho: float,
        gamma_max: float
    ) -> float:
        gamma_stress = 0.3

        alpha = (gamma_stress / gamma_base) - 1 
        gamma_t = min(gamma_max, gamma_base * (1 + alpha * rho))


        return gamma_t


    # ── core a-s formulas ─────────────────────────────────────────────────────────

    @staticmethod
    def reservation_price(
        s: float,
        q: float,
        gamma: float,
        sigma: float,
        T: float,
        t: float
    ) -> float:
        
        tau = max(T - t, 0.0)
        r = s - q * gamma * (sigma ** 2) * tau

        return r



    @staticmethod
    def optimal_quotes(
        gamma: float,
        sigma: float,
        T: float,
        t: float,
        kappa: float,
        rho: float,
        r: float,
    ) -> float:
        tau = max(T - t, 0.0)
        
        delta = gamma * sigma**2 * (tau) + (2 / gamma) * np.log(1 + gamma / kappa)

        return delta



    # ── quote assembly ────────────────────────────────────────────────────────────

    @staticmethod
    def quotes(
        s: float,
        q: float,
        sigma: float,
        gamma_base: float,
        alpha: float,
        T: float,
        t: float,
        kappa: float,
        rho: float
    ) -> Tuple[float, float]:
    
        if gamma_base <= 0:
            raise ValueError("gamma_base must be positive")
        if kappa <= 0:
            raise ValueError("kappa must be positive")

        gamma = MarketMakingStrategy.adaptive_gamma(
            gamma_base=gamma_base,
            rho=float(np.clip(rho, 0.0, 1.0)),
            gamma_max=max(gamma_base, gamma_base * (1.0 + abs(alpha))),
        )
        r = MarketMakingStrategy.reservation_price(
            s=s,
            q=q,
            gamma=gamma,
            sigma=max(sigma, 0.0),
            T=T,
            t=t,
        )
        spread = MarketMakingStrategy.optimal_quotes(
            gamma=gamma,
            sigma=max(sigma, 0.0),
            T=T,
            t=t,
            kappa=kappa,
            rho=rho,
            r=r,
        )

        # A-S spread can be very wide for bounded binary prices; cap half-spread so
        # reservation-price inventory skew remains observable after clipping.
        half_spread = min(max(spread / 2.0, 0.0), 0.49)
        bid = max(0.0, r - half_spread)
        ask = min(1.0, r + half_spread)

        # Ensure non-crossed output after clipping.
        if ask < bid:
            midpoint = float(np.clip(r, 0.0, 1.0))
            return midpoint, midpoint
        return float(bid), float(ask)


    async def initialize(self):
        """Initialize the strategy"""
        self.logger.info("Initializing market making strategy")

        # If using historical data, skip the websockets
        if getattr(self, "mode", None) == "historical":
            self._bootstrap_historical_market_metadata()
            self.logger.info("Historical mode — skipping WebSocket init and market discovery")
            return
        
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
        mm = self.mm_as_settings
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

    def _bootstrap_historical_market_metadata(self) -> None:
        """Load lower/upper/eod metadata for replay market from bounds JSON artifacts."""
        data_path = getattr(self, "historical_data_path", None)
        if not data_path:
            return
        frames_path = Path(data_path).expanduser().resolve()
        if not frames_path.is_file():
            return

        replay_market_id = frames_path.parent.name
        snapshot_path = frames_path.parent / "snapshot.json"
        ticker = None
        if snapshot_path.is_file():
            try:
                snapshot_payload = json.loads(snapshot_path.read_text())
                ticker = snapshot_payload.get("market_id")
            except json.JSONDecodeError:
                ticker = None

        data_root = None
        for parent in frames_path.parents:
            if parent.name == "data":
                data_root = parent
                break
        if data_root is None:
            return

        candidate_bounds_files = [
            data_root / f"kalshi_market_bounds_{replay_market_id}.json",
            data_root / "kalshi_market_bounds.json",
        ]
        bounds_path = next((p for p in candidate_bounds_files if p.is_file()), None)
        if bounds_path is None:
            return

        try:
            bounds_payload = json.loads(bounds_path.read_text())
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse bounds file: {bounds_path}")
            return

        rows = bounds_payload.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return

        selected = None
        if ticker:
            selected = next((r for r in rows if r.get("ticker") == ticker), None)
        if selected is None:
            selected = next((r for r in rows if r.get("has_bounds")), None)
        if selected is None:
            return

        lower = selected.get("lower_bound")
        upper = selected.get("upper_bound")
        eod = selected.get("eod_timestamp")
        if lower is None or upper is None:
            return
        try:
            metadata = {
                "lower_bound": float(lower),
                "upper_bound": float(upper),
                "eod_timestamp": float(eod) if eod is not None else None,
            }
        except (TypeError, ValueError):
            return

        self.historical_market_metadata[replay_market_id] = metadata
        self.logger.info(
            "Loaded historical band metadata for %s from %s (ticker=%s, lower=%s, upper=%s)",
            replay_market_id,
            bounds_path.name,
            selected.get("ticker"),
            metadata["lower_bound"],
            metadata["upper_bound"],
        )

    def _get_reference_time(self, market_id: str) -> datetime:
        """Use event time in historical mode so replay timing matches the data."""
        orderbook = self.orderbooks.get(market_id)
        if getattr(self, "mode", None) == "historical" and orderbook is not None:
            return orderbook.timestamp
        return datetime.utcnow()
    
    def _calculate_fair_value(self, market_id: str, orderbook: OrderBook) -> Optional[float]:
        """Calculate fair value for a market"""
        if not orderbook.bids or not orderbook.asks:
            return None
        
        # Simple mid-price as fair value
        best_bid = max(level.price for level in orderbook.bids)
        best_ask = min(level.price for level in orderbook.asks)

        # Locked or crossed touch (common in archived YES/NO books at 1¢): use first
        # disjoint level so mid and spreads are well-defined.
        if best_bid >= best_ask:
            asks_above = [level.price for level in orderbook.asks if level.price > best_bid]
            if asks_above:
                best_ask = min(asks_above)
            else:
                bids_below = [level.price for level in orderbook.bids if level.price < best_ask]
                if bids_below:
                    best_bid = max(bids_below)
                else:
                    return None

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
        if spread_pct > self.mm_as_settings.max_spread:
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
        update_type = data.get("update_type")
        if update_type == "underlying_price":
            self._ingest_underlying_update(data)
            return

        market_id = data.get("market_id")
        if market_id:
            if market_id in self.active_markets:
                for key in ("lower_bound", "upper_bound", "eod_timestamp"):
                    if key in data:
                        self.active_markets[market_id][key] = data[key]
                model_fair = self._compute_band_fair_value(market_id)
                if model_fair is not None:
                    self.model_fair_values[market_id] = model_fair
            # Update market information
            if market_id not in self.active_markets:
                orderbook = self.orderbooks.get(market_id)
                if orderbook and self._is_market_suitable(market_id, orderbook):
                    self.active_markets[market_id] = {
                        "platform": orderbook.platform,
                        "started_at": datetime.utcnow(),
                        "lower_bound": data.get("lower_bound"),
                        "upper_bound": data.get("upper_bound"),
                        "eod_timestamp": data.get("eod_timestamp"),
                    }
                    self.logger.info(f"Started market making on {market_id} from market update")

    def _ingest_underlying_update(self, data: Dict) -> None:
        """Store latest underlying observation and refresh model fair values."""
        price = data.get("price")
        symbol = data.get("symbol", self.underlying_state.symbol)
        if price is None:
            return
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            return

        timestamp_value = data.get("timestamp")
        if isinstance(timestamp_value, str):
            try:
                ts = datetime.fromisoformat(timestamp_value)
            except ValueError:
                ts = datetime.utcnow()
        elif isinstance(timestamp_value, datetime):
            ts = timestamp_value
        else:
            ts = datetime.utcnow()

        if self.underlying_state.symbol != symbol:
            self.underlying_state = UnderlyingPriceState(symbol=symbol)
        self.underlying_state.add(
            timestamp=ts,
            price=price_value,
            source=data.get("source", "market_update"),
            metadata=data.get("metadata", {}),
        )

        for market_id in self.active_markets.keys():
            model_fair = self._compute_band_fair_value(market_id, now=ts)
            if model_fair is not None:
                self.model_fair_values[market_id] = model_fair

    def _compute_band_fair_value(self, market_id: str, now: Optional[datetime] = None) -> Optional[float]:
        """Compute P(lower <= close <= upper) using a Cauchy return model."""
        market_data = self.active_markets.get(market_id, {})
        lower = market_data.get("lower_bound")
        upper = market_data.get("upper_bound")
        eod_ts = market_data.get("eod_timestamp")
        spot = self.underlying_state.latest_price()
        if spot is None or lower is None or upper is None:
            return None

        try:
            lower_f = float(lower)
            upper_f = float(upper)
            eod_f = float(eod_ts) if eod_ts is not None else None
        except (TypeError, ValueError):
            return None

        if lower_f >= upper_f:
            return None

        current_time = now or datetime.utcnow()
        if eod_f is not None:
            time_to_close = max(eod_f - current_time.timestamp(), 0.0)
        else:
            # Conservative fallback to avoid zero gamma.
            time_to_close = 60.0
        gamma_t = self.cauchy_gamma_base * max(time_to_close, 1.0) ** (3.0 / 5.0)
        gamma_t = max(gamma_t, 1e-9)

        lo_ret = (lower_f - spot) / spot
        hi_ret = (upper_f - spot) / spot

        prob = cauchy.cdf(hi_ret, loc=self.cauchy_x0, scale=gamma_t) - cauchy.cdf(
            lo_ret, loc=self.cauchy_x0, scale=gamma_t
        )
        return float(min(max(prob, 0.0), 1.0))
    
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update"""
        market_id = orderbook.market_id

        # Store order book
        self.orderbooks[market_id] = orderbook
        
        # Update price history for this market
        mid_price = orderbook.get_mid_price()
        if mid_price is not None:
            if market_id not in self.price_histories:
                self.price_histories[market_id] = PriceHistory(market_id=market_id)
            self.price_histories[market_id].add(orderbook.timestamp, mid_price)
        
        # Calculate fair value
        fair_value = self._calculate_fair_value(market_id, orderbook)
        if fair_value:
            self.fair_values[market_id] = fair_value
        
        # Check if market is suitable
        if market_id not in self.active_markets:
            if self._is_market_suitable(market_id, orderbook):
                market_state = {
                    "platform": orderbook.platform,
                    "started_at": datetime.utcnow()
                }
                market_state.update(self.historical_market_metadata.get(market_id, {}))
                self.active_markets[market_id] = market_state
                self.logger.info(f"Started market making on {market_id}")
                model_fair = self._compute_band_fair_value(market_id)
                if model_fair is not None:
                    self.model_fair_values[market_id] = model_fair
        
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
        quote_spread = self.mm_as_settings.quote_spread
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
        market_id = trade.market_id
        if trade.price is None:
            return

        # Blend trade prints into fair value to remain responsive in thin books.
        prior_fv = self.fair_values.get(market_id)
        if prior_fv is None:
            self.fair_values[market_id] = float(trade.price)
        else:
            self.fair_values[market_id] = float(0.8 * prior_fv + 0.2 * trade.price)

    async def on_fill(self, trade: Trade):
        """Track this strategy's own inventory as signed size per market."""
        delta = trade.size if trade.side == OrderSide.BUY else -trade.size
        self.inventory[trade.market_id] = self.inventory.get(trade.market_id, 0.0) + delta

    def get_inventory(self, market_id: str) -> float:
        """Return signed inventory for a market."""
        return self.inventory.get(market_id, 0.0)

    def _compute_quote_sizes(self, market_id: str, rho: float) -> Tuple[float, float]:
        """Compute regime- and inventory-aware bid/ask sizes (used only when overlays on)."""
        mm = self.mm_as_settings
        max_position = max(mm.max_position, 1e-9)
        base_size = max_position * self.base_size_fraction
        rho_clamped = min(max(rho, 0.0), 1.0)

        regime_multiplier = max(
            self.min_size_fraction,
            1.0 - self.regime_size_beta * rho_clamped,
        )

        q = self.get_inventory(market_id)
        long_pressure = min(max(q, 0.0) / max_position, 1.0)
        short_pressure = min(max(-q, 0.0) / max_position, 1.0)

        taper_exp = max(mm.inventory_size_taper_exponent, 1.0)
        inv_floor = max(mm.inventory_min_size_fraction, 0.0)

        bid_inventory_multiplier = max(
            inv_floor,
            1.0 - self.inventory_size_eta * (long_pressure**taper_exp),
        )
        ask_inventory_multiplier = max(
            inv_floor,
            1.0 - self.inventory_size_eta * (short_pressure**taper_exp),
        )

        bid_size = base_size * regime_multiplier * bid_inventory_multiplier
        ask_size = base_size * regime_multiplier * ask_inventory_multiplier
        return bid_size, ask_size

    def _band_position_z(self, market_id: str) -> Optional[float]:
        """Normalized underlying location in [lower_bound, upper_bound], or None."""
        market_data = self.active_markets.get(market_id, {})
        lower = market_data.get("lower_bound")
        upper = market_data.get("upper_bound")
        spot = self.underlying_state.latest_price()
        if lower is None or upper is None or spot is None:
            return None
        try:
            lo = float(lower)
            hi = float(upper)
            px = float(spot)
        except (TypeError, ValueError):
            return None
        if hi <= lo:
            return None
        center = 0.5 * (lo + hi)
        half_width = 0.5 * (hi - lo)
        return float(np.clip((px - center) / max(half_width, 1e-12), -1.0, 1.0))

    def _seconds_to_eod(self, market_id: str, now: datetime) -> Optional[float]:
        """Seconds until eod_timestamp (unix) if configured."""
        eod = self.active_markets.get(market_id, {}).get("eod_timestamp")
        if eod is None:
            return None
        try:
            eod_ts = float(eod)
        except (TypeError, ValueError):
            return None
        if now.tzinfo is None:
            now_ts = now.replace(tzinfo=timezone.utc).timestamp()
        else:
            now_ts = now.timestamp()
        return eod_ts - now_ts

    def _flatten_pressure(self, market_id: str, now: datetime) -> float:
        """0..1 urgency to flatten inventory as session end approaches."""
        tau = self._seconds_to_eod(market_id, now)
        if tau is None:
            return 0.0
        window = max(self.mm_as_settings.session_flatten_seconds, 1.0)
        if tau <= 0:
            return 1.0
        if tau >= window:
            return 0.0
        return float(np.clip(1.0 - tau / window, 0.0, 1.0))

    def _build_reversal_history(self, market_id: str) -> pd.DataFrame:
        """Convert recent price path into reversal labels for regime estimation."""
        history = self.price_histories.get(market_id)
        if history is None:
            return pd.DataFrame(columns=["price", "is_reversal"])
        prices = history.get_prices()
        if prices is None or len(prices) < 3:
            return pd.DataFrame(columns=["price", "is_reversal"])

        p = np.asarray(prices, dtype=float)
        if p.size < 3:
            return pd.DataFrame(columns=["price", "is_reversal"])
        returns = np.diff(p)
        signs = np.sign(returns)
        is_reversal = np.zeros(p.shape[0], dtype=float)
        for i in range(1, signs.shape[0]):
            if signs[i] != 0 and signs[i - 1] != 0 and signs[i] != signs[i - 1]:
                is_reversal[i + 1] = 1.0
        return pd.DataFrame({"price": p, "is_reversal": is_reversal})

    def _compute_rho(self, market_id: str) -> float:
        """Estimate current regime stress from local reversal frequency."""
        if not MM_AS_REGIME_SCORE_ENABLED:
            return 0.0
        history = self.price_histories.get(market_id)
        if history is None:
            return 0.0
        prices = history.get_prices()
        if prices is None or len(prices) < 3:
            return 0.0
        reversals = self._build_reversal_history(market_id)
        return self.regime_score(
            prices=np.asarray(prices, dtype=float),
            historical_reversals=reversals,
            n_buckets=max(int(self.mm_as_settings.regime_buckets), 2),
        )
    
    async def generate_signals(self) -> List[StrategySignal]:
        if self.state != StrategyState.RUNNING:
            return []

        signals = []
        for market_id, market_data in self.active_markets.items():
            orderbook = self.orderbooks.get(market_id)
            if not orderbook:
                continue
            now = self._get_reference_time(market_id)

            mfv = self.model_fair_values.get(market_id)
            bfv = self.fair_values.get(market_id)
            fair_value = mfv if mfv is not None else bfv
            if fair_value is None:
                continue

            # Check time throttle
            last_update = self.last_quote_update.get(market_id)
            if last_update and (now - last_update) < self.quote_update_interval:
                continue

            # Check if fair value has moved enough to warrant repricing
            current = self.current_quotes.get(market_id, {})
            current_bid = current.get("bid")
            current_ask = current.get("ask")

            if current_bid and current_ask:
                current_mid = (current_bid + current_ask) / 2
                price_move = abs(fair_value - current_mid) / current_mid
                if price_move < self.quote_reprice_threshold:
                    continue  # fair value hasn't moved enough, skip

            platform = market_data.get("platform", orderbook.platform)
            # ρ from reversal-bucket regime_score; see MM_AS_REGIME_SCORE_ENABLED.
            rho = self._compute_rho(market_id)
            sigma = self.rolling_realized_vol(self.price_histories.get(market_id)) or 0.0
            q = self.get_inventory(market_id)
            t = 0.0
            T = max(self.mm_as_settings.session_horizon_seconds, 1.0)
            try:
                bid_price, ask_price = self.quotes(
                    s=fair_value,
                    q=q,
                    sigma=sigma,
                    gamma_base=self.mm_as_settings.gamma_base,
                    alpha=self.mm_as_settings.gamma_alpha,
                    T=T,
                    t=t,
                    kappa=self.mm_as_settings.kappa,
                    rho=rho,
                )
                # The continuous-time A-S spread can be too wide for bounded binary
                # books; fall back to a tighter operational spread around fair value.
                model_spread = ask_price - bid_price
                max_operational_spread = max(self.mm_as_settings.quote_spread * 3.0, 0.05)
                if model_spread > max_operational_spread:
                    half = self.mm_as_settings.quote_spread / 2.0
                    bid_price = fair_value - half
                    ask_price = fair_value + half
                bid_price = max(0.01, bid_price)
                ask_price = min(0.99, ask_price)
                if ask_price < bid_price:
                    mid = float(np.clip(fair_value, 0.01, 0.99))
                    bid_price = mid
                    ask_price = mid
            except ValueError:
                quote_spread = self.mm_as_settings.quote_spread
                bid_price = max(0.01, fair_value - quote_spread / 2)
                ask_price = min(0.99, fair_value + quote_spread / 2)

            mm = self.mm_as_settings
            max_pos = max(mm.max_position, 1e-9)
            room_long = max(0.0, max_pos - q)
            room_short = max(0.0, max_pos + q)

            if MM_AS_INVENTORY_OVERLAYS_ENABLED:
                q_norm = float(np.clip(q / max_pos, -1.0, 1.0))
                flatten_u = self._flatten_pressure(market_id, now)
                z_band = self._band_position_z(market_id)
                if z_band is None:
                    z_band = 0.0
                skew_scale = 1.0 + flatten_u
                skew = mm.inventory_quote_skew_coeff * q_norm * skew_scale
                if abs(q_norm) > 1e-9:
                    skew += mm.band_quote_skew_coeff * z_band * q_norm
                bid_price = float(np.clip(bid_price - skew, 0.01, 0.99))
                ask_price = float(np.clip(ask_price - skew, 0.01, 0.99))
                if ask_price < bid_price:
                    mid = float(np.clip(fair_value - skew, 0.01, 0.99))
                    bid_price = mid
                    ask_price = mid

                bid_size, ask_size = self._compute_quote_sizes(market_id, rho)

                gate = max_pos * mm.inventory_hard_gate_fraction
                if q >= gate:
                    bid_size = 0.0
                if q <= -gate:
                    ask_size = 0.0

                if flatten_u > 0.0:
                    if q > 0:
                        bid_size *= max(0.0, 1.0 - flatten_u)
                    elif q < 0:
                        ask_size *= max(0.0, 1.0 - flatten_u)

                bid_size = min(bid_size, room_long)
                ask_size = min(ask_size, room_short)
            else:
                # Base A-S: quotes() already folded inventory via reservation price only.
                one = float(max(MM_AS_BASE_QUOTE_SIZE, 1e-9))
                bid_size = one if room_long >= one else 0.0
                ask_size = one if room_short >= one else 0.0

            min_quote = 1e-9
            if bid_size > min_quote:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="buy",
                    size=bid_size,
                    price=bid_price,
                    order_type="limit",
                    confidence=0.8,
                    reason=f"MM bid reprice to {bid_price:.4f} (fv={fair_value:.4f})",
                    timestamp=now,
                ))
            else:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="buy",
                    size=0.0,
                    price=bid_price,
                    order_type="limit",
                    confidence=0.0,
                    reason="MM cancel bid (zero size)",
                    timestamp=now,
                ))
            if ask_size > min_quote:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="sell",
                    size=ask_size,
                    price=ask_price,
                    order_type="limit",
                    confidence=0.8,
                    reason=f"MM ask reprice to {ask_price:.4f} (fv={fair_value:.4f})",
                    timestamp=now,
                ))
            else:
                signals.append(StrategySignal(
                    market_id=market_id,
                    platform=platform,
                    side="sell",
                    size=0.0,
                    price=ask_price,
                    order_type="limit",
                    confidence=0.0,
                    reason="MM cancel ask (zero size)",
                    timestamp=now,
                ))

            self.current_quotes[market_id] = {"bid": bid_price, "ask": ask_price}
            self.last_quote_update[market_id] = now

        return signals
