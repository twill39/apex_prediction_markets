# Strategy Guides

This document provides quick-start guides for each trading strategy, including commands to run and expected outputs.

## Prerequisites

Before running any strategy, ensure you have:

1. Installed dependencies: `pip install -r requirements.txt`
2. Created a `.env` file with your API credentials (see `.env.example`)
3. Set up the database directory: `mkdir -p data logs`

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
- **Solution:** Ensure the `data/` directory exists and is writable

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
