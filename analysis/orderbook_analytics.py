"""Replay Kalshi/Polymarket HFT deltas and extract order-book features for research notebooks.

Assumes ``snapshot.json`` + ``deltas.jsonl`` under ``data_root/platform/market_id/``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.data.hft_storage import (
    OP_DELETE,
    OP_SET,
    SIDE_ASK,
    SIDE_BID,
    DeltaEvent,
    load_snapshot_as_state,
    stream_deltas,
    apply_delta_events,
    trades_path,
)


def _top_n_depth(side_map: Dict[float, float], *, bids: bool, n: int) -> Tuple[float, int]:
    """Sum size at best N price levels (bids: highest prices first; asks: lowest first)."""
    if not side_map or n <= 0:
        return 0.0, 0
    prices = sorted(side_map.keys(), reverse=bids)
    total = 0.0
    k = 0
    for p in prices[:n]:
        s = float(side_map.get(p) or 0)
        if s > 0:
            total += s
            k += 1
    return total, k


def _parse_delta_stats(events: List[DeltaEvent]) -> Dict[str, float]:
    """Summarize one deltas.jsonl line (compact or legacy dict events)."""
    n_set_bid = n_set_ask = n_del_bid = n_del_ask = 0
    max_set_bid = max_set_ask = 0.0
    sum_set_bid = sum_set_ask = 0.0
    for ev in events or []:
        if isinstance(ev, dict):
            op = ev.get("op")
            side = ev.get("side")
            is_bid = side == "bid"
            if op == "set":
                sz = float(ev.get("size") or 0)
                if is_bid:
                    n_set_bid += 1
                    sum_set_bid += sz
                    max_set_bid = max(max_set_bid, sz)
                else:
                    n_set_ask += 1
                    sum_set_ask += sz
                    max_set_ask = max(max_set_ask, sz)
            elif op == "delete":
                if is_bid:
                    n_del_bid += 1
                else:
                    n_del_ask += 1
            continue
        if not isinstance(ev, (list, tuple)) or len(ev) < 3:
            continue
        try:
            op = int(ev[0])
            side = int(ev[1])
        except (TypeError, ValueError):
            continue
        is_bid = side == SIDE_BID
        if op == OP_SET and len(ev) >= 4:
            sz = float(ev[3])
            if is_bid:
                n_set_bid += 1
                sum_set_bid += sz
                max_set_bid = max(max_set_bid, sz)
            else:
                n_set_ask += 1
                sum_set_ask += sz
                max_set_ask = max(max_set_ask, sz)
        elif op == OP_DELETE:
            if is_bid:
                n_del_bid += 1
            else:
                n_del_ask += 1
    return {
        "n_set_bid": float(n_set_bid),
        "n_set_ask": float(n_set_ask),
        "n_del_bid": float(n_del_bid),
        "n_del_ask": float(n_del_ask),
        "max_set_bid": max_set_bid,
        "max_set_ask": max_set_ask,
        "sum_set_bid": sum_set_bid,
        "sum_set_ask": sum_set_ask,
    }


def replay_orderbook_features(
    data_root: str,
    platform: str,
    market_id: str,
    *,
    top_n_levels: int = 5,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """After each deltas line, record mid, spread, imbalance, depth, and delta-line stats.

    Returns one row per deltas.jsonl line (empty list if no snapshot).
    """
    state = load_snapshot_as_state(data_root, platform, market_id)
    if state is None:
        return []

    rows: List[Dict[str, Any]] = []
    bids = state.get("bids") or {}
    asks = state.get("asks") or {}

    for t, events in stream_deltas(data_root, platform, market_id, start_ts=start_ts, end_ts=end_ts):
        dst = _parse_delta_stats(events)
        apply_delta_events(state, events)
        bids = state.get("bids") or {}
        asks = state.get("asks") or {}

        bid_top, _ = _top_n_depth(bids, bids=True, n=top_n_levels)
        ask_top, _ = _top_n_depth(asks, bids=False, n=top_n_levels)
        bid_all = sum(float(s) for s in bids.values() if s and s > 0)
        ask_all = sum(float(s) for s in asks.values() if s and s > 0)

        best_bid = max(bids.keys()) if bids else None
        best_ask = min(asks.keys()) if asks else None
        if best_bid is not None and best_ask is not None:
            spread = float(best_ask) - float(best_bid)
            mid = (float(best_bid) + float(best_ask)) / 2.0
        else:
            spread = None
            mid = None

        imbalance = bid_top - ask_top  # + => more displayed size on bid side near touch
        depth = bid_all + ask_all

        row = {
            "t": float(t),
            "mid": mid,
            "spread": spread,
            "best_bid": float(best_bid) if best_bid is not None else None,
            "best_ask": float(best_ask) if best_ask is not None else None,
            "bid_top5": bid_top,
            "ask_top5": ask_top,
            "imbalance_top5": imbalance,
            "bid_depth_all": bid_all,
            "ask_depth_all": ask_all,
            "depth_all": depth,
        }
        row.update(dst)
        rows.append(row)
    return rows


def load_kalshi_trades_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Parse ``trades.jsonl`` written by ``collect_hft_kalshi``."""
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            km = o.get("kalshi_msg") or {}
            tr = o.get("trade") or {}
            meta = tr.get("metadata") or {}
            taker = (km.get("taker_side") or meta.get("taker_side") or "").lower()
            try:
                sz = float(km.get("count_fp") or tr.get("size") or 0)
            except (TypeError, ValueError):
                sz = 0.0
            try:
                yes_px = float(km.get("yes_price_dollars") or tr.get("price") or 0)
            except (TypeError, ValueError):
                yes_px = None
            ts_ms = km.get("ts_ms")
            ts_sec = km.get("ts")
            t_unix = None
            if ts_ms is not None:
                try:
                    t_unix = int(ts_ms) / 1000.0
                except (TypeError, ValueError):
                    pass
            if t_unix is None and ts_sec is not None:
                try:
                    t_unix = float(ts_sec)
                except (TypeError, ValueError):
                    pass
            out.append(
                {
                    "received_at": o.get("received_at"),
                    "t_unix": t_unix,
                    "taker_side": taker or None,
                    "taker_yes": 1.0 if taker == "yes" else 0.0 if taker == "no" else None,
                    "size": sz,
                    "yes_price": yes_px,
                }
            )
    return out


def trades_path_for(data_root: str, platform: str, market_id: str) -> Path:
    return trades_path(data_root, platform, market_id)
