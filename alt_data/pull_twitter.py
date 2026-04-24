#!/usr/bin/env python3
"""Append one snapshot of X/Twitter recent-search metrics to JSONL (for alt-data research).

Uses TWITTER_BEARER_TOKEN from the environment unless --bearer is set.
X Recent Search covers roughly the last ~7 days; build long horizons via scheduled pulls.

Examples:
  python alt_data/pull_twitter.py --query "OpenAI OR GPT" --out alt_data/out/openai.jsonl
  python alt_data/pull_twitter.py --keywords fed rate cut inflation --out alt_data/out/macro.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.data.collectors import TwitterCollector


def _build_query(args: argparse.Namespace) -> str:
    if args.query and args.query.strip():
        return args.query.strip()
    if args.keywords:
        parts = [k.strip() for k in args.keywords if k and k.strip()]
        return " OR ".join(parts[:5])
    raise SystemExit("Provide --query or at least one --keywords term.")


def _write_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _write_raw_tweets(
    dump_path: Path,
    *,
    query: str,
    collected_at: str,
    tweets: list,
) -> None:
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    with dump_path.open("a", encoding="utf-8") as f:
        for t in tweets:
            line = {
                "pulled_query": query,
                "pulled_at": collected_at,
                "id": t.get("id"),
                "created_at": t.get("created_at"),
                "text": t.get("text"),
                "public_metrics": t.get("public_metrics"),
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


async def _run(args: argparse.Namespace) -> None:
    token = args.bearer or os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        raise SystemExit("Set TWITTER_BEARER_TOKEN or pass --bearer.")

    query = _build_query(args)
    collector = TwitterCollector(bearer_token=token)
    want_raw = bool(args.dump_raw_tweets)

    result = await collector.collect_query(query, return_tweets=want_raw)
    tweets = result.pop("tweets", None) if want_raw else None

    record = {
        "collected_at": result.get("collected_at"),
        "query": result.get("query", query),
        "sentiment_score": result.get("sentiment_score"),
        "mention_count": result.get("mention_count"),
        "engagement_score": result.get("engagement_score"),
        "tweets_analyzed": result.get("tweets_analyzed"),
    }
    if result.get("error"):
        record["error"] = result["error"]

    out_path = Path(args.out).expanduser().resolve()
    _write_jsonl(out_path, record)

    if want_raw and tweets is not None:
        raw_path = Path(args.dump_raw_tweets).expanduser().resolve()
        _write_raw_tweets(
            raw_path,
            query=record["query"],
            collected_at=record["collected_at"] or "",
            tweets=tweets,
        )

    print(json.dumps(record, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Pull X recent-search metrics and append to JSONL.")
    p.add_argument(
        "--query",
        type=str,
        default="",
        help="Full X search query string (takes precedence over --keywords).",
    )
    p.add_argument(
        "--keywords",
        nargs="*",
        default=[],
        help="Terms combined as OR (up to 5), e.g. --keywords fed inflation jobs",
    )
    p.add_argument(
        "--out",
        required=True,
        help="Output JSONL path (appended each run).",
    )
    p.add_argument(
        "--bearer",
        default="",
        help="Bearer token (default: env TWITTER_BEARER_TOKEN).",
    )
    p.add_argument(
        "--dump-raw-tweets",
        metavar="PATH",
        default="",
        help="Optional JSONL path for minimal per-tweet rows; comply with X developer/display rules.",
    )
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
