#!/usr/bin/env python3
"""One-off generator for analysis/*.ipynb (run from repo: python analysis/_gen_notebooks.py)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

def cell_md(s: str):
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in s.strip().split("\n")]}

def cell_py(s: str):
    return {"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None, "source": [l + "\n" for l in s.strip().split("\n")]}

def save(name: str, cells: list):
    nb = {
        "cells": cells,
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
    (ROOT / name).write_text(json.dumps(nb, indent=1), encoding="utf-8")

# --- 00 ---
save(
    "00_hft_reconstruct_validate.ipynb",
    [
        cell_md("""# HFT reconstruction and multi-run validation

Use `reconstruct_time_series` with **`data_root`** set to `data_HFT`, `data_HFT2`, or `data_HFT3` to compare runs. If a snapshot was overwritten, mid/spread for **that** folder may be wrong for the start of the series — see `presentation.md`."""),
        cell_py("""import sys
from pathlib import Path
REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."  # if launched from analysis/
sys.path.insert(0, str(REPO))

import matplotlib.pyplot as plt
import pandas as pd

from scripts.reconstruct_hft_orderbook import reconstruct_time_series

# --- edit these ---
KALSHI_TICKER = "KXNFLDRAFTTOP-26-R1-AHIL"
HFT_ROOTS = [
    ("run_1", REPO / "data_HFT"),
    ("run_2", REPO / "data_HFT2"),
    ("run_3", REPO / "data_HFT3"),
]

def load_series(name: str, data_root: Path) -> pd.DataFrame:
    rows = reconstruct_time_series(str(data_root), "kalshi", KALSHI_TICKER)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df["label"] = name
    return df

dfs = [load_series(n, p) for n, p in HFT_ROOTS if p.is_dir()]
fig, ax = plt.subplots(figsize=(10, 4))
for d in dfs:
    if d.empty or "mid" not in d:
        continue
    ax.plot(d["t"], d["mid"], label=d["label"].iloc[0], alpha=0.8)
ax.set_title(f"Mid (Kalshi) — {KALSHI_TICKER}")
ax.set_xlabel("Time (UTC)"); ax.set_ylabel("Mid")
ax.legend()
fig.tight_layout()
plt.show()

for d in dfs:
    n = d["label"].iloc[0] if not d.empty else "?"
    print(f"{n} rows: {len(d)}")"""),
    ],
)

# --- 01 ---
save(
    "01_microstructure_dynamics.ipynb",
    [
        cell_md("""# Microstructure: spread, mid volatility, order-book activity (deltas)

**Ideas (not all implemented here):** rolling spread, absolute mid change, number of level updates per second from `deltas.jsonl` (compact format `[op,side,price]`), correlation with *future* mid moves (your label: forward return over horizon H). For Polymarket, sparse WS may yield few deltas; Kalshi is usually denser."""),
        cell_py("""import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
sys.path.insert(0, str(REPO))

from analysis.paths import REPO_ROOT
from src.data.hft_storage import deltas_path

# Kalshi: count delta events per second
TICKER = "KXNFLDRAFTTOP-26-R1-AHIL"
root = REPO_ROOT / "data_HFT" / "kalshi" / TICKER
dpath = root / "deltas.jsonl"
if not dpath.is_file():
    print("No deltas at", dpath, "- set TICKER and path to your data")
