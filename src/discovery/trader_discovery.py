"""Discover Polymarket traders by leaderboard: low volume, high PnL (edge)."""

from typing import List, Optional

from ._http import get_json

DATA_API_LEADERBOARD = "https://data-api.polymarket.com/v1/leaderboard"

# Leaderboard limit per request (API max 50)
PAGE_LIMIT = 50
# Max offset (API allows 0-1000)
MAX_OFFSET = 1000


def discover_traders(
    max_volume: Optional[float] = None,
    min_pnl: Optional[float] = None,
    min_pnl_per_vol: Optional[float] = None,
    time_period: str = "WEEK",
    category: str = "OVERALL",
    max_results: int = 200,
) -> List[dict]:
    """
    Fetch Polymarket leaderboard and filter for low volume + high PnL traders.

    Args:
        max_volume: Include only traders with vol <= this (None = no cap).
        min_pnl: Include only traders with pnl >= this (None = no floor).
        min_pnl_per_vol: Include only traders with (pnl/vol) >= this when vol > 0 (None = no floor).
        time_period: DAY, WEEK, MONTH, or ALL.
        category: OVERALL, POLITICS, SPORTS, CRYPTO, etc.
        max_results: Stop after collecting this many candidates (before filtering).

    Returns:
        List of dicts with keys: proxyWallet, userName, vol, pnl, (pnl_per_vol if vol > 0).
    """
    results: List[dict] = []
    offset = 0

    while offset <= MAX_OFFSET and len(results) < max_results:
        url = (
            f"{DATA_API_LEADERBOARD}?"
            f"category={category}&timePeriod={time_period}&orderBy=PNL&"
            f"limit={PAGE_LIMIT}&offset={offset}"
        )
        data = get_json(url)
        if not isinstance(data, list):
            break
        if not data:
            break
        for entry in data:
            if len(results) >= max_results:
                break
            proxy = entry.get("proxyWallet") or entry.get("proxy_wallet")
            if not proxy:
                continue
            vol = _num(entry.get("vol"))
            pnl = _num(entry.get("pnl"))
            pnl_per_vol = (pnl / vol) if vol and vol > 0 else None
            row = {
                "proxyWallet": proxy,
                "userName": entry.get("userName") or entry.get("user_name") or "",
                "vol": vol,
                "pnl": pnl,
                "rank": entry.get("rank"),
            }
            if pnl_per_vol is not None:
                row["pnl_per_vol"] = pnl_per_vol

            if max_volume is not None and (vol is None or vol > max_volume):
                continue
            if min_pnl is not None and (pnl is None or pnl < min_pnl):
                continue
            if min_pnl_per_vol is not None and (pnl_per_vol is None or pnl_per_vol < min_pnl_per_vol):
                continue

            results.append(row)
        offset += PAGE_LIMIT
        if len(data) < PAGE_LIMIT:
            break

    return results


def get_trader_ids_meeting_spec(
    max_volume: Optional[float] = None,
    min_pnl: Optional[float] = None,
    min_pnl_per_vol: Optional[float] = None,
    time_period: str = "WEEK",
    category: str = "OVERALL",
    max_traders: int = 50,
) -> List[str]:
    """
    Return list of proxyWallet addresses for traders meeting the spec.
    Suitable for copy_trading strategy (tracked_traders).
    """
    traders = discover_traders(
        max_volume=max_volume,
        min_pnl=min_pnl,
        min_pnl_per_vol=min_pnl_per_vol,
        time_period=time_period,
        category=category,
        max_results=max_traders,
    )
    return [t["proxyWallet"] for t in traders]


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
