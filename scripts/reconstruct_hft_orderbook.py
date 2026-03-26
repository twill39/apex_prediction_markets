#!/usr/bin/env python3
"""Reconstruct orderbook state from HFT snapshot + deltas; optionally export time series (mid, spread, etc.)."""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.hft_storage import (
    load_snapshot_as_state,
    stream_deltas,
    apply_delta_events,
    frames_path,
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
    """Load snapshot + deltas (or frames), compute mid/spread series, optionally write to file.

    Supports two storage modes:
    - Deltas mode (snapshot.json + deltas.jsonl): load snapshot, apply deltas, compute metrics.
    - Snapshots mode (frames.jsonl): read each full-frame snapshot and compute metrics directly.
    """
    rows = []

    frames_file = frames_path(data_root, platform, market_id)
    if frames_file.is_file():
        # Snapshots mode: frames.jsonl with full bids/asks per frame
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
                rows.append({"t": t_float, "best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread": spread})
    else:
        # Deltas mode: snapshot.json + deltas.jsonl
        state = load_snapshot_as_state(data_root, platform, market_id)
        if state is None:
            print(f"No snapshot (and no frames.jsonl) found for {platform}/{market_id}", file=sys.stderr)
            return 1
        for t, events in stream_deltas(data_root, platform, market_id, start_ts=start_ts, end_ts=end_ts):
            apply_delta_events(state, events)
            best_bid = max(state.get("bids", {}).keys()) if state.get("bids") else None
            best_ask = min(state.get("asks", {}).keys()) if state.get("asks") else None
            mid = (best_bid + best_ask) / 2.0 if (best_bid is not None and best_ask is not None) else None
            spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
            rows.append({"t": t, "best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread": spread})

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
    parser.add_argument("--data-root", type=str, default="./data_HFT", help="Path to data_HFT root")
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
