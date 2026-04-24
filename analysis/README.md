# Retrospective analysis (Kalshi, Polymarket, alt data)

Run notebooks from the **repository root** so `sys.path` resolves to `apex_prediction_markets` and `data_HFT*` paths work as written.

## Setup

```bash
cd /path/to/apex_prediction_markets
source venv/bin/activate
pip install -r requirements.txt -r requirements-analysis.txt
```

### Jupyter kernel (fixes “install ipykernel” in Cursor / VS Code)

The venv must have **`ipykernel`** installed, then register it once so the notebook UI can pick it:

```bash
cd /path/to/apex_prediction_markets
./venv/bin/pip install ipykernel
./venv/bin/python -m ipykernel install --user --name=apex_prediction_markets --display-name="Python (apex_prediction_markets venv)"
```

If that name already exists and you need to refresh it: `jupyter kernelspec uninstall apex_prediction_markets` (confirm), then run the `ipykernel install` line again.

In the notebook, choose kernel **“Python (apex_prediction_markets venv)”** (or pick interpreter `./venv/bin/python` if the UI offers “Python Environments”).

Alternatively, open a terminal with the venv active and run:

```bash
jupyter lab   # or: jupyter notebook
```

Open notebooks in `analysis/`. The first code cell in each notebook prepends the repo to `sys.path` if needed.

## Data layout

- **HFT:** `data_HFT/`, `data_HFT2/`, `data_HFT3/`, each with `kalshi/<TICKER>/` and `polymarket/<token_id>/` containing `snapshot.json`, `deltas.jsonl`, `trades.jsonl` (etc.).
- **Reconstruction:** `scripts/reconstruct_hft_orderbook.py` exposes `reconstruct_time_series(data_root, platform, market_id)` for programmatic use. Pass `data_root="./data_HFT"` (or `data_HFT2`, …) to point at a specific capture run.
- **Twitter:** e.g. `alt_data/out/draft_night_handles_stream.jsonl`.

## Notebooks (overview)

| Notebook | Focus |
|----------|--------|
| `00_hft_reconstruct_validate.ipynb` | Load mid/spread from multiple HFT roots; spot-check snapshot + delta integrity |
| `01_microstructure_dynamics.ipynb` | Spread, mid changes, activity from deltas; lead/lag style plots |
| `02_cross_venue_prices.ipynb` | Align Polymarket + Kalshi (mapping stub); price gaps / arb hypotheses |
| `03_trades_orderflow.ipynb` | `trades.jsonl` size, taker side, timing; retail vs. informed proxies |
| `04_twitter_draft_altdata.ipynb` | Filtered-stream JSONL volume, per-handle activity; LLM / keyword stubs |
| `05_key_statistics_summary.ipynb` | Tables and figures to export for presentation |
| `06_orderbook_pressure_informed_flow.ipynb` | **Full-book replay:** imbalance (top-N depth), spread dynamics, large limit adds, **taker-side trades** vs forward mid — exploratory “pressure / informed flow” proxies |

## Caveats

- Reconstruction from **deltas** requires a **valid `snapshot.json`** for that run; bad snapshots make mid/spread **wrong** for the early period (see `presentation.md`).
- **Kalshi vs Polymarket** notional prices differ in convention (cents, YES/NO). Cross-venue comparison needs explicit mapping and scaling — stubbed in `02_`.

## Mapping (manual)

To compare the same **player** across venues, maintain a table (e.g. CSV) of:
`kalshi_ticker_suffix` (e.g. `AHIL`) → `polymarket_clob_token_id` or `conditionId`. The repo does not infer this from APIs alone; fill from Gamma market metadata or by hand for your event.
