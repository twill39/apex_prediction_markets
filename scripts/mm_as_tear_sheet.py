#!/usr/bin/env python3
"""Tear-sheet + trade analysis for Avellaneda–Stoikov / MM-AS backtests.

Loads fills from SQLite, builds FIFO bucketed realized PnL, inventory/equity plots,
and a Markdown slide-oriented summary.

Usage:
  python scripts/mm_as_tear_sheet.py --db-path data/trading_fund.db \\
      --market-id may04 --out-dir reports/tear_may04 --prefix may04_mm_as
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.plot_backtest_graphics import (
    enrich_trade_series,
    load_trades_dataframe,
    plot_cash_and_equity,
    plot_inventory,
)


SIZE_BIN_EDGES = [0.0, 50.0, 200.0, 1000.0, float("inf")]
SIZE_BIN_LABELS = ["0–50", "50–200", "200–1000", "1000+"]


def size_bucket_label(size: float) -> str:
    s = float(size)
    for lo, hi, lab in zip(
        SIZE_BIN_EDGES[:-1],
        SIZE_BIN_EDGES[1:],
        SIZE_BIN_LABELS,
    ):
        if lo <= s < hi:
            return lab
    return SIZE_BIN_LABELS[-1]


def fifo_realized_by_closing_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """
    FIFO match per market. Realized PnL rows attribute to closing fill's size bucket.
    """
    rows: List[Dict[str, Any]] = []
    long_q: DefaultDict[str, List[Dict[str, float]]] = defaultdict(list)
    short_q: DefaultDict[str, List[Dict[str, float]]] = defaultdict(list)

    for _, r in df.iterrows():
        market_id = str(r["market_id"])
        side = str(r["side"]).lower()
        price = float(r["price"])
        size = float(r["size"])
        fees = float(r.get("fees", 0.0) or 0.0)
        fee_u = fees / size if size > 0 else 0.0
        bkt = size_bucket_label(size)

        if side == "buy":
            rem = size
            while rem > 1e-12 and short_q[market_id]:
                lot = short_q[market_id][0]
                m = min(rem, lot["size"])
                pnl = (lot["price"] - price) * m - (lot["fee_u"] + fee_u) * m
                rows.append(
                    {
                        "market_id": market_id,
                        "pnl": pnl,
                        "matched": m,
                        "closing_bucket": bkt,
                        "closing_side": "buy",
                    }
                )
                rem -= m
                lot["size"] -= m
                if lot["size"] <= 1e-12:
                    short_q[market_id].pop(0)
            if rem > 1e-12:
                long_q[market_id].append({"price": price, "size": rem, "fee_u": fee_u})
        else:
            rem = size
            while rem > 1e-12 and long_q[market_id]:
                lot = long_q[market_id][0]
                m = min(rem, lot["size"])
                pnl = (price - lot["price"]) * m - (lot["fee_u"] + fee_u) * m
                rows.append(
                    {
                        "market_id": market_id,
                        "pnl": pnl,
                        "matched": m,
                        "closing_bucket": bkt,
                        "closing_side": "sell",
                    }
                )
                rem -= m
                lot["size"] -= m
                if lot["size"] <= 1e-12:
                    long_q[market_id].pop(0)
            if rem > 1e-12:
                short_q[market_id].append({"price": price, "size": rem, "fee_u": fee_u})

    return (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["pnl", "matched", "closing_bucket", "closing_side"])
    )


def plot_realized_pnl_by_bucket(closed: pd.DataFrame, out_path: Path) -> None:
    if closed.empty:
        return
    agg = closed.groupby("closing_bucket", observed=True)["pnl"].sum().reindex(SIZE_BIN_LABELS).fillna(0.0)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in agg.values]
    ax.bar(agg.index.astype(str), agg.values, color=colors, edgecolor="white", linewidth=0.5)
    ax.axhline(0.0, color="white", linewidth=0.8, alpha=0.8)
    ax.set_title("FIFO realized P&L by closing-fill size bucket")
    ax.set_xlabel("Closing trade size (contracts)")
    ax.set_ylabel("Total realized P&L ($)")
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#1a1a1a")
    ax.tick_params(colors="white")
    ax.title.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def plot_mean_pnl_per_contract_by_bucket(closed: pd.DataFrame, out_path: Path) -> None:
    if closed.empty:
        return
    g = closed.groupby("closing_bucket", observed=True).agg(pnl=("pnl", "sum"), matched=("matched", "sum"))
    g = g.reindex(SIZE_BIN_LABELS).fillna(0.0)
    g["per_contract"] = np.where(g["matched"] > 0, g["pnl"] / g["matched"], 0.0)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in g["per_contract"]]
    ax.bar(g.index.astype(str), g["per_contract"].values, color=colors, edgecolor="white", linewidth=0.5)
    ax.axhline(0.0, color="white", linewidth=0.8, alpha=0.8)
    ax.set_title("Mean realized P&L per matched contract (by closing-fill bucket)")
    ax.set_xlabel("Closing trade size (contracts)")
    ax.set_ylabel("$/contract (matched qty)")
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#1a1a1a")
    ax.tick_params(colors="white")
    ax.title.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def plot_fill_counts_by_bucket_side(df: pd.DataFrame, out_path: Path) -> None:
    if df.empty:
        return
    df = df.copy()
    df["bucket"] = df["size"].map(size_bucket_label)
    df["side_l"] = df["side"].str.lower()
    pivot = (
        df.pivot_table(index="bucket", columns="side_l", values="size", aggfunc="count", fill_value=0)
        .reindex(SIZE_BIN_LABELS)
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(SIZE_BIN_LABELS))
    w = 0.35
    buy = pivot["buy"].values if "buy" in pivot.columns else np.zeros(len(SIZE_BIN_LABELS))
    sell = pivot["sell"].values if "sell" in pivot.columns else np.zeros(len(SIZE_BIN_LABELS))
    ax.bar(x - w / 2, buy, width=w, label="Buy fills", color="#3498db")
    ax.bar(x + w / 2, sell, width=w, label="Sell fills", color="#e67e22")
    ax.set_xticks(x)
    ax.set_xticklabels(SIZE_BIN_LABELS)
    ax.set_title("Fill count by size bucket and side")
    ax.legend()
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#1a1a1a")
    ax.tick_params(colors="white")
    ax.title.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    ax.yaxis.label.set_text("Number of fills")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    leg = ax.get_legend()
    if leg:
        leg.get_frame().set_facecolor("#2a2a2a")
        for t in leg.get_texts():
            t.set_color("white")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def plot_buy_sell_vwap_spread(enriched: pd.DataFrame, out_path: Path) -> None:
    """Crude spread-capture proxy: VWAP_sell - VWAP_buy (not time-synchronized)."""
    if enriched.empty:
        return
    buys = enriched[enriched["side"].str.lower() == "buy"]
    sells = enriched[enriched["side"].str.lower() == "sell"]
    def vwap(g: pd.DataFrame) -> float:
        if g.empty:
            return float("nan")
        n = (g["price"] * g["size"]).sum()
        d = g["size"].sum()
        return float(n / d) if d > 0 else float("nan")

    vb, vs = vwap(buys), vwap(sells)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.barh([0, 1], [vb, vs], color=["#3498db", "#e67e22"], height=0.5)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["VWAP buys", "VWAP sells"])
    ax.set_xlim(0.0, 1.0)
    ax.set_title(f"Session VWAP (all fills)  |  sell−buy = {vs - vb:+.4f} if both sides exist")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def inventory_stress_stats(enriched: pd.DataFrame) -> Dict[str, float]:
    if enriched.empty or "inventory" not in enriched.columns:
        return {}
    inv = enriched["inventory"].astype(float)
    mx = float(inv.abs().max())
    q95 = float(inv.abs().quantile(0.95))
    end = float(inv.iloc[-1])
    return {"max_abs_inventory": mx, "p95_abs_inventory": q95, "ending_inventory": end}


def equity_drawdown_stats(enriched: pd.DataFrame) -> Dict[str, float]:
    if enriched.empty or "equity_m2m" not in enriched.columns:
        return {}
    eq = enriched["equity_m2m"].astype(float)
    peak = eq.cummax()
    dd = (peak - eq).max()
    return {"max_drawdown_m2m": float(dd)}


def build_slide_markdown(
    *,
    prefix: str,
    stats: Dict[str, Any],
    strengths: List[str],
    risks: List[str],
) -> str:
    lines = [
        f"# MM–AS tear sheet — `{prefix}`",
        "",
        "## Slide 1 — Executive summary",
        "",
    ]
    for k, v in stats.items():
        if str(k).startswith("fig_"):
            continue
        lines.append(f"- **{k}:** {v}")
    lines.extend(["", "## Slide 2 — What looks good", ""])
    for s in strengths:
        lines.append(f"- {s}")
    lines.extend(["", "## Slide 3 — Where it breaks", ""])
    for s in risks:
        lines.append(f"- {s}")
    lines.extend(
        [
            "",
            "## Slide 4 — Figures (drop into deck)",
            "",
        ]
    )
    for key in (
        "fig_inventory",
        "fig_cash_equity",
        "fig_pnl_bucket",
        "fig_pnl_per_contract",
        "fig_fill_counts",
        "fig_vwap",
    ):
        p = stats.get(key)
        if p:
            lines.append(f"- `{p}`")
    lines.extend(["", "## Slide 5 — Methods note", ""])
    lines.append(
        "- *Closing bucket P&L:* FIFO match per market; each closed lot’s P&L is "
        "grouped by the **closing** fill’s size (informed-flow-style lens)."
    )
    lines.append(
        "- *MTM equity:* cash from fills + inventory × last print (same as plot_backtest_graphics)."
    )
    return "\n".join(lines)


def auto_bullets(
    closed: pd.DataFrame,
    enriched: pd.DataFrame,
    ending_cash: float,
    ending_eq: float,
) -> tuple:
    strengths: List[str] = []
    risks: List[str] = []

    if not closed.empty:
        by_bkt = closed.groupby("closing_bucket")["pnl"].sum().reindex(SIZE_BIN_LABELS).fillna(0.0)
        tail = float(by_bkt.get("1000+", 0.0))
        small = float(by_bkt.get("0–50", 0.0)) + float(by_bkt.get("50–200", 0.0))
        if small > 0 and tail < small * 0.5:
            strengths.append(
                f"Realized P&L from small/mid closing sizes (0–200) dominates tail bucket losses "
                f"(small buckets sum ≈ ${small:,.0f} vs 1000+ ≈ ${tail:,.0f})."
            )
        if tail < -abs(small) * 0.25:
            risks.append(
                f"Large closing prints (1000+ contracts) contribute outsized negative realized P&L "
                f"(≈ ${tail:,.0f}) — classic adverse-selection / informed-flow signature."
            )

    stress = inventory_stress_stats(enriched)
    mx = stress.get("max_abs_inventory", 0.0)
    if mx > 5000:
        risks.append(
            f"Inventory spikes to ~{mx:,.0f} contracts — strategy is acting like a directional book, not tight MM."
        )
    elif mx > 0:
        strengths.append(
            f"Peak |inventory| ≈ {mx:,.0f} contracts — size of directional exposure to monitor vs your cap."
        )

    if ending_eq > ending_cash + 100.0:
        strengths.append(
            f"Ending MTM equity (${ending_eq:,.0f}) sits above cash-only path (${ending_cash:,.0f}); "
            "mark is carrying a chunk of P&L (settle / unwind risk remains)."
        )
    if ending_cash > ending_eq + 100.0:
        risks.append(
            f"Cash path (${ending_cash:,.0f}) is above MTM equity (${ending_eq:,.0f}); "
            "marked inventory may be underwater vs prints."
        )

    if not strengths:
        strengths.append("Add venue-specific context (latency, fee Tier, real vs sim fills).")
    if not risks:
        risks.append("Re-run after parameter sweeps (γ, cap, flatten window) to stress robustness.")
    return strengths, risks


def run_tear_sheet(
    *,
    db_path: str,
    market_id: Optional[str],
    out_dir: Path,
    prefix: str,
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = load_trades_dataframe(db_path, strategy_id=None, market_id=market_id)
    outputs: Dict[str, str] = {}

    if raw.empty:
        md = f"# No trades for filter market_id={market_id!r}\n"
        p = out_dir / f"{prefix}_TEAR_SHEET.md"
        p.write_text(md)
        outputs["summary"] = str(p)
        return outputs

    enriched = enrich_trade_series(raw)
    closed = fifo_realized_by_closing_bucket(raw)

    fig1, ax1 = plt.subplots(figsize=(12, 4))
    plot_inventory(enriched, ax=ax1)
    fig1.patch.set_facecolor("#111111")
    ax1.set_facecolor("#1a1a1a")
    p1 = out_dir / f"{prefix}_ts_inventory.png"
    fig1.savefig(p1, dpi=140, facecolor=fig1.get_facecolor(), bbox_inches="tight")
    plt.close(fig1)
    outputs["fig_inventory"] = str(p1)

    fig2 = plot_cash_and_equity(enriched)
    fig2.patch.set_facecolor("#111111")
    for ax in fig2.axes:
        ax.set_facecolor("#1a1a1a")
        ax.tick_params(colors="white")
        ax.title.set_color("white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
    p2 = out_dir / f"{prefix}_ts_cash_equity.png"
    fig2.savefig(p2, dpi=140, facecolor=fig2.get_facecolor(), bbox_inches="tight")
    plt.close(fig2)
    outputs["fig_cash_equity"] = str(p2)

    p3 = out_dir / f"{prefix}_ts_pnl_by_bucket.png"
    plot_realized_pnl_by_bucket(closed, p3)
    outputs["fig_pnl_bucket"] = str(p3)

    p4 = out_dir / f"{prefix}_ts_pnl_per_contract.png"
    plot_mean_pnl_per_contract_by_bucket(closed, p4)
    outputs["fig_pnl_per_contract"] = str(p4)

    p5 = out_dir / f"{prefix}_ts_fill_counts.png"
    plot_fill_counts_by_bucket_side(raw, p5)
    outputs["fig_fill_counts"] = str(p5)

    p6 = out_dir / f"{prefix}_ts_vwap_spread.png"
    plot_buy_sell_vwap_spread(enriched, p6)
    outputs["fig_vwap"] = str(p6)

    t0, t1 = enriched["timestamp"].iloc[0], enriched["timestamp"].iloc[-1]
    duration_h = (t1 - t0).total_seconds() / 3600.0 if len(enriched) > 1 else 0.0
    ending_cash = float(enriched["cash_balance_delta"].iloc[-1])
    ending_eq = float(enriched["equity_m2m"].iloc[-1])

    fifo_total = float(closed["pnl"].sum()) if not closed.empty else 0.0
    n_closed_lots = int(len(closed))

    stress = inventory_stress_stats(enriched)
    dd = equity_drawdown_stats(enriched)

    summary_stats: Dict[str, Any] = {
        "fig_inventory": outputs.get("fig_inventory"),
        "fig_cash_equity": outputs.get("fig_cash_equity"),
        "fig_pnl_bucket": outputs.get("fig_pnl_bucket"),
        "fig_pnl_per_contract": outputs.get("fig_pnl_per_contract"),
        "fig_fill_counts": outputs.get("fig_fill_counts"),
        "fig_vwap": outputs.get("fig_vwap"),
        "fills": len(enriched),
        "markets": enriched["market_id"].nunique(),
        "time_start": str(t0),
        "time_end": str(t1),
        "approx_duration_h": f"{duration_h:.2f}",
        "ending_cash_delta": f"${ending_cash:,.2f}",
        "ending_equity_m2m": f"${ending_eq:,.2f}",
        "fifo_realized_sum": f"${fifo_total:,.2f}",
        "fifo_closed_lots": n_closed_lots,
        "max_abs_inventory": f'{stress.get("max_abs_inventory", float("nan")):,.0f}',
        "p95_abs_inventory": f'{stress.get("p95_abs_inventory", float("nan")):,.0f}',
        "ending_inventory": f'{stress.get("ending_inventory", float("nan")):,.0f}',
        "max_drawdown_m2m": f'${dd.get("max_drawdown_m2m", float("nan")):,.2f}',
    }

    strengths, risks = auto_bullets(closed, enriched, ending_cash, ending_eq)
    md_text = build_slide_markdown(prefix=prefix, stats=summary_stats, strengths=strengths, risks=risks)
    mp = out_dir / f"{prefix}_TEAR_SHEET.md"
    mp.write_text(md_text)
    outputs["summary"] = str(mp)

    js = {
        "summary_stats": {k: v for k, v in summary_stats.items() if not str(k).startswith("fig_")},
        "strengths": strengths,
        "risks": risks,
    }
    jp = out_dir / f"{prefix}_tear_metrics.json"
    jp.write_text(json.dumps(js, indent=2))
    outputs["json"] = str(jp)

    return outputs


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MM-AS tear sheet from SQLite trades")
    p.add_argument("--db-path", default="data/trading_fund.db")
    p.add_argument("--market-id", default=None, help="Filter to one market (e.g. may04)")
    p.add_argument("--out-dir", default="reports/tear_sheet")
    p.add_argument("--prefix", default="mm_as", help="Output file prefix")
    return p


def main() -> int:
    args = _parser().parse_args()
    out = run_tear_sheet(
        db_path=args.db_path,
        market_id=args.market_id,
        out_dir=Path(args.out_dir).expanduser().resolve(),
        prefix=args.prefix,
    )
    for k, v in out.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
