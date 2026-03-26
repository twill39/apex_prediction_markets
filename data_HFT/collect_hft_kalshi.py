#!/usr/bin/env python3
"""HFT orderbook collector for Kalshi: subscribe via WebSocket, store initial snapshot + 1s frames/deltas."""

import argparse
import asyncio
import copy
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.hft_storage import (
    book_state_from_levels,
    compute_delta,
    write_snapshot,
    append_delta_line,
    append_snapshot_frame,
)
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.base import WebSocketEventType
from src.utils.logger import get_logger

logger = get_logger("collect_hft_kalshi")

# In-memory state: current book and last emitted book per market_id
current_books: dict = {}
last_emitted_books: dict = {}
snapshot_written: dict = {}  # market_id -> bool


def _on_orderbook(event):
    """Callback: update current_books from WebSocket orderbook."""
    market_id = event.market_id
    if not market_id:
        return
    data = event.data or {}
    ob = data.get("orderbook")
    if not ob:
        return
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    state = book_state_from_levels(bids, asks)
    current_books[market_id] = state


async def _tick_loop(
    ws: KalshiWebSocket,
    output_root: str,
    interval: float,
    duration: float,
    market_ids: list,
    mode: str,
) -> None:
    """Every interval seconds, either append full snapshots (frames.jsonl) or deltas (deltas.jsonl)."""
    platform = "kalshi"
    start = time.time()
    while ws.is_running and ws.is_connected:
        await asyncio.sleep(interval)
        if duration and (time.time() - start) >= duration:
            logger.info("Duration %s s reached, stopping", duration)
            break
        now = time.time()
        for mid in market_ids:
            curr = current_books.get(mid)
            last = last_emitted_books.get(mid)
            if curr is None:
                continue

            # First time: write base snapshot + (in snapshots mode) first frame
            if not snapshot_written.get(mid):
                ts_iso = datetime.now(timezone.utc).isoformat()
                write_snapshot(output_root, platform, mid, curr, ts_iso)
                snapshot_written[mid] = True
                last_emitted_books[mid] = copy.deepcopy(curr)
                logger.info("Wrote snapshot for %s", mid)
                if mode == "snapshots":
                    append_snapshot_frame(output_root, platform, mid, now, curr)
                continue

            if mode == "snapshots":
                # Always write full snapshot each frame (frames.jsonl)
                append_snapshot_frame(output_root, platform, mid, now, curr)
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue

            # Deltas mode
            if last is None:
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue

            events = compute_delta(last, curr)
            if events:
                append_delta_line(output_root, platform, mid, now, events)
            last_emitted_books[mid] = copy.deepcopy(curr)


def _load_markets(markets_file: str, markets_cli: str) -> list:
    """Load market IDs from file or CLI."""
    if markets_file:
        from src.simulator.market_list import load_markets_from_file

        out = load_markets_from_file(markets_file)
        return [m for m in out if m.strip()]
    if markets_cli:
        return [m.strip() for m in markets_cli.split(",") if m.strip()]
    return []


