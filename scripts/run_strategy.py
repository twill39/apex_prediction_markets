#!/usr/bin/env python3
"""CLI to run trading strategies"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies import CopyTradingStrategy, MarketMakingStrategy, AltDataStrategy
from src.simulator import HistoricalSimulator, PaperTradingSimulator, SimulatorMode
from src.simulator.metrics import generate_report
from src.simulator.market_list import (
    load_markets_from_file,
    parse_markets_from_cli,
    resolve_markets,
)
from src.utils.logger import setup_logger


def get_raw_markets(
    cli_markets: Optional[str], markets_file: Optional[str], default_file: Path
) -> List[str]:
    """Build raw market list from CLI and/or file. CLI takes precedence."""
    if cli_markets:
        return parse_markets_from_cli(cli_markets)
    file_path = Path(markets_file) if markets_file else default_file
    return load_markets_from_file(str(file_path))


def resolve_market_list(raw_list: List[str]) -> List[str]:
    """Resolve Polymarket slugs to asset IDs; leave IDs and Kalshi tickers as-is."""
    return resolve_markets(raw_list)


async def run_strategy(
    strategy_name: str,
    mode: str,
    data_path: str = None,
    markets: Optional[List[str]] = None,
    duration_minutes: Optional[float] = None,
):
    """Run a trading strategy"""
    logger = setup_logger("CLI")
    logger.info(f"Starting {strategy_name} strategy in {mode} mode")
    
    # Create strategy
    if strategy_name == "copy_trading":
        strategy = CopyTradingStrategy()
    elif strategy_name == "market_making":
        strategy = MarketMakingStrategy()
    elif strategy_name == "alt_data":
        strategy = AltDataStrategy()
    else:
        logger.error(f"Unknown strategy: {strategy_name}")
        return
    
    # Create simulator
    if mode == "historical":
        if not data_path:
            logger.error("Historical mode requires --data-path")
            return
        simulator = HistoricalSimulator(data_path=data_path, markets=markets or [])
        simulator.load_historical_data(data_path)
    elif mode == "paper":
        simulator = PaperTradingSimulator(markets=markets or [], duration_minutes=duration_minutes)
    else:
        logger.error(f"Unknown mode: {mode}")
        return
    
    # Add strategy to simulator
    simulator.add_strategy(strategy)
    
    try:
        # Run simulator
        await simulator.run()
        
        # Skip report if paper simulator exited due to WebSocket failure
        if getattr(simulator, "websocket_connection_failed", False):
            logger.info("Simulator exited due to WebSocket connection failure.")
            return
        
        # Generate report
        metrics = simulator.get_metrics()
        report = generate_report(metrics)
        print(report)
        
        logger.info("Strategy execution completed")
        
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        await simulator.stop()
    except Exception as e:
        logger.error(f"Error running strategy: {e}", exc_info=True)
        await simulator.stop()


def main():
    """Main CLI entry point"""
    root = Path(__file__).parent.parent
    default_markets_file = root / "simulator" / "test_markets.txt"

    parser = argparse.ArgumentParser(description="Run trading strategies")
    parser.add_argument(
        "--strategy",
        choices=["copy_trading", "market_making", "alt_data"],
        required=True,
        help="Strategy to run",
    )
    parser.add_argument(
        "--mode",
        choices=["historical", "paper"],
        default="paper",
        help="Simulator mode (default: paper)",
    )
    parser.add_argument(
        "--data-path",
        help="Path to historical data file (required for historical mode)",
    )
    parser.add_argument(
        "--markets",
        type=str,
        default=None,
        help="Comma-separated market/asset IDs to subscribe to (e.g. id1,id2,id3)",
    )
    parser.add_argument(
        "--markets-file",
        type=str,
        default=None,
        help=f"Path to file listing market IDs (one per line). Default: {default_markets_file}",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        metavar="MINUTES",
        help="(Paper mode only) Run for this many minutes, then stop and print performance report.",
    )

    args = parser.parse_args()

    raw = get_raw_markets(args.markets, args.markets_file, default_markets_file)
    markets = resolve_market_list(raw)
    logger = setup_logger("CLI")
    if markets:
        logger.info(f"Using {len(markets)} market(s) from CLI/file (after resolving slugs)")

    duration = args.duration if args.mode == "paper" else None
    asyncio.run(run_strategy(args.strategy, args.mode, args.data_path, markets=markets, duration_minutes=duration))


if __name__ == "__main__":
    main()
