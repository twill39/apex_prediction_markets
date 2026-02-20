"""Tests for simulator"""

import pytest
from datetime import datetime

from src.simulator.historical import HistoricalSimulator
from src.simulator.paper_trading import PaperTradingSimulator
from src.simulator.metrics import calculate_metrics, PerformanceMetrics
from src.data.models import Trade, Platform, OrderSide
from src.strategies.market_making import MarketMakingStrategy


def test_historical_simulator_initialization():
    """Test historical simulator initialization"""
    simulator = HistoricalSimulator()
    assert simulator.mode.value == "historical"
    assert simulator.initial_balance == 10000.0


def test_paper_trading_simulator_initialization():
    """Test paper trading simulator initialization"""
    simulator = PaperTradingSimulator()
    assert simulator.mode.value == "paper"
    assert simulator.initial_balance == 10000.0


def test_metrics_calculation():
    """Test metrics calculation"""
    trades = [
        Trade(
            trade_id="1",
            market_id="test",
            platform=Platform.KALSHI,
            side=OrderSide.BUY,
            price=0.5,
            size=100.0,
            timestamp=datetime.utcnow()
        )
    ]
    
    metrics = calculate_metrics(
        trades=trades,
        positions=[],
        initial_balance=10000.0,
        current_balance=10000.0,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow()
    )
    
    assert metrics.total_trades == 1
    assert metrics.start_time is not None
    assert metrics.end_time is not None