async def run(output_root: str, interval: float, duration: float, market_ids: list, mode: str) -> None:
    if not market_ids:
        logger.error("No markets specified (--markets-file or --markets)")
        return

    ws = KalshiWebSocket()
    ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, _on_orderbook)

    for mid in market_ids:
        # Start as None so we don't write snapshot.json until we receive
        # the first real orderbook state from WebSocket.
        current_books[mid] = None
        last_emitted_books[mid] = None
        snapshot_written[mid] = False

    start_task = asyncio.create_task(ws.start())
    await asyncio.sleep(3)
    if not ws.is_connected:
        logger.warning("WebSocket not connected after 3s, attempting subscribe anyway")

    for mid in market_ids:
        await ws.subscribe_market(mid, subscribe_orderbook=True, subscribe_trades=False)
    logger.info("Subscribed to %d Kalshi markets", len(market_ids))

    try:
        await _tick_loop(ws, output_root, interval, duration, market_ids, mode)
    except asyncio.CancelledError:
        pass

    ws.is_running = False
    await asyncio.sleep(1)
    start_task.cancel()
    try:
        await start_task
    except asyncio.CancelledError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="HFT orderbook collector for Kalshi (snapshot + 1s frames or deltas)"
    )
    parser.add_argument("--markets-file", type=str, default=None, help="Path to file with one market ID per line")
    parser.add_argument("--markets", type=str, default=None, help="Comma-separated Kalshi market tickers")
    parser.add_argument("--output-root", type=str, default="./data_HFT", help="Output root (default: ./data_HFT)")
    parser.add_argument("--interval", type=float, default=1.0, help="Delta interval in seconds (default: 1.0)")
    parser.add_argument("--duration", type=float, default=None, help="Run for N seconds then exit (optional)")
    parser.add_argument(
        "--mode",
        type=str,
        default="snapshots",
        choices=["snapshots", "deltas"],
        help="Storage mode: 'snapshots' stores full book every interval (default), 'deltas' stores snapshot+per-second deltas",
    )
    args = parser.parse_args()

    market_ids = _load_markets(args.markets_file, args.markets)
    if not market_ids:
        print("No markets specified. Use --markets-file or --markets.")
        sys.exit(1)

    asyncio.run(run(args.output_root, args.interval, args.duration, market_ids, args.mode))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""HFT orderbook collector for Kalshi: subscribe via WebSocket, store initial snapshot + 1s deltas."""

import argparse
import asyncio
import copy
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.hft_storage import (
    book_state_from_levels,
    compute_delta,
    write_snapshot,
    append_delta_line,
    append_snapshot_frame,
)
from src.websockets.kalshi import KalshiWebSocket
from src.websockets.base import WebSocketEventType
from src.utils.logger import get_logger

logger = get_logger("collect_hft_kalshi")

# In-memory state: current book and last emitted book per market_id
current_books: dict = {}
last_emitted_books: dict = {}
snapshot_written: dict = {}  # market_id -> bool


def _on_orderbook(event):
    """Callback: update current_books from WebSocket orderbook."""
    market_id = event.market_id
    if not market_id:
        return
    data = event.data or {}
    ob = data.get("orderbook")
    if not ob:
        return
    bids = ob.get("bids") or []
    asks = ob.get("asks") or []
    state = book_state_from_levels(bids, asks)
    current_books[market_id] = state


async def _tick_loop(
    ws: KalshiWebSocket,
    output_root: str,
    interval: float,
    duration: float,
    market_ids: list,
    mode: str,
) -> None:
    """Every interval seconds, either append full snapshots (frames.jsonl) or deltas (deltas.jsonl)."""
    platform = "kalshi"
    start = time.time()
    while ws.is_running and ws.is_connected:
        await asyncio.sleep(interval)
        if duration and (time.time() - start) >= duration:
            logger.info("Duration %s s reached, stopping", duration)
            break
        now = time.time()
        for mid in market_ids:
            curr = current_books.get(mid)
            last = last_emitted_books.get(mid)
            if curr is None:
                continue
            # First time: write base snapshot only when we have at least some book data (avoid empty snapshot)
            if not snapshot_written.get(mid):
                ts_iso = datetime.now(timezone.utc).isoformat()
                write_snapshot(output_root, platform, mid, curr, ts_iso)
                snapshot_written[mid] = True
                last_emitted_books[mid] = copy.deepcopy(curr)
                logger.info("Wrote snapshot for %s", mid)
                if mode == "snapshots":
                    append_snapshot_frame(output_root, platform, mid, now, curr)
                continue
            if mode == "snapshots":
                # Always write full snapshot each frame (frames.jsonl)
                append_snapshot_frame(output_root, platform, mid, now, curr)
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue
            # Deltas mode
            if last is None:
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue
            events = compute_delta(last, curr)
            if events:
                append_delta_line(output_root, platform, mid, now, events)
            last_emitted_books[mid] = copy.deepcopy(curr)


def _load_markets(markets_file: str, markets_cli: str) -> list:
    """Load market IDs from file or CLI."""
    if markets_file:
        from src.simulator.market_list import load_markets_from_file
        out = load_markets_from_file(markets_file)
        return [m for m in out if m.strip()]
    if markets_cli:
        return [m.strip() for m in markets_cli.split(",") if m.strip()]
    return []


async def run(output_root: str, interval: float, duration: float, market_ids: list, mode: str) -> None:
    if not market_ids:
        logger.error("No markets specified (--markets-file or --markets)")
        return
    ws = KalshiWebSocket()
    ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, _on_orderbook)

    for mid in market_ids:
        current_books[mid] = {"bids": {}, "asks": {}}
        last_emitted_books[mid] = None
        snapshot_written[mid] = False

    start_task = asyncio.create_task(ws.start())
    await asyncio.sleep(3)
    if not ws.is_connected:
        logger.warning("WebSocket not connected after 3s, attempting subscribe anyway")
    for mid in market_ids:
        await ws.subscribe_market(mid, subscribe_orderbook=True, subscribe_trades=False)
    logger.info("Subscribed to %d Kalshi markets", len(market_ids))

    try:
        await _tick_loop(ws, output_root, interval, duration, market_ids, mode)
    except asyncio.CancelledError:
        pass
    ws.is_running = False
    await asyncio.sleep(1)
    start_task.cancel()
    try:
        await start_task
    except asyncio.CancelledError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="HFT orderbook collector for Kalshi (snapshot + 1s frames or deltas)"
    )
    parser.add_argument("--markets-file", type=str, default=None, help="Path to file with one market ID per line")
    parser.add_argument("--markets", type=str, default=None, help="Comma-separated Kalshi market tickers")
    parser.add_argument("--output-root", type=str, default="./data_HFT", help="Output root (default: ./data_HFT)")
    parser.add_argument("--interval", type=float, default=1.0, help="Delta interval in seconds (default: 1.0)")
    parser.add_argument("--duration", type=float, default=None, help="Run for N seconds then exit (optional)")
    parser.add_argument(
        "--mode",
        type=str,
        default="snapshots",
        choices=["snapshots", "deltas"],
        help="Storage mode: 'snapshots' stores full book every interval (default), 'deltas' stores snapshot+per-second deltas",
    )
    args = parser.parse_args()

    market_ids = _load_markets(args.markets_file, args.markets)
    if not market_ids:
        print("No markets specified. Use --markets-file or --markets.")
        sys.exit(1)
    asyncio.run(run(args.output_root, args.interval, args.duration, market_ids, args.mode))


if __name__ == "__main__":
    main()
