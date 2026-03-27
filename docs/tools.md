# CLI tools reference

Run from the repo root. If you use a virtualenv, prefix with `./venv/bin/python` (or activate the venv first).

---

## Kalshi: spread + volume market discovery (where it lives)

**Logic:** `src/discovery/market_discovery.py` — `discover_kalshi_markets` (Kalshi only) and `discover_markets_for_making` (Polymarket + Kalshi).

**CLI:** `scripts/discover_markets.py` — use `kalshi` or `both` as the source. Relevant flags include `--min-spread-pct`, `--min-volume-24h-kalshi`, `--max-results`, and `--kalshi-base`.

**Strategy defaults:** `MarketMakingStrategy` calls `discover_markets_for_making` using thresholds from `MarketMakingSettings` in `src/config/settings.py` (`discovery_min_spread_pct`, `discovery_min_volume_24h_kalshi`, `discovery_min_liquidity`, `discovery_max_markets`; env vars prefixed `MARKET_MAKING_DISCOVERY_*`).

See also the **Trading & discovery** table below for `discover_markets.py`.

---

## Kalshi: batch data gathering (`data_gathering/`)

| Script | What it does | Example |
|--------|----------------|---------|
| `data_gathering/list_kalshi_historical_markets.py` | Paginates **historical** Kalshi markets, filters by ticker substring, writes tickers to a file. | `python data_gathering/list_kalshi_historical_markets.py --output ./data/kalshi_historical_tickers.txt --ticker-contains KXNFLGAME` |
| `data_gathering/collect_kalshi_historical.py` | For each ticker (single or file): **historical** market metadata, candlesticks, optional orders under `data/kalshi_historical/`. | `python data_gathering/collect_kalshi_historical.py --tickers-file ./data/kalshi_historical_tickers.txt --output ./data` |
| `data_gathering/list_kalshi_live_markets.py` | Paginates **live** `GET /markets`, filters, writes tickers. Use `--max-pages` to cap runtime. | `python data_gathering/list_kalshi_live_markets.py --output ./data/kalshi_live_tickers.txt --ticker-contains KXNFLGAME --max-pages 1000` |
| `data_gathering/collect_kalshi_live.py` | **Live** market JSON + candlesticks via `GET /series/{series}/markets/{ticker}/candlesticks` (for markets not in historical). | `python data_gathering/collect_kalshi_live.py --ticker KXNFLGAME-25DEC04DALDET-DET --output ./data --period 1` |

More detail: `data_gathering/guides.md`.

---

## Polymarket: batch data gathering (`data_gathering_poly/`)

| Script | What it does | Example |
|--------|----------------|---------|
| `data_gathering_poly/list_polymarket_markets.py` | Lists events from Gamma, outputs **token IDs** (plus slug/dates per line). Filters: `--closed`, `--min-end-date`, `--recent-days`, title/question substrings, `--max-pages`. | `python data_gathering_poly/list_polymarket_markets.py --closed true --min-end-date 2024-01-01 --output ./data_poly/polymarket_tickers.txt` |
| `data_gathering_poly/collect_polymarket.py` | Per token: saves `market.json` (Gamma event when slug known) and `prices.json`. **Closed** markets: Data API trades (aggregated). **Active** (or no event): CLOB `prices-history`. `prices.json` includes `source` (`clob_prices_history` vs `data_api_trades`). | `python data_gathering_poly/collect_polymarket.py --tickers-file ./data_poly/polymarket_tickers.txt --output ./data_poly --interval 1m` |

More detail: `data_gathering_poly/guides.md` (includes warnings about old/closed markets with no trade history).

---

## High-frequency orderbook capture (`data_HFT/`)

| Script | What it does | Example |
|--------|----------------|---------|
| `data_HFT/collect_hft_kalshi.py` | WebSocket orderbook for Kalshi markets; default **`--mode snapshots`** (`frames.jsonl`); **`--mode deltas`** for `snapshot.json` + `deltas.jsonl`. | `python data_HFT/collect_hft_kalshi.py --markets TICKER1,TICKER2 --output-root ./data_HFT --duration 60 --interval 1 --mode snapshots` |
| `data_HFT/collect_hft_polymarket.py` | Same pattern for Polymarket (asset/token IDs). | `python data_HFT/collect_hft_polymarket.py --markets ASSET_ID --output-root ./data_HFT --duration 60 --mode snapshots` |

More detail: `data_HFT/guides.md`.

---

## Analysis & reconstruction (`scripts/`)

| Script | What it does | Example |
|--------|----------------|---------|
| `scripts/reconstruct_hft_orderbook.py` | Reads **`frames.jsonl`** (snapshots mode) or **`snapshot.json` + `deltas.jsonl`** (deltas mode); outputs time series (mid, spread, etc.) to stdout or CSV/JSON. | `python scripts/reconstruct_hft_orderbook.py --platform kalshi --market-id YOUR_TICKER --data-root ./data_HFT --output ./data_HFT/recon.csv --format csv` |
| `scripts/analyze_kalshi_orderbook_history.py` | Analyzes **historical** Kalshi order data from `data/kalshi_historical/{ticker}/` (requires `collect_kalshi_historical` with orders). | `python scripts/analyze_kalshi_orderbook_history.py --ticker YOUR_TICKER --file ./data --step 60` |
| `scripts/resolve_polymarket_slugs.py` | Resolves Polymarket **slugs** to CLOB asset IDs (for simulators / WebSockets). | `python scripts/resolve_polymarket_slugs.py fed-decision-in-october` |
| `scripts/collect_historical.py` | Short **WebSocket** sample: records orderbook/trade events to one JSON file (legacy / exploratory; not the same as REST batch collectors). | `python scripts/collect_historical.py --platform kalshi --markets TICKER --duration 60 --output ./logs/ws_sample.json` |

---

## Trading & discovery (`scripts/`)

| Script | What it does | Example |
|--------|----------------|---------|
| `scripts/run_strategy.py` | Runs **copy_trading**, **market_making**, or **alt_data** in **paper** or **historical** simulator mode. | `python scripts/run_strategy.py --strategy market_making --mode paper --markets TICKER1,TICKER2 --duration 30` |
| `scripts/discover_markets.py` | Discovers markets suited to **market making** (spread/liquidity heuristics) on Polymarket, Kalshi, or both. | `python scripts/discover_markets.py both --min-spread-pct 0.01 --max-results 50` |
| `scripts/discover_traders.py` | Discovers **Polymarket** leaderboard traders (for copy-trading workflows); prints wallets / stats. | `python scripts/discover_traders.py --time-period WEEK --limit 20 --ids-only` |

Strategy and workflow context: `GUIDES.md`, `setup.md`.