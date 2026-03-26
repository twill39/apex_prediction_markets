# Strategy Guides

This document provides quick-start guides for each trading strategy, including commands to run and expected outputs.

## How the pieces intersect

```text
┌─────────────────────────────────────────────────────────────────┐
│  scripts/run_strategy.py  →  strategies (src/strategies/*)     │
│         │                        │                               │
│         ▼                        ▼                               │
│  paper / historical simulator (src/simulator/*)                │
│         │                                                        │
│         ├── WebSockets + REST  →  Kalshi / Polymarket (live)     │
│         └── DataStorage (SQLite) → data/trading_fund.db        │
│              (orders, trades, etc.; file created on first use)   │
└─────────────────────────────────────────────────────────────────┘

Separate research / data pipelines (no SQLite):
  • data_gathering/        → Kalshi REST historical + live tickers → JSON under data/
  • data_gathering_poly/   → Polymarket Gamma/CLOB/Data API       → data_poly/  (see data_gathering_poly/guides.md)
  • data_HFT/              → Live orderbook snapshots or deltas   → data_HFT/   (see data_HFT/guides.md)
  • scripts/collect_historical.py → WebSocket event JSON for --mode historical (this doc, below)
```

**Takeaway:** **`trading_fund.db`** is only for **simulator/strategy persistence** (in-memory + SQLite). **Bulk market history and HFT orderbook data** live in **files** under `data/`, `data_poly/`, or `data_HFT/` — different tools, different outputs.

For install and `.env` setup, see [setup.md](setup.md).

## Prerequisites

Before running any strategy, ensure you have:

1. Completed [setup.md](setup.md): venv, `pip install -r requirements.txt`, `.env` with Kalshi credentials (and Polymarket if needed).
2. Recommended: `mkdir -p data logs` (SQLite default path is `./data/trading_fund.db`; the app can create `data/` when the DB is first written — see setup.md).

## Strategy 1: Copy Trading

### Overview
The Copy Trading strategy identifies profitable traders on Polymarket and automatically replicates their trades on both Kalshi and Polymarket.

### Running in Paper Trading Mode

```bash
python scripts/run_strategy.py --strategy copy_trading --mode paper
```

**What to expect:**
- The strategy will connect to both Kalshi and Polymarket WebSocket feeds
- It will start tracking trader activity and calculating performance metrics
- When profitable traders make trades, the strategy will generate signals to copy them
- You'll see log output showing:
  - WebSocket connection status
  - Trader performance calculations
  - Copy signals generated
  - Trades executed
- At the end, a performance report will be displayed with metrics like:
  - Total trades executed
  - Win rate
  - Total P&L
  - Sharpe ratio

**Expected Output:**
```
INFO - Starting copy_trading strategy in paper mode
INFO - Initializing copy trading strategy
INFO - WebSocket connections initialized
INFO - Initialized with X tracked traders
INFO - Copy signal generated: market_id=..., side=buy, size=100.0
INFO - Filled order ... at 0.5234

Performance Report
=================
Total Trades: 15
Win Rate: 60.00%
Total P&L: $125.50
...
```

### Running in Historical Mode

```bash
python scripts/run_strategy.py --strategy copy_trading --mode historical --data-path ./data/historical_data.json
```

**What to expect:**
- The strategy will load historical market data from the specified file
- It will replay events chronologically
- Copy signals will be generated based on historical trader activity
- All trades will be simulated against historical prices
- A performance report will show how the strategy would have performed

**Note:** You need to collect historical data first using `scripts/collect_historical.py`

---

## Strategy 2: Market Making

### Overview
The Market Making strategy identifies niche markets with high spreads and provides liquidity by placing limit orders on both sides of the book.

### Running in Paper Trading Mode

```bash
python scripts/run_strategy.py --strategy market_making --mode paper
```

**What to expect:**
- The strategy will connect to WebSocket feeds and monitor order books
- It will identify markets suitable for market making based on:
  - Spread size (within configured max spread)
  - Volume thresholds
  - Fair value calculations
- The strategy will place bid and ask orders to capture the spread
- You'll see log output showing:
  - Markets identified for market making
  - Fair value calculations
  - Quote updates (bid/ask prices)
  - Orders placed and filled
- Performance metrics will show:
  - Number of markets being made
  - Spread captured
  - Inventory management

