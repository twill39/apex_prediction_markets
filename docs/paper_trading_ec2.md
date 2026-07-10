# Paper Trading on EC2 (S&P Band Market)

Run the Avellaneda-Stoikov market making strategy live on a remote EC2 instance against one Kalshi S&P daily closing-band market, with live Kalshi orderbook data and a Schwab SPX spot feed.

## Daily workflow

### 1. Fetch band bounds for today's market

Run once per trading day (or when the ticker changes):

```bash
python scripts/fetch_kalshi_market_bounds.py \
  --ticker "KXINX-26JUN05H1600-B7237" \
  --output data/kalshi_market_bounds.json
```

Verify the output row has `"has_bounds": true` with `lower_bound`, `upper_bound`, and `eod_timestamp`.

### 2. Configure environment

Required Kalshi credentials:

```bash
export KALSHI_API_KEY="your-kalshi-api-key"
export KALSHI_PRIVATE_KEY_PATH="/path/to/kalshi_private_key.pem"
export SIMULATOR_USE_KALSHI=True
export SIMULATOR_USE_POLYMARKET=False
```

Required Schwab credentials (for live SPX feed):

```bash
export APP_KEY="your-schwab-app-key"
export APP_SECRET="your-schwab-app-secret"
export CALLBACK_URL="https://127.0.0.1"   # if needed for initial OAuth
export SIMULATOR_USE_SCHWAB_SPX=True
```

Schwab OAuth tokens must already exist on the instance (schwabdev stores them locally after the first browser auth). Copy the token database from your dev machine if needed, or complete OAuth once on EC2.

**SPX feed mode:** By default the paper trader uses **REST polling** (`quote` / `price_history`) every ~5 seconds — the same APIs as `fetch_schwab_spx_minute_history.py`. Schwab **WebSocket streaming** is optional and requires the **Trader API** enabled on your Schwab app (streaming uses `GET /userPreference` → `streamerInfo`, not the Market Data API alone). If you see `HTTP 401` / `streamerInfo` errors, leave streaming off (default) or enable Trader API in the developer portal and set `SIMULATOR_SCHWAB_SPX_USE_STREAM=True`.

Optional simulator tuning:

```bash
export SIMULATOR_INITIAL_BALANCE=10000
export MARKET_MAKING_AS_MAX_POSITION=50
export SIMULATOR_BOUNDS_FILE=data/kalshi_market_bounds.json
export LOG_LEVEL=INFO
export LOG_FILE=./logs/paper_trading.log
```

### 3. Start paper trading

```bash
python scripts/run_strategy.py \
  --strategy market_making_as \
  --mode paper \
  --markets "KXINX-26JUN05H1600-B7237" \
  --bounds-file data/kalshi_market_bounds.json \
  --spx-stream \
  --duration 480
```

- `--markets`: Kalshi ticker for the band contract
- `--bounds-file`: JSON from step 1 (injected once when orderbook data arrives)
- `--spx-stream`: enable Schwab SPX spot feed (or set `SIMULATOR_USE_SCHWAB_SPX=True`)
- `--duration`: optional stop after N minutes; omit to run until stopped manually

### 4. Monitor

```bash
tail -f logs/paper_trading.log
```

Look for:

- `Loaded bounds for 1 market(s)` at startup
- `Injected band bounds for <ticker>` after the first orderbook update
- `Started Schwab SPX feed for $SPX`
- `SPX feed stale for ...` warnings if the spot feed stops updating

Trades and orders are persisted to SQLite at `./data/trading_fund.db`.

## Data flow

1. **Kalshi WebSocket** delivers live orderbook deltas for your ticker.
2. **Bounds file** supplies `lower_bound`, `upper_bound`, and `eod_timestamp` once the market is active.
3. **Schwab stream** (with REST poll fallback) pushes `$SPX` spot into the strategy for band fair-value calculation.
4. **Paper simulator** simulates limit-order fills against the live book and tracks P&L.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------- |
| `Could not load simulator because of bad websocket connection` | Kalshi credentials, network egress, or wrong `KALSHI_WS_URL` |
| `Bounds file not found` | Run `fetch_kalshi_market_bounds.py` or fix `--bounds-file` path |
| No model fair value / quotes use orderbook mid only | Missing bounds injection or no SPX price yet |
| `Failed to start Schwab SPX feed` | Missing `APP_KEY`/`APP_SECRET` or expired OAuth tokens |
| `SPX feed stale` | Schwab stream down; poll fallback should still update every ~5s |

## Long-running on EC2

Use `tmux` or `systemd` to keep the process alive after SSH disconnect:

```bash
tmux new -s mm_as
# run the python command above
# Ctrl+B, D to detach
```

Re-fetch bounds and update `--markets` each trading day when the Kalshi ticker rolls.
