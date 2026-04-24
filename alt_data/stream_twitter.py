#!/usr/bin/env python3
"""X API v2 filtered stream: manage rules and listen for matching tweets in real time.

Uses OAuth 2.0 Bearer token (TWITTER_BEARER_TOKEN or --bearer). Filtered stream access,
rule counts, and operator support depend on your X developer project tier; missing access
often returns 401/403 with a JSON error body. If the project has no streaming credits,
opening the stream returns 402 with ``CreditsDepleted`` in the JSON body.

Rules reference: https://developer.x.com/en/docs/twitter-api/tweets/filtered-stream/integrate/build-a-rule

Example commands::

    # List rules currently on the app
    python alt_data/stream_twitter.py --list-rules

    # Validate a rule without saving
    python alt_data/stream_twitter.py --dry-run --add-rule "OpenAI OR GPT -is:retweet"

    # Replace all rules, then open stream and append matches to JSONL
    python alt_data/stream_twitter.py --replace --yes \\
        --add-rule "Polymarket OR Kalshi -is:retweet lang:en" \\
        --out alt_data/out/poly_kalshi_stream.jsonl

    # Stream only (rules must already exist on the app)
    python alt_data/stream_twitter.py --verbose

Example --add-rule values (see --help epilog for more)::

    OpenAI OR GPT -is:retweet
    (Polymarket OR Kalshi) lang:en
    from:elonmusk
    \\"climate change\\" lang:en
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

BASE = "https://api.twitter.com/2/tweets/search/stream"
RULES_URL = "https://api.twitter.com/2/tweets/search/stream/rules"
USER_AGENT = "ApexPredictionMarkets/1.0"


def _headers(bearer: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": USER_AGENT,
    }


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg, file=sys.stderr)


def _print_api_error(r: requests.Response) -> None:
    try:
        body = r.json()
        print(json.dumps(body, indent=2), file=sys.stderr)
    except Exception:
        print(r.text[:2000], file=sys.stderr)


def _fail_response(r: requests.Response, *, context: str) -> None:
    """Print body and exit with guidance for common X billing / access errors."""
    _print_api_error(r)
    if r.status_code == 402:
        print(
            "\nX returned 402 (Payment Required). The JSON often means CreditsDepleted: "
            "filtered streaming is not available on your current plan or the project has "
            "no API credits left.\n"
            "Fix: in the X developer portal, add billing / credits or upgrade access for "
            "Filtered stream, or use a project that includes it.\n"
            "Fallback (no live stream): poll with `alt_data/pull_twitter.py` on a cron "
            "(Recent Search; not real-time).\n",
            file=sys.stderr,
        )
        sys.exit(1)
    if r.status_code == 403:
        print(
            f"\nX returned 403 for {context}. Check app permissions, project tier, and "
            "that filtered stream is enabled for this key.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"\n{context}: {e}", file=sys.stderr)
        sys.exit(1)


def _rules_from_handles_file(path: str, suffix: str) -> List[str]:
    """Load handle lines and build `from:handle ...` rule strings.

    File format:
    - one handle per line (with or without leading @)
    - empty lines and lines starting with # are ignored
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Handles file not found: {p}")

    rules: List[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        h = raw.strip()
        if not h or h.startswith("#"):
            continue
        if h.startswith("@"):
            h = h[1:]
        rule = f"from:{h}"
        if suffix.strip():
            rule = f"{rule} {suffix.strip()}"
        rules.append(rule)
    return rules


def list_rules(bearer: str, *, verbose: bool) -> Dict[str, Any]:
    r = requests.get(RULES_URL, headers=_headers(bearer), timeout=30)
    _log(verbose, f"GET rules -> {r.status_code}")
    if not r.ok:
        _fail_response(r, context="GET /tweets/search/stream/rules")
    return r.json()


def delete_all_rules(bearer: str, *, verbose: bool) -> None:
    data = list_rules(bearer, verbose=verbose)
    rules = data.get("data") or []
    ids = [str(x["id"]) for x in rules if x.get("id")]
    if not ids:
        _log(verbose, "No rules to delete.")
        return
    payload = {"delete": {"ids": ids}}
    r = requests.post(
        RULES_URL,
        headers={**_headers(bearer), "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    _log(verbose, f"DELETE rules ({len(ids)}) -> {r.status_code}")
    if not r.ok:
        _fail_response(r, context="POST /tweets/search/stream/rules (delete)")


def add_rules(
    bearer: str,
    rules: List[Dict[str, str]],
    *,
    dry_run: bool,
    verbose: bool,
) -> Dict[str, Any]:
    payload = {"add": rules}
    params = {}
    if dry_run:
        params["dry_run"] = "true"
    r = requests.post(
        RULES_URL,
        headers={**_headers(bearer), "Content-Type": "application/json"},
        params=params,
        json=payload,
        timeout=60,
    )
    _log(verbose, f"POST rules (dry_run={dry_run}) -> {r.status_code}")
    if not r.ok:
        _fail_response(r, context="POST /tweets/search/stream/rules (add)")
    return r.json()


def run_stream(
    bearer: str,
    *,
    out_path: Optional[Path],
    verbose: bool,
) -> None:
    params = {
        "tweet.fields": "created_at,public_metrics,text",
        "expansions": "author_id",
    }
    _log(verbose, f"Connecting stream GET {BASE} ...")
    out_file = None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_path.open("a", encoding="utf-8")
    try:
        with requests.get(
            BASE,
            headers=_headers(bearer),
            params=params,
            stream=True,
            timeout=(10, None),
        ) as r:
            if not r.ok:
                _fail_response(r, context="GET /tweets/search/stream")
            _log(verbose, "Stream connected; press Ctrl+C to stop.")
            for raw in r.iter_lines(decode_unicode=True):
                if raw is None or raw.strip() == "":
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    _log(verbose, f"Non-JSON line skipped: {raw[:120]!r}")
                    continue

                # Keep-alive / system messages may omit "data"
                if "data" not in obj:
                    _log(verbose, f"Stream meta: {json.dumps(obj)[:500]}")
                    continue

                received_at = datetime.now(timezone.utc).isoformat()
                out_obj = {
                    "received_at": received_at,
                    "matching_rules": obj.get("matching_rules"),
                    "data": obj.get("data"),
                    "includes": obj.get("includes"),
                }
                line = json.dumps(out_obj, ensure_ascii=False)
                if out_file is not None:
                    out_file.write(line + "\n")
                    out_file.flush()
                else:
                    print(line)
    finally:
        if out_file is not None:
            out_file.close()


def main() -> None:
    epilog = """
Example rule strings for --add-rule:
  OpenAI OR GPT -is:retweet          Tech keywords, exclude pure retweets
  (Polymarket OR Kalshi) lang:en     Theme + English
  from:elonmusk                      Single account (high volume — use carefully)
  "climate change" lang:en           Exact phrase + language

Sample workflow:
  python alt_data/stream_twitter.py --list-rules
  python alt_data/stream_twitter.py --replace --yes \\
    --add-rule "Polymarket OR Kalshi -is:retweet lang:en" \\
    --out alt_data/out/poly_kalshi_stream.jsonl

  # Build rules from handles file (one handle per line, optional # comments)
  python alt_data/stream_twitter.py --replace --yes \\
    --handles-file alt_data/draft_night_handles.txt \\
    --out alt_data/out/draft_night_handles_stream.jsonl
"""
    p = argparse.ArgumentParser(
        description="X filtered stream: list/add/delete rules and consume matching tweets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    p.add_argument("--bearer", default="", help="Bearer token (default: env TWITTER_BEARER_TOKEN).")
    p.add_argument("--verbose", "-v", action="store_true", help="Log steps to stderr.")

    p.add_argument("--list-rules", action="store_true", help="GET current rules and exit.")
    p.add_argument(
        "--delete-all",
        action="store_true",
        help="Delete all stream rules for this app and exit (requires --yes).",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="Delete all rules, then add --add-rule entries, then stream (requires --yes).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Confirm --delete-all or --replace (wipes existing rules when replacing).",
    )
    p.add_argument(
        "--add-rule",
        action="append",
        default=[],
        metavar="VALUE",
        help="Rule value (repeat for multiple). Used with --replace or before streaming.",
    )
    p.add_argument(
        "--handles-file",
        default="",
        help="Path to file with one X handle per line. Converted to rules like from:handle -is:retweet.",
    )
    p.add_argument(
        "--handle-rule-suffix",
        default="-is:retweet",
        help="Suffix appended to each handle-derived rule (default: -is:retweet). Use '' to disable.",
    )
    p.add_argument(
        "--tag",
        default="",
        help="Optional tag applied to every rule added in this invocation.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate --add-rule with POST dry_run=true; do not persist or stream.",
    )
    p.add_argument(
        "--out",
        default="",
        help="Append one JSON object per tweet (JSONL). Default: print JSON lines to stdout.",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="After rule changes, exit without connecting (e.g. after --add-rule only).",
    )

    args = p.parse_args()

    extra_rules: List[str] = []
    if args.handles_file:
        try:
            extra_rules = _rules_from_handles_file(args.handles_file, args.handle_rule_suffix)
        except Exception as e:
            print(f"Failed to load --handles-file: {e}", file=sys.stderr)
            sys.exit(1)

    # Combine explicit --add-rule values with any handle-derived rules.
    all_rules = list(args.add_rule) + extra_rules

    token = args.bearer or os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        print("Set TWITTER_BEARER_TOKEN or pass --bearer.", file=sys.stderr)
        sys.exit(1)

    if args.list_rules:
        print(json.dumps(list_rules(token, verbose=args.verbose), indent=2))
        return

    if args.delete_all:
        if not args.yes:
            print("--delete-all requires --yes.", file=sys.stderr)
            sys.exit(1)
        delete_all_rules(token, verbose=args.verbose)
        return

    if args.dry_run:
        if not all_rules:
            print("--dry-run requires at least one --add-rule or --handles-file.", file=sys.stderr)
            sys.exit(1)
        rules_payload = [{"value": v, "tag": args.tag or None} for v in all_rules]
        rules_payload = [{k: v for k, v in r.items() if v is not None} for r in rules_payload]
        print(json.dumps(add_rules(token, rules_payload, dry_run=True, verbose=args.verbose), indent=2))
        return

    if args.replace:
        if not args.yes:
            print("--replace requires --yes.", file=sys.stderr)
            sys.exit(1)
        if not all_rules:
            print("--replace requires at least one --add-rule or --handles-file.", file=sys.stderr)
            sys.exit(1)
        delete_all_rules(token, verbose=args.verbose)
        rules_payload = [{"value": v, "tag": args.tag or None} for v in all_rules]
        rules_payload = [{k: v for k, v in r.items() if v is not None} for r in rules_payload]
        add_rules(token, rules_payload, dry_run=False, verbose=args.verbose)
    elif all_rules:
        rules_payload = [{"value": v, "tag": args.tag or None} for v in all_rules]
        rules_payload = [{k: v for k, v in r.items() if v is not None} for r in rules_payload]
        add_rules(token, rules_payload, dry_run=False, verbose=args.verbose)

    if args.no_stream:
        return

    out_path = Path(args.out).expanduser().resolve() if args.out else None
    try:
        run_stream(token, out_path=out_path, verbose=args.verbose)
    except KeyboardInterrupt:
        _log(args.verbose, "Stopped.")


if __name__ == "__main__":
    main()