**Expected Output:**
```
INFO - Starting market_making strategy in paper mode
INFO - Initializing market making strategy
INFO - Started market making on market_12345
INFO - Market making bid at 0.4950
INFO - Market making ask at 0.5050
INFO - Filled order ... at 0.4950
INFO - Filled order ... at 0.5050

Performance Report
=================
Total Trades: 42
Win Rate: 85.71%
Total P&L: $89.20
...
```

### Running in Historical Mode

```bash
python scripts/run_strategy.py --strategy market_making --mode historical --data-path ./data/historical_data.json
```

**What to expect:**
- Historical order book data will be replayed
- The strategy will identify markets and place quotes
- Performance will show how market making would have worked historically

---

## Strategy 3: Alt Data Trading

### Overview
The Alt Data strategy uses alternative data sources (Twitter, satellite imagery, etc.) to build fair value models and trade when market prices deviate from predicted values.

### Running in Paper Trading Mode

```bash
python scripts/run_strategy.py --strategy alt_data --mode paper
```

**What to expect:**
- The strategy will connect to WebSocket feeds and Twitter API (if configured)
- It will collect alternative data for markets based on keywords
- Fair value models will be built/updated using the alt data
- Trading signals will be generated when:
  - Market price deviates significantly from predicted fair value
  - Confidence threshold is met
- You'll see log output showing:
  - Alt data collection (Twitter sentiment, mentions, etc.)
  - Fair value predictions
  - Price deviations detected
  - Trading signals generated
- Performance metrics will show:
  - Accuracy of fair value predictions
  - Returns from alt data signals

**Expected Output:**
```
INFO - Starting alt_data strategy in paper mode
INFO - Initializing alt data strategy
INFO - Twitter collector initialized
INFO - Collected alt data for market_67890: sentiment=0.65, mentions=23
INFO - Predicted fair value: 0.72, Current price: 0.68
INFO - Signal generated: buy at 0.68 (confidence: 0.85)
INFO - Filled order ... at 0.6820

Performance Report
=================
Total Trades: 8
Win Rate: 75.00%
Total P&L: $156.30
...
```

**Configuration Requirements:**
- Set `TWITTER_BEARER_TOKEN` in `.env` for Twitter data collection
- Strategy will work without Twitter but with limited alt data sources

### Running in Historical Mode

```bash
python scripts/run_strategy.py --strategy alt_data --mode historical --data-path ./data/historical_data.json
```

**What to expect:**
- Historical data will be replayed
- Alt data collection will be simulated based on historical market events
- Fair value models will be tested against historical outcomes

---

## Specifying Markets for the Simulator

You can restrict paper (and historical) runs to specific markets so strategies only receive data for those markets.

**From the CLI:**

```bash
# Comma-separated list
python scripts/run_strategy.py --strategy copy_trading --mode paper --markets "id1,id2,id3"

# From a file (default: simulator/test_markets.txt)
python scripts/run_strategy.py --strategy market_making --mode paper --markets-file simulator/test_markets.txt

# Custom file path
python scripts/run_strategy.py --strategy alt_data --mode paper --markets-file ./my_markets.txt

# Run paper for a fixed duration (minutes), then stop and print report
python scripts/run_strategy.py --strategy copy_trading --mode paper --duration 5
```

**Duration (paper mode):** Use `--duration MINUTES` to run the paper simulator for that many minutes, then stop and print the performance report. Omit to run until you press Ctrl+C.

**Market list file (`simulator/test_markets.txt`):**

- One market or asset ID per line (or one Polymarket slug per line).
- Lines starting with `#` are ignored; blank lines are skipped.
- **Polymarket:** You can use either CLOB asset IDs (long numeric strings) or **event slugs** (e.g. `fed-decision-in-october`). Slugs are resolved to asset IDs automatically via the Gamma API when you run the simulator.
- **Kalshi:** Use market tickers (e.g. `KXBTC-24`, `KXCLOSEHORMUZ-27JAN-26MAY`); these are left as-is.
- The same list is used for both platforms; IDs valid on only one platform will only receive data from that platform.

**Resolving slugs manually:** To print asset IDs for slugs (e.g. to paste elsewhere), run:

```bash
# Resolve one or more slugs
python scripts/resolve_polymarket_slugs.py fed-decision-in-october

# Resolve all slug-like lines from a file (e.g. test_markets.txt)
python scripts/resolve_polymarket_slugs.py --file simulator/test_markets.txt

# See which lines are treated as slugs vs IDs (no API call)
python scripts/resolve_polymarket_slugs.py --file simulator/test_markets.txt --no-resolve
```

