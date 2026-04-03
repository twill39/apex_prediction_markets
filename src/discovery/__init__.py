"""Discovery of traders and markets for copy trading and market making."""

from .trader_discovery import (
    discover_traders,
    get_trader_ids_meeting_spec,
)
from .market_discovery import (
    discover_polymarket_markets,
    discover_kalshi_markets,
    discover_markets_for_making,
)
from .copy_trading_market_discovery import (
    discover_markets_for_copying,
    discover_insider_prone_markets,
    discover_markets_from_traders,
)

__all__ = [
    "discover_traders",
    "get_trader_ids_meeting_spec",
    "discover_polymarket_markets",
    "discover_kalshi_markets",
    "discover_markets_for_making",
    "discover_markets_for_copying",
    "discover_insider_prone_markets",
    "discover_markets_from_traders",
]
