# EC2 Instance Flow — Paper Trading (S&P Band)

Step-by-step guide for running the Avellaneda-Stoikov market making strategy on an AWS EC2 instance with live Kalshi orderbook data and a Schwab SPX spot feed.

---

## Overview

| What | Where |
| ---- | ----- |
| Strategy | `market_making_as` |
| Mode | `paper` (live data, simulated fills) |
| Kalshi feed | WebSocket orderbook deltas |
| SPX feed | Schwab stream (`--spx-stream`) |
| Band bounds | `data/kalshi_market_bounds.json` (fetch daily) |
| App logs | `LOG_FILE` env var (default `./logs/trading_fund.log`) |
| Trades DB | `./data/trading_fund.db` (SQLite, auto-created) |

---

## First-time setup (once per instance)

### 1. Launch EC2

- **AMI:** Ubuntu 22.04 or similar
- **Security group:** allow SSH (port 22) from your IP
- **Storage:** enough for logs + SQLite (a few GB is fine)
- Optional: attach an **Elastic IP** so the public address does not change on restart

### 2. Clone repo and install deps

SSH in (see below), then:

```bash
git clone <your-repo-url> apex_prediction_markets
cd apex_prediction_markets
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data logs
```

### 3. Copy secrets to the instance

On EC2 you need:

| File / config | Purpose |
| ------------- | ------- |
| `.env` | API keys and simulator settings |
| Kalshi `.pem` | Path set in `KALSHI_PRIVATE_KEY_PATH` |
| Schwab OAuth tokens | schwabdev token DB (copy from laptop after first OAuth, or auth once on EC2) |

Example `.env` (do not commit):

```bash
KALSHI_API_KEY=your-kalshi-api-key
KALSHI_PRIVATE_KEY_PATH=/home/ubuntu/apex_prediction_markets/kalshi_private_key.pem

APP_KEY=your-schwab-app-key
APP_SECRET=your-schwab-app-secret
CALLBACK_URL=https://127.0.0.1
SCHWAB_TOKEN_PATH=/home/ubuntu/.schwabdev/tokens.db

SIMULATOR_USE_KALSHI=True
SIMULATOR_USE_POLYMARKET=False
SIMULATOR_USE_SCHWAB_SPX=True
SIMULATOR_MARKET_DATA_STALE_SECONDS=60
SIMULATOR_FEED_DISCONNECT_GRACE_SECONDS=60
MARKET_MAKING_AS_INVENTORY_OVERLAYS_ENABLED=True

LOG_LEVEL=INFO
LOG_FILE=/home/ubuntu/apex_prediction_markets/logs/paper_trading.log
DATABASE_PATH=/home/ubuntu/apex_prediction_markets/data/trading_fund.db
SIMULATOR_BOUNDS_FILE=/home/ubuntu/apex_prediction_markets/data/kalshi_market_bounds.json
```

Verify:

```bash
ls -la .env
ls -la "$KALSHI_PRIVATE_KEY_PATH"
ls -la "$SCHWAB_TOKEN_PATH"
```

---

## Connect to EC2

From your laptop:

```bash
ssh -i ~/.ssh/your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

If you use an SSH config alias:

```bash
ssh my-apex-ec2
```

Find the IP in **AWS Console → EC2 → Instances** (instance must be **Running**).

### Activate project

```bash
cd ~/apex_prediction_markets   # adjust path if different
source venv/bin/activate
```

Pull latest code when needed:

```bash
git pull
pip install -r requirements.txt
```

---

## Daily workflow (each trading day)

### Step 1 — Set today's Kalshi ticker

Update `YOUR-TICKER` to the current S&P daily closing-band contract (e.g. `KXINX-26JUN05H1600-B7237`).

### Step 2 — Fetch band bounds

```bash
python scripts/fetch_kalshi_market_bounds.py \
  --ticker "YOUR-TICKER" \
  --output data/kalshi_market_bounds.json
