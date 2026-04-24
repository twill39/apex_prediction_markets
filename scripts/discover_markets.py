#!/usr/bin/env python3
"""Discover Polymarket and Kalshi markets: high spread, decent liquidity for market making."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.discovery import (
    discover_polymarket_markets,
    discover_kalshi_markets,
    discover_markets_for_making,
)


def main():
    parser = argparse.ArgumentParser(
        description="Discover markets suitable for market making (high spread, decent liquidity).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Kalshi tips:
  Filters are ANDed: a market must pass BOTH min spread and min 24h volume (when set).
  --min-volume-24h-kalshi is in CONTRACTS (Kalshi volume_24h_fp), not dollars.
  Tight spreads often go with high volume; use --min-spread-pct 0 to debug volume-only.
  Without --max-kalshi-pages, discovery may paginate through all open markets (slow if few
  markets match). Cap pages to fail fast, e.g. --max-kalshi-pages 50.
""",
    )
    parser.add_argument(
        "source",
        choices=["poly", "kalshi", "both"],
        nargs="?",
        default="both",
        help="Which platform(s) to query (default: both).",
    )
    parser.add_argument(
        "--min-spread-pct",
        type=float,
        default=0.005,
        help="Min (ask-bid)/mid as decimal; e.g. 0.01=1%%, 0=disable spread filter. Default 0.005.",
    )
    parser.add_argument(
        "--min-liquidity",
        type=float,
        default=0,
        help="Min liquidity for Polymarket (default 0).",
    )
    parser.add_argument(
        "--min-volume-24h-kalshi",
        type=float,
        default=0,
        help="Min Kalshi 24h volume in contracts (API volume_24h_fp), not dollars (default 0).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=100,
        help="Max markets per platform (default 100).",
    )
    parser.add_argument(
        "--kalshi-base",
        type=str,
        default="https://api.elections.kalshi.com/trade-api/v2",
        help="Kalshi API base URL.",
    )
    parser.add_argument(
        "--max-kalshi-pages",
        type=int,
        default=None,
        metavar="N",
        help="Kalshi only: stop after N GET /markets pages (~100 markets each). Omit = scan until cursor ends.",
    )
    parser.add_argument(
        "--ids-only",
        action="store_true",
        help="Print only market IDs (one per line).",
    )
    args = parser.parse_args()

    if args.source == "poly":
        markets = discover_polymarket_markets(
            min_liquidity=args.min_liquidity,
            min_spread_pct=args.min_spread_pct,
            max_results=args.max_results,
        )
    elif args.source == "kalshi":
        markets = discover_kalshi_markets(
            base_url=args.kalshi_base,
            min_spread_pct=args.min_spread_pct,
            min_volume_24h=args.min_volume_24h_kalshi,
            max_results=args.max_results,
            max_pages=args.max_kalshi_pages,
        )
    else:
        markets = discover_markets_for_making(
            min_liquidity_poly=args.min_liquidity,
            min_spread_pct=args.min_spread_pct,
            min_volume_24h_kalshi=args.min_volume_24h_kalshi,
            max_poly=args.max_results,
            max_kalshi=args.max_results,
            kalshi_base_url=args.kalshi_base,
            kalshi_max_pages=args.max_kalshi_pages,
        )

    if not markets:
        print("No markets met the criteria.", file=sys.stderr)
        sys.exit(0)

    if args.ids_only:
        for m in markets:
            print(m["market_id"])
        return

    for m in markets:
        mid = m.get("market_id", "")
        plat = m.get("platform", "")
        spread = m.get("spread_pct")
        liq = m.get("liquidity")
        vol = m.get("volume") or m.get("volume_24h")
        title = (m.get("title") or "")[:60]
        line = f"{plat}\t{mid}\tspread={spread}\t"
        if liq is not None:
            line += f"liq={liq}\t"
        if vol is not None:
            line += f"vol={vol}\t"
        line += title
        print(line)


if __name__ == "__main__":
    main()
