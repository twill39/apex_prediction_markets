# MM–AS tear sheet — `may01_mm_as`

## Slide 1 — Executive summary

- **fills:** 3767
- **markets:** 1
- **time_start:** 2026-05-01 13:30:01.160384+00:00
- **time_end:** 2026-05-01 19:58:00.236364+00:00
- **approx_duration_h:** 6.47
- **ending_cash_delta:** $10,640.46
- **ending_equity_m2m:** $16,286.58
- **fifo_realized_sum:** $14,873.47
- **fifo_closed_lots:** 3736
- **max_abs_inventory:** 20,761
- **p95_abs_inventory:** 16,585
- **ending_inventory:** 5,709
- **max_drawdown_m2m:** $4,065.92

## Slide 2 — What looks good

- Realized P&L from small/mid closing sizes (0–200) dominates tail bucket losses (small buckets sum ≈ $73 vs 1000+ ≈ $0).
- Ending MTM equity ($16,287) sits above cash-only path ($10,640); mark is carrying a chunk of P&L (settle / unwind risk remains).

## Slide 3 — Where it breaks

- Inventory spikes to ~20,761 contracts — strategy is acting like a directional book, not tight MM.

## Slide 4 — Figures (drop into deck)

- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_inventory.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_cash_equity.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_pnl_by_bucket.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_pnl_per_contract.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_fill_counts.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may01/may01_mm_as_ts_vwap_spread.png`

## Slide 5 — Methods note

- *Closing bucket P&L:* FIFO match per market; each closed lot’s P&L is grouped by the **closing** fill’s size (informed-flow-style lens).
- *MTM equity:* cash from fills + inventory × last print (same as plot_backtest_graphics).