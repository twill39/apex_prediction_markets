#!/usr/bin/env python3
"""Fetch Kalshi market bounds (lower/upper) and EOD timestamp by ticker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kalshi_client import KalshiClient


MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch Kalshi lower/upper bounds for tickers")
    parser.add_argument("--ticker", action="append", default=[], help="Kalshi ticker (repeatable)")
    parser.add_argument("--tickers-file", type=str, default=None, help="File with one ticker per line")
    parser.add_argument(
        "--snapshot-json",
        action="append",
        default=[],
        help="Path to snapshot.json containing market_id (repeatable)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/kalshi_market_bounds.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--timezone",
        type=str,
        default="America/New_York",
        help="Timezone used to infer EOD from ticker when missing in API metadata",
    )
    parser.add_argument(
        "--default-eod-hour",
        type=int,
        default=16,
        help="Default EOD hour when inferring from ticker date (default 16)",
    )
    return parser


def _read_tickers_file(path: str) -> List[str]:
    out: List[str] = []
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return out
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _read_ticker_from_snapshot(path: str) -> Optional[str]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return None
    try:
        payload = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    ticker = payload.get("market_id")
    return str(ticker) if ticker else None


def _parse_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_bounds(market: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    lower_keys = [
        "lower_bound",
        "lowerBound",
        "floor_strike",
        "floorStrike",
        "strike_floor",
        "min_value",
    ]
    upper_keys = [
        "upper_bound",
        "upperBound",
        "cap_strike",
        "capStrike",
        "strike_cap",
        "max_value",
    ]

    lower = next((_parse_float(market.get(k)) for k in lower_keys if _parse_float(market.get(k)) is not None), None)
    upper = next((_parse_float(market.get(k)) for k in upper_keys if _parse_float(market.get(k)) is not None), None)

    if lower is not None and upper is not None:
        return lower, upper

    # Fallback: try parsing two numbers from title/subtitle-like fields.
    text_fields = [
        "title",
        "subtitle",
        "yes_sub_title",
        "no_sub_title",
        "yes_subtitle",
        "no_subtitle",
    ]
    number_pattern = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
    for key in text_fields:
        raw = market.get(key)
        if not raw:
            continue
        nums = [_parse_float(x.replace(",", "")) for x in number_pattern.findall(str(raw))]
        nums = [x for x in nums if x is not None]
        if len(nums) >= 2:
            lo = min(nums[0], nums[1])
            hi = max(nums[0], nums[1])
            return lo, hi

    return None, None


def _parse_timestamp_any(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        ts = float(v)
        # heuristic: treat >1e11 as ms
        if ts > 1e11:
            ts /= 1000.0
        return ts
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        num = _parse_float(s)
        if num is not None:
            return _parse_timestamp_any(num)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _infer_eod_from_ticker(ticker: str, tz_name: str, default_hour: int) -> Optional[float]:
    # Example: KXINX-26MAY01H1600-B7237
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})H(\d{2})(\d{2})", ticker)
    tz = ZoneInfo(tz_name)
    if m:
        year = 2000 + int(m.group(1))
        mon = MONTHS.get(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        if mon:
            return datetime(year, mon, day, hour, minute, tzinfo=tz).timestamp()

    # Date-only fallback: -26MAY01-
    m2 = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", ticker)
    if not m2:
        return None
    year = 2000 + int(m2.group(1))
    mon = MONTHS.get(m2.group(2))
    day = int(m2.group(3))
    if mon is None:
        return None
    return datetime(year, mon, day, default_hour, 0, tzinfo=tz).timestamp()


def _extract_eod_timestamp(market: Dict[str, Any], ticker: str, tz_name: str, default_hour: int) -> Optional[float]:
    candidate_keys = [
        "eod_timestamp",
        "close_time",
        "close_time_utc",
        "expiration_time",
        "expiry_time",
        "end_date",
        "close_ts",
        "settlement_time",
    ]
    for key in candidate_keys:
        ts = _parse_timestamp_any(market.get(key))
        if ts is not None:
            return ts
    return _infer_eod_from_ticker(ticker, tz_name, default_hour)


def _fetch_market(client: KalshiClient, ticker: str) -> Tuple[Dict[str, Any], str]:
    try:
        return client.get_market(ticker), "live"
    except Exception:
        return client.get_historical_market(ticker), "historical"


def main() -> int:
    args = _build_parser().parse_args()

    tickers: List[str] = []
    tickers.extend(args.ticker or [])
    if args.tickers_file:
        tickers.extend(_read_tickers_file(args.tickers_file))
    for snapshot_path in args.snapshot_json or []:
        t = _read_ticker_from_snapshot(snapshot_path)
        if t:
            tickers.append(t)

    # De-dup while preserving order.
    deduped: List[str] = []
    seen = set()
    for t in tickers:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    tickers = deduped

    if not tickers:
        raise SystemExit("No tickers provided. Use --ticker, --tickers-file, or --snapshot-json.")

    client = KalshiClient()
    rows: List[Dict[str, Any]] = []
    for ticker in tickers:
        try:
            market, source = _fetch_market(client, ticker)
            lower, upper = _extract_bounds(market)
            eod_ts = _extract_eod_timestamp(
                market=market,
                ticker=ticker,
                tz_name=args.timezone,
                default_hour=args.default_eod_hour,
            )
            rows.append(
                {
                    "ticker": ticker,
                    "source": source,
                    "lower_bound": lower,
                    "upper_bound": upper,
                    "eod_timestamp": eod_ts,
                    "has_bounds": lower is not None and upper is not None,
                    "market_keys": sorted(list(market.keys())),
                }
            )
        except Exception as e:
            rows.append(
                {
                    "ticker": ticker,
                    "error": str(e),
                }
            )

    output = {
        "generated_at_utc": datetime.utcnow().isoformat(),
        "timezone": args.timezone,
        "rows": rows,
    }
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    ok = sum(1 for r in rows if r.get("has_bounds"))
    print(f"Wrote {len(rows)} rows to {out_path} ({ok} with extracted bounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

