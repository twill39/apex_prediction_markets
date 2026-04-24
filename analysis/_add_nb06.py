#!/usr/bin/env python3
"""Append notebook 06 (run: python analysis/_add_nb06.py)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def cell_md(s: str):
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in s.strip().split("\n")]}


def cell_py(s: str):
    return {"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None, "source": [l + "\n" for l in s.strip().split("\n")]}


nb = {
    "cells": [
        cell_md(
            """# Order book pressure, spread dynamics, and trade-side signals (Kalshi)

This notebook uses **full book replay** from `snapshot.json` + `deltas.jsonl` (not only best bid/ask from the thin reconstruct script).

**Hypotheses (exploratory, not investment advice):**
- **Imbalance (top-5 bid size − top-5 ask size)** may lean with **near-term mid** if one side is stacking limit liquidity.
- **Spread** and its **volatility** describe stress / uncertainty in the YES/NO book.
- **Taker side** (`yes` vs `no` in Kalshi public trades): aggressive flow hitting the YES book vs NO book; relate to **forward mid** over the next few delta steps or a short time window.
- **Large resting adds** (`max_set_bid` / `max_set_ask` per delta line) as a **heuristic** for “whale” vs noise — **cannot** identify informed vs retail without account IDs; interpret as *size concentration in displayed liquidity*.

**Caveats:** bad `snapshot.json` invalidates the early path; correlation ≠ causation; multiple testing — use as *story-building* for the project deck."""
        ),
        cell_py(
            """import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
sys.path.insert(0, str(REPO))

from analysis.orderbook_analytics import (
    replay_orderbook_features,
    load_kalshi_trades_jsonl,
    trades_path_for,
)

# --- edit: HFT run + ticker ---
DATA_ROOT = str(REPO / "data_HFT3")
TICKER = "KXNFLDRAFTTOP-26-R1-AHIL"
TOP_N = 5
FORWARD_STEPS = 15  # delta lines ahead for "future" mid change

rows = replay_orderbook_features(DATA_ROOT, "kalshi", TICKER, top_n_levels=TOP_N)
book = pd.DataFrame(rows)
if book.empty:
    raise SystemExit("No book replay rows — check snapshot + deltas under DATA_ROOT")

book = book.sort_values("t").reset_index(drop=True)
book["mid_fwd"] = book["mid"].shift(-FORWARD_STEPS)
book["d_mid_fwd"] = book["mid_fwd"] - book["mid"]
book["spread_roll_std"] = book["spread"].rolling(60, min_periods=10).std()

print(book[["mid", "spread", "imbalance_top5", "depth_all"]].describe().to_string())"""
        ),
        cell_py(
            """# 1) Spread over time + rolling volatility
fig, ax = plt.subplots(2, 1, figsize=(11, 5), sharex=True)
ax[0].plot(pd.to_datetime(book["t"], unit="s", utc=True), book["spread"], lw=0.6, alpha=0.85)
ax[0].set_ylabel("Spread")
ax[0].set_title(f"Spread (Kalshi {TICKER})")
ax[1].plot(pd.to_datetime(book["t"], unit="s", utc=True), book["spread_roll_std"], color="C1", lw=0.7)
ax[1].set_ylabel("Rolling std(spread)")
ax[1].set_xlabel("Time (UTC)")
fig.tight_layout()
plt.show()"""
        ),
        cell_py(
            """# 2) Order-book pressure vs future mid change (same series, lead-lag)
sub = book.dropna(subset=["imbalance_top5", "d_mid_fwd"])
if len(sub) > 50:
    r = sub["imbalance_top5"].corr(sub["d_mid_fwd"])
    print(f"Corr(imbalance_top5, d_mid over next {FORWARD_STEPS} steps): {r:.4f}")
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.scatter(sub["imbalance_top5"], sub["d_mid_fwd"], s=4, alpha=0.25, rasterized=True)
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_xlabel("Imbalance (top-5 bid vol − top-5 ask vol)")
    ax.set_ylabel(f"Forward Δmid ({FORWARD_STEPS} steps)")
    ax.set_title("Pressure vs future mid (exploratory)")
    fig.tight_layout()
    plt.show()
else:
    print("Not enough rows with valid forward mid")"""
        ),
        cell_py(
            """# 3) Large displayed adds (heuristic) vs forward mid