If you omit both `--markets` and `--markets-file`, the default file `simulator/test_markets.txt` is used if it exists; otherwise no markets are subscribed and you may receive no trade/orderbook data until you add a list.

---

## Discovery Scripts (Traders & Markets)

The strategies can discover traders and markets via API; you can also run the same logic from the CLI.

**Trader discovery (copy trading):** Find Polymarket traders with low volume and high PnL (potential edge).

```bash
# List traders meeting spec (default: WEEK leaderboard)
python scripts/discover_traders.py

# Stricter: max volume 50k, min PnL 1k, min PnL/vol 0.02
python scripts/discover_traders.py --max-volume 50000 --min-pnl 1000 --min-pnl-per-vol 0.02

# Output only proxyWallet addresses (for config/scripts)
python scripts/discover_traders.py --ids-only --limit 20
```

Copy trading uses these settings from `.env`: `COPY_TRADING_TRADER_MAX_VOLUME`, `COPY_TRADING_TRADER_MIN_PNL`, `COPY_TRADING_TRADER_MIN_PNL_PER_VOL`, `COPY_TRADING_TRADER_TIME_PERIOD`. If unset, the strategy uses leaderboard data without filtering by volume/PnL.

**Market discovery (market making):** Find Polymarket and Kalshi markets with high spread and decent liquidity.

```bash
# Discover on both platforms (default)
python scripts/discover_markets.py both

# Polymarket only
python scripts/discover_markets.py poly --min-spread-pct 0.01 --min-liquidity 1000

# Kalshi only
python scripts/discover_markets.py kalshi --min-spread-pct 0.005

# Output only market IDs (for test_markets.txt or --markets)
python scripts/discover_markets.py both --ids-only
```

Market making uses: `MARKET_MAKING_DISCOVERY_MIN_LIQUIDITY`, `MARKET_MAKING_DISCOVERY_MIN_SPREAD_PCT`, `MARKET_MAKING_DISCOVERY_MIN_VOLUME_24H_KALSHI`, `MARKET_MAKING_DISCOVERY_MAX_MARKETS`. When you run the market_making strategy in paper mode, it discovers markets from the APIs and subscribes to them (in addition to any `--markets` / file list).

---

## Collecting Historical Data

Before running strategies in historical mode, you need to collect historical market data:

### Collect from Kalshi

```bash
python scripts/collect_historical.py --platform kalshi --markets MARKET_ID_1 MARKET_ID_2 --duration 300 --output ./data/kalshi_historical.json
```

**Parameters:**
- `--platform`: Either `kalshi` or `polymarket`
- `--markets`: Space-separated list of market IDs to collect
- `--duration`: Collection duration in seconds (default: 60)
- `--output`: Output file path

**What to expect:**
- WebSocket connection to the platform
- Subscription to specified markets
- Collection of order book updates and trades for the duration
- Data saved to JSON file with structure:
  ```json
  {
    "collected_at": "2024-01-01T12:00:00",
    "total_events": 1234,
    "events": [
      {
        "type": "orderbook_update",
        "market_id": "...",
        "platform": "kalshi",
        "timestamp": "...",
        "data": {...}
      }
    ]
  }
  ```

### Collect from Polymarket

```bash
python scripts/collect_historical.py --platform polymarket --markets MARKET_ID_1 MARKET_ID_2 --duration 300 --output ./data/polymarket_historical.json
```

---

## Kalshi Historical Orderbook Backtester

The backtester uses Kalshi’s REST API: **GET /historical/markets/{ticker}** (market metadata), **GET /historical/markets/{ticker}/candlesticks** (OHLCV with start_ts, end_ts, period_interval), and optionally **GET /historical/orders** (paginated). Candlesticks are stored for price-over-time analysis; orders can be reassembled into orderbook snapshots.

**All data-gathering scripts for this flow live in the `data_gathering/` folder.** Output data is still written to the `data/` folder (or the path you pass with `--output`). Ticker list files use one ticker per line; lines starting with `#` are comments.

### 1. List historical markets (write tickers to file)

To see which historical markets are available and filter by ticker or event type, use the list script. It calls **GET /historical/markets** (paginated), filters by optional substrings, and writes tickers to a file that the collect script can read.

```bash
python data_gathering/list_kalshi_historical_markets.py --output ./data/kalshi_historical_tickers.txt --ticker-contains KXBTC,BTC
```

