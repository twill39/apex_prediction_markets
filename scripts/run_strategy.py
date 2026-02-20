#!/usr/bin/env python3
"""CLI to run trading strategies"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies import CopyTradingStrategy, MarketMakingStrategy, AltDataStrategy
from src.simulator import HistoricalSimulator, PaperTradingSimulator, SimulatorMode
from src.simulator.metrics import generate_report
from src.utils.logger import setup_logger


async def run_strategy(strategy_name: str, mode: str, data_path: str = None):
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
        simulator = HistoricalSimulator(data_path=data_path)
        simulator.load_historical_data(data_path)
    elif mode == "paper":
        simulator = PaperTradingSimulator()
    else:
        logger.error(f"Unknown mode: {mode}")
        return
    
    # Add strategy to simulator
    simulator.add_strategy(strategy)
    
    try:
        # Run simulator
        await simulator.run()
        
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
    parser = argparse.ArgumentParser(description="Run trading strategies")
    parser.add_argument(
        "--strategy",
        choices=["copy_trading", "market_making", "alt_data"],
        required=True,
        help="Strategy to run"
    )
    parser.add_argument(
        "--mode",
        choices=["historical", "paper"],
        default="paper",
        help="Simulator mode (default: paper)"
    )
    parser.add_argument(
        "--data-path",
        help="Path to historical data file (required for historical mode)"
    )
    
    args = parser.parse_args()
    
    # Run strategy
    asyncio.run(run_strategy(args.strategy, args.mode, args.data_path))


if __name__ == "__main__":
    main()
