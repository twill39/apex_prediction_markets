#!/usr/bin/env python3
"""Build an executive PowerPoint summarizing Apex MM–Avellaneda–Stoikov work.

Depends on: pip install python-pptx

Usage:
  python scripts/build_mm_as_presentation.py [--out apex_mm_as_review.pptx]

Embeds tear-sheet PNGs from reports/tear_may07/ when present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: pip install python-pptx\n" + str(e)
    ) from e


def _title_slide(prs: Presentation, title: str, subtitle: str) -> None:
    layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title
    tf = slide.placeholders[1]
    tf.text = subtitle


def _bullets_slide(prs: Presentation, title: str, bullets: list[str]) -> None:
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.clear()
    for i, line in enumerate(bullets):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        p.text = line
        p.level = 0
        p.font.size = Pt(18)


def _two_column_bullets(
    prs: Presentation, title: str, left_title: str, left: list[str], right_title: str, right: list[str]
) -> None:
    """Use blank layout + two text boxes for side-by-side bullets."""
    layout = prs.slide_layouts[5]  # blank
    slide = prs.slides.add_slide(layout)
    title_shape = slide.shapes.add_textbox(Inches(0.5), Inches(0.25), Inches(9), Inches(0.6))
    title_shape.text_frame.text = title
    title_shape.text_frame.paragraphs[0].font.size = Pt(32)
    title_shape.text_frame.paragraphs[0].font.bold = True

    lx, rx = Inches(0.5), Inches(5.1)
    y = Inches(1.0)
    w, h = Inches(4.4), Inches(5.2)

    for x, sub, items in ((lx, left_title, left), (rx, right_title, right)):
        box = slide.shapes.add_textbox(x, y, w, h)
        tf = box.text_frame
        tf.clear()
        h1 = tf.paragraphs[0]
        h1.text = sub
        h1.font.size = Pt(22)
        h1.font.bold = True
        for line in items:
            p = tf.add_paragraph()
            p.text = line
            p.level = 0
            p.font.size = Pt(15)
            p.space_after = Pt(6)


def _add_picture_slide(prs: Presentation, title: str, image_path: Path) -> None:
    layout = prs.slide_layouts[5]
    slide = prs.slides.add_slide(layout)
    t = slide.shapes.add_textbox(Inches(0.4), Inches(0.2), Inches(9), Inches(0.55))
    t.text_frame.text = title
    t.text_frame.paragraphs[0].font.size = Pt(28)
    t.text_frame.paragraphs[0].font.bold = True
    slide.shapes.add_picture(str(image_path), Inches(0.4), Inches(0.85), width=Inches(9.1))


def build_deck(out_path: Path, repo: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    _title_slide(
        prs,
        "Apex Prediction Markets",
        "Avellaneda–Stoikov market making · Kalshi S&P niche · results & roadmap",
    )

    _bullets_slide(
        prs,
        "Niche: S&P / index prediction on Kalshi",
        [
            "Focused stack for short-dated binary-style contracts tied to realized SPX (or band) outcomes.",
            "Rich local data: archived order-book frames (JSONL), snapshots, Kalshi market-bounds artifacts for replay bands.",
            "External reference: Schwab/minute SPX history scripts to relate spot path to conditional fair value.",
            "Single-market deep dives (tear sheets labeled may01 / may04 / may07) instead of scattering across many unrelated tickers.",
        ],
    )

    _bullets_slide(
        prs,
        "Project depth (repository map)",
        [
            "Live + paper paths: Kalshi (and optional Polymarket) WebSockets, discovery, storage.",
            "Strategies package: legacy MM, copy-trading, alt-data — plus MM–AS (`src/strategies/market_making_as.py`).",
            "Simulator layer: historical replay from frames, paper trading, metrics aligned with plotting.",
            "Analysis: `mm_as_tear_sheet.py` (FIFO bucketed realized PnL, inventory/equity charts), Kalshi OB history/live analyzers.",
            "Ops: CLI `scripts/run_strategy.py`, config via Pydantic (`MarketMakingAsSettings`).",
        ],
    )

    _bullets_slide(
        prs,
        "Avellaneda–Stoikov: what we implemented",
        [
            "Mid / fair value s: blend of book mid, optional model track; rolling realized σ from price history.",
            "Reservation price r = s − q γ σ² τ (inventory q, risk aversion γ, horizon τ = T−t).",
            "Half-spread from A-S formula, then clipped to [0, 0.49] for valid binary prices in [0,1].",
            "Adaptive γ(ρ): widens risk aversion under regime stress (ρ from reversal-bucket score when enabled).",
            "Regime score currently unwired (`MM_AS_REGIME_SCORE_ENABLED = False`) so ρ = 0 in production path.",
            "Sizing: base fraction of max position, Cauchy/band-based fair value hooks, inventory taper + hard gate + quote skew near limits.",
        ],
    )

    _two_column_bullets(
        prs,
        "Configuration highlights (MarketMakingAsSettings)",
        "Risk & quotes",
        [
            "γ_base, κ, session_horizon_seconds",
            "quote_update_interval, reprice threshold",
            "max_position (signed cap target)",
            "inventory_hard_gate_fraction, skew coeffs",
            "session_flatten_seconds before EOD",
        ],
        "Discovery & sim",
        [
            "Kalshi/Poly discovery filters (spread, volume)",
            "Simulator: enforce_signed_inventory_cap backstop",
            "Historical: bounds JSON → band metadata bootstrap",
        ],
    )

    _bullets_slide(
        prs,
        "Measurement: tear-sheet methodology",
        [
            "FIFO pairing per market; realized PnL attributed to closing fill size bucket (0–50, …, 1000+).",
            "Mark-to-market equity: cash from fills + inventory × last print (consistent with plot_backtest_graphics).",
            "Reports: Markdown executive summary + PNG time series (inventory, cash/equity, bucket PnL, fills, VWAP spread).",
        ],
    )

    _bullets_slide(
        prs,
        "Results snapshot (single Kalshi markets, ~6.5h sessions)",
        [
            "May 01 — fills 3,767 · MTM equity ~$16.3k vs cash ~$10.6k · max |inv| ~20.8k · max DD ~$4.1k.",
            "May 04 — fills 1,792 · cash ~$4.5k vs MTM ~$3.9k · max |inv| ~60k (extreme directional book) · max DD ~$5.8k.",
            "May 07 — fills 852 · MTM ~−$1.7k vs cash ~−$1.8k · max |inv| ~9.3k · max DD ~$2.6k.",
            "Pattern: small/mid closing sizes often dominated P&L in the “good” days; tail inventory remains the structural risk.",
        ],
    )

    _two_column_bullets(
        prs,
        "Strengths vs gaps",
        "What looked good",
        [
            "End-to-end path from data → replay → FIFO analytics.",
            "A-S machinery + binary clips + inventory-aware sizing hooks.",
            "Actionable diagnostics (bucketed realized, inventory spikes).",
        ],
        "Where it breaks / next work",
        [
            "Inventory explodes relative to “tight MM” — need stronger flattening, caps, or vol/λ calibration.",
            "Regime ρ path off — re-enable or replace with execution-level signal.",
            "Fees, latency tier, partial fills: label sim vs live explicitly.",
            "Fair value: stress-test Cauchy/band model vs pure mid under fast moves.",
        ],
    )

    _bullets_slide(
        prs,
        "Roadmap (concrete)",
        [
            "Tighten signed inventory path: lower effective κ or dynamic spread; kill-switch on inventory velocity.",
            "Revisit γ, horizon τ, and max half-spread vs Kalshi tick structure.",
            "Calibrate to arrival rate / queue position if OB data supports it.",
            "Expand SPX-aligned features: joint plots of spot path vs quoted r and inventory.",
            "Automate deck refresh: tie tear_sheet outputs into this script for dated runs.",
        ],
    )

    tear_dir = repo / "reports" / "tear_may07"
    for img_name, slide_title in (
        ("may07_mm_as_ts_inventory.png", "May 07 — inventory (illustrative)"),
        ("may07_mm_as_ts_cash_equity.png", "May 07 — cash vs MTM equity"),
    ):
        p = tear_dir / img_name
        if p.is_file():
            _add_picture_slide(prs, slide_title, p)

    _bullets_slide(
        prs,
        "Scripts & entry points",
        [
            "Strategy: `src/strategies/market_making_as.py`",
            "Run: `python scripts/run_strategy.py --strategy market_making …`",
            "Tear sheet: `python scripts/mm_as_tear_sheet.py --db-path … --out-dir reports/tear_*`",
            "This deck: `python scripts/build_mm_as_presentation.py`",
        ],
    )

    prs.save(str(out_path))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build MM–AS PowerPoint deck.")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO / "reports" / "apex_mm_as_review.pptx",
        help="Output .pptx path",
    )
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    build_deck(args.out.resolve(), _REPO)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
