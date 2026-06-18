#!/usr/bin/env python3
"""Analyze Kalshi live candlestick data: price over time, volatility, spread, plot."""

import argparse
import sys
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.kalshi_historical_storage import load_live_market, load_live_orders

from src.data.kalshi_historical_storage import get_live_candlesticks_path


def run_analysis(
    base_path: str,
    ticker: str,
    output_plot: str = None,
) -> dict:
    """Load candlestick data, compute metrics, optionally plot. Returns metrics dict."""
    data = load_live_orders(base_path, ticker)  # loads candlesticks.json
    if not data:
        print("No candlestick data found. Run collect_kalshi_live first.")
        return {}

    candles = data.get("candlesticks", data) if isinstance(data, dict) else data
    if not candles:
        print("Empty candlesticks.")
        return {}

    times = []
    mid_prices = []
    best_bids = []
    best_asks = []
    spreads = []

    for c in candles:
        ts = c.get("end_period_ts")
        bid = c.get("yes_bid", {}).get("close_dollars")
        ask = c.get("yes_ask", {}).get("close_dollars")

        if ts is None:
            continue
        bid = float(bid) if bid is not None else None
        ask = float(ask) if ask is not None else None

        times.append(ts)
        best_bids.append(bid)
        best_asks.append(ask)

        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
            spread = ask - bid
        else:
            mid = None
            spread = None

        mid_prices.append(mid)
        spreads.append(spread)

    valid_mids = [m for m in mid_prices if m is not None]
    valid_spreads = [s for s in spreads if s is not None]

    avg_mid = sum(valid_mids) / len(valid_mids) if valid_mids else None
    volatility_std = (
        (sum((x - avg_mid) ** 2 for x in valid_mids) / len(valid_mids)) ** 0.5
        if len(valid_mids) > 1 else 0.0
    )

    metrics = {
        "ticker": ticker,
        "n_candles": len(candles),
        "average_price": avg_mid,
        "min_price": min(valid_mids) if valid_mids else None,
        "max_price": max(valid_mids) if valid_mids else None,
        "volatility_std": volatility_std,
        "average_spread": sum(valid_spreads) / len(valid_spreads) if valid_spreads else None,
    }

    if len(valid_mids) > 1:
        returns = [
            (valid_mids[i] - valid_mids[i - 1]) / valid_mids[i - 1]
            for i in range(1, len(valid_mids))
            if valid_mids[i - 1] != 0
        ]
        metrics["volatility_returns_std"] = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5 if returns else None

    print(f"Ticker: {ticker}")
    print(f"Candles: {metrics['n_candles']}")
    print(f"Average price: {metrics['average_price']}")
    print(f"Min / Max price: {metrics['min_price']} / {metrics['max_price']}")
    print(f"Volatility (std of mid): {metrics['volatility_std']}")
    if "volatility_returns_std" in metrics:
        print(f"Volatility (std of returns): {metrics['volatility_returns_std']}")
    print(f"Average spread: {metrics['average_spread']}")

    if output_plot:
        matplotlib.use("Agg")
        fig, ax = plt.subplots()
        ax.plot(times, mid_prices, label="Mid price")
        t_ok = [t for t, b, a in zip(times, best_bids, best_asks) if b is not None and a is not None]
        b_ok = [b for b, a in zip(best_bids, best_asks) if b is not None and a is not None]
        a_ok = [a for b, a in zip(best_bids, best_asks) if b is not None and a is not None]
        if t_ok and b_ok and a_ok:
            ax.fill_between(t_ok, b_ok, a_ok, alpha=0.2, label="Spread")
        ax.set_xlabel("Time (Unix s)")
        ax.set_ylabel("Price ($)")
        ax.set_title(f"Kalshi {ticker} – Mid price over time")
        ax.legend()
        ax.grid(True)
        fig.savefig(output_plot, dpi=150)
        plt.close()
        print(f"Plot saved to {output_plot}")

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Analyze Kalshi candlestick data")
    parser.add_argument("--file", "--data", dest="base_path", default="./data", help="Base path to data (default: ./data)")
    parser.add_argument("--ticker", required=True, help="Market ticker")
    parser.add_argument("--output-plot", type=str, default=None, help="Save price-over-time plot to this path")
    args = parser.parse_args()
    run_analysis(
        base_path=args.base_path,
        ticker=args.ticker,
        output_plot=args.output_plot,
    )


if __name__ == "__main__":
    main()