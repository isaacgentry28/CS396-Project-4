# Real-Time Stock Analysis Pipeline

This project implements the CS396 Project 4 requirements: a three-service Dockerized pipeline that gathers real-time prices, collects fundamental metrics, fuses them together, and renders an interactive dashboard. Everything runs locally via Docker Compose, backed by Postgres for shared storage.

## Architecture Overview

- **Price Polling Service (`services/price`)** – FastAPI app that hits Alpha Vantage’s intraday API for each configured ticker at a fixed cadence. Data is normalized and bulk inserted into the `prices` table.
- **Fundamental Data Service (`services/fundamentals`)** – FastAPI app calling Alpha Vantage’s `OVERVIEW` endpoint hourly (configurable). Each response is upserted into the `fundamentals` table so the latest P/E, market cap, etc. are always available.
- **Analysis & Visualization Service (`services/analysis`)** – Reads both tables, computes a 20-period (configurable) Simple Moving Average, exposes a JSON API (`/api/summary`) and a responsive Chart.js dashboard (`/`). The UI highlights data freshness so users know whether the “< 15 minute” requirement is met.
- **Postgres + Adminer** – Shared database plus a lightweight UI so you can inspect tables during development.

**Data flow**
1. Price service polls Alpha Vantage (5 min cadence), throttling between requests to stay inside rate limits.
2. Fundamental service polls Alpha Vantage `OVERVIEW` (1 hour cadence) with similar cooldown/backoff.
3. Both services write into Postgres via SQLAlchemy using `INSERT ... ON CONFLICT` so duplicates are ignored/updated.
4. Analysis service reads from Postgres when a user hits the dashboard/API, fuses price/fundamental data, and calculates SMA values on the fly.

## Database Schemas

`prices`:
| column | type | notes |
| --- | --- | --- |
| `symbol` | text | uppercase ticker |
| `ts` | timestamptz | datapoint timestamp; (symbol, ts) primary key |
| `open/high/low/close` | double precision | OHLC values |
| `volume` | bigint | trade volume |

`fundamentals`:
| column | type | notes |
| --- | --- | --- |
| `symbol` | text PK | ticker |
| `pe_ratio` | double precision | Alpha Vantage P/E |
| `market_cap` | bigint | market capitalization |
| `fifty_two_week_high` | double precision | 52-week high |
| `updated_at` | timestamptz | auto-updated on upsert |

## Getting Started

1. **Get an Alpha Vantage API key**: https://www.alphavantage.co/support/#api-key.
2. **Configure `.env`** – replace `ALPHA_VANTAGE_KEY=PUT_YOUR_REAL_KEY_HERE` with your key. Adjust tickers/intervals if desired (see next section).
3. **Build & run**:
   ```bash
   docker compose up --build
   ```
   - Price service → http://localhost:8001/health  
   - Fundamentals service → http://localhost:8002/health  
   - Analysis dashboard → http://localhost:8003/  
   - Adminer → http://localhost:8081/ (System: PostgreSQL, Server: `db`, User: `stocks_user`, Pass: `stocks_pass`, DB: `stocks`)
4. **Stop**: `Ctrl+C` in the Compose terminal or `docker compose down`.

## Configuration (`.env`)

| Variable | Default | Used By | Description |
| --- | --- | --- | --- |
| `POSTGRES_*` | see file | DB + all services | Connection details |
| `ALPHA_VANTAGE_KEY` | (required) | price, fundamentals | API key |
| `TICKERS` | `AAPL,MSFT,GOOGL` | price, fundamentals, analysis | Comma-separated tickers |
| `PRICE_INTERVAL` | `5min` | price | Alpha Vantage intraday interval |
| `POLL_SECONDS` | `300` | price | How often to fetch prices |
| `PRICE_API_COOLDOWN_SECONDS` | `15` | price | Delay between ticker API calls |
| `PRICE_RATE_LIMIT_BACKOFF_SECONDS` | `60` | price | Extra wait when Alpha Vantage rate-limits |
| `FUNDAMENTAL_REFRESH_SECONDS` | `3600` | fundamentals | How often to refresh fundamentals |
| `FUNDAMENTAL_API_COOLDOWN_SECONDS` | `15` | fundamentals | Delay between ticker overview calls |
| `FUNDAMENTAL_RATE_LIMIT_BACKOFF_SECONDS` | `60` | fundamentals | Wait when rate-limited |
| `ANALYSIS_PRICE_POINTS` | `120` | analysis | Number of candles plotted/served |
| `ANALYSIS_SMA_WINDOW` | `20` | analysis | SMA period used in dashboard/API |

Tweak these values to change cadence, tickers, or analytic behavior. The cooldown/backoff settings keep the system compliant with free-tier API limits.

## Dashboard & APIs

- **Dashboard (`/`)**: Select a ticker to see price vs. SMA plus fundamentals. A warning banner appears if price data is older than 15 minutes or fundamentals are stale (>60 minutes).
- **JSON API (`/api/summary?symbol=XYZ`)**: Returns the latest prices (with ISO timestamps), SMA array, fundamentals snapshot, and freshness metadata. Suitable for feeding other tools.
- **Health endpoints** on every service enumerate runtime configuration and help Compose health checks.

## Resilience & Error Handling

- Both polling services gracefully handle HTTP errors, log API failures, and keep looping instead of crashing.
- Cooldown/backoff values prevent Alpha Vantage rate-limit errors from cascading; when a `Note`/`Information` response is detected, the service sleeps before retrying.
- Database inserts use `ON CONFLICT` clauses to avoid duplicate exceptions.

## Testing

Lightweight unit tests cover the SMA helper logic that powers the dashboard:
```bash
python -m unittest discover -s services/analysis
```
Run inside the repo root (Python 3.11+ recommended). Add your own tests following the same pattern for additional logic.

## Troubleshooting

- **API rate limits**: Increase cooldown/backoff values or reduce `TICKERS`. Alpha Vantage’s free tier allows 5 calls/minute.
- **Adminer port conflict**: Change the host port mapping in `docker-compose.yml`.
- **No data on dashboard**: Verify the price/fundamental services logs and ensure the API key is correct. Data freshness warnings will tell you if ingestion is behind.

## Next Steps

- Add automated diagram(s) or architecture docs to complement this README if required by your deliverable.
- Deploy to a remote host or add CI/CD as needed.

Happy analyzing!
