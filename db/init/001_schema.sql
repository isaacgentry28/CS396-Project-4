CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    ts TIMESTAMPZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION ,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT NOT NULL,
    PRIMARY KEY (symbol, ts)
);

CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts ON prices(symbol, ts DESC);

CREATE TABLE IF NOT EXISTS fundamentals (
    symbol TEXT PRIMARY KEY,
    pe_ratio DOUBLE PRECISION,
    market_cap BIGINT,
    fifty_two_week_high DOUBLE PRECISION,
    updated_at TIMESTAMPZ NOT NULL DEFAULT NOW()
);