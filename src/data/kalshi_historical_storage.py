"""Storage helpers for Kalshi historical market and orders data (paths, read/write JSON)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_historical_dir(base_path: str, ticker: str) -> Path:
    """Return directory for a ticker: base_path/kalshi_historical/{ticker}."""
    return Path(base_path).expanduser().resolve() / "kalshi_historical" / ticker


def get_live_dir(base_path: str, ticker: str) -> Path:
    """Return directory for a live market ticker: base_path/kalshi_live/{ticker}."""
    return Path(base_path).expanduser().resolve() / "kalshi_live" / ticker


def get_live_market_path(base_path: str, ticker: str) -> Path:
    """Path to market.json for live ticker."""
    return get_live_dir(base_path, ticker) / "market.json"


def get_live_candlesticks_path(base_path: str, ticker: str) -> Path:
    """Path to candlesticks.json for live ticker."""
    return get_live_dir(base_path, ticker) / "candlesticks.json"


def get_market_path(base_path: str, ticker: str) -> Path:
    """Path to market.json for ticker."""
    return get_historical_dir(base_path, ticker) / "market.json"


def get_orders_path(base_path: str, ticker: str) -> Path:
    """Path to orders.json for ticker."""
    return get_historical_dir(base_path, ticker) / "orders.json"


def get_candlesticks_path(base_path: str, ticker: str) -> Path:
    """Path to candlesticks.json for ticker."""
    return get_historical_dir(base_path, ticker) / "candlesticks.json"


def ensure_dir(path: Path) -> None:
    """Create parent directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def save_market(base_path: str, ticker: str, market: Dict[str, Any]) -> Path:
    """Save market response (full GET /historical/markets/{ticker} response or market object)."""
    p = get_market_path(base_path, ticker)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(market, f, indent=2)
    return p


def save_orders(base_path: str, ticker: str, orders: List[Dict[str, Any]]) -> Path:
    """Save orders list to orders.json."""
    p = get_orders_path(base_path, ticker)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(orders, f, indent=2)
    return p


def load_market(base_path: str, ticker: str) -> Optional[Dict[str, Any]]:
    """Load market.json. Returns None if file does not exist."""
    p = get_market_path(base_path, ticker)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)


def load_orders(base_path: str, ticker: str) -> Optional[List[Dict[str, Any]]]:
    """Load orders.json. Returns None if file does not exist."""
    p = get_orders_path(base_path, ticker)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)


def save_candlesticks(base_path: str, ticker: str, data: Dict[str, Any]) -> Path:
    """Save candlesticks API response (ticker + candlesticks array) to candlesticks.json."""
    p = get_candlesticks_path(base_path, ticker)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
    return p


def save_live_market(base_path: str, ticker: str, market: Dict[str, Any]) -> Path:
    """Save live market (GET /markets/{ticker} response) to kalshi_live/{ticker}/market.json."""
    p = get_live_market_path(base_path, ticker)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(market, f, indent=2)
    return p


def save_live_candlesticks(base_path: str, ticker: str, data: Dict[str, Any]) -> Path:
    """Save live candlesticks response to kalshi_live/{ticker}/candlesticks.json."""
    p = get_live_candlesticks_path(base_path, ticker)
    ensure_dir(p)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
    return p


def load_candlesticks(base_path: str, ticker: str) -> Optional[Dict[str, Any]]:
    """Load candlesticks.json. Returns None if file does not exist."""
    p = get_candlesticks_path(base_path, ticker)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)


def has_historical_data(base_path: str, ticker: str) -> bool:
    """True if both market.json and orders.json exist for ticker."""
    return get_market_path(base_path, ticker).is_file() and get_orders_path(base_path, ticker).is_file()
