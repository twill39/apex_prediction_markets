# Apex Prediction Markets Trading Fund

A comprehensive trading fund system for Kalshi and Polymarket prediction markets with WebSocket integration, three distinct trading strategies, and a robust simulator for strategy testing.

## Features

- **WebSocket Integration**: Real-time market data from both Kalshi and Polymarket
- **Three Trading Strategies**:
  1. Copy Trading: Automatically copy profitable traders
  2. Market Making: Provide liquidity on niche markets
  3. Alt Data Trading: Use alternative data sources for edge
- **Dual-Mode Simulator**: Historical replay and paper trading
- **Performance Metrics**: Comprehensive tracking and reporting

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd apex_prediction_markets
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API credentials
```

## Configuration

Create a `.env` file with the following variables:

- `KALSHI_API_KEY`: Your Kalshi API key
- `KALSHI_API_SECRET`: Your Kalshi API secret
- `POLYMARKET_API_KEY`: Your Polymarket API key (if required)
- `DATABASE_PATH`: Path to SQLite database (default: `./data/trading_fund.db`)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `LOG_FILE`: Path to log file (default: `./logs/trading_fund.log`)

See `.env.example` for all available configuration options.

## Usage

Run a strategy:
```bash
python scripts/run_strategy.py --strategy copy_trading
python scripts/run_strategy.py --strategy market_making
python scripts/run_strategy.py --strategy alt_data
```

Run simulator:
```bash
python scripts/run_strategy.py --strategy copy_trading --mode paper
python scripts/run_strategy.py --strategy market_making --mode historical
```

## Project Structure

```
apex_prediction_markets/
├── src/
│   ├── config/          # Configuration management
│   ├── websockets/      # WebSocket clients
│   ├── strategies/       # Trading strategies
│   ├── data/            # Data models and storage
│   ├── simulator/       # Simulator framework
│   └── utils/           # Utility functions
├── tests/               # Test files
├── scripts/             # CLI scripts
└── requirements.txt     # Python dependencies
```

## Development

Run tests:
```bash
pytest tests/
```

## License

[Add your license here]
