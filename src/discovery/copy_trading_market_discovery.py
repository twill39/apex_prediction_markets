"""Discover markets for copy trading by analyzing tracked trader activity
and identifying insider-prone market categories."""

import json
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from ._http import get_json
from .trader_discovery import get_user_trades, get_user_positions

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"

# Keywords associated with markets historically prone to insider trading.
# These categories often have outcomes known to insiders before public resolution.
INSIDER_PRONE_KEYWORDS = [
    # Entertainment / social media metrics — employees, analysts, partners know
    "youtube", "subscriber", "mrbeast", "twitch", "spotify", "box office",
    "followers", "views", "ratings", "streams", "downloads", "tiktok",
    # Crypto / token announcements — team insiders, exchange staff
    "airdrop", "token", "launch", "listing", "delist", "mainnet",
    "testnet", "upgrade", "fork", "halving", "etf",
    # Corporate events — employees, auditors, board members
    "earnings", "revenue", "acquisition", "merger", "ipo", "layoff",
    "ceo", "resign", "fired", "hired", "partnership",
    # Product / tech releases — employees, supply chain, testers
    "release", "announcement", "leak", "update", "feature",
    "iphone", "android", "google", "apple", "microsoft", "nvidia",
    # Entertainment media — studios, distributors, reviewers
    "hbo", "netflix", "disney", "amazon prime", "oscar", "grammy",
    "emmy", "golden globe", "premiere", "cancel", "renew", "season",
]


def discover_markets_from_traders(
    tracked_traders: Set[str],
    max_markets: int = 200,
) -> List[Dict[str, Any]]:
    """Discover markets by analyzing where tracked traders are active.

    For each tracked trader, fetches their recent trades and open positions,
    collects the CLOB token IDs (asset IDs), and ranks markets by how many
    tracked traders are active in them.

    Args:
        tracked_traders: Set of proxy wallet addresses from screeners.
        max_markets: Maximum number of asset IDs to return.

    Returns:
        List of dicts with keys: asset_id, trader_count, source.
        Sorted by trader_count descending (most popular among tracked traders first).
    """
    # Count how many tracked traders are active per asset
    asset_counter: Counter = Counter()
    asset_sources: Dict[str, str] = {}  # asset_id -> 'trades' or 'positions'

    for trader_id in tracked_traders:
        seen_assets: Set[str] = set()

        # Fetch recent trades
        trades = get_user_trades(trader_id, limit=200)
        for t in trades:
            asset = t.get("asset")
            if asset and asset not in seen_assets:
                seen_assets.add(asset)
                asset_counter[asset] += 1
                asset_sources.setdefault(asset, "trades")

        # Fetch open positions
        positions = get_user_positions(trader_id, limit=100)
        for p in positions:
            asset = p.get("asset")
            if asset and asset not in seen_assets:
                seen_assets.add(asset)
                asset_counter[asset] += 1
                asset_sources.setdefault(asset, "positions")

    # Sort by number of tracked traders active in each market
    ranked = asset_counter.most_common(max_markets)

    return [
        {
            "asset_id": asset_id,
            "trader_count": count,
            "source": asset_sources.get(asset_id, "unknown"),
        }
        for asset_id, count in ranked
    ]


def discover_insider_prone_markets(
    max_results: int = 200,
    keywords: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch active Polymarket events and filter for insider-prone categories.

    Scans event titles/slugs for keywords associated with markets where
    insider information is historically common (entertainment metrics,
    crypto launches, corporate announcements, etc.).

    Args:
        max_results: Maximum number of markets to return.
        keywords: Custom keyword list. Defaults to INSIDER_PRONE_KEYWORDS.

    Returns:
        List of dicts with keys: asset_id, slug, title, matched_keyword.
    """
    kw_list = keywords or INSIDER_PRONE_KEYWORDS
    results: List[Dict[str, Any]] = []
    offset = 0
    limit = 100

    while len(results) < max_results:
        url = (
            f"{GAMMA_EVENTS_URL}?active=true&closed=false"
            f"&limit={limit}&offset={offset}"
        )
        data = get_json(url)
        if not isinstance(data, list) or not data:
            break

        for event in data:
            if len(results) >= max_results:
                break

            title = (event.get("title") or "").lower()
            slug = (event.get("slug") or "").lower()
            search_text = f"{title} {slug}"

            matched = None
            for kw in kw_list:
                if kw in search_text:
                    matched = kw
                    break

            if not matched:
                continue

            # Extract CLOB token IDs from the event's markets
            markets = event.get("markets") or []
            for m in markets:
                if len(results) >= max_results:
                    break

                raw_ids = m.get("clobTokenIds")
                if isinstance(raw_ids, str):
                    try:
                        token_ids = json.loads(raw_ids)
                    except json.JSONDecodeError:
                        token_ids = []
                else:
                    token_ids = raw_ids or []

                for tid in token_ids:
                    if len(results) >= max_results:
                        break
                    results.append({
                        "asset_id": str(tid),
                        "slug": event.get("slug") or "",
                        "title": m.get("question") or event.get("title") or "",
                        "matched_keyword": matched,
                    })

        offset += limit
        if len(data) < limit:
            break

    return results


def discover_markets_for_copying(
    tracked_traders: Set[str],
    max_trader_markets: int = 150,
    max_insider_markets: int = 100,
    max_total: int = 200,
) -> List[str]:
    """Combined market discovery for copy trading.

    Merges trader-derived markets (highest priority) with insider-prone
    category markets, deduplicates, and returns a flat list of asset IDs
    ready for WebSocket subscription.

    Args:
        tracked_traders: Set of proxy wallet addresses from screeners.
        max_trader_markets: Max markets to pull from trader activity.
        max_insider_markets: Max markets to pull from insider categories.
        max_total: Max total asset IDs to return.

    Returns:
        List of unique CLOB token ID strings.
    """
    seen: Set[str] = set()
    ordered: List[str] = []

    # 1. Trader-derived markets (highest priority — these are where our
    #    vetted traders are actually active right now)
    if tracked_traders:
        trader_markets = discover_markets_from_traders(
            tracked_traders, max_markets=max_trader_markets
        )
        for m in trader_markets:
            aid = m["asset_id"]
            if aid not in seen:
                seen.add(aid)
                ordered.append(aid)

    # 2. Insider-prone category markets (fills in markets our traders
    #    haven't entered yet but are likely targets)
    insider_markets = discover_insider_prone_markets(
        max_results=max_insider_markets
    )
    for m in insider_markets:
        aid = m["asset_id"]
        if aid not in seen:
            seen.add(aid)
            ordered.append(aid)

    return ordered[:max_total]
