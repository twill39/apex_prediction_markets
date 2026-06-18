"""Tests for MM-AS tear sheet helpers."""

import pandas as pd

from scripts.mm_as_tear_sheet import fifo_realized_by_closing_bucket, size_bucket_label


def test_size_bucket_labels():
    assert size_bucket_label(10) == "0–50"
    assert size_bucket_label(50) == "50–200"
    assert size_bucket_label(1500) == "1000+"


def test_fifo_realized_buy_to_close_short():
    df = pd.DataFrame(
        {
            "market_id": ["m", "m"],
            "side": ["sell", "buy"],
            "price": [0.6, 0.55],
            "size": [100.0, 100.0],
            "fees": [0.0, 0.0],
            "timestamp": pd.date_range("2026-05-01", periods=2, freq="min"),
        }
    )
    out = fifo_realized_by_closing_bucket(df)
    assert len(out) == 1
    assert out.iloc[0]["pnl"] == (0.6 - 0.55) * 100.0
    assert out.iloc[0]["closing_bucket"] == size_bucket_label(100.0)
