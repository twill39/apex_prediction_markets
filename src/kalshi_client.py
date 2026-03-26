"""Kalshi REST API client with signed GET requests for historical and other endpoints."""

import base64
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.config import get_credentials
from src.utils.logger import get_logger


def _load_private_key(private_key_path: str):
    path = Path(private_key_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Kalshi private key file not found: {path}")
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _sign_message(private_key, message: str) -> str:
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _path_from_url(url: str) -> str:
    """Return path (including leading slash) from full URL, without query or fragment."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    return path


def _build_headers(api_key: str, private_key_path: str, method: str, path_no_query: str) -> Dict[str, str]:
    """Build KALSHI-ACCESS-* headers for a request. Path must not include query string."""
    timestamp_ms = str(int(time.time() * 1000))
    message = timestamp_ms + method + path_no_query
    private_key = _load_private_key(private_key_path)
    signature = _sign_message(private_key, message)
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Accept": "application/json",
    }


class KalshiClient:
    """Sync REST client for Kalshi API with PEM-based request signing."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, private_key_path: Optional[str] = None):
        creds = get_credentials()
        if not creds.kalshi:
            raise ValueError("Kalshi credentials not configured (set KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH)")
        k = creds.kalshi
        self.base_url = (base_url or k.base_url).rstrip("/")
        self.api_key = api_key or k.api_key
        self.private_key_path = private_key_path or k.private_key_path
        self.logger = get_logger("KalshiClient")
        self._session = requests.Session()

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
        """Send a signed request. path is the path after base_url (e.g. /historical/markets/TICKER)."""
        url = self.base_url + path
        if params:
            from urllib.parse import urlencode
            query = urlencode(params)
            full_url = url + "?" + query
        else:
            full_url = url
        path_no_query = _path_from_url(url)
        headers = _build_headers(self.api_key, self.private_key_path, method, path_no_query)
        resp = self._session.get(full_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def get_historical_markets(
        self,
        limit: int = 1000,
        cursor: Optional[str] = None,
        event_ticker: Optional[str] = None,
        tickers: Optional[str] = None,
        mve_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /historical/markets. Filters (event_ticker, tickers, mve_filter) are mutually exclusive."""
        path = "/historical/markets"
        params = {"limit": min(limit, 1000)}
        if cursor:
            params["cursor"] = cursor
        if event_ticker:
            params["event_ticker"] = event_ticker
        elif tickers:
            params["tickers"] = tickers
        elif mve_filter:
            params["mve_filter"] = mve_filter
        return self._request("GET", path, params=params)

    def get_historical_markets_all_pages(
        self,
        limit: int = 1000,
        event_ticker: Optional[str] = None,
        tickers: Optional[str] = None,
        mve_filter: Optional[str] = None,
    ) -> list:
        """Fetch all pages of historical markets and return a single list of market dicts."""
        markets = []
        cursor = None
        while True:
            data = self.get_historical_markets(
                limit=limit,
                cursor=cursor,
                event_ticker=event_ticker,
                tickers=tickers,
                mve_filter=mve_filter,
            )
            batch = data.get("markets", [])
            markets.extend(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                break
        return markets

    def get_historical_market(self, ticker: str) -> Dict[str, Any]:
        """GET /historical/markets/{ticker}. Returns the market object (metadata + top of book)."""
        path = f"/historical/markets/{ticker}"
        out = self._request("GET", path)
        return out.get("market", out)

    def get_historical_orders(self, ticker: str, max_ts: Optional[int] = None, limit: int = 200, cursor: Optional[str] = None) -> Dict[str, Any]:
        """GET /historical/orders. max_ts: Unix timestamp (ms) - return orders before this time. limit: 1-200. cursor: pagination."""
        path = "/historical/orders"
        params = {"ticker": ticker, "limit": limit}
        if max_ts is not None:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", path, params=params)

    def get_historical_orders_all_pages(self, ticker: str, max_ts: Optional[int] = None, limit: int = 200) -> list:
        """Fetch all pages of historical orders for a ticker and return a single list of orders."""
        orders = []
        cursor = None
        while True:
            data = self.get_historical_orders(ticker=ticker, max_ts=max_ts, limit=limit, cursor=cursor)
            batch = data.get("orders", [])
            orders.extend(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                break
        return orders

    def get_historical_candlesticks(
        self,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> Dict[str, Any]:
        """
        GET /historical/markets/{ticker}/candlesticks.
        start_ts, end_ts: Unix timestamps (seconds). Candlesticks ending on or after start_ts, on or before end_ts.
        period_interval: 1 (1 min), 60 (1 hour), or 1440 (1 day).
        """
        path = f"/historical/markets/{ticker}/candlesticks"
        params = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_interval,
        }
        return self._request("GET", path, params=params)

    def get_markets(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /markets. Live markets list. status: unopened, open, closed, settled. Returns {markets, cursor}."""
        path = "/markets"
        params = {"limit": min(limit, 100)}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._request("GET", path, params=params)

    def get_markets_all_pages(
        self,
        limit: int = 100,
        status: Optional[str] = None,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
    ) -> list:
        """Fetch all pages of live markets and return a single list of market dicts."""
        markets = []
        cursor = None
        while True:
            data = self.get_markets(
                limit=limit,
                cursor=cursor,
                status=status,
                event_ticker=event_ticker,
                series_ticker=series_ticker,
            )
            batch = data.get("markets", [])
            markets.extend(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                break
        return markets

    def get_market(self, ticker: str) -> Dict[str, Any]:
        """GET /markets/{ticker}. Live market by ticker. Returns dict with 'market' key (or raw response)."""
        path = f"/markets/{ticker}"
        out = self._request("GET", path)
        return out.get("market", out)

    def get_event(self, event_ticker: str) -> Dict[str, Any]:
        """GET /events/{event_ticker}. Live event; response may include series_ticker for candlestick requests."""
        path = f"/events/{event_ticker}"
        out = self._request("GET", path)
        return out.get("event", out)

    def get_live_candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
        include_latest_before_start: bool = False,
    ) -> Dict[str, Any]:
        """
        GET /series/{series_ticker}/markets/{ticker}/candlesticks.
        Use for markets that are still in the live window (not yet in historical).
        series_ticker: from the event (e.g. event has series_ticker), or often the prefix of event_ticker (e.g. KXNFLGAME).
        start_ts, end_ts: Unix timestamps (seconds). period_interval: 1, 60, or 1440.
        """
        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        params = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_interval,
        }
        if include_latest_before_start:
            params["include_latest_before_start"] = "true"
        return self._request("GET", path, params=params)
