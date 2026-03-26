#!/usr/bin/env python3
"""Collect Polymarket market metadata and price history; save to data_poly."""

import argparse
import logging
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import json

from polymarket_client import get_event_by_slug, get_prices_history, get_trades_all
from polymarket_storage import save_market, save_prices

logger = logging.getLogger("collect_polymarket")

# Chunk size for price history: 60 days to avoid huge responses
CHUNK_DAYS = 60
MAX_CONSECUTIVE_EMPTY_CHUNKS = 3  # Avoid truncating active-market collection on transient empty responses


def _iso_to_unix_seconds(iso_str: str) -> int:
    """Parse ISO8601 string to Unix seconds (integer)."""
    if not iso_str or not iso_str.strip():
        return 0
    try:
        s = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _event_time_bounds(event: dict) -> tuple:
    """Return (start_ts, end_ts) from event start_date/end_date (or camelCase). Fallback to now and now-1y if missing."""
    start_ts = _iso_to_unix_seconds(event.get("start_date") or event.get("startDate") or "")
    end_ts = _iso_to_unix_seconds(event.get("end_date") or event.get("endDate") or "")
    now = int(_time.time())
    if end_ts <= 0 or end_ts > now:
        end_ts = now
    if start_ts <= 0:
        start_ts = end_ts - (365 * 24 * 3600)
    return (start_ts, end_ts)


def condition_id_for_token(event: dict, token_id: str) -> str | None:
    """Return conditionId (0x-prefixed hex) for the market that contains this token_id, or None."""
    token_id = (token_id or "").strip()
    if not token_id:
        return None
    for m in event.get("markets") or []:
        raw = m.get("clobTokenIds")
        if not raw:
            continue
        if isinstance(raw, str):
            try:
                ids = json.loads(raw)
            except json.JSONDecodeError:
                continue
        else:
            ids = raw if isinstance(raw, list) else []
        if token_id in [str(i) for i in ids]:
            cid = m.get("conditionId") or m.get("condition_id")
            if cid:
                return cid.strip()
    return None


def interval_to_minutes(interval: str) -> int:
    """Map CLOB interval string to minutes for aggregation. Default 1 for unknown."""
    m = {"1m": 1, "1h": 60, "6h": 360, "1d": 1440, "1w": 10080}
    return m.get((interval or "").strip().lower(), 1)


def _trade_timestamp_seconds(trade: dict) -> int:
    """Normalize trade timestamp to Unix seconds (Data API may return ms)."""
    ts = trade.get("timestamp")
    if ts is None:
        return 0
    if isinstance(ts, (int, float)):
        t = int(ts)
        return t // 1000 if t > 1e12 else t
    return 0


