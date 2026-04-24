#!/usr/bin/env python3
"""Align time-stamped Twitter metric JSONL with Polymarket price history; report correlations.

Polymarket file: prices.json with { "history": [ { "t": unix_sec, "p": price }, ... ] }
as produced by data_gathering_poly (or CLOB prices-history).

Twitter file: JSONL lines from alt_data/pull_twitter.py (collected_at, sentiment_score, etc.).

Daily alignment (UTC): Twitter metrics aggregated with mean per day; Polymarket uses last price
per UTC day. Inner-join on dates present in both series.

Examples:
  python alt_data/correlate_polymarket.py \\
    --twitter-jsonl alt_data/out/macro.jsonl \\
    --data-root ./data_poly --token-id YOUR_TOKEN_ID

  python alt_data/correlate_polymarket.py \\
    --twitter-jsonl alt_data/out/macro.jsonl \\
    --prices-json ./data_poly/polymarket/YOUR_TOKEN_ID/prices.json \\
    --lag-days 0 1 2 --csv alt_data/out/panel.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def load_twitter_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"No rows in {path}")
    df = pd.DataFrame(rows)
    if "collected_at" not in df.columns:
        raise ValueError("Twitter JSONL must include collected_at")
    df["ts"] = pd.to_datetime(df["collected_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    return df


def load_prices_json(path: Path) -> pd.DataFrame:
    with path.open(encoding="utf-8") as f:
        blob = json.load(f)
    hist = blob.get("history") or []
    if not hist:
        raise ValueError(f"No history in {path}")
    df = pd.DataFrame(hist)
    if "t" not in df.columns or "p" not in df.columns:
        raise ValueError("prices history must have t and p")
    df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df["p"] = pd.to_numeric(df["p"], errors="coerce")
    df = df.dropna(subset=["ts", "p"])
    return df


def resolve_prices_path(prices_json: Optional[str], data_root: Optional[str], token_id: Optional[str]) -> Path:
    if prices_json:
        return Path(prices_json).expanduser().resolve()
    if data_root and token_id:
        return Path(data_root).expanduser().resolve() / "polymarket" / str(token_id).strip() / "prices.json"
    raise SystemExit("Provide --prices-json or both --data-root and --token-id.")


def daily_twitter(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    numeric_cols = ["sentiment_score", "mention_count", "engagement_score", "tweets_analyzed"]
    use = [c for c in numeric_cols if c in df.columns]
    if not use:
        raise ValueError("Twitter frame has no known metric columns")
    g = df.set_index("ts")[use].sort_index().resample(freq).mean()
    g = g.dropna(how="all")
    g["date"] = g.index.normalize()
    return g.reset_index()


def daily_prices(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    s = df.set_index("ts")["p"].sort_index().resample(freq).last()
    s = s.dropna()
    out = s.to_frame(name="price")
    out["date"] = out.index.normalize()
    return out.reset_index()


def add_return_and_logit(merged: pd.DataFrame) -> pd.DataFrame:
    m = merged.sort_values("date").copy()
    m["daily_return"] = m["price"].pct_change()
    eps = 1e-6
    pc = m["price"].clip(eps, 1.0 - eps)
    m["logit_price"] = np.log(pc / (1.0 - pc))
    return m


def shift_twitter_metrics(
    merged: pd.DataFrame,
    twitter_cols: List[str],
    lag_days: int,
) -> pd.DataFrame:
    m = merged.copy()
    if lag_days == 0:
        return m
    for c in twitter_cols:
        if c in m.columns:
            m[c] = m[c].shift(lag_days)
    return m


def corr_pair(a: pd.Series, b: pd.Series, method: str) -> float:
    pair = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(pair) < 3:
        return float("nan")
    return float(pair["a"].corr(pair["b"], method=method))


def run_correlation(
    merged: pd.DataFrame,
    twitter_cols: List[str],
    targets: List[str],
) -> List[Tuple[str, str, float, float]]:
    rows: List[Tuple[str, str, float, float]] = []
    for tcol in twitter_cols:
        if tcol not in merged.columns:
            continue
        for target in targets:
            if target not in merged.columns:
                continue
            p = corr_pair(merged[tcol], merged[target], "pearson")
            s = corr_pair(merged[tcol], merged[target], "spearman")
            rows.append((tcol, target, p, s))
    return rows


def main() -> None:
    p = argparse.ArgumentParser(
        description="Correlate Twitter metric JSONL with Polymarket price history (daily UTC)."
    )
    p.add_argument("--twitter-jsonl", required=True, help="JSONL from pull_twitter.py")
    p.add_argument("--prices-json", default="", help="Path to prices.json")
    p.add_argument("--data-root", default="", help="Base path containing polymarket/{token_id}/prices.json")
    p.add_argument("--token-id", default="", help="CLOB token id (with --data-root)")
    p.add_argument(
        "--freq",
        default="1D",
        help="Pandas offset alias for resampling (default 1D).",
    )
    p.add_argument(
        "--lag-days",
        type=int,
        nargs="*",
        default=[0],
        help="Shift Twitter metrics forward by N days (0-7 typical). Space-separated list.",
    )
    p.add_argument(
        "--csv",
        default="",
        help="Optional path to write merged daily panel CSV (uses --csv-lag).",
    )
    p.add_argument(
        "--csv-lag",
        type=int,
        default=None,
        help="Lag applied in exported CSV (default: min of --lag-days).",
    )
    args = p.parse_args()

    tw_path = Path(args.twitter_jsonl).expanduser().resolve()
    prices_path = resolve_prices_path(
        args.prices_json or None,
        args.data_root or None,
        args.token_id or None,
    )

    tw = load_twitter_jsonl(tw_path)
    poly = load_prices_json(prices_path)

    tw_d = daily_twitter(tw, args.freq)
    poly_d = daily_prices(poly, args.freq)

    merged_base = tw_d.merge(poly_d, on="date", how="inner")
    if merged_base.empty:
        raise SystemExit("No overlapping dates after daily merge; check time ranges and JSONL coverage.")

    twitter_cols = [
        c
        for c in ["sentiment_score", "mention_count", "engagement_score", "tweets_analyzed"]
        if c in merged_base.columns
    ]
    targets = ["price", "daily_return", "logit_price"]

    print(f"Twitter rows (raw): {len(tw)}  file={tw_path}")
    print(f"Price points (raw): {len(poly)}  file={prices_path}")
    print(f"Overlapping daily rows: {len(merged_base)}")
    print()

    lags = sorted({int(x) for x in args.lag_days})
    csv_lag = args.csv_lag if args.csv_lag is not None else (lags[0] if lags else 0)

    for lag in lags:
        if lag < 0 or lag > 30:
            print(f"Skipping invalid lag-days={lag}", file=sys.stderr)
            continue
        m = add_return_and_logit(merged_base)
        m = shift_twitter_metrics(m, twitter_cols, lag)
        m = m.dropna(subset=["price"])
        print(
            f"--- lag_days={lag} "
            f"(Twitter metrics shifted forward by {lag}: row date D uses values from D-{lag}) ---"
        )
        usable = m.dropna(subset=twitter_cols + ["price"])
        print(f"Usable rows (non-null twitter + price): {len(usable)}")

        results = run_correlation(m, twitter_cols, targets)
        for tcol, target, pear, spear in results:
            print(f"  {tcol:20} vs {target:14}  Pearson={pear:+.4f}  Spearman={spear:+.4f}")
        print()

    if args.csv:
        m_export = add_return_and_logit(merged_base)
        m_export = shift_twitter_metrics(m_export, twitter_cols, csv_lag)
        out = Path(args.csv).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        m_export.to_csv(out, index=False)
        print(f"Wrote panel CSV (lag={csv_lag}): {out}")


if __name__ == "__main__":
    main()
