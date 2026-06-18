#!/usr/bin/env python3
"""Fetch recent 1-minute SPX data from Schwab and write a CSV.

This script uses the `schwabdev` client to fetch recent minute candles for a
BTC symbol, converts timestamps to America/New_York, filters to 09:00-17:00 ET,
keeps the most recent 10 dates, and writes a CSV for downstream regime-score
work.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import schwabdev

import pandas as pd
from dotenv import load_dotenv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch minute SPX history from Schwab")
    parser.add_argument(
        "--symbol",
        default="$SPX",
        help="Schwab symbol to query (default: $SPX)",
    )
    parser.add_argument(
        "--period-days",
        type=int,
        default=10,
        help="Calendar-day lookback to request from Schwab (default: 14)",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=10,
        help="Number of most recent ET dates to keep after filtering (default: 10)",
    )
    parser.add_argument(
        "--start-hour",
        type=int,
        default=9,
        help="ET hour at which to start keeping candles, inclusive (default: 9)",
    )
    parser.add_argument(
        "--end-hour",
        type=int,
        default=16,
        help="ET hour at which to stop keeping candles, exclusive (default: 16)",
    )
    parser.add_argument(
        "--output",
        default="data/spx_schwab",
        help="Output directory for per-day CSV files",
    )
    return parser


def _load_client():
    load_dotenv()
    app_key = os.getenv("APP_KEY")
    app_secret = os.getenv("APP_SECRET")

    if not app_key or not app_secret:
        raise SystemExit("APP_KEY and APP_SECRET must be set in your environment or .env")

    return schwabdev.Client(app_key, app_secret)


def _fetch_candles(client, symbol: str, period_days: int) -> list[dict]:
    response = client.price_history(
        symbol=symbol,
        periodType="day",
        period=period_days,
        frequencyType="minute",
        frequency=1,
    )

    payload = response.json()
    candles = payload.get("candles", [])
    if not candles:
        raise SystemExit(f"No candles returned for symbol={symbol}. Response keys: {list(payload.keys())}")
    return candles


def _prepare_frame(
    candles: list[dict],
    keep_days: int,
    start_hour: int,
    end_hour: int,
) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if "datetime" not in df.columns:
        raise SystemExit(f"Expected 'datetime' in Schwab candles, got columns: {list(df.columns)}")

    df["timestamp_utc"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
    df["timestamp_et"] = df["timestamp_utc"].dt.tz_convert("America/New_York")
    df["trade_date_et"] = df["timestamp_et"].dt.date

    df = df[(df["timestamp_et"].dt.hour >= start_hour) & (df["timestamp_et"].dt.hour < end_hour)].copy()
    if df.empty:
        raise SystemExit("No rows remained after applying the ET session-hour filter.")

    recent_dates = sorted(df["trade_date_et"].unique())[-keep_days:]
    df = df[df["trade_date_et"].isin(recent_dates)].copy()

    df = df.sort_values("timestamp_et").reset_index(drop=True)

    preferred_cols = [
        "timestamp_utc",
        "timestamp_et",
        "trade_date_et",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    existing_cols = [col for col in preferred_cols if col in df.columns]
    remaining_cols = [col for col in df.columns if col not in existing_cols]
    return df[existing_cols + remaining_cols]


def _write_per_day_csvs(df: pd.DataFrame, output_dir: Path, symbol: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for trade_date, day_df in df.groupby("trade_date_et", sort=True):
        trade_date_str = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
        day_path = output_dir / f"{symbol.lower()}_1min_{trade_date_str}.csv"
        day_df.to_csv(day_path, index=False)
        written += 1

    return written


def main() -> int:
    args = _build_parser().parse_args()

    client = _load_client()
    candles = _fetch_candles(client, args.symbol, args.period_days)
    df = _prepare_frame(candles, args.keep_days, args.start_hour, args.end_hour)

    output_dir = Path(args.output)
    written = _write_per_day_csvs(df, output_dir, args.symbol)

    print(
        f"Wrote {len(df)} rows across {df['trade_date_et'].nunique()} ET dates "
        f"for {args.symbol} into {written} CSV files under {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
