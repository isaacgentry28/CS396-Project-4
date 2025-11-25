# Real-Time Stock Analysis Pipeline

Three Dockerized FastAPI services plus Postgres form a complete data pipeline: one fetches intraday prices, another pulls fundamentals, and the third fuses both to power an interactive dashboard. All market data comes from Yahoo Finance via the `yfinance` Python library—no API key required.

## Architecture Overview

- **Price Polling Service (`services/price`)** – Downloads near real-time OHLCV candles from Yahoo Finance for each configured ticker (default 5-minute interval) and stores them in the `prices` table.
- **Fundamental Data Service (`services/fundamentals`)** – Fetches company fundamentals (P/E, market cap, 52-week high, etc.) via `yfinance` and upserts them into the `fundamentals` table.
- **Analysis & Visualization Service (`services/analysis`)** – Joins both datasets, computes a configurable Simple Moving Average, serves a JSON API, and renders a Chart.js dashboard that highlights data freshness.
- **Postgres + Adminer** – Central store plus a lightweight SQL UI for inspection.



**Data flow**
1. Price service polls Yahoo Finance every `POLL_SECONDS`, staggering requests per ticker.
2. Fundamental service polls Yahoo Finance on a slower cadence (default hourly).
3. Both services write into Postgres using `INSERT ... ON CONFLICT` safeguards.
4. Analysis service queries Postgres on demand and renders the dashboard/API.

## Database Schemas

`prices`

| column | type | notes |
| --- | --- | --- |
| `symbol` | text | uppercase ticker |
| `ts` | timestamptz | datapoint timestamp; `(symbol, ts)` primary key |
| `open/high/low/close` | double precision | OHLC values |
| `volume` | bigint | trade volume |

`fundamentals`

| column | type | notes |
| --- | --- | --- |
| `symbol` | text PK | ticker |
| `pe_ratio` | double precision | trailing/forward P/E |
| `market_cap` | bigint | market capitalization |
| `fifty_two_week_high` | double precision | 52-week high |
| `updated_at` | timestamptz | auto-updated on upsert |

## Getting Started

1. **Configure `.env`** – set tickers/intervals/cadences (defaults work out of the box).
2. **Launch the stack**:
   ```bash
   docker compose up --build
   ```
   Services listen on:
   - Price service → http://localhost:8001/health  
   - Fundamentals service → http://localhost:8002/health  
   - Analysis dashboard → http://localhost:8003/  
   - Adminer → http://localhost:8081/ (System: PostgreSQL, Server: `db`, User: `stocks_user`, Pass: `stocks_pass`, DB: `stocks`)
3. **Stop**: `Ctrl+C` or `docker compose down`.

## Configuration (`.env`)

| Variable | Default | Used By | Description |
| --- | --- | --- | --- |
| `POSTGRES_*` | see file | DB + all services | Connection details |
| `TICKERS` | `AAPL,MSFT,GOOGL` | price, fundamentals, analysis | Comma-separated tickers |
| `PRICE_INTERVAL` | `5m` | price | yfinance interval (`1m`, `5m`, `15m`, `1h`, `1d`, …) |
| `PRICE_HISTORY_PERIOD` | `1d` | price | Lookback period per poll (`1d`, `5d`, `1mo`, …) |
| `POLL_SECONDS` | `300` | price | How often to refetch prices |
| `PRICE_API_COOLDOWN_SECONDS` | `5` | price | Delay between ticker downloads |
| `FUNDAMENTAL_REFRESH_SECONDS` | `3600` | fundamentals | How often to refresh fundamentals |
| `FUNDAMENTAL_API_COOLDOWN_SECONDS` | `15` | fundamentals | Delay between ticker fundamentals calls |
| `ANALYSIS_PRICE_POINTS` | `120` | analysis | Number of candles plotted/served |
| `ANALYSIS_SMA_WINDOW` | `20` | analysis | SMA period used in dashboard/API |

Adjust these knobs to change cadence or analytical behavior. Yahoo Finance is unauthenticated, but please stay respectful of their infrastructure.

## Dashboard & APIs

- **Dashboard (`/`)**: Select a ticker to see Close price vs. SMA along with fundamentals. Warning banners appear if price data is older than 15 minutes or fundamentals are older than 60 minutes.
- **JSON API (`/api/summary?symbol=XYZ`)**: Returns prices (with ISO timestamps), SMA array, fundamentals snapshot, plus freshness metadata.
- **Health endpoints**: `http://localhost:8001/health`, `http://localhost:8002/health`, `http://localhost:8003/health`.

## Resilience & Error Handling

- `yfinance` calls run inside `asyncio.to_thread`, so slow network requests do not block the event loop.
- Cooldown delays stagger per-ticker calls to avoid hammering Yahoo.
- Any exception during polling is logged and the loop keeps running.
- Database writes rely on `ON CONFLICT` to deduplicate incoming candles/fundamentals.

## Testing

Run unit tests (currently covering SMA calculations) with:

```bash
python -m unittest discover -s services/analysis
```

Add additional tests for new business logic as needed.

## Troubleshooting

- **Empty dashboard**: Check price/fundamental logs. For testing without live data, you can insert fixture rows into Postgres via Adminer.
- **Invalid interval/period combo**: Yahoo Finance only serves certain combinations (e.g., `1m` requires `1d` or `5d`). Adjust `PRICE_INTERVAL` and `PRICE_HISTORY_PERIOD` accordingly.
- **Port conflicts**: Edit the `ports` section in `docker-compose.yml` if a service fails to bind.

Happy analyzing!
