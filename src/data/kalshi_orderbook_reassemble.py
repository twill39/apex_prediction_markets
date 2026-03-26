"""Reassemble Kalshi orderbook at a timepoint T from stored historical market + orders."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.data.models import OrderBook, OrderBookLevel, Platform


def _parse_ts(value: Any) -> float:
    """Parse API timestamp to Unix seconds (float)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return value / 1000.0 if value > 1e12 else float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0
    return 0.0


def _order_price_dollars(order: dict, side: str) -> float:
    """Price in dollars (0-1) for the order. side is 'yes' or 'no'."""
    if side == "yes":
        p = order.get("yes_price_dollars") or order.get("yes_price")
        if p is None:
            return 0.0
        if isinstance(p, str):
            return float(p)
        return float(p) / 100.0 if p > 1 else float(p)
    else:
        p = order.get("no_price_dollars") or order.get("no_price")
        if p is None:
            return 0.0
        if isinstance(p, str):
            return float(p)
        return float(p) / 100.0 if p > 1 else float(p)


def _order_size(order: dict) -> float:
    """Size (contracts) for contribution to book. Use initial_count."""
    v = order.get("initial_count") or order.get("remaining_count") or 0
    if isinstance(v, str):
        return float(v)
    return float(v)


def aggregate_orders_at_t(
    orders: List[Dict[str, Any]],
    t_seconds: float,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    Orders that were resting at time T: created_time <= T < last_update_time.
    Returns (yes_bids, yes_asks) where each is list of (price_dollars, size).
    yes_bids from side=yes at yes_price; yes_asks from side=no at no_price -> yes_ask = 1 - no_price.
    """
    yes_bids: Dict[float, float] = defaultdict(float)
    no_bids: Dict[float, float] = defaultdict(float)

    for o in orders:
        created = _parse_ts(o.get("created_time"))
        updated = _parse_ts(o.get("last_update_time"))
        if updated <= 0:
            updated = float("inf")
        if not (created <= t_seconds < updated):
            continue
        side = (o.get("side") or "yes").lower()
        size = _order_size(o)
        if side == "yes":
            p = _order_price_dollars(o, "yes")
            yes_bids[p] += size
        else:
            p = _order_price_dollars(o, "no")
            no_bids[p] += size

    # Yes bids: list of (price, size), sorted price descending
    yes_bid_list = sorted([(p, s) for p, s in yes_bids.items() if s > 0], key=lambda x: -x[0])
    # Yes asks: no bid at P = sell YES at (1-P)
    yes_ask_list = sorted([(1.0 - p, s) for p, s in no_bids.items() if s > 0], key=lambda x: x[0])
    return (yes_bid_list, yes_ask_list)


def orderbook_at_t(
    ticker: str,
    orders: List[Dict[str, Any]],
    t_seconds: float,
    ts_datetime: Optional[datetime] = None,
) -> OrderBook:
    """Build OrderBook at time T from orders list."""
    yes_bids, yes_asks = aggregate_orders_at_t(orders, t_seconds)
    bids = [OrderBookLevel(price=p, size=s) for p, s in yes_bids]
    asks = [OrderBookLevel(price=p, size=s) for p, s in yes_asks]
    return OrderBook(
        market_id=ticker,
        platform=Platform.KALSHI,
        timestamp=ts_datetime or datetime.utcnow(),
        bids=bids,
        asks=asks,
    )


def iter_orderbooks(
    ticker: str,
    orders: List[Dict[str, Any]],
    start_ts: float,
    end_ts: float,
    step_seconds: float = 60.0,
) -> Iterator[Tuple[float, OrderBook]]:
    """Yield (timestamp_seconds, OrderBook) at each step in [start_ts, end_ts]."""
    t = start_ts
    while t <= end_ts:
        dt = datetime.utcfromtimestamp(t) if t else datetime.utcnow()
        ob = orderbook_at_t(ticker, orders, t, ts_datetime=dt)
        yield (t, ob)
        t += step_seconds


def get_orderbook_at(
    base_path: str,
    ticker: str,
    ts: float,
    market_data: Optional[Dict[str, Any]] = None,
    orders_data: Optional[List[Dict[str, Any]]] = None,
) -> Optional[OrderBook]:
    """
    Load stored data (if not provided), reassemble orderbook at ts (Unix seconds).
    Returns OrderBook or None if data missing.
    """
    from src.data.kalshi_historical_storage import load_market, load_orders

    if orders_data is None:
        orders_data = load_orders(base_path, ticker)
    if orders_data is None:
        return None
    market = market_data or load_market(base_path, ticker)
    ticker = ticker or (market.get("market", market) or {}).get("ticker", ticker)
    dt = datetime.utcfromtimestamp(ts) if ts else datetime.utcnow()
    return orderbook_at_t(ticker, orders_data, ts, ts_datetime=dt)
