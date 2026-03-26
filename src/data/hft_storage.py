"""Storage helpers for HFT orderbook data: snapshot + delta/snapshot-stream layout under data_HFT/{platform}/{market_id}/."""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PLATFORMS = ("kalshi", "polymarket")


def get_hft_dir(output_root: str, platform: str, market_id: str) -> Path:
    """Return directory for a market: output_root/platform/market_id."""
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    return Path(output_root).expanduser().resolve() / platform / market_id


def snapshot_path(output_root: str, platform: str, market_id: str) -> Path:
    """Path to snapshot.json for a market."""
    return get_hft_dir(output_root, platform, market_id) / "snapshot.json"


def deltas_path(output_root: str, platform: str, market_id: str) -> Path:
    """Path to deltas.jsonl for a market."""
    return get_hft_dir(output_root, platform, market_id) / "deltas.jsonl"


def frames_path(output_root: str, platform: str, market_id: str) -> Path:
    """Path to frames.jsonl for a market (full snapshot per frame)."""
    return get_hft_dir(output_root, platform, market_id) / "frames.jsonl"


def meta_path(output_root: str, platform: str, market_id: str) -> Path:
    """Path to meta.json for a market."""
    return get_hft_dir(output_root, platform, market_id) / "meta.json"


def ensure_dir(path: Path) -> None:
    """Create parent directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def book_state_from_levels(bids: List[Any], asks: List[Any]) -> Dict[str, Dict[float, float]]:
    """Convert list of (price, size) or OrderBookLevel-like dicts to {bids: {price: size}, asks: {price: size}}."""
    def level_to_map(levels: List[Any]) -> Dict[float, float]:
        out: Dict[float, float] = {}
        for lev in levels or []:
            if isinstance(lev, (list, tuple)) and len(lev) >= 2:
                p, s = float(lev[0]), float(lev[1])
            elif isinstance(lev, dict):
                p = float(lev.get("price", 0))
                s = float(lev.get("size", 0))
            else:
                continue
            if s > 0:
                out[p] = s
        return out

    return {
        "bids": level_to_map(bids),
        "asks": level_to_map(asks),
    }


def snapshot_to_levels(snapshot: Dict[str, Any]) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Convert snapshot.json structure to (bids_list, asks_list) with (price, size) tuples. Bids desc, asks asc."""
    bids_raw = snapshot.get("bids") or []
    asks_raw = snapshot.get("asks") or []
    bids = []
    for b in bids_raw:
        if isinstance(b, (list, tuple)) and len(b) >= 2:
            bids.append((float(b[0]), float(b[1])))
        elif isinstance(b, dict):
            bids.append((float(b.get("price", 0)), float(b.get("size", 0))))
    asks = []
    for a in asks_raw:
        if isinstance(a, (list, tuple)) and len(a) >= 2:
            asks.append((float(a[0]), float(a[1])))
        elif isinstance(a, dict):
            asks.append((float(a.get("price", 0)), float(a.get("size", 0))))
    bids.sort(key=lambda x: -x[0])
    asks.sort(key=lambda x: x[0])
    return (bids, asks)


def write_snapshot(
    output_root: str,
    platform: str,
    market_id: str,
    book_state: Dict[str, Dict[float, float]],
    timestamp_iso: str,
) -> Path:
    """Write snapshot.json. book_state = {bids: {price: size}, asks: {price: size}}."""
    p = snapshot_path(output_root, platform, market_id)
    ensure_dir(p)
    bids_list = sorted([(pr, sz) for pr, sz in book_state.get("bids", {}).items() if sz > 0], key=lambda x: -x[0])
    asks_list = sorted([(pr, sz) for pr, sz in book_state.get("asks", {}).items() if sz > 0], key=lambda x: x[0])
    payload = {
        "market_id": market_id,
        "platform": platform,
        "timestamp": timestamp_iso,
        "bids": bids_list,
        "asks": asks_list,
    }
    with open(p, "w") as f:
        json.dump(payload, f, indent=2)
    return p