- **--output**: Output file path (default: `./data/kalshi_historical_tickers.txt`).
- **--ticker-contains**: Comma-separated substrings; keep only markets whose **ticker** contains any of them (e.g. `KXBTC`, `BTC` for crypto).
- **--event-contains**: Comma-separated substrings; keep only markets whose **event_ticker** contains any of them.
- **--limit**: Page size for the API (default: 1000).

If you omit both filters, all historical market tickers are written. The file format is one ticker per line (with an optional `#` header line), suitable for `--tickers-file` below.

### 2. Collect historical data

Requires Kalshi credentials in `.env` (API key + PEM private key). Fetches the market (for metadata and time bounds), then **candlesticks** from the earliest to latest available at the most frequent interval (1-minute by default), and optionally orders.

**Single market:**

```bash
python data_gathering/collect_kalshi_historical.py --ticker KXBTC-24DEC31-T50000 --output ./data
```

**Batch (from ticker list file):**

```bash
python data_gathering/collect_kalshi_historical.py --tickers-file ./data/kalshi_historical_tickers.txt --output ./data --orders
```

- **--ticker**: Single market ticker (ignored if `--tickers-file` is set).
- **--tickers-file**: Path to a file with one ticker per line (`#` = comment); collect data for every listed ticker. On per-ticker failure, the script logs and continues; a summary of collected vs failed is printed at the end.
- **--output**: Base directory; data is written under `{output}/kalshi_historical/{ticker}/` as `market.json`, `candlesticks.json`, and (if requested) `orders.json`.
- **--period**: Candlestick period: `1` (1 min), `60` (1 hr), or `1440` (1 day). Default: `1`.
- **--orders**: Also fetch and save historical orders (for orderbook reassembly).

Start and end times are derived automatically from the market’s `open_time` and `close_time` (or expiration). Candlesticks are requested in chunks to avoid oversized responses.

### 3. Reassembler (library usage)

Use the reassembler to get the orderbook at a specific time or over a time grid:

- **Orderbook at one time:** `get_orderbook_at(base_path, ticker, ts)` in `src.data.kalshi_orderbook_reassemble`.
- **Iterator over timepoints:** `iter_orderbooks(ticker, orders, start_ts, end_ts, step_seconds)`.

Data is loaded with `load_market(base_path, ticker)` and `load_orders(base_path, ticker)` from `src.data.kalshi_historical_storage`.

### 4. Analysis script (metrics + plot)

Computes price series from the reassembled book (mid, best bid/ask), then volatility, average price, and optional plot.

```bash
python scripts/analyze_kalshi_orderbook_history.py --ticker KXBTC-24DEC31-T50000 --file ./data --step 60 --output-plot ./data/kalshi_price_plot.png
```

- **--file** / **--data**: Base path to data (default: `./data`).
- **--ticker** (required): Market ticker.
- **--step**: Time step in seconds for the grid (default: 60).
- **--start** / **--end**: Time range (Unix seconds); default from order timestamps.
- **--output-plot**: Path to save the price-over-time plot.

Output: printed summary (average price, min/max, volatility, average spread) and, if **--output-plot** is set, a saved figure.

---

## Common Issues and Troubleshooting

### WebSocket Connection Failures
- **Issue:** "Failed to connect" errors
- **Solution:** Check your API credentials in `.env` and ensure you have network access

### No Signals Generated
- **Issue:** Strategy runs but generates no trading signals
- **Solution:** 
  - For copy trading: Ensure there are active traders being tracked
  - For market making: Check that markets meet the spread/volume criteria
  - For alt data: Verify Twitter API credentials if using Twitter data

### Database Errors
- **Issue:** SQLite database errors
- **Solution:** Ensure the parent directory for `DATABASE_PATH` (default `./data/`) exists and is writable. You do **not** need to create `trading_fund.db` manually — `DataStorage` creates the file and schema on first write.

### Missing Dependencies
- **Issue:** Import errors
- **Solution:** Run `pip install -r requirements.txt` to install all dependencies

---

## Performance Metrics Explained

All strategies output the following metrics:

- **Total Trades**: Number of trades executed
- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Net profit/loss in dollars
- **Total Return**: Percentage return on initial balance
- **Sharpe Ratio**: Risk-adjusted return metric (higher is better)
- **Max Drawdown**: Largest peak-to-trough decline
- **Profit Factor**: Ratio of gross profit to gross loss

---

## Next Steps

1. Start with paper trading mode to test strategies safely
2. Collect historical data for backtesting
3. Analyze performance metrics to optimize strategy parameters
4. Adjust configuration in `.env` for strategy-specific settings
5. Monitor logs for detailed execution information