else:
    counts = []
    times = []
    with open(dpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            t = rec.get("t")
            n = len(rec.get("e") or rec.get("events") or [])
            times.append(float(t))
            counts.append(n)
    s = pd.Series(counts, index=pd.to_datetime(pd.Series(times), unit="s", utc=True))
    fig, ax = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    ax[0].plot(s.index, s.values, color="C0", lw=0.8)
    ax[0].set_ylabel("Events / line")
    ax[0].set_title("Deltas line length (book updates batch per tick)")
    # rolling 30s sum of events
    roll = s.resample("30s").sum()
    ax[1].bar(roll.index, roll.values, width=0.0003, color="C1", alpha=0.7)
    ax[1].set_ylabel("30s sum")
    fig.tight_layout()
    plt.show()"""),
        cell_py("""# Mid + spread from reconstruction (if snapshot valid for this run)
from scripts.reconstruct_hft_orderbook import reconstruct_time_series
rows = reconstruct_time_series(str(REPO_ROOT / "data_HFT"), "kalshi", TICKER)
dfr = pd.DataFrame(rows)
if not dfr.empty and "spread" in dfr:
    dfr["t"] = pd.to_datetime(dfr["t"], unit="s", utc=True)
    dfr = dfr.dropna(subset=["mid", "spread"])
    dfr["mid_ret_1s"] = dfr["mid"].diff()
    print(dfr["spread"].describe().to_string())
    print("mid 1s diff |mean|", dfr["mid_ret_1s"].abs().mean())"""),
    ],
)

# --- 02 ---
save(
    "02_cross_venue_prices.ipynb",
    [
        cell_md("""# Cross-venue: Kalshi vs Polymarket (alignment stub)

**Problem:** the same *economic* outcome (player drafted in round 1) appears as:
- a Kalshi `market_ticker` and
- one or more Polymarket CLOB `asset_id` strings.

**This notebook** loads reconstructed mids for a **hand-picked** pair. Build a CSV mapping, e.g. `analysis/venue_map_template.csv`, with columns `kalshi_ticker, polymarket_token_id, label`. Then merge series on time (as-of join) and plot **implied** gap (after scaling to similar probability space).

**Arb / microstructure:** large gaps *after* fees may indicate friction or latency; HFT data helps describe *when* books moved, not guaranteed tradeable edge."""),
        cell_py("""import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
sys.path.insert(0, str(REPO))
from analysis.paths import REPO_ROOT
from scripts.reconstruct_hft_orderbook import reconstruct_time_series

# --- set one pair you know is the same outcome ---
KALSHI = "KXNFLDRAFTTOP-26-R1-AHIL"
# replace with a token from data_HFT3/polymarket/... or poly_tokens_draft_r1.txt
POLY = "14508344936788585593838466817376200856495780195297665568221873275696145422256"
DATA = REPO_ROOT / "data_HFT"

rk = reconstruct_time_series(str(DATA), "kalshi", KALSHI)
rp = reconstruct_time_series(str(DATA), "polymarket", POLY)
k = pd.DataFrame(rk)
p = pd.DataFrame(rp)
if not k.empty: k["t"] = pd.to_datetime(k["t"], unit="s", utc=True)
if not p.empty: p["t"] = pd.to_datetime(p["t"], unit="s", utc=True)

fig, ax = plt.subplots(figsize=(10,4))
if not k.empty: ax.plot(k["t"], k["mid"], label="Kalshi mid (YES price scale)", alpha=0.8)
if not p.empty: ax.plot(p["t"], p["mid"], label="Polymarket mid (token/cents)", alpha=0.8)
ax.legend()
ax.set_title("Compare scales before interpreting — align to probability 0-1 if needed")
plt.show()"""),
    ],
)

# --- 03 ---
save(
    "03_trades_orderflow.ipynb",
    [
        cell_md("""# Trades: size distribution, taker side, time clustering (Kalshi)

`trades.jsonl` records public executions from the Kalshi `trade` channel. `kalshi_msg` has `taker_side`, `count_fp`, `yes_price_dollars` — useful to separate **aggressive** flow. \"Toxicity\" in the book-building sense and \"retail\" are **not** directly observed without account IDs; use heuristics: time-of-day, size buckets, burstiness, correlation with price moves. **Exploit**-seeking is research-only here."""),
        cell_py("""import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
TICKER = "KXNFLDRAFTTOP-26-R1-ATER"  # example with more trades
trp = REPO / "data_HFT2" / "kalshi" / TICKER / "trades.jsonl"  # adjust
rows = []
if trp.is_file():
    with open(trp) as f:
        for line in f:
            line=line.strip()
            if not line: continue
            o = json.loads(line)
            km = o.get("kalshi_msg") or {}
            rows.append({
                "t": o.get("received_at"),
                "size": float(km.get("count_fp") or 0),
                "taker": km.get("taker_side"),
                "yes_price": float(km.get("yes_price_dollars") or 0) if km.get("yes_price_dollars") else None,
            })
    df = pd.DataFrame(rows)
    if "t" in df.columns: df["t"] = pd.to_datetime(df["t"], utc=True)
    print(df.describe(include="all").T.head(20))
    fig, ax = plt.subplots(1,2, figsize=(10,4))
    if not df.empty and "size" in df:
        ax[0].hist(df["size"].clip(upper=df["size"].quantile(0.99)), bins=30, color="C0", edgecolor="white")
        ax[0].set_title("Trade size (capped 99% for viz)")
    if not df.empty and "t" in df:
        c = df.set_index("t")["size"].resample("1min").count()
        ax[1].plot(c.index, c.values)
        ax[1].set_title("Trades per minute")
    fig.tight_layout()
    plt.show()
else:
    print("Missing", trp)"""),
    ],
)

