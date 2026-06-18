#!/usr/bin/env python3
"""CLI to run trading strategies"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies import (
    CopyTradingStrategy,
    MarketMakingStrategy,
    MarketMakingAsStrategy,
    AltDataStrategy,
)
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
    underlying_path: str = None,
    underlying_symbol: str = "$SPX",
    historical_rth_only: Optional[bool] = None,
    markets: Optional[List[str]] = None,
    duration_minutes: Optional[float] = None,
    bounds_file: Optional[str] = None,
    use_schwab_spx: Optional[bool] = None,
):
    """Run a trading strategy"""
    logger = setup_logger("CLI")
    logger.info(f"Starting {strategy_name} strategy in {mode} mode")
    
    # Create strategy
    if strategy_name == "copy_trading":
        strategy = CopyTradingStrategy()
    elif strategy_name == "market_making":
        strategy = MarketMakingStrategy()
    elif strategy_name == "market_making_as":
        strategy = MarketMakingAsStrategy()
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
        strategy.mode = "historical"
        strategy.historical_data_path = data_path
        simulator = HistoricalSimulator(
            data_path=data_path,
            markets=markets or [],
            underlying_path=underlying_path,
            underlying_symbol=underlying_symbol,
            historical_rth_only=historical_rth_only,
        )
        simulator.load_historical_data(data_path)
    elif mode == "paper":
        simulator = PaperTradingSimulator(
            markets=markets or [],
            duration_minutes=duration_minutes,
            bounds_file=bounds_file,
            use_schwab_spx=use_schwab_spx,
        )
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
        choices=["copy_trading", "market_making", "market_making_as", "alt_data"],
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
        "--underlying-path",
        type=str,
        default=None,
        help="Optional path to minute underlying CSV (merged into historical event timeline)",
    )
    parser.add_argument(
        "--underlying-symbol",
        type=str,
        default="$SPX",
        help="Symbol label for underlying CSV feed (default: $SPX)",
    )
    parser.add_argument(
        "--rth-only",
        action="store_true",
        help="(Historical mode) Replay only regular-session data (9:30-16:00 in simulator timezone)",
    )
    parser.add_argument(
        "--all-hours",
        action="store_true",
        help="(Historical mode) Force full-session replay, overriding RTH-only setting",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        metavar="MINUTES",
        help="(Paper mode only) Run for this many minutes, then stop and print performance report.",
    )
    parser.add_argument(
        "--bounds-file",
        type=str,
        default="data/kalshi_market_bounds.json",
        help="(Paper mode) JSON file with lower/upper/eod bounds for the target market",
    )
    parser.add_argument(
        "--spx-stream",
        dest="spx_stream",
        action="store_true",
        default=None,
        help="(Paper mode) Enable live Schwab SPX spot feed",
    )
    parser.add_argument(
        "--no-spx-stream",
        dest="spx_stream",
        action="store_false",
        help="(Paper mode) Disable live Schwab SPX spot feed",
    )

    args = parser.parse_args()

    raw = get_raw_markets(args.markets, args.markets_file, default_markets_file)
    markets = resolve_market_list(raw)
    logger = setup_logger("CLI")
    if args.rth_only and args.all_hours:
        parser.error("Choose only one of --rth-only or --all-hours")
    if markets:
        logger.info(f"Using {len(markets)} market(s) from CLI/file (after resolving slugs)")

    duration = args.duration if args.mode == "paper" else None
    bounds_file = args.bounds_file if args.mode == "paper" else None
    use_schwab_spx = args.spx_stream if args.mode == "paper" else None
    asyncio.run(
        run_strategy(
            args.strategy,
            args.mode,
            args.data_path,
            underlying_path=args.underlying_path,
            underlying_symbol=args.underlying_symbol,
            historical_rth_only=True if args.rth_only else (False if args.all_hours else None),
            markets=markets,
            duration_minutes=duration,
            bounds_file=bounds_file,
            use_schwab_spx=use_schwab_spx,
        )
    )


if __name__ == "__main__":
    main()
