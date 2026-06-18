#!/usr/bin/env python3
"""Reusable plotting helpers for backtest trade diagnostics.

This module provides both importable functions and a simple CLI to render
common backtest graphics from the SQLite trades table.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Dict, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_trades_dataframe(
    db_path: str,
    strategy_id: Optional[str] = None,
    market_id: Optional[str] = None,
) -> pd.DataFrame:
    """Load trades from SQLite into a timestamp-sorted DataFrame."""
    conn = sqlite3.connect(db_path)
    try:
        query = "SELECT * FROM trades"
        conditions = []
        params = []
        if strategy_id:
            conditions.append("strategy_id = ?")
            params.append(strategy_id)
        if market_id:
            conditions.append("market_id = ?")
            params.append(market_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp ASC"
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["size"] = pd.to_numeric(df["size"], errors="coerce")
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["timestamp", "price", "size"]).reset_index(drop=True)
    return df


def enrich_trade_series(df: pd.DataFrame) -> pd.DataFrame:
    """Add signed size, inventory, cash flow, MTM equity, and cumulative trade PnL columns."""
    if df.empty:
        return df.copy()

    out = df.copy()
    side_sign = np.where(out["side"].str.lower() == "buy", 1.0, -1.0)
    out["signed_size"] = side_sign * out["size"]
    out["inventory"] = out["signed_size"].cumsum()

    notional = out["price"] * out["size"]
    # Buy reduces cash, sell increases cash.
    out["cash_delta"] = np.where(out["side"].str.lower() == "buy", -notional, notional) - out["fees"]
    out["cash_balance_delta"] = out["cash_delta"].cumsum()

    # Mark-to-market equity at each fill: cash from trades plus position valued at last print.
    # Without L2 data, use this row's execution price as the post-trade last price.
    out["mark_price"] = out["price"]
    out["position_m2m"] = out["inventory"] * out["mark_price"]
    out["equity_m2m"] = out["cash_balance_delta"] + out["position_m2m"]

    # Realized round-trip outcome approximation at trade granularity.
    out["trade_value_signed"] = -out["price"] * out["signed_size"] - out["fees"]
    out["cum_trade_value_signed"] = out["trade_value_signed"].cumsum()
    return out


def plot_inventory(df: pd.DataFrame, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """Plot signed inventory over time."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["timestamp"], df["inventory"], linewidth=1.5)
    ax.axhline(0.0, color="black", linewidth=1.0, alpha=0.5)
    ax.set_title("Inventory Over Time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Signed Contracts")
    ax.grid(alpha=0.2)
    return ax


