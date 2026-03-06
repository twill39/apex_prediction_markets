"""Load market/asset ID list from file or CLI. Resolve Polymarket slugs to asset IDs."""

import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List

try:
    import certifi
except ImportError:
    certifi = None

POLYMARKET_GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"


def _ssl_context() -> ssl.SSLContext:
    """Use certifi CA bundle if available (fixes SSL verify on macOS)."""
    ctx = ssl.create_default_context()
    if certifi is not None:
        ctx.load_verify_locations(certifi.where())
    return ctx


def looks_like_polymarket_slug(value: str) -> bool:
    """True if value looks like a Polymarket slug (not a numeric asset ID or Kalshi ticker)."""
    s = value.strip()
    if not s:
        return False
    # Long numeric string = Polymarket asset ID
    if s.isdigit() and len(s) >= 20:
        return False
    # Kalshi tickers typically start with KX and contain uppercase
    if s.startswith("KX") and "-" in s:
        return False
    # Otherwise treat as slug (e.g. fed-decision-in-october, lowercase-hyphenated)
    return True


def resolve_polymarket_slug(slug: str) -> List[str]:
    """Resolve a Polymarket event slug to CLOB token IDs via Gamma API. Returns empty list on failure."""
    slug = slug.strip()
    if not slug:
        return []
    url = f"{POLYMARKET_GAMMA_EVENTS_URL}?slug={urllib.parse.quote(slug)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    if not isinstance(data, list) or not data:
        return []
    asset_ids = []
    for event in data:
        markets = event.get("markets") or []
        for m in markets:
            raw = m.get("clobTokenIds")
            if not raw:
                continue
            if isinstance(raw, str):
                try:
                    ids = json.loads(raw)
                except json.JSONDecodeError:
                    continue
            else:
                ids = raw
            if isinstance(ids, list):
                asset_ids.extend(str(i) for i in ids)
    return asset_ids


def resolve_markets(raw_list: List[str]) -> List[str]:
    """Expand Polymarket slugs to asset IDs; leave asset IDs and Kalshi tickers unchanged."""
    result = []
    for item in raw_list:
        item = item.strip()
        if not item:
            continue
        if looks_like_polymarket_slug(item):
            ids = resolve_polymarket_slug(item)
            result.extend(ids)
        else:
            result.append(item)
    return result


def load_markets_from_file(file_path: str) -> List[str]:
    """Load market IDs from a text file (one per line, # = comment)."""
    path = Path(file_path)
    if not path.is_file():
        return []
    markets = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        markets.append(line)
    return markets


def load_markets_from_file_resolved(file_path: str) -> List[str]:
    """Load from file and resolve any Polymarket slugs to asset IDs."""
    raw = load_markets_from_file(file_path)
    return resolve_markets(raw)


def parse_markets_from_cli(comma_separated: str) -> List[str]:
    """Parse comma-separated market IDs from CLI."""
    if not comma_separated or not comma_separated.strip():
        return []
    return [m.strip() for m in comma_separated.split(",") if m.strip()]
