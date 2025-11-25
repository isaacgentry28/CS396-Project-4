import os
import datetime as dt
import asyncio
import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

# -------- Config --------

TICKERS: List[str] = [
    t.strip().upper()
    for t in os.getenv("TICKERS", "AAPL,MSFT,GOOGL").split(",")
    if t.strip()
]

PRICE_POINTS = int(os.getenv("ANALYSIS_PRICE_POINTS", "120"))
SMA_WINDOW = int(os.getenv("ANALYSIS_SMA_WINDOW", "20"))
WS_REFRESH_SECONDS = int(os.getenv("WS_REFRESH_SECONDS", "10"))

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
app = FastAPI(title="Analysis & Visualization Service")
templates = Jinja2Templates(directory="templates")

# -------- Data helpers --------

def fetch_available_symbols() -> List[str]:
    sql = text("SELECT DISTINCT symbol FROM prices ORDER BY symbol")
    with engine.begin() as conn:
        rows = conn.execute(sql).scalars().all()
    if rows:
        return rows
    return TICKERS


def fetch_price_history(symbol: str, limit: int) -> list[dict]:
    sql = text(
        """
        SELECT ts, open, high, low, close, volume
        FROM prices
        WHERE symbol = :symbol
        ORDER BY ts DESC
        LIMIT :limit
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(sql, {"symbol": symbol, "limit": limit}).all()

    history = [
        {
            "ts": row.ts,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        for row in rows
    ]
    # reverse so chart goes oldest -> newest
    return list(reversed(history))


def fetch_fundamentals(symbol: str) -> Optional[dict]:
    sql = text(
        """
        SELECT symbol, pe_ratio, market_cap, fifty_two_week_high, updated_at
        FROM fundamentals
        WHERE symbol = :symbol
        """
    )
    with engine.begin() as conn:
        row = conn.execute(sql, {"symbol": symbol}).mappings().first()
    return dict(row) if row else None


def compute_sma(values: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("SMA window must be positive")
    sma: List[Optional[float]] = []
    running_sum = 0.0
    queue: List[float] = []
    for value in values:
        queue.append(value)
        running_sum += value
        if len(queue) < window:
            sma.append(None)
            continue
        if len(queue) > window:
            running_sum -= queue.pop(0)
        sma.append(running_sum / window)
    return sma


# -------- Routes --------

def build_summary_payload(selected: str) -> dict:
    prices = fetch_price_history(selected, PRICE_POINTS)
    closes = [row["close"] for row in prices]
    sma_values = compute_sma(closes, SMA_WINDOW) if closes else []
    latest_ts = prices[-1]["ts"] if prices else None
    freshness_minutes = None
    if latest_ts:
        freshness_minutes = (dt.datetime.now(dt.timezone.utc) - latest_ts).total_seconds() / 60
    fundamentals = fetch_fundamentals(selected)
    fundamentals_iso = None
    if fundamentals:
        fundamentals_iso = fundamentals.copy()
        if fundamentals_iso.get("updated_at"):
            fundamentals_iso["updated_at"] = fundamentals_iso["updated_at"].isoformat()

    return {
        "symbol": selected,
        "prices": [
            {**row, "ts": row["ts"].isoformat()}
            for row in prices
        ],
        "sma": sma_values,
        "fundamentals": fundamentals_iso,
        "price_freshness_minutes": freshness_minutes if prices else None,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, symbol: Optional[str] = None):
    symbols = fetch_available_symbols()
    if not symbols:
        raise HTTPException(status_code=503, detail="No tickers available. Populate price data first.")

    selected = (symbol or symbols[0]).upper()
    if selected not in symbols:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{selected}'")

    prices = fetch_price_history(selected, PRICE_POINTS)
    closes = [row["close"] for row in prices]
    sma_values = compute_sma(closes, SMA_WINDOW) if closes else []
    labels = [row["ts"].strftime("%Y-%m-%d %H:%M") for row in prices]
    latest_ts = prices[-1]["ts"] if prices else None
    fundamentals = fetch_fundamentals(selected)
    fundamentals_age = None
    if fundamentals and fundamentals.get("updated_at"):
        fundamentals_age = (dt.datetime.now(dt.timezone.utc) - fundamentals["updated_at"]).total_seconds() / 60

    chart_payload = json.dumps(
        {
            "labels": labels,
            "prices": closes,
            "sma": [round(v, 4) if v is not None else None for v in sma_values],
        }
    )

    freshness_minutes = None
    if latest_ts:
        freshness_minutes = (dt.datetime.now(dt.timezone.utc) - latest_ts).total_seconds() / 60

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "symbols": symbols,
            "selected": selected,
            "chart_payload": chart_payload,
            "latest_ts": latest_ts,
            "freshness_minutes": freshness_minutes,
            "fundamentals": fundamentals,
            "fundamentals_age": fundamentals_age,
            "sma_window": SMA_WINDOW,
            "price_points": PRICE_POINTS,
        },
    )


@app.get("/api/summary")
async def api_summary(symbol: Optional[str] = None):
    symbols = fetch_available_symbols()
    if not symbols:
        raise HTTPException(status_code=503, detail="No tickers available")

    selected = (symbol or symbols[0]).upper()
    if selected not in symbols:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{selected}'")

    prices = fetch_price_history(selected, PRICE_POINTS)
    closes = [row["close"] for row in prices]
    sma_values = compute_sma(closes, SMA_WINDOW) if closes else []
    latest_ts = prices[-1]["ts"] if prices else None
    freshness_minutes = None
    if latest_ts:
        freshness_minutes = (dt.datetime.now(dt.timezone.utc) - latest_ts).total_seconds() / 60
    fundamentals = fetch_fundamentals(selected)
    if fundamentals and fundamentals.get("updated_at"):
        fundamentals["updated_at"] = fundamentals["updated_at"].isoformat()

    return {
        "symbol": selected,
        "prices": [
            {
                **row,
                "ts": row["ts"].isoformat(),
            }
            for row in prices
        ],
        "sma": sma_values,
        "fundamentals": fundamentals,
        "price_freshness_minutes": freshness_minutes if prices else None,
    }


@app.websocket("/ws")
async def websocket_summary(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            symbols = fetch_available_symbols()
            if not symbols:
                await asyncio.sleep(WS_REFRESH_SECONDS)
                continue

            # Read the symbol from query params (e.g., /ws?symbol=MSFT); fall back to the first known symbol.
            symbol = websocket.query_params.get("symbol")
            selected = (symbol or symbols[0]).upper()
            if selected not in symbols:
                selected = symbols[0]

            payload = build_summary_payload(selected)
            await websocket.send_json(payload)
            await asyncio.sleep(WS_REFRESH_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        # On unexpected error, close the socket to avoid dangling connections.
        await websocket.close(code=1011, reason=str(exc))
        return


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tickers_configured": TICKERS,
        "price_points": PRICE_POINTS,
        "sma_window": SMA_WINDOW,
    }
