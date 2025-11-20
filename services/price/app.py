import os
import asyncio
import datetime as dt
from typing import List

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, text

# ---------- Config ----------

ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY")
if not ALPHA_KEY:
    raise RuntimeError("Missing ALPHA_VANTAGE_KEY environment variable")

TICKERS: List[str] = [
    t.strip().upper()
    for t in os.getenv("TICKERS", "AAPL,MSFT,GOOGL").split(",")
    if t.strip()
]

INTERVAL = os.getenv("PRICE_INTERVAL", "5min")      # 1min, 5min, 15min, etc.
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))  # how often to poll, default 5 min
PRICE_API_COOLDOWN_SECONDS = int(os.getenv("PRICE_API_COOLDOWN_SECONDS", "15"))
PRICE_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("PRICE_RATE_LIMIT_BACKOFF_SECONDS", "60"))

# Build DB URL from the Postgres env vars docker-compose will give us
POSTGRES_USER = os.getenv("POSTGRES_USER", "stocks_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "stocks_pass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "stocks")

DB_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

engine = create_engine(DB_URL, future=True)

app = FastAPI(title="Price Polling Service")


# ---------- DB helper ----------

def insert_prices(rows: list[dict]):
    """
    rows: list of dicts with keys:
      symbol, ts, open, high, low, close, volume
    """
    if not rows:
        return

    sql = text(
        """
        INSERT INTO prices (symbol, ts, open, high, low, close, volume)
        VALUES (:symbol, :ts, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol, ts) DO NOTHING;
        """
    )

    with engine.begin() as conn:
        conn.execute(sql, rows)


# ---------- API helper ----------

async def fetch_intraday_for_symbol(client: httpx.AsyncClient, symbol: str) -> list[dict]:
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": INTERVAL,
        "apikey": ALPHA_KEY,
        "outputsize": "compact",
    }

    resp = await client.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Handle rate limiting / errors
    if "Note" in data or "Information" in data:
        msg = data.get("Note") or data.get("Information")
        print(f"[{symbol}] API rate/usage notice: {msg}", flush=True)
        await asyncio.sleep(PRICE_RATE_LIMIT_BACKOFF_SECONDS)
        return []
    if "Error Message" in data:
        print(f"[{symbol}] API error: {data['Error Message']}", flush=True)
        return []

    key = f"Time Series ({INTERVAL})"
    if key not in data:
        print(f"[{symbol}] Unexpected response keys: {list(data.keys())}", flush=True)
        return []

    ts_block = data[key]

    rows: list[dict] = []
    for ts_str, values in ts_block.items():
        try:
            ts = dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )
            rows.append(
                {
                    "symbol": symbol,
                    "ts": ts,
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": int(float(values["5. volume"])),
                }
            )
        except Exception as e:
            print(f"[{symbol}] Skipping bad datapoint {ts_str}: {e}", flush=True)
            continue

    print(f"[{symbol}] fetched {len(rows)} datapoints", flush=True)
    return rows


# ---------- Background polling loop ----------

async def poll_loop():
    # Small delay so Postgres can start up
    await asyncio.sleep(5)

    print("Starting price polling loop...", flush=True)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                all_rows: list[dict] = []
                for symbol in TICKERS:
                    rows = await fetch_intraday_for_symbol(client, symbol)
                    all_rows.extend(rows)
                    if symbol != TICKERS[-1]:
                        await asyncio.sleep(PRICE_API_COOLDOWN_SECONDS)

                insert_prices(all_rows)
                print(f"Inserted {len(all_rows)} rows total", flush=True)

            except Exception as e:
                # Don't crash the container; log and keep going
                print(f"Error in polling loop: {e}", flush=True)

            print(f"Sleeping {POLL_SECONDS} seconds...", flush=True)
            await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def on_startup():
    # fire-and-forget polling task
    asyncio.create_task(poll_loop())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tickers": TICKERS,
        "interval": INTERVAL,
    }
