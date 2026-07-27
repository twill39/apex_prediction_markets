"""Tests for simulator"""

import asyncio
import pytest
import json
import time
from datetime import datetime
from unittest.mock import Mock

from src.simulator.historical import HistoricalSimulator
from src.simulator.paper_trading import PaperTradingSimulator
from src.simulator.metrics import calculate_metrics, PerformanceMetrics
from src.data.models import (
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    Platform,
    Position,
    PositionSide,
    Trade,
    OrderSide,
)
from src.strategies.base import StrategySignal
from src.strategies.market_making import MarketMakingStrategy
from src.strategies.base import StrategyState
from src.strategies.market_making_as import (
    MarketMakingStrategy as MarketMakingAsStrategy,
)


def test_historical_simulator_initialization():
    """Test historical simulator initialization"""
    simulator = HistoricalSimulator()
    assert simulator.mode.value == "historical"
    assert simulator.initial_balance == 100.0


def test_paper_trading_simulator_initialization():
    """Test paper trading simulator initialization"""
    simulator = PaperTradingSimulator()
    assert simulator.mode.value == "paper"
    assert simulator.initial_balance == 100.0


def test_paper_trading_load_bounds(tmp_path):
    """Paper simulator should load band metadata keyed by ticker."""
    bounds_path = tmp_path / "bounds.json"
    bounds_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "ticker": "KXINX-26MAY01H1600-B7237",
                        "has_bounds": True,
                        "lower_bound": 7200.0,
                        "upper_bound": 7250.0,
                        "eod_timestamp": 1714579200.0,
                    }
                ]
            }
        )
    )
    simulator = PaperTradingSimulator(bounds_file=str(bounds_path))
    assert "KXINX-26MAY01H1600-B7237" in simulator._market_bounds
    meta = simulator._market_bounds["KXINX-26MAY01H1600-B7237"]
    assert meta["lower_bound"] == 7200.0
    assert meta["upper_bound"] == 7250.0


@pytest.mark.asyncio
async def test_paper_trading_injects_bounds_once(tmp_path):
    """Bounds should be injected as a single MARKET_UPDATE per market."""
    bounds_path = tmp_path / "bounds.json"
    ticker = "KXINX-26MAY01H1600-B7237"
    bounds_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "ticker": ticker,
                        "has_bounds": True,
                        "lower_bound": 7200.0,
                        "upper_bound": 7250.0,
                        "eod_timestamp": 1714579200.0,
                    }
                ]
            }
        )
    )

    class RecordingStrategy(MarketMakingStrategy):
        def __init__(self):
            super().__init__()
            self.bounds_events = []

        async def on_market_event(self, event):
            if event.data.get("lower_bound") is not None:
                self.bounds_events.append(event.data)
            await super().on_market_event(event)

    simulator = PaperTradingSimulator(bounds_file=str(bounds_path))
    strategy = RecordingStrategy()
    simulator.add_strategy(strategy)

    await simulator._maybe_inject_bounds(ticker)
    await simulator._maybe_inject_bounds(ticker)

    assert len(strategy.bounds_events) == 1
    assert strategy.bounds_events[0]["lower_bound"] == 7200.0
    assert ticker in simulator._bounds_injected


def _paper_book(market_id: str = "KXTEST") -> OrderBook:
    return OrderBook(
        market_id=market_id,
        platform=Platform.KALSHI,
        bids=[OrderBookLevel(price=0.40, size=10)],
        asks=[OrderBookLevel(price=0.60, size=10)],
    )


@pytest.mark.asyncio
async def test_paper_cancel_replace_persists_partial_order_cancellation():
    simulator = PaperTradingSimulator()
    simulator.storage = Mock()
    simulator.market_state["KXTEST"] = {"orderbook": _paper_book()}

    first = StrategySignal(
        market_id="KXTEST",
        platform=Platform.KALSHI,
        side="buy",
        size=3,
        price=0.40,
        order_type="limit",
    )
    await simulator.execute_signal(first, strategy_id="test")
    old = next(iter(simulator.pending_orders.values()))
    old.status = OrderStatus.PARTIALLY_FILLED
    old.filled_size = 1
    old.size = 2

    replacement = first.model_copy(update={"price": 0.39})
    await simulator.execute_signal(replacement, strategy_id="test")

    assert old.status == OrderStatus.CANCELLED
    assert old.metadata["cancel_reason"] == "replaced"
    assert len(simulator.pending_orders) == 1
    assert next(iter(simulator.pending_orders.values())).price == pytest.approx(0.39)
    simulator.storage.save_order.assert_any_call(old)