def aggregate_trades_to_history(
    trades: list,
    token_id: str,
    interval_minutes: int = 1,
) -> list:
    """
    Filter trades to asset == token_id, bucket by interval, use last trade price per bucket.
    Returns [{"t": bucket_start_unix_sec, "p": price}, ...] sorted by t (sparse: only buckets with trades).
    """
    token_id = str(token_id).strip()
    filtered = [t for t in trades if str((t.get("asset") or "")).strip() == token_id]
    filtered.sort(key=_trade_timestamp_seconds)
    if not filtered:
        return []
    interval_seconds = interval_minutes * 60
    buckets: dict[int, float] = {}
    for t in filtered:
        ts = _trade_timestamp_seconds(t)
        if ts <= 0:
            continue
        price = t.get("price")
        if price is None:
            continue
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        bucket = (ts // interval_seconds) * interval_seconds
        buckets[bucket] = p
    return [{"t": t, "p": p} for t, p in sorted(buckets.items())]


def _load_tickers_file(file_path: str) -> list:
    """Load rows from list script output: token_id, slug, start_date, end_date (tab-separated). Returns list of (token_id, slug, start_date, end_date)."""
    path = Path(file_path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        token_id = (parts[0] or "").strip()
        if not token_id:
            continue
        slug = (parts[1] if len(parts) > 1 else "").strip()
        start_date = (parts[2] if len(parts) > 2 else "").strip()
        end_date = (parts[3] if len(parts) > 3 else "").strip()
        rows.append((token_id, slug, start_date, end_date))
    return rows


def collect_one(
    token_id: str,
    slug: str,
    start_date: str,
    end_date: str,
    output_base: str,
    interval: str,
    logger_instance,
) -> bool:
    """Collect market metadata and price history for one token. Returns True on success."""
    # Time bounds: from file first, then from Gamma event if slug present and bounds missing
    start_ts = _iso_to_unix_seconds(start_date) if start_date else 0
    end_ts = _iso_to_unix_seconds(end_date) if end_date else 0

    event = None
    if slug:
        event = get_event_by_slug(slug)
        if event:
            if start_ts <= 0 or end_ts <= 0:
                start_ts, end_ts = _event_time_bounds(event)
            save_market(output_base, token_id, {"event": event})
        else:
            logger_instance.warning("Could not fetch event for slug %s", slug)
            save_market(output_base, token_id, {"token_id": token_id, "slug": slug, "event": None})
    else:
        save_market(output_base, token_id, {"token_id": token_id, "slug": "", "event": None})

    if start_ts <= 0:
        start_ts = int(_time.time()) - (365 * 24 * 3600)
    if end_ts <= 0 or end_ts > _time.time():
        end_ts = int(_time.time())

    all_history: list = []

    # Closed markets: use Data API trades (CLOB returns empty). Active: use CLOB prices-history.
    use_data_api = event and (event.get("closed") is True)
    source = "clob_prices_history"
    if use_data_api:
        source = "data_api_trades"
        condition_id = condition_id_for_token(event, token_id)
        if condition_id:
            try:
                trades = get_trades_all(market_condition_ids=[condition_id])
                interval_mins = interval_to_minutes(interval)
                all_history = aggregate_trades_to_history(trades, token_id, interval_minutes=interval_mins)
            except Exception as e:
                logger_instance.error("Data API trades %s: %s", token_id, e)
        else:
            logger_instance.warning("No conditionId for token %s (closed event); cannot use Data API", token_id)
    else:
        # CLOB path (active or no event)
        chunk_seconds = CHUNK_DAYS * 24 * 3600
        t_start = start_ts
        consecutive_empty = 0
        while t_start < end_ts:
            t_end = min(t_start + chunk_seconds, end_ts)
            try:
                resp = get_prices_history(
                    token_id,
                    start_ts=t_start,
                    end_ts=t_end,
                    interval=interval,
                )
            except Exception as e:
                logger_instance.error("Failed prices-history %s: %s", token_id, e)
                break
            history = resp.get("history") or []
            all_history.extend(history)

            if len(history) == 0:
                consecutive_empty += 1
            else:
                consecutive_empty = 0

            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_CHUNKS:
                logger_instance.warning(
                    "Stopping CLOB chunk loop for %s after %d consecutive empty chunks",
                    token_id,
                    consecutive_empty,
                )
                break

            t_start = t_end + 1
            if t_start < end_ts:
                _time.sleep(0.2)

    save_prices(
        output_base,
        token_id,
        {
            "token_id": token_id,
            "interval": interval,
            "history": all_history,
            "source": source,
        },
    )
    logger_instance.info("Collected %s: %d price points (interval=%s)", token_id, len(all_history), interval)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Collect Polymarket market metadata and price history (from list file or single token)"
    )
    parser.add_argument(
        "--token-id",
        type=str,
        default=None,
        help="Single token ID (use with --slug for time bounds and metadata)",
    )
    parser.add_argument(
        "--slug",
        type=str,
        default=None,
        help="Event slug (required for --token-id to fetch metadata and time bounds)",
    )
    parser.add_argument(
        "--tickers-file",
        type=str,
        default=None,
        help="Path to file from list_polymarket_markets.py (token_id, slug, start_date, end_date per line)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./data_poly",
        help="Base directory for output (default: ./data_poly)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1m",
        choices=["1m", "1h", "6h", "1d", "1w", "max", "all"],
        help="Price history interval (default: 1m)",
    )
    args = parser.parse_args()

    if args.tickers_file:
        rows = _load_tickers_file(args.tickers_file)
        if not rows:
            logger.error("No rows found in %s", args.tickers_file)
            sys.exit(1)
        logger.info("Collecting %d tokens from %s", len(rows), args.tickers_file)
        ok = 0
        failed = []
        for i, (token_id, slug, start_date, end_date) in enumerate(rows):
            logger.info("Token %d/%d: %s", i + 1, len(rows), token_id)
            if collect_one(
                token_id, slug, start_date, end_date, args.output, args.interval, logger
            ):
                ok += 1
            else:
                failed.append(token_id)
        print(f"Done. Collected {ok} tokens, {len(failed)} failed.")
        if failed:
            print("Failed token IDs:", ", ".join(failed))
        return

    if not args.token_id:
        logger.error("Provide --token-id (and --slug) or --tickers-file")
        sys.exit(1)
    success = collect_one(
        args.token_id,
        args.slug or "",
        "",
        "",
        args.output,
        args.interval,
        logger,
    )
    if not success:
        sys.exit(1)
    print(f"Done. Data saved under {args.output}/polymarket/{args.token_id}/")


if __name__ == "__main__":
    main()
