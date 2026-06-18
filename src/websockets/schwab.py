"""Schwab SPX spot feed via schwabdev streamer with REST poll fallback."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from src.config import get_credentials
from src.utils.logger import get_logger

PriceCallback = Callable[[float, datetime], None]

# Schwab stream field ids commonly used for last/close/mark.
_PRICE_FIELD_KEYS = ("3", "4", "12", "15", "lastPrice", "mark", "close", "regularMarketLastPrice")


def _parse_stream_price(message: str, symbol: str) -> Optional[float]:
    """Extract a spot price from a Schwab streamer JSON message."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None

    data_blocks = payload.get("data") or []
    if not isinstance(data_blocks, list):
        return None

    sym_upper = symbol.upper()
    for block in data_blocks:
        if not isinstance(block, dict):
            continue
        content = block.get("content") or []
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("symbol") or "").upper()
            if key and key != sym_upper:
                continue
            for field_key in _PRICE_FIELD_KEYS:
                if field_key in item:
                    try:
                        price = float(item[field_key])
                    except (TypeError, ValueError):
                        continue
                    if price > 0:
                        return price
    return None


def _parse_quote_response(payload: dict, symbol: str) -> Optional[float]:
    """Extract spot from Schwab REST quote payload."""
    if not isinstance(payload, dict):
        return None

    sym_upper = symbol.upper()
    candidates = []

    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        if key.upper() != sym_upper and str(value.get("symbol", "")).upper() != sym_upper:
            continue
        quote = value.get("quote") if isinstance(value.get("quote"), dict) else value
        if not isinstance(quote, dict):
            quote = value
        for field in (
            "lastPrice",
            "mark",
            "closePrice",
            "regularMarketLastPrice",
            "totalVolume",
        ):
            if field in ("totalVolume",):
                continue
            raw = quote.get(field)
            if raw is None:
                continue
            try:
                price = float(raw)
            except (TypeError, ValueError):
                continue
            if price > 0:
                candidates.append(price)

    if candidates:
        return candidates[0]
    return None


def _parse_price_history(payload: dict) -> Optional[float]:
    candles = payload.get("candles") if isinstance(payload, dict) else None
    if not candles:
        return None
    last = candles[-1]
    if not isinstance(last, dict):
        return None
    for field in ("close", "open", "high", "low"):
        raw = last.get(field)
        if raw is None:
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


class SchwabSpxStream:
    """Background Schwab feed that invokes on_price(price, timestamp) from a worker thread."""

    def __init__(
        self,
        symbol: str = "$SPX",
        poll_interval_seconds: float = 5.0,
        stream_warmup_seconds: float = 15.0,
    ):
        self.symbol = symbol
        self.poll_interval_seconds = max(float(poll_interval_seconds), 1.0)
        self.stream_warmup_seconds = max(float(stream_warmup_seconds), 5.0)
        self.logger = get_logger("SchwabSpxStream")

        self._on_price: Optional[PriceCallback] = None
        self._client = None
        self._streamer = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False
        self._use_poll_fallback = False
        self._last_price: Optional[float] = None
        self._last_update: Optional[datetime] = None
        self._lock = threading.Lock()

    @property
    def last_price(self) -> Optional[float]:
        with self._lock:
            return self._last_price

    @property
    def last_update(self) -> Optional[datetime]:
        with self._lock:
            return self._last_update

    def _build_client(self):
        credentials = get_credentials()
        if not credentials.schwab:
            raise ValueError(
                "Schwab credentials not configured (set APP_KEY and APP_SECRET)"
            )
        import schwabdev

        schwab = credentials.schwab
        if schwab.callback_url:
            return schwabdev.Client(schwab.app_key, schwab.app_secret, schwab.callback_url)
        return schwabdev.Client(schwab.app_key, schwab.app_secret)

    def _emit_price(self, price: float, ts: Optional[datetime] = None) -> None:
        if price <= 0 or self._on_price is None:
            return
        event_ts = ts or datetime.now(timezone.utc)
        with self._lock:
            if self._last_price == price and self._last_update == event_ts:
                return
            self._last_price = price
            self._last_update = event_ts
        try:
            self._on_price(price, event_ts)
        except Exception as exc:
            self.logger.error("SPX price callback failed: %s", exc, exc_info=True)

    def _handle_stream_message(self, message: str) -> None:
        price = _parse_stream_price(message, self.symbol)
        if price is not None:
            self._emit_price(price)

    def _poll_once(self) -> Optional[float]:
        if self._client is None:
            return None
        try:
            resp = self._client.quote(self.symbol)
            payload = resp.json()
            price = _parse_quote_response(payload, self.symbol)
            if price is not None:
                return price
        except Exception as exc:
            self.logger.debug("Schwab quote poll failed: %s", exc)

        try:
            resp = self._client.price_history(
                symbol=self.symbol,
                periodType="day",
                period=1,
                frequencyType="minute",
                frequency=1,
            )
            price = _parse_price_history(resp.json())
            if price is not None:
                return price
        except Exception as exc:
            self.logger.debug("Schwab price_history poll failed: %s", exc)
        return None

    def _poll_loop(self) -> None:
        self.logger.info(
            "Schwab SPX poll fallback running for %s every %.1fs",
            self.symbol,
            self.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            price = self._poll_once()
            if price is not None:
                self._emit_price(price)
            self._stop_event.wait(self.poll_interval_seconds)

    def _start_stream(self) -> bool:
        import schwabdev

        try:
            self._streamer = schwabdev.Stream(self._client)
            self._streamer.start(self._handle_stream_message)
            # Prefer chart stream for index symbols like $SPX; equities stream as backup.
            self._streamer.send(
                self._streamer.chart_equity(
                    self.symbol,
                    "0,1,2,3,4,5,6,7,8",
                    command="SUBS",
                )
            )
            self._streamer.send(
                self._streamer.level_one_equities(
                    self.symbol,
                    "0,1,2,3,4,5,6,7,8",
                    command="ADD",
                )
            )
            self.logger.info("Schwab stream subscribed for %s", self.symbol)
            return True
        except Exception as exc:
            self.logger.warning("Schwab stream start failed, using poll fallback: %s", exc)
            self._streamer = None
            return False

    def start(self, on_price: PriceCallback) -> None:
        """Start stream (with poll fallback) and invoke on_price from a background thread."""
        if self._started:
            return
        self._on_price = on_price
        self._stop_event.clear()
        self._client = self._build_client()

        stream_ok = self._start_stream()
        if stream_ok:
            warmup_deadline = time.time() + self.stream_warmup_seconds
            while time.time() < warmup_deadline and not self._stop_event.is_set():
                if self.last_price is not None:
                    self._started = True
                    return
                time.sleep(0.5)
            self.logger.warning(
                "No SPX stream ticks within %.0fs; enabling poll fallback",
                self.stream_warmup_seconds,
            )
            self._use_poll_fallback = True
            try:
                if self._streamer is not None:
                    self._streamer.stop()
            except Exception:
                pass
            self._streamer = None
        else:
            self._use_poll_fallback = True

        if self._use_poll_fallback:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="SchwabSpxPoll",
                daemon=True,
            )
            self._poll_thread.start()

        self._started = True

    def stop(self) -> None:
        """Stop stream and poll threads."""
        if not self._started and not self._poll_thread and not self._streamer:
            return
        self._stop_event.set()
        if self._streamer is not None:
            try:
                self._streamer.stop()
            except Exception as exc:
                self.logger.debug("Error stopping Schwab streamer: %s", exc)
            self._streamer = None
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
        self._poll_thread = None
        self._started = False