@pytest.mark.asyncio
async def test_paper_cancel_during_latency_prevents_fill():
    simulator = PaperTradingSimulator()
    simulator.storage = Mock()
    simulator.settings.simulator.latency_ms = 50
    book = _paper_book()
    simulator.market_state["KXTEST"] = {"orderbook": book}
    signal = StrategySignal(
        market_id="KXTEST",
        platform=Platform.KALSHI,
        side="buy",
        size=2,
        price=0.60,
        order_type="limit",
    )
    await simulator.execute_signal(signal, strategy_id="test")
    order = next(iter(simulator.pending_orders.values()))

    fill_task = asyncio.create_task(
        simulator._fill_order(order, book, execution_price_override=0.60)
    )
    await asyncio.sleep(0.01)
    await simulator.execute_signal(
        signal.model_copy(update={"size": 0.0}), strategy_id="test"
    )
    assert await fill_task is None

    assert order.status == OrderStatus.CANCELLED
    assert simulator.trades == []
    assert simulator.pending_orders == {}


@pytest.mark.asyncio
async def test_paper_public_trade_fills_passive_limit():
    simulator = PaperTradingSimulator()
    simulator.storage = Mock()
    simulator.settings.simulator.latency_ms = 0
    simulator.current_balance = 100.0
    book = _paper_book()
    simulator.market_state["KXTEST"] = {"orderbook": book}
    await simulator.execute_signal(
        StrategySignal(
            market_id="KXTEST",
            platform=Platform.KALSHI,
            side="buy",
            size=2,
            price=0.40,
            order_type="limit",
        ),
        strategy_id="test",
    )

    await simulator._check_trade_fills(
        Trade(
            trade_id="public-1",
            market_id="KXTEST",
            platform=Platform.KALSHI,
            side=OrderSide.SELL,
            price=0.40,
            size=2,
        )
    )

    assert len(simulator.trades) == 1
    assert simulator.trades[0].price == pytest.approx(0.40)
    assert simulator.pending_orders == {}


@pytest.mark.asyncio
async def test_paper_eod_signal_flattens_strategy_and_simulator_inventory():
    simulator = PaperTradingSimulator()
    simulator.use_schwab_spx = False
    simulator.storage = Mock()
    simulator.settings.simulator.latency_ms = 0
    book = _paper_book()
    simulator.market_state["KXTEST"] = {"orderbook": book}
    simulator.positions["KXTEST_kalshi"] = Position(
        position_id="KXTEST_kalshi",
        market_id="KXTEST",
        platform=Platform.KALSHI,
        side=PositionSide.LONG,
        size=3,
        average_price=0.35,
        opened_at=datetime.utcnow(),
    )

    strategy = MarketMakingAsStrategy()
    strategy.state = StrategyState.RUNNING
    strategy.orderbooks["KXTEST"] = book
    strategy.active_markets["KXTEST"] = {
        "platform": Platform.KALSHI,
        "eod_timestamp": time.time() - 1,
    }
    strategy.inventory["KXTEST"] = 3
    simulator.add_strategy(strategy)

    await simulator._process_strategy_signals()

    assert strategy.get_inventory("KXTEST") == pytest.approx(0)
    assert simulator.positions["KXTEST_kalshi"].size == pytest.approx(0)
    assert len(simulator.trades) == 1
    assert simulator.trades[0].side == OrderSide.SELL


def test_paper_feed_health_fails_closed_while_waiting_for_fresh_snapshot():
    simulator = PaperTradingSimulator(markets=["KXTEST"])
    simulator.use_schwab_spx = False
    simulator.settings.simulator.feed_startup_grace_seconds = 1
    simulator.settings.simulator.market_data_stale_seconds = 5
    simulator._run_started_monotonic = time.monotonic() - 10
    simulator._subscribed_market_ids = {"KXTEST"}
    simulator._market_unready_since = {"KXTEST": time.monotonic() - 10}

    assert (
        simulator._feed_health_error()
        == "no fresh orderbook snapshot for KXTEST after 10s"
    )


