#!/usr/bin/env python3
"""Analyze Kalshi historical orderbook: price over time, volatility, average price, plot."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.kalshi_historical_storage import load_market, load_orders
from src.data.kalshi_orderbook_reassemble import aggregate_orders_at_t, _parse_ts


def _order_time_bounds(orders: list) -> tuple:
    """Return (min_created_ts, max_last_update_ts) in Unix seconds."""
    if not orders:
        return (0.0, 0.0)
    created = [_parse_ts(o.get("created_time")) for o in orders]
    updated = [_parse_ts(o.get("last_update_time")) or 1e12 for o in orders]
    return (min(created), max(updated))


def run_analysis(
    base_path: str,
    ticker: str,
    step_seconds: float = 60.0,
    start_ts: float = None,
    end_ts: float = None,
    output_plot: str = None,
) -> dict:
    """Load data, reassemble at grid, compute metrics, optionally plot. Returns metrics dict."""
    market = load_market(base_path, ticker)
    orders = load_orders(base_path, ticker)
    if not orders:
        print("No orders found. Run collect_kalshi_historical first.")
        return {}
    ticker = ticker or (market.get("market", market) or {}).get("ticker", ticker)

    t_min, t_max = _order_time_bounds(orders)
    if start_ts is None:
        start_ts = t_min
    if end_ts is None:
        end_ts = t_max

    times = []
    mid_prices = []
    best_bids = []
    best_asks = []
    spreads = []

    t = start_ts
    while t <= end_ts:
        yes_bids, yes_asks = aggregate_orders_at_t(orders, t)
        times.append(t)
        best_bid = float(yes_bids[0][0]) if yes_bids else None
        best_ask = float(yes_asks[0][0]) if yes_asks else None
        best_bids.append(best_bid)
        best_asks.append(best_ask)
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
        else:
            mid = None
            spread = None
        mid_prices.append(mid)
        spreads.append(spread)
        t += step_seconds

    # Filter out None mids for stats
    valid_mids = [m for m in mid_prices if m is not None]
    valid_spreads = [s for s in spreads if s is not None]

    metrics = {
        "ticker": ticker,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "step_seconds": step_seconds,
        "n_points": len(times),
        "average_price": sum(valid_mids) / len(valid_mids) if valid_mids else None,
        "min_price": min(valid_mids) if valid_mids else None,
        "max_price": max(valid_mids) if valid_mids else None,
        "volatility_std": (sum((x - sum(valid_mids) / len(valid_mids)) ** 2 for x in valid_mids) / len(valid_mids)) ** 0.5 if len(valid_mids) > 1 else 0.0,
        "average_spread": sum(valid_spreads) / len(valid_spreads) if valid_spreads else None,
    }
    if len(valid_mids) > 1:
        returns = [(valid_mids[i] - valid_mids[i - 1]) / valid_mids[i - 1] for i in range(1, len(valid_mids))]
        metrics["volatility_returns_std"] = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5

    # Print summary
    print(f"Ticker: {metrics['ticker']}")
    print(f"Points: {metrics['n_points']} (step={step_seconds}s)")
    print(f"Average price: {metrics['average_price']}")
    print(f"Min / Max price: {metrics['min_price']} / {metrics['max_price']}")
    print(f"Volatility (std of mid): {metrics.get('volatility_std')}")
    if "volatility_returns_std" in metrics:
        print(f"Volatility (std of returns): {metrics['volatility_returns_std']}")
    print(f"Average spread: {metrics['average_spread']}")

    if output_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot(times, mid_prices, label="Mid price")
        t_ok = [t for t, b, a in zip(times, best_bids, best_asks) if b is not None and a is not None]
        b_ok = [b for b, a in zip(best_bids, best_asks) if b is not None and a is not None]
        a_ok = [a for b, a in zip(best_bids, best_asks) if b is not None and a is not None]
        if t_ok and b_ok and a_ok:
            ax.fill_between(t_ok, b_ok, a_ok, alpha=0.2, label="Spread")
        ax.set_xlabel("Time (Unix s)")
        ax.set_ylabel("Price")
        ax.set_title(f"Kalshi {ticker} – Mid price over time")
        ax.legend()
        ax.grid(True)
        fig.savefig(output_plot, dpi=150)
        plt.close()
        print(f"Plot saved to {output_plot}")

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Analyze Kalshi historical orderbook data")
    parser.add_argument("--file", "--data", dest="base_path", default="./data", help="Base path to data (default: ./data)")
    parser.add_argument("--ticker", required=True, help="Market ticker")
    parser.add_argument("--step", type=float, default=60.0, help="Time step in seconds (default: 60)")
    parser.add_argument("--start", type=float, default=None, help="Start time (Unix seconds)")
    parser.add_argument("--end", type=float, default=None, help="End time (Unix seconds)")
    parser.add_argument("--output-plot", type=str, default=None, help="Save price-over-time plot to this path")
    args = parser.parse_args()
    run_analysis(
        base_path=args.base_path,
        ticker=args.ticker,
        step_seconds=args.step,
        start_ts=args.start,
        end_ts=args.end,
        output_plot=args.output_plot,
    )


if __name__ == "__main__":
    main()
