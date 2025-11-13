import os, asyncio, datetime as dt
import httpx
from fastapi import FastAPI, HTTPException
from typing import List
from sqlalchemy import create_engine, text

ALPHA = os.environ("ALPHA_VANTAGE_KEY")
TICKERS = os.environ("TICKERS", "AAPL,MSFT,GOOGL").split(",")
DB_URL = f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