def test_paper_feed_health_allows_quiet_book_after_valid_snapshot():
    simulator = PaperTradingSimulator(markets=["KXTEST"])
    simulator.use_schwab_spx = False
    simulator.settings.simulator.feed_startup_grace_seconds = 1
    simulator.settings.simulator.market_data_stale_seconds = 5
    simulator._run_started_monotonic = time.monotonic() - 300
    simulator._subscribed_market_ids = {"KXTEST"}
    simulator._last_orderbook_monotonic = {"KXTEST": time.monotonic() - 300}
    simulator._market_unready_since = {}

    assert simulator._feed_health_error() is None


def test_schwab_parse_stream_price():
    from src.websockets.schwab import _parse_stream_price

    message = json.dumps(
        {
            "data": [
                {
                    "service": "CHART_EQUITY",
                    "content": [{"key": "$SPX", "4": 5234.5}],
                }
            ]
        }
    )
    assert _parse_stream_price(message, "$SPX") == 5234.5


def test_schwab_parse_quote_response():
    from src.websockets.schwab import _parse_quote_response

    payload = {
        "$SPX": {
            "quote": {
                "lastPrice": 5200.25,
            }
        }
    }
    assert _parse_quote_response(payload, "$SPX") == 5200.25


def test_historical_simulator_merges_underlying_timeline(tmp_path):
    """Historical simulator should merge underlying minute events into replay order."""
    orderbook_path = tmp_path / "frames.jsonl"
    orderbook_row = {
        "t": 1714485600,  # 2024-04-30T14:00:00Z
        "bids": [[0.45, 10]],
        "asks": [[0.54, 12]],
    }
    orderbook_path.write_text(json.dumps(orderbook_row) + "\n")

    underlying_path = tmp_path / "spx.csv"
    underlying_path.write_text(
        "timestamp_utc,close\n"
        "2024-04-30T13:59:00Z,5100.0\n"
        "2024-04-30T14:01:00Z,5101.5\n"
    )

    simulator = HistoricalSimulator(
        underlying_path=str(underlying_path),
        underlying_symbol="$SPX",
    )
    simulator.load_historical_data(str(orderbook_path))

    assert len(simulator.events) == 3
    assert simulator.events[0]["type"] == "market_update"
    assert simulator.events[1]["type"] == "orderbook_update"
    assert simulator.events[2]["type"] == "market_update"

    first_update = simulator.events[0]["data"]
    assert first_update["update_type"] == "underlying_price"
    assert first_update["symbol"] == "$SPX"


def test_historical_simulator_regular_session_filter_et():
    """Session filter should keep 9:30-16:00 ET and drop outside timestamps."""
    simulator = HistoricalSimulator(historical_rth_only=True)

    in_session = {"timestamp": "2024-05-01T13:30:00+00:00"}  # 9:30 ET
    late_session = {"timestamp": "2024-05-01T20:00:00+00:00"}  # 16:00 ET
    premarket = {"timestamp": "2024-05-01T13:29:59+00:00"}  # 9:29:59 ET
    after_hours = {"timestamp": "2024-05-01T20:00:01+00:00"}  # 16:00:01 ET

    assert simulator._is_in_regular_session(in_session) is True
    assert simulator._is_in_regular_session(late_session) is True
    assert simulator._is_in_regular_session(premarket) is False
    assert simulator._is_in_regular_session(after_hours) is False