sub2 = book.dropna(subset=["max_set_bid", "max_set_ask", "d_mid_fwd"])
if len(sub2) > 50:
    sub2["large_side"] = np.maximum(sub2["max_set_bid"], sub2["max_set_ask"])
    r2 = sub2["large_side"].corr(sub2["d_mid_fwd"])
    print(f"Corr(max single-line set size, d_mid_fwd): {r2:.4f}")
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.scatter(np.log1p(sub2["large_side"]), sub2["d_mid_fwd"], s=4, alpha=0.2, rasterized=True)
    ax.set_xlabel("log(1 + max set size on line)")
    ax.set_ylabel(f"Forward Δmid ({FORWARD_STEPS} steps)")
    fig.tight_layout()
    plt.show()"""
        ),
        cell_py(
            """# 4) Trades: taker_side vs forward mid (book index, not trade count)
from pathlib import Path

tpath = trades_path_for(DATA_ROOT, "kalshi", TICKER)
tr_raw = load_kalshi_trades_jsonl(Path(tpath))
tr = pd.DataFrame(tr_raw)
if tr.empty or tr["t_unix"].isna().all():
    print("No trades or missing t_unix — skip trade block")
else:
    tr = tr.dropna(subset=["t_unix"]).sort_values("t_unix")
    tr["taker_yes"] = tr["taker_side"].map({"yes": 1.0, "no": 0.0})
    bk = book.dropna(subset=["mid"]).reset_index(drop=True)
    ts = bk["t"].values
    mids = bk["mid"].values
    idx = np.searchsorted(ts, tr["t_unix"].values, side="right") - 1
    idx = np.clip(idx, 0, len(bk) - 1)
    idx2 = np.clip(idx + FORWARD_STEPS, 0, len(bk) - 1)
    tr["mid_at"] = mids[idx]
    tr["mid_fwd"] = mids[idx2]
    tr["d_mid_fwd_trade"] = tr["mid_fwd"] - tr["mid_at"]
    m = tr.dropna(subset=["taker_yes", "d_mid_fwd_trade"])
    if len(m) > 30:
        yes = m[m["taker_yes"] == 1.0]["d_mid_fwd_trade"]
        no = m[m["taker_yes"] == 0.0]["d_mid_fwd_trade"]
        print("Mean forward Δmid after taker_yes=yes trades:", float(yes.mean()))
        print("Mean forward Δmid after taker_yes=no trades: ", float(no.mean()))
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.boxplot([yes.dropna(), no.dropna()], labels=["taker yes", "taker no"])
        ax.axhline(0, color="k", lw=0.5)
        ax.set_ylabel(f"Δmid over next {FORWARD_STEPS} book updates from trade time")
        ax.set_title("Taker side vs subsequent mid (aligned to book timeline)")
        fig.tight_layout()
        plt.show()
    else:
        print("Too few merged trade rows")""",
        ),
        cell_py(
            """# 5) Rolling trade imbalance vs rolling mid change (count windows)
if not tr.empty and tr["taker_yes"].notna().any():
    tr = tr.sort_values("t_unix").reset_index(drop=True)
    win = 50
    tr["roll_yes_frac"] = tr["taker_yes"].rolling(win, min_periods=10).mean()
    bk2 = book.dropna(subset=["mid"]).reset_index(drop=True)
    bk2["d_mid"] = bk2["mid"].diff()
    bk2["roll_dmid"] = bk2["d_mid"].rolling(win, min_periods=10).mean()
    # align on nearest book row index to each trade (same as above)
    ts = bk2["t"].values
    idx = np.searchsorted(ts, tr["t_unix"].values, side="right") - 1
    idx = np.clip(idx, 0, len(bk2) - 1)
    tr["roll_dmid_book"] = bk2["roll_dmid"].values[idx]
    u = tr.dropna(subset=["roll_yes_frac", "roll_dmid_book"])
    if len(u) > 30:
        print("Corr(rolling taker_yes frac, rolling mean d_mid on book):", u["roll_yes_frac"].corr(u["roll_dmid_book"]))"""
        ),
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.12.0"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

(ROOT / "06_orderbook_pressure_informed_flow.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("Wrote", ROOT / "06_orderbook_pressure_informed_flow.ipynb")
