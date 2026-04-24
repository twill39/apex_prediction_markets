#!/usr/bin/env python3
"""Reconstruct orderbook state from HFT snapshot + deltas; optionally export time series (mid, spread, etc.).

Delta lines are compact ``{"t","e"}`` (see ``src.data.hft_storage``) or legacy ``{"t","events"}`` dict events;
both are replayed via ``apply_delta_events``.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.hft_storage import (
    load_snapshot_as_state,
    stream_deltas,
    apply_delta_events,
    frames_path,
    snapshot_path,
)


def reconstruct_time_series(
    data_root: str,
    platform: str,
    market_id: str,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Return ``[{t, best_bid, best_ask, mid, spread}, ...]`` for notebooks and Python callers.

    Uses ``frames.jsonl`` if present; otherwise ``snapshot.json`` + ``deltas.jsonl``.

    Returns an empty list if there is no ``frames.jsonl`` and no readable ``snapshot.json``.
    """
    rows: List[Dict[str, Any]] = []
    frames_file = frames_path(data_root, platform, market_id)
    if frames_file.is_file():
        with open(frames_file) as f:
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
                bids_raw = rec.get("bids") or []
                asks_raw = rec.get("asks") or []
                best_bid = max((float(b[0]) for b in bids_raw), default=None) if bids_raw else None
                best_ask = min((float(a[0]) for a in asks_raw), default=None) if asks_raw else None
                mid = (best_bid + best_ask) / 2.0 if (best_bid is not None and best_ask is not None) else None
                spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
                rows.append(
                    {
                        "t": t_float,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "mid": mid,
                        "spread": spread,
                    }
                )
        return rows

    state = load_snapshot_as_state(data_root, platform, market_id)
    if state is None:
        return []
    for t, events in stream_deltas(data_root, platform, market_id, start_ts=start_ts, end_ts=end_ts):
        apply_delta_events(state, events)
        best_bid = max(state.get("bids", {}).keys()) if state.get("bids") else None
        best_ask = min(state.get("asks", {}).keys()) if state.get("asks") else None
        mid = (best_bid + best_ask) / 2.0 if (best_bid is not None and best_ask is not None) else None
        spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
        rows.append({"t": t, "best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread": spread})
    return rows


def _has_hft_source(data_root: str, platform: str, market_id: str) -> bool:
    return (
        frames_path(data_root, platform, market_id).is_file()
        or snapshot_path(data_root, platform, market_id).is_file()
    )


def run_reconstruct(
    data_root: str,
    platform: str,
    market_id: str,
    start_ts: float = None,
    end_ts: float = None,
    output_path: str = None,
    output_format: str = "csv",
):
    """CLI: same logic as :func:`reconstruct_time_series`, with optional file output."""
    rows = reconstruct_time_series(
        data_root, platform, market_id, start_ts=start_ts, end_ts=end_ts
    )
    if not rows and not _has_hft_source(data_root, platform, market_id):
        print(
            f"No snapshot, deltas, or frames for {platform}/{market_id} under {data_root}",
            file=sys.stderr,
        )
        return 1

    if not output_path:
        for r in rows:
            print(json.dumps(r))
        return 0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if output_format == "csv":
        with open(output_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["t", "best_bid", "best_ask", "mid", "spread"])
            w.writeheader()
            w.writerows(rows)
    else:
        with open(output_path, "w") as f:
            json.dump(rows, f, indent=2)
    print(f"Wrote {len(rows)} rows to {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Reconstruct HFT orderbook from snapshot + deltas")
    parser.add_argument("--platform", choices=["kalshi", "polymarket"], required=True)
    parser.add_argument("--market-id", type=str, required=True, help="Market or asset ID")
    parser.add_argument("--data-root", type=str, default="./data_HFT", help="HFT output root (e.g. ./data_HFT, ./data_HFT2)")
    parser.add_argument("--start-ts", type=float, default=None, help="Filter deltas from this Unix time")
    parser.add_argument("--end-ts", type=float, default=None, help="Filter deltas until this Unix time")
    parser.add_argument("--output", type=str, default=None, help="Write time series to file (CSV or JSON)")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output file format")
    args = parser.parse_args()

    return run_reconstruct(
        args.data_root,
        args.platform,
        args.market_id,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        output_path=args.output,
        output_format=args.format,
    )


if __name__ == "__main__":
    sys.exit(main())