def append_delta_line(
    output_root: str,
    platform: str,
    market_id: str,
    unix_ts: float,
    events: List[Dict[str, Any]],
) -> Path:
    """Append one JSON line to deltas.jsonl. events = [{op, side, price?, size?}, ...]."""
    p = deltas_path(output_root, platform, market_id)
    ensure_dir(p)
    line = json.dumps({"t": unix_ts, "events": events}) + "\n"
    with open(p, "a") as f:
        f.write(line)
    return p


def append_snapshot_frame(
    output_root: str,
    platform: str,
    market_id: str,
    unix_ts: float,
    book_state: Dict[str, Dict[float, float]],
) -> Path:
    """Append one JSON line with full snapshot to frames.jsonl. book_state = {bids: {price: size}, asks: {price: size}}."""
    p = frames_path(output_root, platform, market_id)
    ensure_dir(p)
    bids_list = sorted(
        [(pr, sz) for pr, sz in (book_state.get("bids") or {}).items() if sz > 0],
        key=lambda x: -x[0],
    )
    asks_list = sorted(
        [(pr, sz) for pr, sz in (book_state.get("asks") or {}).items() if sz > 0],
        key=lambda x: x[0],
    )
    line = json.dumps({"t": unix_ts, "bids": bids_list, "asks": asks_list}) + "\n"
    with open(p, "a") as f:
        f.write(line)
    return p


def load_snapshot(output_root: str, platform: str, market_id: str) -> Optional[Dict[str, Any]]:
    """Load snapshot.json. Returns None if missing."""
    p = snapshot_path(output_root, platform, market_id)
    if not p.is_file():
        return None
    with open(p) as f:
        return json.load(f)


def load_snapshot_as_state(output_root: str, platform: str, market_id: str) -> Optional[Dict[str, Dict[float, float]]]:
    """Load snapshot and return book_state {bids: {price: size}, asks: {...}}."""
    snap = load_snapshot(output_root, platform, market_id)
    if not snap:
        return None
    bids_list, asks_list = snapshot_to_levels(snap)
    return {
        "bids": {p: s for p, s in bids_list if s > 0},
        "asks": {p: s for p, s in asks_list if s > 0},
    }


def compute_delta(
    prev: Dict[str, Dict[float, float]],
    curr: Dict[str, Dict[float, float]],
) -> List[Dict[str, Any]]:
    """Compute delta events from prev to curr. Returns list of {op, side, price, size?}."""
    events: List[Dict[str, Any]] = []
    for side in ("bids", "asks"):
        prev_side = prev.get(side) or {}
        curr_side = curr.get(side) or {}
        all_prices = set(prev_side.keys()) | set(curr_side.keys())
        for price in all_prices:
            prev_sz = prev_side.get(price)
            curr_sz = curr_side.get(price)
            if curr_sz is None or curr_sz <= 0:
                if prev_sz is not None and prev_sz > 0:
                    events.append({"op": "delete", "side": side[:-1], "price": price})
            else:
                if prev_sz != curr_sz:
                    events.append({"op": "set", "side": side[:-1], "price": price, "size": curr_sz})
    return events


def apply_delta_events(book_state: Dict[str, Dict[float, float]], events: List[Dict[str, Any]]) -> None:
    """Apply delta events in-place to book_state. side in events is 'bid' or 'ask'."""
    for ev in events or []:
        op = ev.get("op")
        side_key = "bids" if ev.get("side") == "bid" else "asks"
        price = ev.get("price")
        if price is None:
            continue
        price_f = float(price)
        if side_key not in book_state:
            book_state[side_key] = {}
        if op == "delete":
            book_state[side_key].pop(price_f, None)
        elif op == "set":
            sz = ev.get("size")
            if sz is not None and float(sz) > 0:
                book_state[side_key][price_f] = float(sz)
            else:
                book_state[side_key].pop(price_f, None)


def stream_deltas(
    output_root: str,
    platform: str,
    market_id: str,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
) -> Iterator[Tuple[float, List[Dict[str, Any]]]]:
    """Yield (unix_ts, events) for each line in deltas.jsonl, optionally filtered by start_ts/end_ts."""
    p = deltas_path(output_root, platform, market_id)
    if not p.is_file():
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = rec.get("t")
            if t is None:
                continue
            t_float = float(t)
            if start_ts is not None and t_float < start_ts:
                continue
            if end_ts is not None and t_float > end_ts:
                continue
            events = rec.get("events") or []
            yield (t_float, events)
