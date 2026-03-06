"""Simulator framework for strategy testing"""

from .base import BaseSimulator, SimulatorMode
from .historical import HistoricalSimulator
from .paper_trading import PaperTradingSimulator
from .metrics import PerformanceMetrics, calculate_metrics
from .market_list import (
    load_markets_from_file,
    load_markets_from_file_resolved,
    parse_markets_from_cli,
    resolve_markets,
)

__all__ = [
    "BaseSimulator",
    "SimulatorMode",
    "HistoricalSimulator",
    "PaperTradingSimulator",
    "PerformanceMetrics",
    "calculate_metrics",
    "load_markets_from_file",
    "load_markets_from_file_resolved",
    "parse_markets_from_cli",
    "resolve_markets",
]
