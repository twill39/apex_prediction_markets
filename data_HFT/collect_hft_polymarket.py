#!/usr/bin/env python3
"""HFT orderbook collector for Polymarket: subscribe via WebSocket, store snapshot + frames/deltas + trades."""

import argparse
import asyncio
import copy
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.hft_storage import (
    append_trade_line,
    book_state_from_levels,
    compute_delta,
    write_snapshot,
    append_delta_line,
    append_snapshot_frame,
)
from src.websockets.polymarket import PolymarketWebSocket
from src.websockets.base import WebSocketEventType
from src.utils.logger import get_logger

logger = get_logger("collect_hft_polymarket")

current_books: dict = {}
last_emitted_books: dict = {}
snapshot_written: dict = {}


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


def _make_trade_handler(output_root: str):
    platform = "polymarket"

    def _on_trade(event):
        mid = event.market_id
        if not mid:
            return
        append_trade_line(
            output_root,
            platform,
            mid,
            {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "trade": (event.data or {}).get("trade"),
            },
        )

    return _on_trade


async def _tick_loop(
    ws: PolymarketWebSocket,
    output_root: str,
    interval: float,
    duration: float,
    market_ids: list,
    mode: str,
) -> None:
    """Every interval seconds, either append full snapshots (frames.jsonl) or deltas (deltas.jsonl)."""
    platform = "polymarket"
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
                append_snapshot_frame(output_root, platform, mid, now, curr)
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue

            if last is None:
                last_emitted_books[mid] = copy.deepcopy(curr)
                continue

            events = compute_delta(last, curr)
            if events:
                append_delta_line(output_root, platform, mid, now, events)
            last_emitted_books[mid] = copy.deepcopy(curr)


def _load_markets(markets_file: str, markets_cli: str) -> list:
    if markets_file:
        from src.simulator.market_list import load_markets_from_file

        out = load_markets_from_file(markets_file)
        return [m for m in out if m.strip()]
    if markets_cli:
        return [m.strip() for m in markets_cli.split(",") if m.strip()]
    return []


async def run(
    output_root: str,
    interval: float,
    duration: float,
    market_ids: list,
    mode: str,
    *,
    include_trades: bool,
) -> None:
    if not market_ids:
        logger.error("No markets specified (--markets-file or --markets)")
        return
    ws = PolymarketWebSocket()
    ws.register_callback(WebSocketEventType.ORDERBOOK_UPDATE, _on_orderbook)
    if include_trades:
        ws.register_callback(WebSocketEventType.TRADE, _make_trade_handler(output_root))

    for mid in market_ids:
        current_books[mid] = None
        last_emitted_books[mid] = None
        snapshot_written[mid] = False

    start_task = asyncio.create_task(ws.start())
    await asyncio.sleep(3)
    if not ws.is_connected:
        logger.warning("WebSocket not connected after 3s, attempting subscribe anyway")
    await ws.subscribe_assets(market_ids)
    logger.info(
        "Subscribed to %d Polymarket assets (logging trades to trades.jsonl=%s)",
        len(market_ids),
        "yes" if include_trades else "no",
    )

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
        description="HFT orderbook collector for Polymarket (snapshot + 1s frames or deltas; WS trades to trades.jsonl)"
    )
    parser.add_argument("--markets-file", type=str, default=None, help="Path to file with one asset ID per line")
    parser.add_argument("--markets", type=str, default=None, help="Comma-separated Polymarket asset (token) IDs")
    parser.add_argument("--output-root", type=str, default="./data_HFT", help="Output root (default: ./data_HFT)")
    parser.add_argument("--interval", type=float, default=1.0, help="Delta interval in seconds (default: 1.0)")
    parser.add_argument("--duration", type=float, default=None, help="Run for N seconds then exit (optional)")
    parser.add_argument(
        "--no-trades",
        action="store_true",
        help="Do not append Polymarket last_trade_price events to trades.jsonl",
    )
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

    asyncio.run(
        run(
            args.output_root,
            args.interval,
            args.duration,
            market_ids,
            args.mode,
            include_trades=not args.no_trades,
        )
    )


if __name__ == "__main__":
    main()
