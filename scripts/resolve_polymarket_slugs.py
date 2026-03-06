#!/usr/bin/env python3
"""Resolve Polymarket slugs to CLOB asset IDs. Use from CLI or to inspect IDs for test_markets.txt."""

import argparse
import importlib.util
import sys
from pathlib import Path

# Load market_list without pulling in the rest of src (avoids pydantic etc.)
_root = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "market_list",
    _root / "src" / "simulator" / "market_list.py",
)
market_list = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(market_list)

looks_like_polymarket_slug = market_list.looks_like_polymarket_slug
resolve_markets = market_list.resolve_markets
load_markets_from_file = market_list.load_markets_from_file


def main():
    parser = argparse.ArgumentParser(
        description="Resolve Polymarket event slugs to CLOB asset IDs (for WebSocket subscriptions)."
    )
    parser.add_argument(
        "slugs",
        nargs="*",
        help="Slug(s) to resolve (e.g. fed-decision-in-october). Omit to read from --file.",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default=None,
        help="Read lines from file (one slug or ID per line, # comments ignored). Resolve slugs only.",
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Only print which lines are slugs vs IDs; do not call the API.",
    )
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        raw = load_markets_from_file(str(path))
    else:
        raw = [s.strip() for s in args.slugs if s.strip()]

    if not raw:
        parser.print_help()
        print("\nExample: python scripts/resolve_polymarket_slugs.py fed-decision-in-october", file=sys.stderr)
        sys.exit(0)

    if args.no_resolve:
        for item in raw:
            kind = "slug (would resolve)" if looks_like_polymarket_slug(item) else "ID/ticker (keep as-is)"
            print(f"{item}\t# {kind}")
        return

    resolved = resolve_markets(raw)
    for aid in resolved:
        print(aid)


if __name__ == "__main__":
    main()
