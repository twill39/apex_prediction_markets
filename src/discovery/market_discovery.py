"""Discover markets on Polymarket and Kalshi suitable for market making: decent liquidity, high spread."""

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ._http import get_json

# Polymarket Gamma
GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"

# Kalshi (public markets endpoint - no auth required for GET /markets)
DEFAULT_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _parse_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def discover_polymarket_markets(
    min_liquidity: float = 0,
    min_spread_pct: float = 0,
    max_results: int = 100,
    order: str = "volume_24hr",
) -> List[Dict[str, Any]]:
    """
    Fetch Gamma events/markets and return those with sufficient liquidity and spread.

    Args:
        min_liquidity: Minimum liquidity (numeric) per market.
        min_spread_pct: Minimum spread as fraction of mid (e.g. 0.01 = 1%).
        max_results: Max number of markets to return.
        order: Sort key for events: volume_24hr, volume, liquidity.

    Returns:
        List of dicts with: platform='polymarket', market_id (clob token id), slug, spread, liquidity, volume, title.
    """
    results: List[Dict[str, Any]] = []
    offset = 0
    limit = 100

    while len(results) < max_results:
        url = (
            f"{GAMMA_EVENTS_URL}?active=true&closed=false&limit={limit}&offset={offset}"
            f"&order={order}&ascending=false"
        )
        data = get_json(url)
        if not isinstance(data, list):
            break
        if not data:
            break

        for event in data:
            if len(results) >= max_results:
                break
            slug = event.get("slug") or event.get("ticker") or ""
            markets = event.get("markets") or []
            for m in markets:
                if len(results) >= max_results:
                    break
                vol = _parse_float(m.get("volumeNum") or m.get("volume"))
                liq = _parse_float(m.get("liquidity") or m.get("liquidity_num"))
                best_bid = _parse_float(m.get("bestBid"))
                best_ask = _parse_float(m.get("bestAsk"))
                spread_pct = None
                if best_bid is not None and best_ask is not None and best_bid > 0:
                    mid = (best_bid + best_ask) / 2
                    if mid > 0:
                        spread_pct = (best_ask - best_bid) / mid

                if min_liquidity and (liq is None or liq < min_liquidity):
                    continue
                if min_spread_pct > 0 and (spread_pct is None or spread_pct < min_spread_pct):
                    continue

                clob_ids_raw = m.get("clobTokenIds")
                if isinstance(clob_ids_raw, str):
                    try:
                        token_ids = json.loads(clob_ids_raw)
                    except json.JSONDecodeError:
                        token_ids = []
                else:
                    token_ids = clob_ids_raw or []
                if not token_ids:
                    continue

                for tid in token_ids:
                    tid_str = str(tid)
                    results.append({
                        "platform": "polymarket",
                        "market_id": tid_str,
                        "slug": slug,
                        "spread_pct": spread_pct,
                        "liquidity": liq,
                        "volume": vol,
                        "title": m.get("question") or event.get("title") or tid_str,
                    })
                    if len(results) >= max_results:
                        break

        offset += limit
        if len(data) < limit:
            break

    return results


def discover_kalshi_markets(
    base_url: str = DEFAULT_KALSHI_BASE,
    min_spread_pct: float = 0,
    min_volume_24h: float = 0,
    max_results: int = 100,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch Kalshi open markets and return those with sufficient spread and volume.

    Args:
        base_url: Kalshi API base URL (e.g. from credentials).
        min_spread_pct: Minimum spread as fraction of mid (e.g. 0.01 = 1%).
        min_volume_24h: Minimum 24h volume in contracts (Kalshi ``volume_24h_fp``), not dollars.
        max_results: Max number of markets to return.
        max_pages: Max GET /markets pages to fetch (100 markets per page). None = until cursor ends.

    Returns:
        List of dicts with: platform='kalshi', market_id (ticker), spread_pct, volume_24h, title.
    """
    results: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    limit = 100
    page_num = 0

    while len(results) < max_results:
        page_num += 1
        if max_pages is not None and page_num > max_pages:
            break
        url = f"{base_url.rstrip('/')}/markets?status=open&limit={limit}"
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        data = get_json(url)
        if not isinstance(data, dict):
            break
        markets = data.get("markets") or []
        cursor = data.get("cursor")

        for m in markets:
            if len(results) >= max_results:
                break
            ticker = m.get("ticker")
            if not ticker:
                continue
            yes_bid = _parse_float(m.get("yes_bid_dollars") or m.get("yes_bid"))
            yes_ask = _parse_float(m.get("yes_ask_dollars") or m.get("yes_ask"))
            vol_24 = _parse_float(m.get("volume_24h_fp"))
            if vol_24 is None:
                vol_24 = _parse_float(m.get("volume_24h"))
            vol_24 = vol_24 or 0

            spread_pct = None
            if yes_bid is not None and yes_ask is not None and yes_bid >= 0 and yes_ask >= 0:
                mid = (yes_bid + yes_ask) / 2
                if mid > 0:
                    spread_pct = (yes_ask - yes_bid) / mid

            if min_volume_24h and vol_24 < min_volume_24h:
                continue
            if min_spread_pct > 0 and (spread_pct is None or spread_pct < min_spread_pct):
                continue

            results.append({
                "platform": "kalshi",
                "market_id": ticker,
                "spread_pct": spread_pct,
                "volume_24h": vol_24,
                "title": m.get("title") or ticker,
            })

        if not cursor or not markets:
            break

    return results


def discover_markets_for_making(
    min_liquidity_poly: float = 0,
    min_spread_pct: float = 0.005,
    min_volume_24h_kalshi: float = 0,
    max_poly: int = 50,
    max_kalshi: int = 50,
    kalshi_base_url: str = DEFAULT_KALSHI_BASE,
    kalshi_max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Return combined list of Polymarket + Kalshi markets suitable for market making.
    Each item has platform and market_id for subscription.
    """
    poly = discover_polymarket_markets(
        min_liquidity=min_liquidity_poly,
        min_spread_pct=min_spread_pct,
        max_results=max_poly,
    )
    kalshi = discover_kalshi_markets(
        base_url=kalshi_base_url,
        min_spread_pct=min_spread_pct,
        min_volume_24h=min_volume_24h_kalshi,
        max_results=max_kalshi,
        max_pages=kalshi_max_pages,
    )
    return poly + kalshi
