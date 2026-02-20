"""Tests for trading strategies"""

import pytest
from datetime import datetime

from src.strategies.base import BaseStrategy, StrategySignal, StrategyState
from src.strategies.copy_trading import CopyTradingStrategy
from src.strategies.market_making import MarketMakingStrategy
from src.strategies.alt_data import AltDataStrategy
from src.data.models import OrderBook, OrderBookLevel, Platform, Trade, OrderSide


def test_strategy_signal():
    """Test strategy signal creation"""
    signal = StrategySignal(
        market_id="test_market",
        platform=Platform.KALSHI,
        side="buy",
        size=100.0,
        price=0.5,
        confidence=0.8
    )
    
    assert signal.market_id == "test_market"
    assert signal.platform == Platform.KALSHI
    assert signal.side == "buy"
    assert signal.size == 100.0


@pytest.mark.asyncio
async def test_copy_trading_strategy_initialization():
    """Test copy trading strategy initialization"""
    strategy = CopyTradingStrategy()
    assert strategy.strategy_id == "copy_trading"
    assert strategy.state == StrategyState.IDLE


@pytest.mark.asyncio
async def test_market_making_strategy_initialization():
    """Test market making strategy initialization"""
    strategy = MarketMakingStrategy()
    assert strategy.strategy_id == "market_making"
    assert strategy.state == StrategyState.IDLE


@pytest.mark.asyncio
async def test_alt_data_strategy_initialization():
    """Test alt data strategy initialization"""
    strategy = AltDataStrategy()
    assert strategy.strategy_id == "alt_data"
    assert strategy.state == StrategyState.IDLE
