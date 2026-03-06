#!/usr/bin/env python3
"""Discover Polymarket traders: low volume, high PnL (potential edge). Output proxyWallet list for copy trading."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.discovery import discover_traders, get_trader_ids_meeting_spec


def main():
    parser = argparse.ArgumentParser(
        description="Discover Polymarket traders meeting spec (low volume, high PnL) for copy trading."
    )
    parser.add_argument(
        "--max-volume",
        type=float,
        default=None,
        help="Max leaderboard volume to consider (omit for no cap).",
    )
    parser.add_argument(
        "--min-pnl",
        type=float,
        default=None,
        help="Min PnL to consider (omit for no floor).",
    )
    parser.add_argument(
        "--min-pnl-per-vol",
        type=float,
        default=None,
        help="Min PnL/volume ratio (omit for no floor).",
    )
    parser.add_argument(
        "--time-period",
        choices=["DAY", "WEEK", "MONTH", "ALL"],
        default="WEEK",
        help="Leaderboard time period.",
    )
    parser.add_argument(
        "--category",
        default="OVERALL",
        help="Leaderboard category (OVERALL, POLITICS, SPORTS, etc.).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=200,
        help="Max leaderboard entries to fetch before filtering.",
    )
    parser.add_argument(
        "--ids-only",
        action="store_true",
        help="Print only proxyWallet addresses (one per line).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max number of traders to output (after filter).",
    )
    args = parser.parse_args()

    if args.ids_only:
        ids = get_trader_ids_meeting_spec(
            max_volume=args.max_volume,
            min_pnl=args.min_pnl,
            min_pnl_per_vol=args.min_pnl_per_vol,
            time_period=args.time_period,
            category=args.category,
            max_traders=args.limit,
        )
        for w in ids:
            print(w)
        return

    traders = discover_traders(
        max_volume=args.max_volume,
        min_pnl=args.min_pnl,
        min_pnl_per_vol=args.min_pnl_per_vol,
        time_period=args.time_period,
        category=args.category,
        max_results=args.max_results,
    )
    traders = traders[: args.limit]
    if not traders:
        print("No traders met the criteria.", file=sys.stderr)
        sys.exit(0)
    for t in traders:
        vol = t.get("vol")
        pnl = t.get("pnl")
        ppv = t.get("pnl_per_vol")
        line = f"{t['proxyWallet']}\t{t.get('userName','')}\tvol={vol}\tpnl={pnl}"
        if ppv is not None:
            line += f"\tpnl_per_vol={ppv:.4f}"
        print(line)


if __name__ == "__main__":
    main()
