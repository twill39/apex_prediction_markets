# MM–AS tear sheet — `may07_mm_as`

## Slide 1 — Executive summary

- **fills:** 852
- **markets:** 1
- **time_start:** 2026-05-07 14:15:20.959317+00:00
- **time_end:** 2026-05-07 19:59:56.600593+00:00
- **approx_duration_h:** 5.74
- **ending_cash_delta:** $-1,818.88
- **ending_equity_m2m:** $-1,747.30
- **fifo_realized_sum:** $-1,782.98
- **fifo_closed_lots:** 843
- **max_abs_inventory:** 9,255
- **p95_abs_inventory:** 4,564
- **ending_inventory:** 3,583
- **max_drawdown_m2m:** $2,645.18

## Slide 2 — What looks good

- Add venue-specific context (latency, fee Tier, real vs sim fills).

## Slide 3 — Where it breaks

- Inventory spikes to ~9,255 contracts — strategy is acting like a directional book, not tight MM.

## Slide 4 — Figures (drop into deck)

- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_inventory.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_cash_equity.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_pnl_by_bucket.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_pnl_per_contract.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_fill_counts.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may07/may07_mm_as_ts_vwap_spread.png`

## Slide 5 — Methods note

- *Closing bucket P&L:* FIFO match per market; each closed lot’s P&L is grouped by the **closing** fill’s size (informed-flow-style lens).
- *MTM equity:* cash from fills + inventory × last print (same as plot_backtest_graphics).