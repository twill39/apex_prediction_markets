"""Copy Trading Strategy - Copy profitable traders

Signal flow:
  1. Screeners discover & cache trader wallet addresses on startup.
  2. A background polling loop calls the Polymarket data API every 30s
     to fetch each tracked trader's recent trades.
  3. New trades are converted to internal Trade objects and stored.
  4. generate_signals() picks up new, unprocessed trades and emits
     StrategySignals for the paper trading simulator.
  5. The WebSocket market channel is used ONLY for live price data
     (orderbook updates) — it does NOT carry trader identity info.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import numpy as np

from .base import BaseStrategy, StrategySignal, StrategyState
from src.data.models import (
    Platform, Trade, OrderBook, OrderSide, Position, TraderPerformance
)
from src.data.storage import get_storage
from src.websockets.base import WebSocketEvent, WebSocketEventType
from src.config import get_settings
from src.discovery import get_trader_ids_meeting_spec
from src.discovery.trader_discovery import get_user_trades
from src.discovery.copy_trading_market_discovery import discover_markets_for_copying
from src.utils.logger import get_logger
from src.strategies.screeners import (
    ConsistentGrinderScreener,
    WhaleConvictionTracker,
    TrendsetterScreener
)

# How many traders to poll concurrently (avoid API rate limits)
POLL_CONCURRENCY = 10

class CopyTradingStrategy(BaseStrategy):
    """Strategy that copies profitable traders"""
    
    def __init__(self, use_kalshi: Optional[bool] = None):
        """Initialize copy trading strategy"""
        super().__init__(
            strategy_id="copy_trading",
            name="Copy Trading Strategy"
        )
        self.settings = get_settings()
        self.use_kalshi = use_kalshi if use_kalshi is not None else self.settings.copy_trading.use_kalshi
        self.logger = get_logger("CopyTradingStrategy")
        self.storage = get_storage()
        
        # Tracked traders
        self.tracked_traders: Set[str] = set()
        self.trader_performance: Dict[str, TraderPerformance] = {}
        
        # Market mapping between platforms
        self.market_mapping: Dict[str, Dict[Platform, str]] = {}
        
        # WebSocket clients
        self.kalshi_ws: Optional[KalshiWebSocket] = None
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
        
        # Screeners
        self.screeners = []
        if self.settings.copy_trading.screeners.grinder.enabled:
            self.screeners.append(ConsistentGrinderScreener())
        if self.settings.copy_trading.screeners.whale.enabled:
            self.screeners.append(WhaleConvictionTracker())
        if self.settings.copy_trading.screeners.trendsetter.enabled:
            self.screeners.append(TrendsetterScreener())
        
        # Trader activity tracking
        self.trader_positions: Dict[str, Dict[str, Position]] = {}
        self.trader_trades: Dict[str, List[Trade]] = {}

        # Dedup: track which trade IDs we've already generated signals for
        self.processed_trade_ids: Set[str] = set()

        # Polling state: last-seen trade ID per trader for incremental fetches
        self._last_seen_trade_id: Dict[str, str] = {}  # trader_id -> latest trade id
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval_secs: int = 30  # seconds between poll cycles

        # Market IDs discovered for subscription (consumed by paper_trading simulator)
        self.discovered_market_ids: List[str] = []
    
    async def initialize(self):
        """Initialize the strategy.
        
        NOTE: WebSocket connections are managed by PaperTradingSimulator,
        not by the strategy. The simulator forwards events to us via
        on_trade() and on_orderbook_update(). We do NOT create our own
        WebSocket connections here.
        """
        self.logger.info("Initializing copy trading strategy")
        
        # Load top traders and discover markets (cached or fresh)
        await self._load_top_traders()

        # Start the background polling loop
        self._poll_task = asyncio.create_task(self._poll_loop())
        self.logger.info(
            f"Initialized with {len(self.tracked_traders)} tracked traders, "
            f"polling every {self._poll_interval_secs}s"
        )

    async def stop(self):
        """Stop the strategy and cancel the polling task."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self.logger.info("Poll task cancelled")
        await super().stop()
    
    SCREENER_CACHE_PATH = Path("data/screener_cache.json")
    SCREENER_CACHE_TTL_MINUTES = 60  # Re-run screeners after this many minutes

    async def _load_top_traders(self):
        """Load traders from cache, Polymarket leaderboard, and screeners."""
        ct = self.settings.copy_trading

        # --- Try loading from cache first (includes both traders and markets) ---
        cached = self._load_screener_cache()
        if cached is not None:
            self.tracked_traders = cached["traders"]
            self.discovered_market_ids = cached.get("market_ids", [])
            self.logger.info(
                f"Loaded {len(self.tracked_traders)} traders and "
                f"{len(self.discovered_market_ids)} markets from cache"
            )
            return

        # --- No valid cache, run full discovery ---
        # 1. Base spec discovery
        try:
            from functools import partial
            loop = asyncio.get_event_loop()
            ids = await loop.run_in_executor(
                None,
                partial(
                    get_trader_ids_meeting_spec,
                    max_volume=ct.trader_max_volume,
                    min_pnl=ct.trader_min_pnl,
                    min_pnl_per_vol=ct.trader_min_pnl_per_vol,
                    time_period=ct.trader_discovery_time_period,
                    max_traders=ct.max_traders,
                )
            )
            if ids:
                self.tracked_traders = set(ids)
                self.logger.info(f"Discovered {len(ids)} traders meeting base spec")
            else:
                self.logger.info("No traders met discovery criteria")
        except Exception as e:
            self.logger.warning(f"Trader discovery failed: {e}")
            
        # 2. Run Advanced Screeners (now concurrent — much faster)
        screener_counts = {}
        for screener in self.screeners:
            screener_name = screener.__class__.__name__
            try:
                self.logger.info(f"Running screener: {screener_name}")
                screener_traders = await screener.get_tracked_traders()
                screener_counts[screener_name] = len(screener_traders)
                self.tracked_traders.update(screener_traders)
            except Exception as e:
                self.logger.warning(f"Screener {screener_name} failed: {e}")
                
        # 3. Log results
        self.logger.info("=== Trader Discovery Results ===")
        for name, count in screener_counts.items():
            self.logger.info(f" - {name}: {count} traders")
        self.logger.info(f" Total unique tracked traders: {len(self.tracked_traders)}")
        self.logger.info("================================")

        # 4. Discover markets (runs HTTP calls — do this now before WS connects)
        await self._discover_markets()

        # 5. Save traders + markets to cache for fast restarts
        self._save_screener_cache(self.tracked_traders, self.discovered_market_ids)

    def _load_screener_cache(self) -> Optional[Dict]:
        """Load cached screener results (traders + markets) if fresh enough."""
        try:
            if not self.SCREENER_CACHE_PATH.is_file():
                return None
            data = json.loads(self.SCREENER_CACHE_PATH.read_text())
            saved_at = datetime.fromisoformat(data["saved_at"])
            age_minutes = (datetime.utcnow() - saved_at).total_seconds() / 60
            if age_minutes > self.SCREENER_CACHE_TTL_MINUTES:
                self.logger.info(f"Screener cache expired ({age_minutes:.0f} min old)")
                return None
            traders = set(data.get("traders", []))
            if not traders:
                return None
            return {
                "traders": traders,
                "market_ids": data.get("market_ids", []),
            }
        except Exception as e:
            self.logger.debug(f"Could not load screener cache: {e}")
            return None

    def _save_screener_cache(self, traders: Set[str], market_ids: List[str]):
        """Save screener results (traders + markets) to disk."""
        try:
            self.SCREENER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "saved_at": datetime.utcnow().isoformat(),
                "trader_count": len(traders),
                "traders": sorted(traders),
                "market_count": len(market_ids),
                "market_ids": market_ids,
            }
            self.SCREENER_CACHE_PATH.write_text(json.dumps(data, indent=2))
            self.logger.info(
                f"Saved {len(traders)} traders and {len(market_ids)} markets to cache"
            )
        except Exception as e:
            self.logger.warning(f"Could not save screener cache: {e}")

    async def _discover_markets(self):
        """Discover markets from tracked trader activity and insider-prone
        categories. Stores IDs in self.discovered_market_ids for the
        simulator to subscribe via its own connected WebSocket."""
        if not self.tracked_traders:
            self.logger.warning("No tracked traders — skipping market discovery")
            return

        self.logger.info("Discovering markets for copy trading...")
        try:
            from functools import partial
            loop = asyncio.get_event_loop()
            market_ids = await loop.run_in_executor(
                None,
                partial(
                    discover_markets_for_copying,
                    tracked_traders=self.tracked_traders,
                    max_trader_markets=150,
                    max_insider_markets=100,
                    max_total=200,
                )
            )
        except Exception as e:
            self.logger.warning(f"Market discovery failed: {e}")
            return

        if not market_ids:
            self.logger.warning("Market discovery returned no markets")
            return

        self.discovered_market_ids = market_ids
        self.logger.info(f"Discovered {len(market_ids)} markets for subscription")

    def get_discovered_market_ids(self) -> List[str]:
        """Return market IDs discovered during initialization.
        Called by PaperTradingSimulator to subscribe via its connected WebSocket."""
        return self.discovered_market_ids
    
    def _calculate_trader_metrics(self, trader_id: str, platform: Platform) -> TraderPerformance:
        """Calculate performance metrics for a trader"""
        trades = self.trader_trades.get(trader_id, [])
        platform_trades = [t for t in trades if t.platform == platform]
        
        if not platform_trades:
            return TraderPerformance(
                trader_id=trader_id,
                platform=platform,
                last_updated=datetime.utcnow()
            )
            
        # Optional: HFT Bot Filtering
        # If they traded thousands of times in a day, they're an HFT bot.
        # Check trade rate: count / timeframe
        if len(platform_trades) > 100:
            dt = platform_trades[-1].timestamp - platform_trades[0].timestamp
            if dt.total_seconds() > 0:
                trades_per_sec = len(platform_trades) / dt.total_seconds()
                if trades_per_sec > 1.0: # simplistic HFT heuristic
                    self.logger.debug(f"{trader_id} exhibits HFT behavior ({trades_per_sec:.2f} t/s). Ignoring.")
                    # return empty/zeroed performance
                    return TraderPerformance(trader_id=trader_id, platform=platform, win_rate=0.0)
        
        # Calculate metrics
        # A trade is "winning" if it was a BUY below 0.5 (undervalued)
        # or a SELL above 0.5 (overvalued) — i.e. they had edge on the price.
        winning = sum(
            1 for t in platform_trades
            if (t.side == OrderSide.BUY and t.price < 0.5)
            or (t.side == OrderSide.SELL and t.price > 0.5)
        )
        losing = len(platform_trades) - winning
        win_rate = winning / len(platform_trades) if platform_trades else 0.0
        
        # Calculate PnL (simplified - would need position tracking)
        total_pnl = sum([t.size * t.price for t in platform_trades])  # Very simplified
        
        # Calculate Sharpe ratio (simplified)
        returns = [t.price / 0.5 - 1 for t in platform_trades]  # Conceptual proxy
        sharpe = None
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
        
        return TraderPerformance(
            trader_id=trader_id,
            platform=platform,
            total_trades=len(platform_trades),
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe,
            average_trade_size=np.mean([t.size for t in platform_trades]) if platform_trades else 0.0,
            last_updated=datetime.utcnow()
        )
    
    async def _identify_profitable_traders(self) -> List[str]:
        """Identify most profitable traders to copy"""
        # Calculate metrics for all tracked traders
        for trader_id in self.tracked_traders:
            for platform in [Platform.POLYMARKET, Platform.KALSHI]:
                performance = self._calculate_trader_metrics(trader_id, platform)
                self.trader_performance[f"{trader_id}_{platform.value}"] = performance
        
        # Sort by performance (e.g., Sharpe ratio, win rate, ROI)
        sorted_traders = sorted(
            self.trader_performance.items(),
            key=lambda x: (
                x[1].sharpe_ratio or 0,
                x[1].win_rate,
                x[1].total_pnl
            ),
            reverse=True
        )
        
        # Return top N traders
        max_traders = self.settings.copy_trading.max_traders
        top_traders = [t[0].split("_")[0] for t in sorted_traders[:max_traders]]
        
        return list(set(top_traders))  # Remove duplicates
    
    async def _on_websocket_event(self, event: WebSocketEvent):
        """Handle WebSocket events forwarded from the simulator."""
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
        # Trade events from WS are anonymous — we ignore them.
        # Trader identification is done via the polling loop.
    
    async def on_orderbook_update(self, orderbook: OrderBook):
        """Handle order book update — store for slippage checks."""
        pass
    
    async def on_trade(self, trade: Trade):
        """Handle trade event from simulator (WS trades are anonymous, so no-op)."""
        pass

    # -----------------------------------------------------------------
    # Polling loop: fetch tracked traders' recent trades from data API
    # -----------------------------------------------------------------

    async def _poll_loop(self):
        """Background loop: poll the Polymarket data API for new trades
        from each tracked trader."""
        self.logger.info(
            f"Starting poll loop ({len(self.tracked_traders)} traders, "
            f"interval={self._poll_interval_secs}s, concurrency={POLL_CONCURRENCY})"
        )

        # First cycle: just set baselines (fetch 1 trade per trader)
        # so we don't generate signals for old trades
        self.logger.info("Setting trade baselines for all traders...")
        await self._set_baselines()
        self.logger.info("Baselines set — now watching for new trades")

        while self.state == StrategyState.RUNNING:
            await asyncio.sleep(self._poll_interval_secs)
            try:
                new_count = await self._poll_all_traders()
                if new_count:
                    self.logger.info(f"Poll cycle found {new_count} new trade(s)")
            except Exception as e:
                self.logger.warning(f"Poll cycle error: {e}")

    async def _set_baselines(self):
        """Fast first pass: fetch 1 trade per trader to record last-seen ID.
        No signals are generated — this just sets the starting point."""
        sem = asyncio.Semaphore(POLL_CONCURRENCY)
        done = 0
        total = len(self.tracked_traders)
        lock = asyncio.Lock()

        async def _baseline_one(trader_id: str):
            nonlocal done
            async with sem:
                try:
                    loop = asyncio.get_event_loop()
                    raw_trades = await loop.run_in_executor(
                        None, get_user_trades, trader_id, 1
                    )
                    if raw_trades:
                        first = raw_trades[0]
                        tid = first.get("id", "")
                        if tid:
                            self._last_seen_trade_id[trader_id] = tid
                except Exception:
                    pass
                async with lock:
                    done += 1
                    if done % 50 == 0:
                        self.logger.info(f"  Baselines: {done}/{total}")

        await asyncio.gather(*[_baseline_one(tid) for tid in self.tracked_traders])
        self.logger.info(f"  Baselines: {done}/{total} complete")

    async def _poll_all_traders(self) -> int:
        """Fetch recent trades for all tracked traders concurrently.
        Returns count of new trades discovered."""
        sem = asyncio.Semaphore(POLL_CONCURRENCY)
        new_count = 0
        lock = asyncio.Lock()

        async def _poll_one(trader_id: str):
            nonlocal new_count
            async with sem:
                try:
                    n = await self._poll_trader(trader_id)
                    if n:
                        async with lock:
                            new_count += n
                except Exception as e:
                    self.logger.debug(f"Poll error for {trader_id[:10]}...: {e}")

        traders = list(self.tracked_traders)
        await asyncio.gather(*[_poll_one(tid) for tid in traders])
        return new_count

    async def _poll_trader(self, trader_id: str) -> int:
        """Fetch recent trades for a single trader from the data API.
        Returns count of new trades found."""
        # Run the synchronous API call in a thread to avoid blocking
        loop = asyncio.get_event_loop()
        raw_trades = await loop.run_in_executor(
            None, get_user_trades, trader_id, 50
        )
        if not raw_trades:
            return 0

        last_seen = self._last_seen_trade_id.get(trader_id)
        new_trades = []
        new_last_id = None

        for raw in raw_trades:
            tid = raw.get("id", "")
            if not tid:
                continue
            # Update the newest trade ID
            if new_last_id is None:
                new_last_id = tid  # Trades are returned newest-first

            # Stop when we hit previously seen trades
            if tid == last_seen:
                break

            trade = self._raw_to_trade(trader_id, raw)
            if trade:
                new_trades.append(trade)

        if new_last_id:
            self._last_seen_trade_id[trader_id] = new_last_id

        if not new_trades:
            return 0

        # Store and generate signals immediately
        if trader_id not in self.trader_trades:
            self.trader_trades[trader_id] = []
        self.trader_trades[trader_id].extend(new_trades)

        self.logger.info(
            f"Trader {trader_id[:10]}... made {len(new_trades)} new trade(s)"
        )
        return len(new_trades)

    @staticmethod
    def _raw_to_trade(trader_id: str, raw: dict) -> Optional[Trade]:
        """Convert a Polymarket data API trade dict to an internal Trade.
        
        Data API format:
          {"id": "...", "asset": "<clob_token_id>", "side": "BUY|SELL",
           "price": "0.55", "size": "100", "proxyWallet": "0x...",
           "timestamp": "2026-03-06T22:00:00Z", ...}
        """
        try:
            side_str = str(raw.get("side", "")).upper()
            side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL

            price = float(raw.get("price", 0))
            size = float(raw.get("size", 0))

            ts_str = raw.get("timestamp") or raw.get("matchTime") or datetime.utcnow().isoformat()
            try:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                # Strip timezone info for consistency with our naive-UTC convention
                timestamp = timestamp.replace(tzinfo=None)
            except (ValueError, AttributeError):
                timestamp = datetime.utcnow()

            return Trade(
                trade_id=str(raw.get("id", "")),
                market_id=raw.get("asset", raw.get("market", "")),
                platform=Platform.POLYMARKET,
                side=side,
                price=price,
                size=size,
                timestamp=timestamp,
                fees=float(raw.get("fee", 0) or 0),
                metadata={"trader_id": trader_id},
            )
        except Exception:
            return None
    
    async def _copy_trader_trade(self, trader_id: str, trade: Trade) -> Optional[StrategySignal]:
        """Generate signal to copy a trader's trade"""
        # Check if trader is in our screened pool
        if trader_id not in self.tracked_traders:
            return None
        
        # Get local trader performance (updated via websocket)
        performance_key = f"{trader_id}_{trade.platform.value}"
        performance = self.trader_performance.get(performance_key)
        
        # If we have enough local data and they're underperforming, stop copying
        if performance and performance.total_trades > 5 and performance.win_rate < 0.5:
            return None
            
        # Slippage limit
        max_slippage = 0.02
        if trade.side == OrderSide.BUY:
            acceptable_price = trade.price * (1 + max_slippage)
        else:
            acceptable_price = trade.price * (1 - max_slippage)
        
        # Bug 5 fix: Calculate trade value in USD (price × size), then cap
        trade_value_usd = trade.price * trade.size
        max_size = self.settings.copy_trading.max_position_size
        size_usd = min(trade_value_usd, max_size)
        # Convert back to shares at the acceptable price
        if acceptable_price > 0:
            size_shares = size_usd / acceptable_price
        else:
            return None  # Can't trade at price 0
        
        # Map to other platform if needed
        target_platform = trade.platform
        target_market_id = trade.market_id
        
        if trade.platform == Platform.POLYMARKET:
            mapped_market = self.market_mapping.get(trade.market_id, {}).get(Platform.KALSHI)
            if mapped_market:
                target_platform = Platform.KALSHI
                target_market_id = mapped_market
        
        # Bug 3 fix: Use default confidence when no local performance data
        confidence = performance.win_rate if performance else 0.7
        
        self.logger.info(
            f"SIGNAL: Copy {trader_id[:10]}... {trade.side.value} "
            f"{size_usd:.2f} USD on {target_market_id[:20]}... "
            f"@ {acceptable_price:.4f} (confidence: {confidence:.0%})"
        )
        
        return StrategySignal(
            market_id=target_market_id,
            platform=target_platform,
            side=trade.side.value,
            size=size_shares,
            order_type="market",  # Use market orders — we may not have orderbooks
            price=acceptable_price,
            confidence=confidence,
            reason=f"Copying trader {trader_id} ({trade.side.value} ${size_usd:.0f})",
            timestamp=datetime.utcnow()
        )
    
    async def generate_signals(self) -> List[StrategySignal]:
        """Generate trading signals from new, unprocessed trades."""
        if self.state != StrategyState.RUNNING:
            return []
        
        signals = []
        
        # Bug 4 fix: Only process trades we haven't seen before
        for trader_id, trades in self.trader_trades.items():
            for trade in trades:
                trade_id = trade.trade_id
                if not trade_id or trade_id in self.processed_trade_ids:
                    continue
                
                # Only process recent trades (last hour)
                age_secs = (datetime.utcnow() - trade.timestamp).total_seconds()
                if age_secs > 3600:
                    continue
                
                self.processed_trade_ids.add(trade_id)
                signal = await self._copy_trader_trade(trader_id, trade)
                if signal:
                    signals.append(signal)
        
        return signals
