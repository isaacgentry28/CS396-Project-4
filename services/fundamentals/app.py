import os
import asyncio
import datetime as dt
from typing import List, Optional

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, text

ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY")
if not ALPHA_KEY:
    raise RuntimeError("Missing ALPHA_VANTAGE_KEY environment variable")

TICKERS: List[str] = [
    t.strip().upper()
    for t in os.getenv("TICKERS", "AAPL,MSFT,GOOGL").split(",")
    if t.strip()
]

REFRESH_SECONDS = int(os.getenv("FUNDAMENTAL_REFRESH_SECONDS", "3600"))
FUNDAMENTAL_API_COOLDOWN_SECONDS = int(os.getenv("FUNDAMENTAL_API_COOLDOWN_SECONDS", "15"))
FUNDAMENTAL_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("FUNDAMENTAL_RATE_LIMIT_BACKOFF_SECONDS", "60"))

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
app = FastAPI(title="Fundamental Data Service")


UPSERT_SQL = text(
    """
    INSERT INTO fundamentals (symbol, pe_ratio, market_cap, fifty_two_week_high, updated_at)
    VALUES (:symbol, :pe_ratio, :market_cap, :fifty_two_week_high, :updated_at)
    ON CONFLICT (symbol) DO UPDATE SET
        pe_ratio = EXCLUDED.pe_ratio,
        market_cap = EXCLUDED.market_cap,
        fifty_two_week_high = EXCLUDED.fifty_two_week_high,
        updated_at = EXCLUDED.updated_at;
    """
)


def _to_float(value: Optional[str]) -> Optional[float]:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: Optional[str]) -> Optional[int]:
    if value in (None, "", "None"):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def upsert_fundamental(symbol: str, payload: dict):
    row = {
        "symbol": symbol,
        "pe_ratio": _to_float(payload.get("PERatio")),
        "market_cap": _to_int(payload.get("MarketCapitalization")),
        "fifty_two_week_high": _to_float(payload.get("52WeekHigh")),
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }

    with engine.begin() as conn:
        conn.execute(UPSERT_SQL, row)


async def fetch_overview(client: httpx.AsyncClient, symbol: str) -> Optional[dict]:
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": ALPHA_KEY,
    }

    resp = await client.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        print(f"[{symbol}] Empty fundamentals response", flush=True)
        return None
    if "Note" in data or "Information" in data:
        msg = data.get("Note") or data.get("Information")
        print(f"[{symbol}] API rate/usage notice: {msg}", flush=True)
        await asyncio.sleep(FUNDAMENTAL_RATE_LIMIT_BACKOFF_SECONDS)
        return None
    if "Error Message" in data:
        print(f"[{symbol}] API error: {data['Error Message']}", flush=True)
        return None
    if "Symbol" not in data:
        print(f"[{symbol}] Unexpected fundamentals payload keys: {list(data.keys())}", flush=True)
        return None

    return data


async def poll_loop():
    await asyncio.sleep(5)
    print("Starting fundamentals polling loop...", flush=True)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                updated = 0
                for symbol in TICKERS:
                    payload = await fetch_overview(client, symbol)
                    if payload:
                        upsert_fundamental(symbol, payload)
                        updated += 1
                    if symbol != TICKERS[-1]:
                        await asyncio.sleep(FUNDAMENTAL_API_COOLDOWN_SECONDS)
                print(f"Updated fundamentals for {updated} symbols", flush=True)
            except Exception as exc:
                print(f"Error in fundamentals polling loop: {exc}", flush=True)

            print(f"Sleeping {REFRESH_SECONDS} seconds...", flush=True)
            await asyncio.sleep(REFRESH_SECONDS)


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(poll_loop())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tickers": TICKERS,
        "refresh_seconds": REFRESH_SECONDS,
    }
