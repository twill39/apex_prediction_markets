# MM–AS tear sheet — `may04_mm_as`

## Slide 1 — Executive summary

- **fills:** 1792
- **markets:** 1
- **time_start:** 2026-05-04 13:30:01.791495+00:00
- **time_end:** 2026-05-04 19:59:55.929284+00:00
- **approx_duration_h:** 6.50
- **ending_cash_delta:** $4,479.16
- **ending_equity_m2m:** $3,874.85
- **fifo_realized_sum:** $849.36
- **fifo_closed_lots:** 1350
- **max_abs_inventory:** 60,492
- **p95_abs_inventory:** 51,537
- **ending_inventory:** -60,492
- **max_drawdown_m2m:** $5,822.15

## Slide 2 — What looks good

- Realized P&L from small/mid closing sizes (0–200) dominates tail bucket losses (small buckets sum ≈ $195 vs 1000+ ≈ $0).

## Slide 3 — Where it breaks

- Inventory spikes to ~60,492 contracts — strategy is acting like a directional book, not tight MM.
- Cash path ($4,479) is above MTM equity ($3,875); marked inventory may be underwater vs prints.

## Slide 4 — Figures (drop into deck)

- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_inventory.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_cash_equity.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_pnl_by_bucket.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_pnl_per_contract.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_fill_counts.png`
- `/Users/dhruvd/Documents/apex/apex_prediction_markets/reports/tear_may04/may04_mm_as_ts_vwap_spread.png`

## Slide 5 — Methods note

- *Closing bucket P&L:* FIFO match per market; each closed lot’s P&L is grouped by the **closing** fill’s size (informed-flow-style lens).
- *MTM equity:* cash from fills + inventory × last print (same as plot_backtest_graphics).