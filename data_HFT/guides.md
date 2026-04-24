# HFT Data Pipeline

This folder captures high-frequency Polymarket/Kalshi orderbook data over WebSockets and writes it to JSON/JSONL files that can later be reconstructed for analysis/backtesting.

## Collectors

### `collect_hft_kalshi.py`
Kalshi HFT collector. Subscribes to Kalshi orderbook updates and records either:

- **Snapshot mode** (`--mode snapshots`, default): writes a base `snapshot.json` once, and then appends full book frames to `frames.jsonl` every `--interval` seconds.
- **Deltas mode** (`--mode deltas`): writes `snapshot.json` once, and then appends orderbook deltas to `deltas.jsonl` every `--interval` seconds.

Example:
```bash
./venv/bin/python data_HFT/collect_hft_kalshi.py \
  --markets KXNFLGAME-25DEC04DALDET-DET \
  --output-root ./data_HFT \
  --duration 30 \
  --interval 1 \
  --mode snapshots
```

### `collect_hft_polymarket.py`
Polymarket HFT collector. Subscribes to Polymarket orderbook updates for a set of token IDs (asset IDs).

Example:
```bash
./venv/bin/python data_HFT/collect_hft_polymarket.py \
  --markets 11015470973684177829729219287262166995141465048508201953575582100565462316088 \
  --output-root ./data_HFT \
  --duration 30 \
  --interval 1 \
  --mode snapshots
```

## Output files

Collectors write under `--output-root/<platform>/<market_id>/...`.

- `snapshot.json`: the initial full orderbook state used for reconstruction.
- `frames.jsonl`: appended full snapshots (one JSON object per line).
- `deltas.jsonl`: appended per-interval delta events (one JSON object per line).

## Reconstruction

Use:
```bash
./venv/bin/python scripts/reconstruct_hft_orderbook.py --output ./data_HFT/recon \
  --platform kalshi --market-id KXNFLGAME-25DEC04DALDET-DET
```

The reconstruct script will prefer `frames.jsonl` if present; otherwise it falls back to `snapshot.json` + `deltas.jsonl`.

# HFT orderbook data pipeline

This folder contains scripts that capture **live** orderbook data at **1-second** resolution using WebSockets, then store an initial snapshot plus per-second **deltas** (changes only) to keep storage small. A separate script reconstructs orderbook state (or mid/spread time series) from snapshot + deltas.

**Prerequisites:** Kalshi credentials in `.env` for Kalshi collector; Polymarket credentials for Polymarket collector (market channel may work without auth). Run from repository root.

---

## 1. Collecting data

### Kalshi

Subscribe to one or more Kalshi market tickers; the first non-empty orderbook update becomes the snapshot; every second thereafter you can either store **full snapshots** (default) or **deltas only**.

```bash
python data_HFT/collect_hft_kalshi.py --markets KXBTC-24DEC31-T50000 --output-root ./data_HFT --duration 60
```

```bash
# From file (one ticker per line)
python data_HFT/collect_hft_kalshi.py --markets-file ./data/kalshi_live_tickers.txt --output-root ./data_HFT --interval 1 --duration 300
```

- **--markets-file**: Path to file with one Kalshi market ticker per line (`#` = comment).
- **--markets**: Comma-separated list of tickers.
- **--output-root**: Root directory for output (default: `./data_HFT`). Data is written under `{output-root}/kalshi/{market_id}/`.
- **--interval**: Seconds between delta frames (default: 1.0).
- **--duration**: Run for this many seconds then exit; omit to run until Ctrl+C.
- **--mode**: `snapshots` (default) stores a full orderbook snapshot every `interval` in `frames.jsonl`; `deltas` stores one base `snapshot.json` plus per-second changes in `deltas.jsonl`.

### Polymarket

Same idea, but use Polymarket **asset (token) IDs** and the Polymarket WebSocket.

```bash
python data_HFT/collect_hft_polymarket.py --markets ASSET_ID_1,ASSET_ID_2 --output-root ./data_HFT --duration 60
```

- **--markets-file** / **--markets**: File or comma-separated Polymarket asset IDs (CLOB token IDs).
- **--output-root**, **--interval**, **--duration**, **--mode**: Same as Kalshi. Data is written under `{output-root}/polymarket/{market_id}/`.

---

## 2. Output layout

Per market:

- **snapshot.json** – Full orderbook at subscription time: `market_id`, `platform`, `timestamp`, `bids`, `asks` (each a list of `[price, size]`).
- **frames.jsonl** (default, `--mode snapshots`) – One JSON object per line: `{"t": unix_ts, "bids": [[price, size], ...], "asks": [[price, size], ...]}`. This is the full book every `interval` seconds; simpler to work with and compresses well.
- **deltas.jsonl** (`--mode deltas`) – One compact JSON object per line: `{"t":unix_ts,"e":[[op,side,price],...]}`. Each event is either `[0,side,price]` (**delete**) or `[1,side,price,size]` (**set**): `op` 0=delete, 1=set; `side` 0=bid, 1=ask. No spaces in JSON. Older captures used `{"t","events"}` with string `op`/`side`; `scripts/reconstruct_hft_orderbook.py` replays both.

---

## 3. Reconstructing orderbook / time series

Use the script in `scripts/` to replay deltas and optionally export mid price and spread over time:

```bash
python scripts/reconstruct_hft_orderbook.py --platform kalshi --market-id KXBTC-24DEC31-T50000 --data-root ./data_HFT
```

Prints one JSON object per delta frame with `t`, `best_bid`, `best_ask`, `mid`, `spread`.

```bash
# Write CSV
python scripts/reconstruct_hft_orderbook.py --platform kalshi --market-id KXBTC-24DEC31-T50000 --output ./data_HFT/reconstructed.csv --format csv

# Filter by time range (Unix seconds)
python scripts/reconstruct_hft_orderbook.py --platform polymarket --market-id YOUR_ASSET_ID --start-ts 1700000000 --end-ts 1700003600 --output out.json --format json
```

- **--platform**: `kalshi` or `polymarket`.
- **--market-id**: Same ID used when collecting (Kalshi ticker or Polymarket asset ID).
- **--data-root**: Path to `data_HFT` root (default: `./data_HFT`).
- **--start-ts** / **--end-ts**: Optional Unix time range for deltas.
- **--output**: If set, write time series to this file.
- **--format**: `csv` or `json` for the output file.

Reconstruction loads the snapshot, then applies each delta in order; the in-memory book state at each step is used to compute best bid/ask, mid, and spread.
