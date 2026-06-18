"""Base simulator interface"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
import asyncio

from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, Platform, PositionSide
from src.simulator.metrics import PerformanceMetrics


class SimulatorMode(str, Enum):
    """Simulator mode"""
    HISTORICAL = "historical"
    PAPER = "paper"


class BaseSimulator(ABC):
    """Base class for simulators"""
    
    def __init__(self, mode: SimulatorMode):
        """Initialize simulator"""
        self.mode = mode
        self.strategies: List[BaseStrategy] = []
        self.is_running = False
        
        # Trading state
        self.orders: Dict[str, Order] = {}
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        
        # Performance tracking
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.initial_balance = 100.0  # Overridden when simulator loads settings (see Historical/Paper init)
        self.current_balance = self.initial_balance
        
        # Metrics
        self.metrics: Optional[PerformanceMetrics] = None
    
    def _signed_inventory_for_market(self, market_id: str, platform: Platform) -> float:
        """Net contracts: long positive, short negative."""
        key = f"{market_id}_{platform.value}"
        pos = self.positions.get(key)
        if not pos or pos.size <= 0:
            return 0.0
        if pos.side == PositionSide.LONG:
            return float(pos.size)
        return -float(pos.size)

    def _allowed_fill_size(self, market_id: str, platform: Platform, side, requested: float) -> float:
        """Max fill size without breaching signed inventory cap (when enforcement is on)."""
        req = max(0.0, float(requested))
        if req <= 0:
            return 0.0
        sim = getattr(self, "settings", None)
        if sim is None:
            return req
        spec = sim.simulator
        if not getattr(spec, "enforce_signed_inventory_cap", True):
            return req
        cap = max(float(getattr(spec, "max_signed_inventory", 0.0)), 0.0)
        if cap <= 0:
            mm_as = getattr(sim, "market_making_as", None)
            if mm_as is not None:
                cap = max(float(getattr(mm_as, "max_position", 0.0)), 0.0)
        if cap <= 0:
            return req
        q = self._signed_inventory_for_market(market_id, platform)
        if isinstance(side, str):
            side_str = side.lower()
        else:
            side_str = str(getattr(side, "value", side)).lower()
        if side_str == "buy":
            return max(0.0, min(req, cap - q))
        if side_str == "sell":
            return max(0.0, min(req, q + cap))
        return req

    def add_strategy(self, strategy: BaseStrategy):
        """Add a strategy to the simulator"""
        self.strategies.append(strategy)

    @abstractmethod
    async def run(self):
        """Run the simulator"""
        pass
    
    @abstractmethod
    async def execute_signal(self, signal: StrategySignal) -> Optional[Trade]:
        """Execute a trading signal"""
        pass
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get performance metrics"""
        if not self.metrics:
            self.metrics = self._calculate_metrics()
        return self.metrics
    
    def _calculate_metrics(self) -> PerformanceMetrics:
        """Calculate performance metrics"""
        from src.simulator.metrics import calculate_metrics
        return calculate_metrics(
            trades=self.trades,
            positions=list(self.positions.values()),
            initial_balance=self.initial_balance,
            current_balance=self.current_balance,
            start_time=self.start_time or datetime.utcnow(),
            end_time=self.end_time or datetime.utcnow()
        )
    
    async def stop(self):
        """Stop the simulator"""
        self.is_running = False
        self.end_time = datetime.utcnow()
        
        # Stop all strategies
        for strategy in self.strategies:
            await strategy.stop()
