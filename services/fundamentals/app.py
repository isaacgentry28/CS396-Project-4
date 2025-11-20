import os
import asyncio
import datetime as dt
from typing import List, Optional

import yfinance as yf
from fastapi import FastAPI
from sqlalchemy import create_engine, text

TICKERS: List[str] = [
    t.strip().upper()
    for t in os.getenv("TICKERS", "AAPL,MSFT,GOOGL").split(",")
    if t.strip()
]

REFRESH_SECONDS = int(os.getenv("FUNDAMENTAL_REFRESH_SECONDS", "3600"))
FUNDAMENTAL_API_COOLDOWN_SECONDS = int(os.getenv("FUNDAMENTAL_API_COOLDOWN_SECONDS", "15"))

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


def _to_float(value):
    if value in (None, "", "None"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value):
    if value in (None, "", "None"):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def upsert_fundamental(symbol: str, payload: dict):
    row = {
        "symbol": symbol,
        "pe_ratio": _to_float(payload.get("pe_ratio")),
        "market_cap": _to_int(payload.get("market_cap")),
        "fifty_two_week_high": _to_float(payload.get("fifty_two_week_high")),
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }

    with engine.begin() as conn:
        conn.execute(UPSERT_SQL, row)


async def fetch_overview(symbol: str) -> Optional[dict]:
    def _fetch():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()
            if not info:
                return None
            return {
                "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            }
        except Exception as exc:
            print(f"[{symbol}] Error fetching fundamentals: {exc}", flush=True)
            return None

    data = await asyncio.to_thread(_fetch)
    if not data:
        print(f"[{symbol}] No fundamentals returned from yfinance", flush=True)
        return None

    return data


async def poll_loop():
    await asyncio.sleep(5)
    print("Starting fundamentals polling loop...", flush=True)

    while True:
        try:
            updated = 0
            for symbol in TICKERS:
                payload = await fetch_overview(symbol)
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
