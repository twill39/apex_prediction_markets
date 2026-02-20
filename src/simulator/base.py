"""Base simulator interface"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
import asyncio

from src.strategies.base import BaseStrategy, StrategySignal
from src.data.models import Order, Trade, Position, Platform
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
        self.initial_balance = 10000.0  # Starting balance
        self.current_balance = self.initial_balance
        
        # Metrics
        self.metrics: Optional[PerformanceMetrics] = None
    
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
