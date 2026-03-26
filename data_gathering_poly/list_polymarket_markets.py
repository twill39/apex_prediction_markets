#!/usr/bin/env python3
"""List Polymarket token IDs from Gamma events, filter by slug/tag/title/question/date, write to file."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Self-contained: ensure this directory is on path when run as script
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from polymarket_client import get_events


def _parse_token_ids(market: dict) -> list:
    """Extract CLOB token IDs from a market (clobTokenIds may be JSON string or list)."""
    raw = market.get("clobTokenIds")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except json.JSONDecodeError:
            return []
    else:
        ids = raw if isinstance(raw, list) else []
    return [str(i) for i in ids]


def _parse_iso_to_ts(iso_str: str) -> int | None:
    """Parse ISO8601 date string to Unix timestamp (seconds). Returns None if missing/invalid."""
    if not iso_str or not str(iso_str).strip():
        return None
    try:
        s = str(iso_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _filter_events(
    events: list,
    title_contains: list,
    question_contains: list,
    min_end_ts: int | None = None,
) -> list:
    """Include event if (no title filter or title matches), (no question filter or any market question matches), and (no min_end or event end_date >= min_end). Case-insensitive."""
    out = []
    for ev in events:
        title = (ev.get("title") or "").strip().lower()
        if title_contains and not any(sub.strip().lower() in title for sub in title_contains if sub.strip()):
            continue
        if min_end_ts is not None:
            end_raw = ev.get("end_date") or ev.get("endDate") or ""
            end_ts = _parse_iso_to_ts(end_raw)
            if end_ts is None or end_ts < min_end_ts:
                continue
        markets = ev.get("markets") or []
        if question_contains:
            any_q = False
            for m in markets:
                q = (m.get("question") or "").strip().lower()
                if any(sub.strip().lower() in q for sub in question_contains if sub.strip()):
                    any_q = True
                    break
            if not any_q:
                continue
        out.append(ev)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Polymarket events from Gamma, filter by slug/tag/title/question, write token_id and slug to file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./data_poly/polymarket_tickers.txt",
        help="Output file path (default: ./data_poly/polymarket_tickers.txt)",
    )
    parser.add_argument(
        "--slug",
        type=str,
        default=None,
        help="Filter by event slug (exact); fetches only that event",
    )
    parser.add_argument(
        "--tag-id",
        type=str,
        default=None,
        help="Filter by Gamma tag_id (category/sport)",
    )
    parser.add_argument(
        "--title-contains",
        type=str,
        default=None,
        help="Comma-separated substrings; keep event if title contains any",
    )
    parser.add_argument(
        "--question-contains",
        type=str,
        default=None,
        help="Comma-separated substrings; keep event if any market question contains any",
    )
    parser.add_argument(
        "--active",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=None,
        metavar="true|false",
        help="Filter by active status (Gamma)",
    )
    parser.add_argument(
        "--closed",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=None,
        metavar="true|false",
        help="Filter by closed status (Gamma)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Page size for Gamma API (default: 100)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1000,
        help="Stop after this many pages (default: 1000)",
    )
    parser.add_argument(
        "--min-end-date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Only include events whose end_date is on or after this date (ISO). Use to limit to recent markets for which Data API trade history is more likely to exist.",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=None,
        metavar="N",
        help="Only include events whose end_date is within the last N days. Alternative to --min-end-date for 'recent only'.",
    )
    args = parser.parse_args()

    title_subs = [s.strip() for s in (args.title_contains or "").split(",") if s.strip()]
    question_subs = [s.strip() for s in (args.question_contains or "").split(",") if s.strip()]

    min_end_ts = None
    if args.recent_days is not None:
        min_end_ts = int((datetime.now(timezone.utc) - timedelta(days=args.recent_days)).timestamp())
    elif args.min_end_date:
        min_end_ts = _parse_iso_to_ts(args.min_end_date.strip())
        if min_end_ts is None:
            print("Warning: --min-end-date could not be parsed; ignoring.", file=sys.stderr)
            min_end_ts = None

    events = []
    offset = 0
    for _ in range(args.max_pages):
        batch = get_events(
            limit=args.limit,
            offset=offset,
            active=args.active,
            closed=args.closed,
            slug=args.slug,
            tag_id=args.tag_id,
        )
        events.extend(batch)
        if len(batch) < args.limit:
            break
        offset += args.limit
        if args.slug:
            break

    filtered = _filter_events(events, title_subs, question_subs, min_end_ts=min_end_ts)

    rows = []
    for ev in filtered:
        slug = (ev.get("slug") or ev.get("ticker") or "").strip()
        start_date = (ev.get("start_date") or ev.get("startDate") or "").strip()
        end_date = (ev.get("end_date") or ev.get("endDate") or "").strip()
        for m in ev.get("markets") or []:
            for tid in _parse_token_ids(m):
                rows.append((tid, slug, start_date, end_date))

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("# token_id\tslug\tstart_date\tend_date\n")
        for tid, slug, start_date, end_date in rows:
            f.write(f"{tid}\t{slug}\t{start_date}\t{end_date}\n")

    print(f"Wrote {len(rows)} token IDs to {out_path}")


if __name__ == "__main__":
    main()
