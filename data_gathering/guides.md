# Data gathering pipeline

Scripts in this folder fetch Kalshi market data (historical and live): market metadata, candlesticks, and optionally orders (historical only). **Output is written to the `data/` folder** (or the path you pass with `--output`). Historical data goes under `kalshi_historical/`, live under `kalshi_live/`. Ticker list files use one ticker per line; lines starting with `#` are comments.

**Prerequisites:** Kalshi credentials in `.env` (API key + PEM private key path). Run commands from the repository root.

---

## 1. List historical markets (write tickers to file)

See which historical markets exist and filter by ticker or event type. The script calls GET /historical/markets (paginated), filters by optional substrings, and writes tickers to a file for the collect script.

```bash
python data_gathering/list_kalshi_historical_markets.py --output ./data/kalshi_historical_tickers.txt --ticker-contains KXBTC,BTC
```

- **--output**: Output file path (default: `./data/kalshi_historical_tickers.txt`).
- **--ticker-contains**: Comma-separated substrings; keep only markets whose **ticker** contains any of them (e.g. `KXBTC`, `BTC` for crypto).
- **--event-contains**: Comma-separated substrings; keep only markets whose **event_ticker** contains any of them.
- **--limit**: Page size for the API (default: 1000).

If you omit both `--ticker-contains` and `--event-contains`, all historical market tickers are written.

---

## 2. Collect historical data

Fetches market metadata and 1-minute candlesticks (from market open to close), and optionally historical orders. Start/end times are taken from the market’s `open_time` and `close_time` (or expiration).

**Single market:**

```bash
python data_gathering/collect_kalshi_historical.py --ticker KXBTC-24DEC31-T50000 --output ./data
```

**Batch (all tickers from a file):**

```bash
python data_gathering/collect_kalshi_historical.py --tickers-file ./data/kalshi_historical_tickers.txt --output ./data
```

- **--ticker**: Single market ticker (ignored if `--tickers-file` is set).
- **--tickers-file**: Path to a file with one ticker per line (`#` = comment). Collects data for each ticker; on failure for one ticker, logs and continues, then prints how many succeeded/failed.
- **--output**: Base directory; data is written under `{output}/kalshi_historical/{ticker}/` as `market.json`, `candlesticks.json`, and (if requested) `orders.json`. Default: `./data`.
- **--period**: Candlestick period: `1` (1 min), `60` (1 hr), or `1440` (1 day). Default: `1`.
- **--orders**: Also fetch and save historical orders (for orderbook reassembly).

---

## Pipeline in one go

```bash
python data_gathering/list_kalshi_historical_markets.py --ticker-contains KXBTC --output ./data/tickers.txt
python data_gathering/collect_kalshi_historical.py --tickers-file ./data/tickers.txt --output ./data
```

Add `--orders` to the collect command if you want orders saved as well.

---

## 3. List live markets (write tickers to file)

Same idea as listing historical markets, but for **live** markets (GET /markets). Use this for markets that are not yet in the historical API (e.g. many sports).

```bash
python data_gathering/list_kalshi_live_markets.py --output ./data/kalshi_live_tickers.txt --ticker-contains KXNFLGAME,NFL
```

- **--output**: Output file path (default: `./data/kalshi_live_tickers.txt`).
- **--ticker-contains**: Comma-separated substrings; keep only markets whose **ticker** contains any.
- **--event-contains**: Comma-separated substrings; keep only markets whose **event_ticker** contains any.
- **--status**: Optional filter: `unopened`, `open`, `closed`, `settled`. Omit for all statuses.
- **--limit**: Page size (default: 100, max 100).
- **--max-pages**: Stop after this many pages (default: 1000). Use a lower value (e.g. 100) for faster runs; each page has up to 100 markets.

---

## 4. Collect live market data (candlesticks)

Fetches live market metadata and candlesticks via GET /markets/{ticker} and GET /series/{series_ticker}/markets/{ticker}/candlesticks. Use for markets that are in the live API but not in historical (e.g. NFL/NBA games). Series ticker is inferred from the event (or from the event_ticker prefix, e.g. KXNFLGAME).

**Single market:**

```bash
python data_gathering/collect_kalshi_live.py --ticker KXNFLGAME-25DEC04DALDET-DET --output ./data
```

**Batch (from a tickers file):**

```bash
python data_gathering/collect_kalshi_live.py --tickers-file ./data/kalshi_live_tickers.txt --output ./data
```

- **--ticker**: Single market ticker (ignored if `--tickers-file` is set).
- **--tickers-file**: Path to file with one ticker per line; collects for each.
- **--output**: Base directory; data is written under `{output}/kalshi_live/{ticker}/` as `market.json` and `candlesticks.json`. Default: `./data`.
- **--period**: Candlestick period: `1`, `60`, or `1440`. Default: `1`.

**Live pipeline in one go:**

```bash
python data_gathering/list_kalshi_live_markets.py --ticker-contains KXNFLGAME --output ./data/nfl_tickers.txt
python data_gathering/collect_kalshi_live.py --tickers-file ./data/nfl_tickers.txt --output ./data
```

---

## Downstream

- **Reassembler / analysis:** See the main repo **GUIDES.md** (Kalshi Historical Orderbook Backtester) for using the stored data with the reassembler (`src.data.kalshi_orderbook_reassemble`) and the analysis script (`scripts/analyze_kalshi_orderbook_history.py`).