```

Confirm the JSON row has `"has_bounds": true` with `lower_bound`, `upper_bound`, and `eod_timestamp`.

### Step 3 — Start paper trading (simple)

```bash
python scripts/run_strategy.py \
  --strategy market_making_as \
  --mode paper \
  --markets "YOUR-TICKER" \
  --bounds-file data/kalshi_market_bounds.json \
  --spx-stream
```

Runs until you stop it with Ctrl+C. Use tmux or systemd below before disconnecting SSH.

**Optional:** auto-stop after the session when starting at 09:30 ET (390 min):

```bash
python scripts/run_strategy.py \
  --strategy market_making_as \
  --mode paper \
  --markets "YOUR-TICKER" \
  --bounds-file data/kalshi_market_bounds.json \
  --spx-stream \
  --duration 390
```

### Step 4 — Use tmux so disconnect does not kill the run

```bash
tmux new -s paper
# run fetch + run_strategy commands inside tmux
# detach: Ctrl+B, then D
```

Reattach later:

```bash
tmux attach -t paper
```

List sessions:

```bash
tmux ls
```

### Step 5 — Monitor

```bash
tail -f logs/paper_trading.log
```

Healthy startup log lines:

- `Loaded bounds for 1 market(s) from kalshi_market_bounds.json`
- `Started Schwab SPX feed for $SPX`
- `Injected band bounds for YOUR-TICKER (lower=... upper=...)`
- a fresh orderbook snapshot at startup; disconnects cancel pending paper orders until a post-reconnect snapshot arrives

When the run ends, a performance report prints to the terminal (and appears in logs if you redirected stdout).

### Step 6 — When done

- Detach from tmux or Ctrl+C inside the session
- Optional: **Stop** the EC2 instance in AWS Console to save cost (public IP may change on next start unless you use Elastic IP)

---

## Quick reference (copy-paste)

```bash
# connect
ssh -i ~/.ssh/your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP

# on EC2
cd ~/apex_prediction_markets && source venv/bin/activate
export TICKER="YOUR-TICKER"

python scripts/fetch_kalshi_market_bounds.py \
  --ticker "$TICKER" \
  --output data/kalshi_market_bounds.json

tmux new -s paper
python scripts/run_strategy.py \
  --strategy market_making_as \
  --mode paper \
  --markets "$TICKER" \
  --bounds-file data/kalshi_market_bounds.json \
  --spx-stream
# Ctrl+B, D to detach
```

---

## Data flow

1. **Kalshi WebSocket** → live orderbook → strategy quotes and simulated fills
2. **Bounds JSON** → injected once → band fair value (`lower_bound`, `upper_bound`, `eod_timestamp`)
3. **Schwab SPX** → underlying spot → Cauchy band probability in `_compute_band_fair_value()`
4. **Paper simulator** → limit orders, fills, P&L → SQLite + end-of-run metrics

---

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------- |
| SSH connection refused | Instance stopped, wrong IP, or security group blocks your IP |
| `Could not load simulator because of bad websocket connection` | Kalshi credentials, network egress, or `KALSHI_WS_URL` |
| `Bounds file not found` | Run `fetch_kalshi_market_bounds.py` first |
| Quotes use orderbook mid only (no band model) | No fresh SPX price; stale SPX intentionally falls back to the book |
| `Failed to start Schwab SPX feed` | Missing `APP_KEY`/`APP_SECRET` or expired OAuth tokens |
| `SPX feed stale` | Stream quiet; REST poll fallback should still update ~every 5s |
| Process died after closing laptop | Forgot tmux — restart inside `tmux new -s paper` |
| `Stopping paper trading because live data is unsafe` | WebSocket reconnect budget expired or no fresh snapshot arrived after startup/reconnect |

---

## Optional: automate market open → close

For hands-off runs, wrap the daily commands in a shell script and schedule with **cron** or **systemd timer** (weekdays ~9:29 ET). See [paper_trading_ec2.md](paper_trading_ec2.md) for env var details and a script sketch.

---

## Related docs

- [setup.md](setup.md) — local venv, `.env`, dependencies
- [paper_trading_ec2.md](paper_trading_ec2.md) — paper trading config and troubleshooting detail
