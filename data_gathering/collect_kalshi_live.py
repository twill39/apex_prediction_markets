#!/usr/bin/env python3
"""Collect Kalshi live market data: market + candlesticks via live API.

Uses GET /markets/{ticker} for metadata and time bounds, then
GET /series/{series_ticker}/markets/{ticker}/candlesticks for 1-minute bars.
For markets that are in the live window but not yet in historical (e.g. many sports).
"""

import argparse
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kalshi_client import KalshiClient
from src.data.kalshi_historical_storage import save_live_market, save_live_candlesticks
from src.simulator.market_list import load_markets_from_file
from src.utils.logger import get_logger

# Kalshi appears to reject larger ranges for 1-min bars on some markets.
# Empirically: ~96h can return 400 while ~72h succeeds, so keep chunks smaller.
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
    """Return (start_ts, end_ts) in Unix seconds for the market's trading range."""
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
        start_ts = end_ts - (365 * 24 * 3600)
    return (start_ts, end_ts)


def _infer_series_ticker(client: KalshiClient, event_ticker: str, logger) -> str:
    """Get series_ticker from event API, or infer as first segment of event_ticker (e.g. KXNFLGAME)."""
    try:
        event = client.get_event(event_ticker)
        if isinstance(event, dict) and event.get("series_ticker"):
            return event["series_ticker"].strip()
    except Exception as e:
        logger.debug("get_event(%s) failed: %s; inferring series from event_ticker", event_ticker, e)
    # Infer: series is usually the first segment before a hyphen (e.g. KXNFLGAME-25DEC04DALDET -> KXNFLGAME)
    if event_ticker:
        parts = event_ticker.split("-")
        if parts:
            return parts[0].strip()
    return event_ticker or ""


def collect_one(
    client: KalshiClient,
    ticker: str,
    output: str,
    period_interval: int,
    logger,
) -> bool:
    """Collect live market + candlesticks for one ticker. Returns True on success."""
    try:
        market = client.get_market(ticker)
    except Exception as e:
        logger.error("Failed to fetch live market %s: %s", ticker, e)
        return False
    if not market or not market.get("ticker"):
        logger.error("Empty or invalid market response for %s", ticker)
        return False

    save_live_market(output, ticker, {"market": market})
    event_ticker = (market.get("event_ticker") or "").strip()
    if not event_ticker:
        logger.warning("No event_ticker for %s; cannot request candlesticks", ticker)
        save_live_candlesticks(output, ticker, {"ticker": ticker, "candlesticks": []})
        return True

    series_ticker = _infer_series_ticker(client, event_ticker, logger)
    if not series_ticker:
        logger.warning("Could not infer series_ticker for %s", ticker)
        save_live_candlesticks(output, ticker, {"ticker": ticker, "candlesticks": []})
        return True

    start_ts, end_ts = _market_time_bounds(market)
    chunk_seconds = CANDLESTICKS_CHUNK_DAYS * 24 * 3600
    all_candlesticks = []
    t_start = start_ts
    while t_start < end_ts:
        t_end = min(t_start + chunk_seconds, end_ts)
        try:
            resp = client.get_live_candlesticks(
                series_ticker,
                ticker,
                start_ts=t_start,
                end_ts=t_end,
                period_interval=period_interval,
            )
        except Exception as e:
            logger.error("Failed live candlesticks %s: %s", ticker, e)
            break
        candlesticks = resp.get("candlesticks", [])
        all_candlesticks.extend(candlesticks)
        if len(candlesticks) == 0:
            break
        t_start = t_end + 1
        if t_start < end_ts:
            _time.sleep(0.2)

    save_live_candlesticks(output, ticker, {"ticker": ticker, "candlesticks": all_candlesticks})
    logger.info("Collected %s: %d candlesticks (series=%s)", ticker, len(all_candlesticks), series_ticker)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Collect Kalshi live market + candlesticks (1-min) from open to close"
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
        "--period",
        type=int,
        default=1,
        choices=[1, 60, 1440],
        help="Candlestick period: 1=1min, 60=1hr, 1440=1day (default: 1)",
    )
    args = parser.parse_args()

    logger = get_logger("collect_kalshi_live")
    client = KalshiClient()

    if args.tickers_file:
        tickers = load_markets_from_file(args.tickers_file)
        if not tickers:
            logger.error("No tickers found in %s", args.tickers_file)
            sys.exit(1)
        logger.info("Collecting %d live markets from %s", len(tickers), args.tickers_file)
        ok = 0
        failed = []
        for i, ticker in enumerate(tickers):
            logger.info("Market %d/%d: %s", i + 1, len(tickers), ticker)
            if collect_one(client, ticker, args.output, args.period, logger):
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
    success = collect_one(client, args.ticker, args.output, args.period, logger)
    if not success:
        sys.exit(1)
    print(f"Done. Data saved under {args.output}/kalshi_live/{args.ticker}/")


if __name__ == "__main__":
    main()
