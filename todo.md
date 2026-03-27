# Next Steps: Profitable Kalshi Trading

## Overall (repo-wide)

1. Finalize and stabilize live data inputs for Kalshi orderbooks and trades (ensure HFT `snapshot/deltas` + `collect_historical.py` schema are consistent and tested on multiple liquid tickers).
2. Add a “market selection + health checks” layer for Kalshi live trading (before running strategies: verify spread/liquidity thresholds, orderbook depth non-empty, and trade feed not silent).
3. Make the simulator outputs the single source of truth for strategy QA (standardize input artifact formats + add a regression test that runs all three strategies on a fixed replay bundle).
4. Improve backtesting fidelity: ensure execution price logic, slippage, fees, and order fill assumptions match Kalshi’s actual microstructure (at least within an acceptable error band).
5. Build an evaluation harness that compares runs across strategies (profit, ROI, max drawdown, turnover, fill-rate, and “time-to-first-trade”).

## 1) Market Making Strategy (`market_making`)

1. Replace the placeholder discovery usage with a deterministic Kalshi market universe builder:
  - use discovery thresholds for spread/liquidity/volume,
  - keep a persisted allowlist (and refresh periodically).
2. Implement a robust fair value model for Kalshi markets (not just mid-price):
  - incorporate historical candlesticks / orderbook imbalance / time-to-expiry,
  - output both `fair_value` and an uncertainty estimate (used for quote sizing).
3. Implement inventory-aware quoting:
  - tighten/widen quotes based on current inventory/position drift,
  - add risk limits (max inventory, max exposure per market).
4. Implement order lifecycle management:
  - quote refresh cadence,
  - cancel/replace rules,
  - handle partial fills (and avoid quote spam).
5. Paper-trading performance loop:
  - run 24–72h paper tests over a curated liquid subset,
  - track realized P&L and fill-rate,
  - iterate quote model + risk limits until metrics exceed thresholds.
6. Backtester training loop:
  - train model parameters on historical replay artifacts (from `collect_kalshi_historical.py` / WS replays),
  - validate on a held-out time window (no leakage),
  - lock parameters, then re-run paper with production-like settings.
7. Only after profitability: enable live execution on small notional, with automatic circuit breakers (halt on drawdown or abnormal loss rates).

## 2) Copy Trading Strategy (`copy_trading`)

1. Fix/extend trader discovery:
  - ensure discovered traders are meaningful (not just “any trader on stream”),
  - add trader selection criteria based on historical consistency (returns, volatility, win-rate).
2. Implement robust attribution to trades:
  - ensure `trade.metadata["trader_id"]` is correctly populated from Kalshi and/or Polymarket inputs used for copy trading.
3. Add execution and risk controls:
  - cap follower exposure per leader,
  - enforce per-market max trades/day,
  - add slippage + latency buffers and validate in simulator.
4. Add “signal quality gating”:
  - ignore leader signals when orderbook conditions don’t support profitable replication (spread too tight/too wide, low depth, etc.).
5. Backtest replication fidelity:
  - measure tracking error between leader fills vs follower execution,
  - incorporate fill-rate mismatch into performance metrics.
6. Paper loop:
  - run small-market paper replicates with strict caps,
  - evaluate profitability net of fees/slippage and turnover.
7. Transition to live with guardrails:
  - start with a single leader universe,
  - require stable profitability over multiple disjoint weeks.

## 3) Alt Data Strategy (`alt_data`)

1. Define the alt-feature pipeline per market:
  - confirm keywords extraction is correct for Kalshi event/market titles,
  - add rate limiting + caching so feature collection is stable in live runs.
2. Train the fair value mapping:
  - build a supervised dataset linking (alt features) -> (market outcome proxy like price movement / implied probabilities),
  - validate out-of-sample and store model artifacts.
3. Calibrate confidence and thresholding:
  - turn model output into a calibrated probability or expected value,
  - tune `confidence_threshold` against backtest ROI, not raw classification accuracy.
4. Implement the actual trading policy:
  - define when to place limit orders vs market orders,
  - size orders based on uncertainty and risk budget.
5. Integrate simulator evaluation:
  - run `alt_data` on replay artifacts,
  - verify that `market_update -> alt model -> order signals` produces trades in the simulator.
6. Paper loop:
  - run for multiple windows with consistent feature generation cadence,
  - compare predicted vs realized performance (expected vs realized P&L).
7. Live rollout only after stability:
  - require statistically significant improvement vs baseline (market-neutral or random),
  - enforce drawdown circuit breakers.

