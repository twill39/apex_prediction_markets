#!/usr/bin/env python3
"""List Kalshi historical market tickers, filter by ticker/event_ticker substring, write to file."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kalshi_client import KalshiClient
from src.utils.logger import get_logger


def _filter_markets(
    markets: list,
    ticker_contains: list,
    event_contains: list,
) -> list:
    """Include market if (no ticker_contains OR ticker contains any) AND (no event_contains OR event_ticker contains any). Case-insensitive. Always excludes MVE combo markets."""
    out = []
    for m in markets:
        ticker = (m.get("ticker") or "").strip()
        event_ticker = (m.get("event_ticker") or "").strip()
        ticker_lower = ticker.lower()
        event_lower = event_ticker.lower()
        if ticker_lower.startswith("kxmve"):
            continue
        if ticker_contains and not any(sub.lower() in ticker_lower for sub in ticker_contains):
            continue
        if event_contains and not any(sub.lower() in event_lower for sub in event_contains):
            continue
        out.append(m)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Kalshi historical markets, filter by ticker/event substring, write tickers to file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./data/kalshi_historical_tickers.txt",
        help="Output file path (default: ./data/kalshi_historical_tickers.txt)",
    )
    parser.add_argument(
        "--ticker-contains",
        type=str,
        default=None,
        help="Comma-separated substrings; keep market if ticker contains any (e.g. KXBTC,BTC)",
    )
    parser.add_argument(
        "--event-contains",
        type=str,
        default=None,
        help="Comma-separated substrings; keep market if event_ticker contains any",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Page size for API (default: 50)",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=None,
        help="Stop after fetching this many markets total (omit to fetch all)",
    )
    args = parser.parse_args()

    logger = get_logger("list_kalshi_historical_markets")
    client = KalshiClient()

    logger.info("Fetching all historical markets (paginated)")
    markets = client.get_historical_markets_all_pages(
        limit=args.limit,
        max_markets=args.max_markets,
        event_ticker=args.event_contains,
        tickers=args.ticker_contains,
    )
    logger.info("Fetched %d markets", len(markets))

    ticker_subs = [s.strip() for s in (args.ticker_contains or "").split(",") if s.strip()]
    event_subs = [s.strip() for s in (args.event_contains or "").split(",") if s.strip()]
    filtered = _filter_markets(markets, ticker_subs, event_subs)
    logger.info("After filter: %d markets", len(filtered))

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("# Kalshi historical tickers")
        if ticker_subs:
            f.write(f" (ticker-contains={','.join(ticker_subs)})")
        if event_subs:
            f.write(f" (event-contains={','.join(event_subs)})")
        f.write("\n")
        for m in filtered:
            t = (m.get("ticker") or "").strip()
            if t:
                f.write(t + "\n")

    print(f"Wrote {len(filtered)} tickers to {out_path}")


if __name__ == "__main__":
    main()
