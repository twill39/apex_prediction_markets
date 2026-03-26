"""Storage helpers for Polymarket data: paths and save/load for market metadata and price history under data_poly."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_polymarket_dir(base_path: str, token_id: str) -> Path:
    """Return directory for a token: base_path/polymarket/{token_id}."""
    return Path(base_path).expanduser().resolve() / "polymarket" / token_id


def get_market_path(base_path: str, token_id: str) -> Path:
    """Path to market.json for token_id."""
    return get_polymarket_dir(base_path, token_id) / "market.json"


def get_prices_path(base_path: str, token_id: str) -> Path:
    """Path to prices.json for token_id."""
    return get_polymarket_dir(base_path, token_id) / "prices.json"


def ensure_dir(path: Path) -> None:
    """Create parent directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def save_market(base_path: str, token_id: str, data: Dict[str, Any]) -> Path:
    """Save Gamma event/market blob to market.json."""
    p = get_market_path(base_path, token_id)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
    return p


def save_prices(base_path: str, token_id: str, data: Dict[str, Any]) -> Path:
    """Save prices response (token_id, interval, history) to prices.json."""
    p = get_prices_path(base_path, token_id)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
    return p


def load_market(base_path: str, token_id: str) -> Optional[Dict[str, Any]]:
    """Load market.json. Returns None if file does not exist."""
    p = get_market_path(base_path, token_id)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)


def load_prices(base_path: str, token_id: str) -> Optional[Dict[str, Any]]:
    """Load prices.json. Returns None if file does not exist."""
    p = get_prices_path(base_path, token_id)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)
