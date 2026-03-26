"""Thin REST client for Polymarket Gamma (events/markets), CLOB (prices-history), and Data API (trades). No auth required for read endpoints."""

import time
from typing import Any, Dict, List, Optional

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
DEFAULT_TIMEOUT = 30
TRADES_PAGE_SIZE = 10000


def get_events(
    limit: int = 100,
    offset: int = 0,
    active: Optional[bool] = None,
    closed: Optional[bool] = None,
    slug: Optional[str] = None,
    tag_id: Optional[str] = None,
    order: Optional[str] = None,
    ascending: Optional[bool] = None,
    start_date_min: Optional[str] = None,
    end_date_max: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    GET /events. Returns list of events (empty list on failure).
    """
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if active is not None:
        params["active"] = str(active).lower()
    if closed is not None:
        params["closed"] = str(closed).lower()
    if slug:
        params["slug"] = slug
    if tag_id:
        params["tag_id"] = tag_id
    if order:
        params["order"] = order
    if ascending is not None:
        params["ascending"] = str(ascending).lower()
    if start_date_min:
        params["start_date_min"] = start_date_min
    if end_date_max:
        params["end_date_max"] = end_date_max

    try:
        r = requests.get(f"{GAMMA_BASE}/events", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_event_by_slug(slug: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[Dict[str, Any]]:
    """
    Fetch a single event by slug. Uses GET /events?slug=... and returns first event or None.
    """
    events = get_events(limit=1, slug=slug, timeout=timeout)
    return events[0] if events else None


def get_prices_history(
    token_id: str,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    interval: str = "1m",
    fidelity: Optional[int] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """
    GET /prices-history. Returns { "history": [ { "t": unix_ts, "p": price } ] }.
    interval: 1m, 1h, 6h, 1d, 1w, max, all.
    """
    params: Dict[str, Any] = {"market": token_id, "interval": interval}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    if fidelity is not None:
        params["fidelity"] = fidelity

    try:
        r = requests.get(f"{CLOB_BASE}/prices-history", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {"history": []}
    except Exception:
        return {"history": []}


def get_trades(
    market_condition_ids: Optional[List[str]] = None,
    event_id: Optional[int] = None,
    limit: int = TRADES_PAGE_SIZE,
    offset: int = 0,
    taker_only: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    GET /trades (Data API). Returns list of trade objects (asset, conditionId, price, size, timestamp, side, ...).
    market_condition_ids: list of 0x-prefixed 64-char hex condition IDs (comma-separated in request).
    event_id: event ID (integer). Mutually exclusive with market_condition_ids; prefer market when available.
    """
    params: Dict[str, Any] = {"limit": limit, "offset": offset, "takerOnly": str(taker_only).lower()}
    if market_condition_ids:
        params["market"] = ",".join(market_condition_ids)
    elif event_id is not None:
        params["eventId"] = event_id
    else:
        return []

    try:
        r = requests.get(f"{DATA_API_BASE}/trades", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_trades_all(
    market_condition_ids: Optional[List[str]] = None,
    event_id: Optional[int] = None,
    taker_only: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
    sleep_between_pages: float = 0.2,
) -> List[Dict[str, Any]]:
    """Paginate GET /trades until no more results. Returns full list of trades."""
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = get_trades(
            market_condition_ids=market_condition_ids,
            event_id=event_id,
            limit=TRADES_PAGE_SIZE,
            offset=offset,
            taker_only=taker_only,
            timeout=timeout,
        )
        out.extend(page)
        if len(page) < TRADES_PAGE_SIZE:
            break
        offset += TRADES_PAGE_SIZE
        if sleep_between_pages > 0:
            time.sleep(sleep_between_pages)
    return out