@pytest.mark.asyncio
async def test_historical_limit_cancel_replace_and_zero_size_cancel(tmp_path):
    """One live limit per side; zero-size limit cancels without enqueueing."""
    from src.strategies.base import StrategySignal
    from src.data.models import Platform

    orderbook_path = tmp_path / "frames.jsonl"
    orderbook_path.write_text(
        json.dumps({"t": 1714485600, "bids": [[0.45, 10]], "asks": [[0.55, 12]]}) + "\n"
    )

    sim = HistoricalSimulator(markets=["may04"])
    sim.load_historical_data(str(orderbook_path))
    evt = sim.events[-1]
    ts = sim._get_event_timestamp(evt)

    class Strat:
        def __init__(self):
            self.out: list = []

        async def generate_signals(self):
            return self.out

        async def on_orderbook_update(self, orderbook):
            return None

        async def on_market_event(self, event):
            return None

        async def on_trade(self, trade):
            return None

    st = Strat()
    sim.strategies = [st]

    st.out = [
        StrategySignal(
            market_id="may04",
            platform=Platform.KALSHI,
            side="buy",
            size=10.0,
            price=0.40,
            order_type="limit",
            timestamp=ts,
        ),
        StrategySignal(
            market_id="may04",
            platform=Platform.KALSHI,
            side="sell",
            size=5.0,
            price=0.60,
            order_type="limit",
            timestamp=ts,
        ),
    ]
    await sim._process_event(evt)
    assert len(sim.pending_orders) == 2

    st.out = [
        StrategySignal(
            market_id="may04",
            platform=Platform.KALSHI,
            side="buy",
            size=20.0,
            price=0.41,
            order_type="limit",
            timestamp=ts,
        ),
    ]
    await sim._process_event(evt)
    buy_sizes = [o["signal"].size for o in sim.pending_orders if o["signal"].side == "buy"]
    assert buy_sizes == [20.0]

    st.out = [
        StrategySignal(
            market_id="may04",
            platform=Platform.KALSHI,
            side="buy",
            size=0.0,
            price=0.41,
            order_type="limit",
            timestamp=ts,
        ),
    ]
    await sim._process_event(evt)
    assert not any(o["signal"].side == "buy" for o in sim.pending_orders)


def test_historical_signed_inventory_cap_limits_additional_buys():
    """Fills must not push signed inventory above simulator.max_signed_inventory."""
    sim = HistoricalSimulator()
    sim.settings.simulator.max_signed_inventory = 5000.0
    sim.settings.simulator.enforce_signed_inventory_cap = True
    sim.positions["may04_kalshi"] = Position(
        position_id="may04_kalshi",
        market_id="may04",
        platform=Platform.KALSHI,
        side=PositionSide.LONG,
        size=4990.0,
        average_price=0.5,
        opened_at=datetime.utcnow(),
    )
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "buy", 500.0) == 10.0
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "sell", 500.0) == 500.0

    sim.positions["may04_kalshi"] = Position(
        position_id="may04_kalshi",
        market_id="may04",
        platform=Platform.KALSHI,
        side=PositionSide.SHORT,
        size=4990.0,
        average_price=0.5,
        opened_at=datetime.utcnow(),
    )
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "sell", 500.0) == 10.0
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "buy", 500.0) == 500.0


def test_historical_signed_inventory_cap_zero_uses_mm_as_max_position():
    """max_signed_inventory<=0 must not disable enforcement; fall back to MM-AS max_position."""
    sim = HistoricalSimulator()
    sim.settings.simulator.max_signed_inventory = 0.0
    sim.settings.simulator.enforce_signed_inventory_cap = True
    sim.settings.market_making_as.max_position = 250.0
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "buy", 10_000.0) == 250.0
    sim.positions["may04_kalshi"] = Position(
        position_id="may04_kalshi",
        market_id="may04",
        platform=Platform.KALSHI,
        side=PositionSide.LONG,
        size=240.0,
        average_price=0.5,
        opened_at=datetime.utcnow(),
    )
    assert sim._allowed_fill_size("may04", Platform.KALSHI, "buy", 500.0) == 10.0


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
    assert metrics.cash_balance == 10000.0
    assert metrics.inventory_value == 50.0
    assert metrics.unrealized_pnl == 0.0
    assert metrics.total_pnl == 50.0
    assert metrics.start_time is not None
    assert metrics.end_time is not None


def test_metrics_short_inventory_mark_to_market():
    """Short positions should contribute negative inventory value and unrealized P&L."""
    trades = [
        Trade(
            trade_id="1",
            market_id="test",
            platform=Platform.KALSHI,
            side=OrderSide.SELL,
            price=0.4,
            size=100.0,
            timestamp=datetime.utcnow()
        )
    ]
    positions = [
        Position(
            position_id="test_kalshi",
            market_id="test",
            platform=Platform.KALSHI,
            side=PositionSide.SHORT,
            size=100.0,
            average_price=0.4,
            current_price=0.3,
            opened_at=datetime.utcnow(),
        )
    ]

    metrics = calculate_metrics(
        trades=trades,
        positions=positions,
        initial_balance=10000.0,
        current_balance=10040.0,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow()
    )

    assert metrics.cash_balance == 10040.0
    assert metrics.inventory_value == -30.0
    assert metrics.unrealized_pnl == pytest.approx(10.0)
    assert metrics.total_pnl == pytest.approx(10.0)
