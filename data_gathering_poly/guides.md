# Polymarket data gathering pipeline

Scripts in this folder fetch Polymarket market data: event/market metadata from the Gamma API and historical price data from the **CLOB API** (active markets) or **Data API** (closed markets). **Output is written to the `data_poly/` folder** (or the path you pass with `--output`). Data is stored under `data_poly/polymarket/{token_id}/` as `market.json` and `prices.json`.

Polymarket uses **token IDs** (CLOB asset IDs) and **event slugs** (URL-friendly identifiers), not Kalshi-style tickers. The list script writes one token per line with optional slug and dates so the collect script can resolve time bounds without re-querying Gamma for every token.

---

## ⚠️ Price data: do not expect it for older markets

**Price history (`prices.json`) should NOT be expected to work for older data.** The CLOB API does not return price history for closed contracts; the Data API often returns **no trades** for older closed markets (e.g. 2021–2022). For those, you will get empty `history: []`. Polymarket does not document how long trade/price data is retained.

**To get markets where price data is likely to exist:** when listing, use **`--min-end-date`** (e.g. `2024-01-01`) or **`--recent-days`** (e.g. `365`) so only events ending on or after that date are included. For active markets, CLOB price history is available; for closed markets, restrict to recent ones so the Data API is more likely to have trades.

---

**Prerequisites:** None (Gamma and CLOB read endpoints are public). Run commands from the repository root.

---

## 1. List markets (write token IDs to file)

Fetch events from the Gamma API, filter by slug, tag, or by title/question substring, and write token IDs (and slug, start_date, end_date) to a file for the collect script.

```bash
python data_gathering_poly/list_polymarket_markets.py --output ./data_poly/polymarket_tickers.txt --title-contains "election"
```

```bash
# Filter by event slug (single event)
python data_gathering_poly/list_polymarket_markets.py --slug fed-decision-in-october --output ./data_poly/polymarket_tickers.txt

# Filter by Gamma tag_id (category/sport)
python data_gathering_poly/list_polymarket_markets.py --tag-id 100381 --output ./data_poly/polymarket_tickers.txt

# Active, non-closed events only (default for discovery)
python data_gathering_poly/list_polymarket_markets.py --active true --closed false --max-pages 100 --output ./data_poly/polymarket_tickers.txt

# Closed markets but only recent (more likely to have Data API trade history)
python data_gathering_poly/list_polymarket_markets.py --closed true --min-end-date 2024-01-01 --output ./data_poly/polymarket_tickers.txt
python data_gathering_poly/list_polymarket_markets.py --closed true --recent-days 365 --output ./data_poly/polymarket_tickers.txt
```

- **--output**: Output file path (default: `./data_poly/polymarket_tickers.txt`).
- **--slug**: Fetch only the event with this slug.
- **--tag-id**: Filter by Gamma tag ID (e.g. from `GET /tags` or `/sports`).
- **--title-contains**: Comma-separated substrings; keep only events whose **title** contains any (case-insensitive).
- **--question-contains**: Comma-separated substrings; keep only events where any market **question** contains any (case-insensitive).
- **--active**: Filter by active status (`true` / `false`).
- **--closed**: Filter by closed status (`true` / `false`).
- **--limit**: Page size for Gamma API (default: 100).
- **--max-pages**: Stop after this many pages (default: 1000) to avoid long runs.
- **--min-end-date**: Only include events whose **end_date** is on or after this date (e.g. `2024-01-01`). Use to limit to more recent markets for which Data API trade history is more likely to exist.
- **--recent-days**: Only include events whose end_date is within the last N days (e.g. `365`). Alternative to `--min-end-date` for “recent only”.

Output file format: one line per token, tab-separated `token_id`, `slug`, `start_date`, `end_date`. Lines starting with `#` are comments.

---

## 2. Collect market data and price history

Fetches event metadata (from Gamma, by slug) and price history for each token. **Active markets** (event not closed): uses CLOB `GET /prices-history`. **Closed markets**: uses Data API `GET /trades` (by condition ID), then aggregates trades into the same 1m-style `(t, p)` history so that closed markets can get non-empty data when the API has trades (CLOB returns empty for closed contracts).

**Again: price data is not expected for older markets.** If you list or collect without `--min-end-date` / `--recent-days`, many closed markets will have empty `history: []`. Use the list script’s **--min-end-date** or **--recent-days** to limit to recent events where trade/price data is more likely to exist.

**Single token (slug required for metadata and time bounds):**

```bash
python data_gathering_poly/collect_polymarket.py --token-id 12345678901234567890 --slug fed-decision-in-october --output ./data_poly
```

**Batch (from list script output):**

```bash
python data_gathering_poly/collect_polymarket.py --tickers-file ./data_poly/polymarket_tickers.txt --output ./data_poly
```

- **--token-id**: Single token ID (use with **--slug** so the script can fetch event metadata and time bounds).
- **--slug**: Event slug (used when collecting a single token to fetch event and time range).
- **--tickers-file**: Path to the file produced by `list_polymarket_markets.py` (token_id, slug, start_date, end_date per line).
- **--output**: Base directory; data is written under `{output}/polymarket/{token_id}/` as `market.json` and `prices.json`. Default: `./data_poly`.
- **--interval**: Price history interval: `1m`, `1h`, `6h`, `1d`, `1w`, `max`, `all`. Default: `1m`.

`market.json` stores the Gamma event (when slug was available). `prices.json` stores `token_id`, `interval`, and a `history` array of `{ "t": unix_ts, "p": price }` — from CLOB for active markets, or from Data API trades (aggregated by interval) for closed markets.

---

## Pipeline in one go

```bash
python data_gathering_poly/list_polymarket_markets.py --title-contains "Bitcoin" --max-pages 10 --output ./data_poly/polymarket_tickers.txt
python data_gathering_poly/collect_polymarket.py --tickers-file ./data_poly/polymarket_tickers.txt --output ./data_poly --interval 1m
```

---

## Output layout

- `data_poly/polymarket_tickers.txt` — list script output (token_id, slug, start_date, end_date per line).
- `data_poly/polymarket/{token_id}/market.json` — Gamma event (and market info) for that token.
- `data_poly/polymarket/{token_id}/prices.json` — Price history: `{ "token_id": "...", "interval": "1m", "history": [ { "t", "p" } ] }` (CLOB for active markets, Data API trades aggregated for closed markets).
