# Setup Guide

Follow these steps in order to get the project running.

---

## 1. Clone or navigate to the repo

If you don’t have the repo yet:

```bash
git clone <repository-url>
cd apex_prediction_markets
```

If you already have it, just go to the project directory:

```bash
cd apex_prediction_markets
```

---

## 2. Create and activate a virtual environment

### Check if you already have a venv

- **Prompt:** If your terminal prompt starts with `(venv)`, `(.venv)`, or another env name, a venv is already active.
- **Command (macOS/Linux):** Run `which python`. If the path is inside this project (e.g. `.../apex_prediction_markets/venv/bin/python`), you’re using a venv. If it’s something like `/usr/bin/python3`, you’re not.
- **Command (Windows):** Run `where python`. An active venv will show a path like `...\venv\Scripts\python.exe`.
- **Folder:** In the project directory, look for a folder named `venv`, `.venv`, or `env`. If it exists, a venv was created; you still need to activate it (see below).

### Create a new venv (if needed)

```bash
python -m venv venv
```

### Activate the venv

- **macOS/Linux:**
  ```bash
  source venv/bin/activate
  ```
- **Windows (Command Prompt):**
  ```cmd
  venv\Scripts\activate.bat
  ```
- **Windows (PowerShell):**
  ```powershell
  venv\Scripts\Activate.ps1
  ```

When active, your prompt should start with `(venv)`.

---

## 3. Install dependencies

From the project root (with the venv activated):

```bash
pip install -r requirements.txt
```

---

## 4. Set up the `.env` file and API keys

### Create `.env` from the example

```bash
cp .env.example .env
```

This creates a `.env` file in the project root. **Do not commit `.env`**—it is listed in `.gitignore` because it will contain secrets.

### Edit `.env` and add your API keys

Open `.env` in your editor and replace the placeholder values with your real credentials.

#### Required to run strategies (Kalshi)

Paper and historical modes use the WebSocket clients, which need Kalshi credentials. Kalshi uses a **private key file (.pem)** for authentication, not a secret string.

| Variable                  | What to put |
|---------------------------|-------------|
| `KALSHI_API_KEY`          | Your Kalshi API key ID (e.g. the UUID shown when you create the key). |
| `KALSHI_PRIVATE_KEY_PATH` | Path to your `.pem` (or `.key`) private key file. E.g. `./kalshi_private_key.pem` if the file is in the project root. |

- Get Kalshi API credentials: go to your Kalshi account → API Keys, create a key, and **download the private key** (e.g. `kalshi_key.key` or save as `.pem`). The API key ID is shown on the same page. Store the key file somewhere safe (e.g. project root or a secure folder) and set `KALSHI_PRIVATE_KEY_PATH` to that path.
- You can use `KALSHI_PEM_PATH` instead of `KALSHI_PRIVATE_KEY_PATH` if you prefer.
- Leave `KALSHI_BASE_URL` as-is unless you use a different environment.

#### Optional: Polymarket

| Variable              | What to put |
|-----------------------|-------------|
| `POLYMARKET_API_KEY`  | Your Polymarket API key (if you have one) |

Public market data may work without this. Leave as the placeholder or leave the line commented if you don’t have a key.

#### Optional: Alt Data strategy (Twitter)

Only needed if you run the **Alt Data** strategy and want Twitter data:

| Variable                | What to put |
|-------------------------|-------------|
| `TWITTER_BEARER_TOKEN`  | Twitter API v2 Bearer Token (easiest option) |
| `TWITTER_API_KEY`       | Twitter API key (if not using only Bearer) |
| `TWITTER_API_SECRET`    | Twitter API secret |

- Get Twitter credentials: [Twitter Developer Portal](https://developer.twitter.com/). Create a project/app and obtain the Bearer Token and/or API Key/Secret.

### Other `.env` options

- **`DATABASE_PATH`** — Path to the SQLite database (default: `./data/trading_fund.db`). Optional.
- **`LOG_LEVEL`** — `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Default: `INFO`.
- **`LOG_FILE`** — Path to the log file (default: `./logs/trading_fund.log`). Optional.

Strategy and simulator options (e.g. `COPY_TRADING_MAX_TRADERS`, `SIMULATOR_SLIPPAGE`) are in `.env.example` with defaults; you can change them in `.env` if you want.

### Save and close

Save `.env` and keep it only on your machine. Never commit it or share it.

---

## 5. Create `data/` and `logs/` directories

The app expects these for the database and log file:

```bash
mkdir -p data logs
```

On Windows (PowerShell): `New-Item -ItemType Directory -Force data, logs`

---

## 6. Run from the project root

Always run commands from the **project root** (`apex_prediction_markets/`), with the venv activated.

**Paper trading (live data, simulated execution):**

```bash
python scripts/run_strategy.py --strategy copy_trading --mode paper
python scripts/run_strategy.py --strategy market_making --mode paper
python scripts/run_strategy.py --strategy alt_data --mode paper
```

**Historical backtest** (requires a historical data file):

```bash
python scripts/run_strategy.py --strategy copy_trading --mode historical --data-path ./data/historical_data.json
```

For more detail on each strategy and what to expect, see [GUIDES.md](GUIDES.md).

---

## Quick reference

| Step | Action |
|------|--------|
| 1 | Clone or `cd` into `apex_prediction_markets` |
| 2 | Create venv: `python -m venv venv` → activate with `source venv/bin/activate` (or Windows equivalent) |
| 3 | `pip install -r requirements.txt` |
| 4 | `cp .env.example .env` → edit `.env` and add at least `KALSHI_API_KEY` and `KALSHI_API_SECRET` |
| 5 | `mkdir -p data logs` |
| 6 | `python scripts/run_strategy.py --strategy <name> --mode paper` (from project root) |
