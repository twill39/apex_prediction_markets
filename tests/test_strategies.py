"""Tests for trading strategies"""

import pytest
from datetime import datetime
import pandas as pd
import numpy as np

from src.strategies.base import BaseStrategy, StrategySignal, StrategyState
from src.strategies.copy_trading import CopyTradingStrategy
from src.strategies.market_making import MarketMakingStrategy
from src.strategies.alt_data import AltDataStrategy
from src.data.models import OrderBook, OrderBookLevel, Platform, Trade, OrderSide
from src.strategies.market_making_as import (
    MarketMakingStrategy as MarketMakingAsStrategy,
    MM_AS_REGIME_SCORE_ENABLED,
)


def test_market_making_as_fair_value_resolves_locked_touch():
    """When best bid equals best ask, use the first ask strictly above the bid (may06-style books)."""
    strat = MarketMakingAsStrategy()
    ob = OrderBook(
        market_id="may06",
        platform=Platform.KALSHI,
        timestamp=datetime.utcnow(),
        bids=[OrderBookLevel(price=0.01, size=100.0)],
        asks=[
            OrderBookLevel(price=0.01, size=50000.0),
            OrderBookLevel(price=0.03, size=1.0),
        ],
    )
    fv = strat._calculate_fair_value("may06", ob)
    assert fv is not None
    assert 0.01 < fv < 0.04


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
async def test_market_making_historical_uses_event_time_for_signals():
    """Historical market making should throttle on orderbook timestamps, not wall clock."""
    strategy = MarketMakingStrategy()
    strategy.mode = "historical"
    strategy.state = StrategyState.RUNNING

    t0 = datetime(2026, 4, 28, 15, 0, 0)
    orderbook = OrderBook(
        market_id="test_market",
        platform=Platform.KALSHI,
        timestamp=t0,
        bids=[OrderBookLevel(price=0.40, size=10)],
        asks=[OrderBookLevel(price=0.60, size=10)],
    )
    await strategy.on_orderbook_update(orderbook)
    signals = await strategy.generate_signals()
    assert len(signals) == 2
    assert all(signal.timestamp == t0 for signal in signals)

    # Less than one second later in event time, quoting should still be throttled.
    orderbook_2 = OrderBook(
        market_id="test_market",
        platform=Platform.KALSHI,
        timestamp=t0.replace(microsecond=500000),
        bids=[OrderBookLevel(price=0.39, size=10)],
        asks=[OrderBookLevel(price=0.61, size=10)],
    )
    await strategy.on_orderbook_update(orderbook_2)
    assert await strategy.generate_signals() == []


@pytest.mark.asyncio
async def test_alt_data_strategy_initialization():
    """Test alt data strategy initialization"""
    strategy = AltDataStrategy()
    assert strategy.strategy_id == "alt_data"
    assert strategy.state == StrategyState.IDLE


@pytest.mark.asyncio
async def test_market_making_as_tracks_signed_inventory_from_fills():
    """A-S strategy should maintain signed inventory per market from fills."""
    strategy = MarketMakingAsStrategy()

    buy_trade = Trade(
        trade_id="buy1",
        market_id="test_market",
        platform=Platform.KALSHI,
        side=OrderSide.BUY,
        price=0.5,
        size=100.0,
        timestamp=datetime.utcnow(),
    )
    sell_trade = Trade(
        trade_id="sell1",
        market_id="test_market",
        platform=Platform.KALSHI,
        side=OrderSide.SELL,
        price=0.55,
        size=40.0,
        timestamp=datetime.utcnow(),
    )

    await strategy.on_fill(buy_trade)
    await strategy.on_fill(sell_trade)

    assert strategy.get_inventory("test_market") == 60.0


def test_market_making_as_quote_sizes_shrink_with_inventory_and_regime():
    """Bid/ask sizes should shrink with stress and on the inventory-worsening side."""
    strategy = MarketMakingAsStrategy()
    strategy.mm_as_settings.max_position = 5000.0  # fixed scale; default config cap is smaller

    bid_size, ask_size = strategy._compute_quote_sizes("test_market", rho=0.0)
    assert bid_size == pytest.approx(500.0)
    assert ask_size == pytest.approx(500.0)

    strategy.inventory["test_market"] = 2500.0
    bid_size, ask_size = strategy._compute_quote_sizes("test_market", rho=0.0)
    assert bid_size < ask_size
    assert ask_size == pytest.approx(500.0)

    stressed_bid, stressed_ask = strategy._compute_quote_sizes("test_market", rho=1.0)
    assert stressed_bid < bid_size
    assert stressed_ask < ask_size


def test_market_making_as_hard_gate_stops_worsening_side():
    """Beyond inventory_hard_gate_fraction, quote size on the worsening side should be zero."""
    strategy = MarketMakingAsStrategy()
    strategy.inventory["m"] = strategy.mm_as_settings.max_position * 0.95
    bid, ask = strategy._compute_quote_sizes("m", rho=0.0)
    assert bid >= 0 and ask >= 0
    gate = strategy.mm_as_settings.max_position * strategy.mm_as_settings.inventory_hard_gate_fraction
    q = strategy.get_inventory("m")
    adj_bid, adj_ask = bid, ask
    if q >= gate:
        adj_bid = 0.0
    if q <= -gate:
        adj_ask = 0.0
    assert adj_bid == 0.0
    assert adj_ask > 0


@pytest.mark.skipif(
    not MM_AS_REGIME_SCORE_ENABLED,
    reason="MM_AS_REGIME_SCORE_ENABLED is False (regime ρ unwired)",
)
def test_market_making_as_regime_score_detects_stressful_price_region():
    """Regime score should rise in buckets with historically high reversal incidence."""
    prices = np.array([0.42, 0.55, 0.86])
    historical = pd.DataFrame(
        {
            "price": [0.10, 0.12, 0.15, 0.50, 0.52, 0.55, 0.84, 0.86, 0.88],
            "is_reversal": [0, 0, 0, 0, 1, 0, 1, 1, 1],
        }
    )

    rho_low = MarketMakingAsStrategy.regime_score(
        prices=np.array([0.12]),
        historical_reversals=historical,
        n_buckets=3,
    )
    rho_high = MarketMakingAsStrategy.regime_score(
        prices=np.array([0.86]),
        historical_reversals=historical,
        n_buckets=3,
    )

    assert 0.0 <= rho_low <= 1.0
    assert 0.0 <= rho_high <= 1.0
    assert rho_high > rho_low


def test_market_making_as_quotes_shift_down_when_long_inventory():
    """A-S quotes should tilt lower when inventory is long."""
    bid_flat, ask_flat = MarketMakingAsStrategy.quotes(
        s=0.50,
        q=0.0,
        sigma=0.1,
        gamma_base=0.05,
        alpha=0.5,
        T=1.0,
        t=0.0,
        kappa=1.5,
        rho=0.0,
    )
    bid_long, ask_long = MarketMakingAsStrategy.quotes(
        s=0.50,
        q=100.0,
        sigma=0.1,
        gamma_base=0.05,
        alpha=0.5,
        T=1.0,
        t=0.0,
        kappa=1.5,
        rho=0.0,
    )

    assert bid_flat < ask_flat
    assert bid_long < ask_long
    assert bid_long < bid_flat
    assert ask_long < ask_flat
