#!/usr/bin/env python3
"""Collect Kalshi historical data: market + candlesticks (and optionally orders).

Uses GET /historical/markets/{ticker} for metadata and time bounds, then
GET /historical/markets/{ticker}/candlesticks with start_ts, end_ts, period_interval=1
to fetch 1-minute bars from earliest to latest available.
"""

import argparse
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kalshi_client import KalshiClient
from src.data.kalshi_historical_storage import save_market, save_orders, save_candlesticks
from src.simulator.market_list import load_markets_from_file
from src.utils.logger import get_logger

# Chunk size for candlesticks: Kalshi appears to reject larger ranges for 1-min bars.
# For example, for some markets a ~96h range returns 400, while ~72h succeeds.
# Using a smaller chunk keeps the request sizes valid/reliable.
CANDLESTICKS_CHUNK_DAYS = 3


def _iso_to_unix_seconds(iso_str: str) -> int:
    """Parse ISO8601 string to Unix seconds (integer)."""
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _market_time_bounds(market: dict) -> tuple:
    """Return (start_ts, end_ts) in Unix seconds for the market's available range."""
    # Prefer open_time -> close_time; fallback to created_time -> expiration_time / latest_expiration_time
    start_ts = _iso_to_unix_seconds(
        market.get("open_time") or market.get("created_time") or ""
    )
    end_ts = _iso_to_unix_seconds(
        market.get("close_time")
        or market.get("expiration_time")
        or market.get("latest_expiration_time")
        or market.get("updated_time")
        or ""
    )
    if end_ts <= 0 or end_ts > _time.time():
        end_ts = int(_time.time())
    if start_ts <= 0:
        start_ts = end_ts - (365 * 24 * 3600)  # fallback: 1 year before end
    return (start_ts, end_ts)


def collect_one(
    client: KalshiClient,
    ticker: str,
    output: str,
    period_interval: int,
    fetch_orders: bool,
    logger,
) -> bool:
    """Collect market + candlesticks + optional orders for one ticker. Returns True on success."""
    try:
        data = client.get_historical_market(ticker)
    except Exception as e:
        logger.error("Failed to fetch market %s: %s", ticker, e)
        return False
    market = data if isinstance(data, dict) and "ticker" in data else data.get("market", data)
    save_market(output, ticker, {"market": market})
    start_ts, end_ts = _market_time_bounds(market)

    chunk_seconds = CANDLESTICKS_CHUNK_DAYS * 24 * 3600
    all_candlesticks = []
    t_start = start_ts
    while t_start < end_ts:
        t_end = min(t_start + chunk_seconds, end_ts)
        try:
            resp = client.get_historical_candlesticks(
                ticker,
                start_ts=t_start,
                end_ts=t_end,
                period_interval=period_interval,
            )
        except Exception as e:
            logger.error("Failed candlesticks %s: %s", ticker, e)
            break
        candlesticks = resp.get("candlesticks", [])
        all_candlesticks.extend(candlesticks)
        if len(candlesticks) == 0:
            break
        t_start = t_end + 1
        if t_start < end_ts:
            _time.sleep(0.2)

    save_candlesticks(output, ticker, {"ticker": ticker, "candlesticks": all_candlesticks})
    if fetch_orders:
        try:
            orders = client.get_historical_orders_all_pages(ticker, max_ts=end_ts)
            save_orders(output, ticker, orders)
        except Exception as e:
            logger.warning("Failed orders %s: %s", ticker, e)
    logger.info("Collected %s: %d candlesticks", ticker, len(all_candlesticks))
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Collect Kalshi historical market + candlesticks (1-min) from earliest to latest available"
    )
    parser.add_argument("--ticker", type=str, default=None, help="Single market ticker (ignored if --tickers-file set)")
    parser.add_argument(
        "--tickers-file",
        type=str,
        default=None,
        help="Path to file with one ticker per line (# = comment); collect for all listed tickers",
    )
    parser.add_argument("--output", type=str, default="./data", help="Base directory for output (default: ./data)")
    parser.add_argument(
        "--orders",
        action="store_true",
        help="Also fetch and save historical orders (paginated)",
    )
    parser.add_argument(
        "--period",
        type=int,
        default=1,
        choices=[1, 60, 1440],
        help="Candlestick period: 1=1min, 60=1hr, 1440=1day (default: 1)",
    )
    args = parser.parse_args()

    logger = get_logger("collect_kalshi_historical")
    client = KalshiClient()

    if args.tickers_file:
        tickers = load_markets_from_file(args.tickers_file)
        if not tickers:
            logger.error("No tickers found in %s", args.tickers_file)
            sys.exit(1)
        logger.info("Collecting %d markets from %s", len(tickers), args.tickers_file)
        ok = 0
        failed = []
        for i, ticker in enumerate(tickers):
            logger.info("Market %d/%d: %s", i + 1, len(tickers), ticker)
            if collect_one(client, ticker, args.output, args.period, args.orders, logger):
                ok += 1
            else:
                failed.append(ticker)
        print(f"Done. Collected {ok} markets, {len(failed)} failed.")
        if failed:
            print("Failed tickers:", ", ".join(failed))
        return

    if not args.ticker:
        logger.error("Provide --ticker or --tickers-file")
        sys.exit(1)
    success = collect_one(client, args.ticker, args.output, args.period, args.orders, logger)
    if not success:
        sys.exit(1)
    print(f"Done. Data saved under {args.output}/kalshi_historical/{args.ticker}/")


if __name__ == "__main__":
    main()
