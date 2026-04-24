# Presentation: Microstructure, cross-venue prediction markets, and alt data

*Draft document for project talks. Sections marked **(TBD)** are filled in after running `analysis/*.ipynb` and locking numbers.*

## 1. Motivation

- **Parity markets, fragmented liquidity:** the same (or similar) propositions about future events can trade on **Kalshi** (CFTC-regulated event contracts) and on **Polymarket** (CLOB, crypto rails). Public WebSocket and REST APIs allow **order-book and trade** data collection without taking proprietary exchange feeds.
- **Why microstructure:** the **path** of the book—spread, best bid/ask, depth changes, and trade sign—can move **before** a headline reprice, especially in fast information windows (e.g. draft night).
- **Why alt data:** exogenous **X/Twitter** flow from a curated set of accounts may **lead** or **confirm** information embedded in price; measuring that requires time-aligned streams and, optionally, **NLP/LLM** scoring of tweet *content* (not only volume).
- **This project (scope):**  
  1) capture and store HFT-style data;  
  2) **reconstruct** (where valid) and visualize **price + microstructure**;  
  3) compare **cross-venue** series where outcomes map;  
  4) relate **tweets to price** with transparent, reproducible methods;  
  5) discuss what can and cannot be claimed about **“toxic” vs. retail** flow on public data alone.

---

## 2. Theoretical & methodological background

### 2.1 Microstructure

- **Quoting and depth:** the visible book summarizes **evolving beliefs**; **spread** is a friction and inventory proxy; **delta** streams approximate **add/cancel/execution**-induced changes to displayed liquidity.
- **Informed flow:** in classical models, informed traders’ orders can move prices; **toxicity** is used loosely here to mean *execution price impact / adverse selection*; full identification requires private tape or user IDs—**not in our data**—so we use **heuristics** (trade size, taker side, clustering).

### 2.2 Cross-venue comparison

- Comparing “the same” outcome means **aligning** (i) `market_ticker` on Kalshi, (ii) a **CLOB token** or **condition** on Polymarket, and (iii) a **time basis** (UTC) for **as-of** joins. **Implied probability** and **fees** differ; simple mid comparison is a **first pass**, not a live arb P&amp;L simulation.

### 2.3 Alt data (X)

- The **Filtered stream** API (when licensed) appends one JSON line per **matching** tweet, with `created_at` and (via expansions) **author** metadata—suitable for **event studies** (tweet time vs. return over $(t, t+H)$).
- **Text signals** (optional): **keyword/regex** (deterministic) or **LLM** (subjective) scores for *“does this text raise probability of player P being drafted in round 1”*; either requires a clear **rubric** and (for LLM) a **repro** recipe without committing API keys to the repo.

### 2.4 Ethics & “exploit”

- The research is **analytic**: describing structure and potential **latency/statistical** regularities, not a trading system. **No** claims of **guaranteed** profit or of identifying individual traders.

---

## 3. System design (practical)

### 3.1 Ingestion

- **Kalshi WebSocket (signed):** `orderbook_delta` and `trade` channels, merged in `data_HFT/collect_hft_kalshi.py` → per-market `snapshot.json`, `deltas.jsonl`, `trades.jsonl` (separate **output roots** e.g. `data_HFT2`, `data_HFT3` to avoid clobbering).
- **Polymarket WebSocket:** `subscribe_assets` (token IDs from Gamma) → `snapshot.json` / `deltas.jsonl` / `trades.jsonl` under `polymarket/`.
- **X filtered stream** (when available): `alt_data/stream_twitter.py` with `--handles-file` → `draft_night_handles_stream.jsonl`.
- **REST backfill (Polymarket trades):** optional `get_trades_all(event_id=…)` in `data_gathering_poly/polymarket_client.py` (independent of WebSocket run).

### 3.2 Storage formats

- **Deltas (compact):** one JSON line per time step: `{"t", "e": [[op,side,price], [1,side,price,size], ...]}` — see `src/data/hft_storage.py`.
- **Reconstruction:** `reconstruct_time_series` in `scripts/reconstruct_hft_orderbook.py` (prefers `frames.jsonl` if present; else **snapshot + deltas**).

### 3.3 Retrospective analysis

- **Notebooks** under `analysis/` (see `analysis/README.md`):
  - Reconstruction and **multi-run** checks (`00_hft_reconstruct_validate.ipynb`).
  - **Microstructure** and activity from `deltas.jsonl` / reconstructed mids (`01_microstructure_dynamics.ipynb`).
  - **Cross-venue** mid plots with a **manual** mapping table (`02_cross_venue_prices.ipynb`).
  - **Trades** / order-flow proxies (`03_trades_orderflow.ipynb`).
  - **Twitter** stream aggregation and (stub) for text features (`04_twitter_draft_altdata.ipynb`).
  - **Key statistics** export (`05_key_statistics_summary.ipynb`).
  - **Order-book replay** (`06_orderbook_pressure_informed_flow.ipynb`) + helpers in `analysis/orderbook_analytics.py`: imbalance, spread path, large resting adds, trade **taker_side** vs forward mid (exploratory; not identity-level “toxic” detection).

---

## 4. Findings

*(TBD — after notebooks are run. Example bullets to replace with your numbers, charts, and caveats:)*

- **Reconstruction integrity:** (TBD) which HFT run roots have **trusted** snapshots; where overwrite/corrupt snapshot invalidates the early path.
- **Microstructure → price:** (TBD) correlation / Granger / simple **event-study** results of **spread** or **delta-activity** vs. **forward** mid/return; horizon $H$ = e.g. 1 min / 5 min.
- **Cross-venue:** (TBD) typical **gap** between implied mids for mapped pairs; stability over time; role of **fees** and **stale** books.
- **Tweets:** (TBD) count by handle; merge with (Kalshi) mid; **narrative** on any **lead** of tweet bursts vs. price; optional **NLP/LLM** table with **rubric** and error modes.
- **Toxic/retail:** (TBD) heuristics only: size and **taker_side** distributions; no micro-ID claims.

### 4.1 Key statistics (to paste or export from notebook)

| Metric | Value (TBD) | Notes |
|--------|-------------|--------|
| Kalshi markets in sample |  |  |
| Total trade lines (Kalshi) |  |  |
| Total delta lines (Kalshi) |  |  |
| Tweets in filtered stream (sample window) |  |  |
| Manually mapped cross-venue pairs |  |  |

---

## 5. Conclusion

*(TBD: 1–2 paragraphs: what the pipeline demonstrated; what is **reliably** measurable on public data; what would need **proprietary** data or a live execution stack; next steps: mapping table maintenance, more robust snapshot discipline, or expanded NLP eval.)*

---

## 6. How to run (presenter one-pager)

```text
# From repo root
source venv/bin/activate
pip install -r requirements.txt -r requirements-analysis.txt
jupyter lab
# open analysis/00_*.ipynb through 05_*.ipynb; set REPO, TICKER, paths as in cells
```

---

## 7. Open questions / ambiguities (for discussion)

- **Player ↔ token mapping** across venues: manual for now; automate from Gamma+Kalshi metadata in a follow-up?
- **Snapshot recovery** for legacy `data_HFT/`: is Time Machine or a **one-time re-backfill** from a historical API (if any) available?
- **X API tier:** **Filtered stream** requires credits; **Retweet filtering** in rules; **Rule count** limits vs. number of `from:handle` rules.
- **LLM scoring:** one global model and prompt vs. per-player fine prompts; how to **calibrate** to draft outcomes (post hoc labels)?

*End of `presentation.md` (draft v1).*