# --- 04 ---
save(
    "04_twitter_draft_altdata.ipynb",
    [
        cell_md("""# Twitter filtered stream: volume, per-handle activity, (optional) text signal

`draft_night_handles_stream.jsonl` has `data.text`, `data.created_at`, and `includes.users` for usernames. **Event study:** merge tweet timestamps to mid-price steps (± e.g. 15 min) on your Kalshi market of interest. **LLM / keyword stub:** add a function that returns a float score 0-1 for \"mentions player X as likely R1\" — use `OPENAI_API_KEY` in env only; do not commit secrets."""),
        cell_py("""import json
from collections import Counter
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
JSONL = REPO / "alt_data" / "out" / "draft_night_handles_stream.jsonl"
if not JSONL.is_file():
    print("Set JSONL path to your stream file")
else:
    rows = []
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            d = o.get("data") or {}
            if "id" not in d:
                continue
            u = (o.get("includes") or {}).get("users") or [{}]
            h = (u[0] or {}).get("username", "?")
            rows.append({"t": d.get("created_at"), "handle": h, "text": (d.get("text") or "")[:200]})
    df = pd.DataFrame(rows)
    if not df.empty and "t" in df:
        df["t"] = pd.to_datetime(df["t"], utc=True, errors="coerce")
        c = df.groupby("handle").size().sort_values(ascending=False).head(20)
        c.plot.bar(figsize=(10,4), title="Top handles by count")
        plt.tight_layout()
        plt.show()
# Placeholder: score_text = lambda t: 0.0  # later: call LLM for player-specific likelihood"""),
    ],
)

# --- 05 ---
save(
    "05_key_statistics_summary.ipynb",
    [
        cell_md("""# Key statistics (exportable for slides)

Edits: point `HFT_DIR` to the run you want in the table (e.g. `data_HFT2`). This cell scans Kalshi subfolders and aggregates row counts. **Findings** column is left for you after you run other notebooks."""),
        cell_py("""from pathlib import Path
import json
import pandas as pd

REPO = Path.cwd().resolve()
if not (REPO / "src").is_dir():
    REPO = REPO / ".."
HFT_DIR = REPO / "data_HFT2" / "kalshi"
if not HFT_DIR.is_dir():
    HFT_DIR = REPO / "data_HFT" / "kalshi"

out = []
for p in sorted(HFT_DIR.iterdir()) if HFT_DIR.is_dir() else []:
    if not p.is_dir():
        continue
    t = p / "trades.jsonl"
    d = p / "deltas.jsonl"
    nt = sum(1 for _ in open(t)) if t.is_file() else 0
    nd = sum(1 for _ in open(d)) if d.is_file() else 0
    out.append({"ticker": p.name, "trades_lines": nt, "deltas_lines": nd})

if out:
    tab = pd.DataFrame(out)
    # totals for slide
    print("Totals:", tab["trades_lines"].sum(), "trade lines", tab["deltas_lines"].sum(), "delta lines")
    print(tab.head(15).to_string())
    tab.to_csv(REPO / "analysis" / "output_key_stats_kalshi.csv", index=False)
    print("Wrote analysis/output_key_stats_kalshi.csv")
else:
    print("No data under", HFT_DIR)""",
        ),
    ],
)

if __name__ == "__main__":
    print("Wrote notebooks in", ROOT)
