#!/usr/bin/env python3
"""List Kalshi market tickers for a single event_ticker using server-side filtering."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kalshi_client import KalshiClient
from src.utils.logger import get_logger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Kalshi market tickers for one event_ticker and write to file"
    )
    parser.add_argument(
        "--event-ticker",
        required=True,
        help="Exact Kalshi event ticker (e.g. KXNFLDRAFTTOP-26-R1).",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="open",
        choices=["unopened", "open", "closed", "settled"],
        help="Market status filter (default: open).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./data/kalshi_event_tickers.txt",
        help="Output file path (default: ./data/kalshi_event_tickers.txt).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size for API (default: 100, max 100).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Stop after this many API pages (default: 100).",
    )
    args = parser.parse_args()

    logger = get_logger("list_kalshi_event_markets")
    client = KalshiClient()

    logger.info(
        "Fetching Kalshi markets for event=%s status=%s (up to %d pages)",
        args.event_ticker,
        args.status,
        args.max_pages,
    )

    markets = []
    cursor = None
    for _ in range(args.max_pages):
        data = client.get_markets(
            limit=min(args.limit, 100),
            cursor=cursor,
            status=args.status,
            event_ticker=args.event_ticker,
        )
        batch = data.get("markets", []) or []
        markets.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break

    tickers = []
    for m in markets:
        ticker = (m.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(f"# Kalshi tickers (event={args.event_ticker}, status={args.status})\n")
        for ticker in tickers:
            f.write(ticker + "\n")

    print(f"Wrote {len(tickers)} tickers to {out_path}")


if __name__ == "__main__":
    main()