def plot_cash_curve(df: pd.DataFrame, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """Plot cumulative cash delta from trade executions."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["timestamp"], df["cash_balance_delta"], linewidth=1.5, color="C0")
    ax.axhline(0.0, color="black", linewidth=1.0, alpha=0.5)
    ax.set_title("Cumulative Cash Delta")
    ax.set_xlabel("Time")
    ax.set_ylabel("Cash Delta")
    ax.grid(alpha=0.2)
    return ax


def plot_m2m_equity(df: pd.DataFrame, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """Plot mark-to-market equity (cash from fills + inventory × last print price)."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    if "equity_m2m" not in df.columns:
        raise ValueError("DataFrame must be produced by enrich_trade_series() for equity_m2m.")
    ax.plot(df["timestamp"], df["equity_m2m"], linewidth=1.5, color="C1", label="Equity (MTM)")
    ax.plot(
        df["timestamp"],
        df["cash_balance_delta"],
        linewidth=1.0,
        color="C0",
        alpha=0.65,
        linestyle="--",
        label="Cash only",
    )
    ax.axhline(0.0, color="black", linewidth=1.0, alpha=0.5)
    ax.set_title("Mark-to-Market Equity (cash + inventory × mark)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Equity")
    ax.grid(alpha=0.2)
    ax.legend(loc="best", fontsize=8)
    return ax


def plot_cash_and_equity(df: pd.DataFrame, figsize: tuple = (12, 7)) -> plt.Figure:
    """Two stacked panels: cumulative cash delta and MTM equity (for side-by-side comparison)."""
    fig, (ax_cash, ax_eq) = plt.subplots(2, 1, figsize=figsize, sharex=True)
    plot_cash_curve(df, ax=ax_cash)
    plot_m2m_equity(df, ax=ax_eq)
    ax_cash.set_xlabel("")
    fig.suptitle("Cash vs mark-to-market equity", fontsize=11, y=1.02)
    return fig


def plot_trade_prices(df: pd.DataFrame, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """Scatter buy/sell executions by price."""
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    buys = df[df["side"].str.lower() == "buy"]
    sells = df[df["side"].str.lower() == "sell"]
    ax.scatter(buys["timestamp"], buys["price"], s=10, alpha=0.7, label="Buy")
    ax.scatter(sells["timestamp"], sells["price"], s=10, alpha=0.7, label="Sell")
    ax.set_title("Execution Prices")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    ax.set_ylim(0.0, 1.0)
    ax.grid(alpha=0.2)
    ax.legend()
    return ax


def plot_trade_notional_hist(df: pd.DataFrame, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """Histogram of per-trade notionals."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 4))
    notionals = (df["price"] * df["size"]).values
    ax.hist(notionals, bins=40, alpha=0.8)
    ax.set_title("Trade Notional Distribution")
    ax.set_xlabel("Notional")
    ax.set_ylabel("Count")
    ax.grid(alpha=0.2)
    return ax


def save_backtest_graphics(
    df: pd.DataFrame,
    out_dir: str,
    prefix: str = "backtest",
) -> Dict[str, str]:
    """Render and save a standard set of graphics, returning output paths."""
    if df.empty:
        raise ValueError("No trades to plot.")

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    outputs: Dict[str, str] = {}

    fig1, ax1 = plt.subplots(figsize=(12, 4))
    plot_inventory(df, ax=ax1)
    p1 = out_path / f"{prefix}_inventory.png"
    fig1.tight_layout()
    fig1.savefig(p1, dpi=140)
    plt.close(fig1)
    outputs["inventory"] = str(p1)

    fig2, ax2 = plt.subplots(figsize=(12, 4))
    plot_cash_curve(df, ax=ax2)
    p2 = out_path / f"{prefix}_cash_curve.png"
    fig2.tight_layout()
    fig2.savefig(p2, dpi=140)
    plt.close(fig2)
    outputs["cash_curve"] = str(p2)

    fig_eq = plot_cash_and_equity(df)
    p_eq = out_path / f"{prefix}_cash_and_equity.png"
    fig_eq.tight_layout()
    fig_eq.savefig(p_eq, dpi=140, bbox_inches="tight")
    plt.close(fig_eq)
    outputs["cash_and_equity"] = str(p_eq)

    fig3, ax3 = plt.subplots(figsize=(12, 4))
    plot_trade_prices(df, ax=ax3)
    p3 = out_path / f"{prefix}_trade_prices.png"
    fig3.tight_layout()
    fig3.savefig(p3, dpi=140)
    plt.close(fig3)
    outputs["trade_prices"] = str(p3)

    fig4, ax4 = plt.subplots(figsize=(8, 4))
    plot_trade_notional_hist(df, ax=ax4)
    p4 = out_path / f"{prefix}_trade_notionals.png"
    fig4.tight_layout()
    fig4.savefig(p4, dpi=140)
    plt.close(fig4)
    outputs["trade_notionals"] = str(p4)

    return outputs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate backtest graphics from SQLite trades")
    parser.add_argument("--db-path", default="data/trading_fund.db", help="Path to SQLite DB")
    parser.add_argument("--strategy-id", default=None, help="Optional strategy_id filter")
    parser.add_argument("--market-id", default=None, help="Optional market_id filter")
    parser.add_argument("--out-dir", default="plots", help="Directory to save plots")
    parser.add_argument("--prefix", default="backtest", help="Filename prefix for output images")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    trades = load_trades_dataframe(
        db_path=args.db_path,
        strategy_id=args.strategy_id,
        market_id=args.market_id,
    )
    if trades.empty:
        print("No trades found for the selected filters.")
        return 0

    enriched = enrich_trade_series(trades)
    outputs = save_backtest_graphics(
        df=enriched,
        out_dir=args.out_dir,
        prefix=args.prefix,
    )

    print(f"Rendered {len(enriched)} trades into {len(outputs)} plots:")
    for key, path in outputs.items():
        print(f"- {key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

