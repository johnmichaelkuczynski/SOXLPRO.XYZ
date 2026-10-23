"""Timestamped benchmark quotes; provider I/O runs only in the worker."""
import json
import math
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from db import get_conn

SYMBOLS = {"QQQ": "QQQ", "TQQQ": "TQQQ", "TLT": "TLT", "XLU": "XLU",
           "VIX": "^VIX", "SOX": "^SOX", "GUSH": "GUSH", "BTC": "BTC-USD"}
# Schema is applied in development; Publish carries it to production.
SCHEMA = """CREATE TABLE IF NOT EXISTS benchmark_quotes (
symbol TEXT PRIMARY KEY, payload JSONB, requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
checked_at TIMESTAMPTZ, error TEXT)"""


def query(sql, params=(), fetch=False):
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = 1500")
                cur.execute(sql, params)
                return cur.fetchall() if fetch else None
    finally:
        conn.close()


def _read_quotes(custom=None):
    """DB only. Custom symbols subscribe to the worker, never fetch on a request."""
    try:
        if custom and re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,29}", custom):
            query("""INSERT INTO benchmark_quotes(symbol) VALUES (%s)
                ON CONFLICT(symbol) DO UPDATE SET requested_at=now()
                WHERE benchmark_quotes.requested_at < now()-interval '1 hour'""", (custom,))
        rows = query("SELECT symbol,payload,checked_at,error FROM benchmark_quotes", fetch=True)
        return {symbol: {**(payload or {}),
                         "checked_at": checked.isoformat() if checked else None,
                         "error": error} for symbol, payload, checked, error in rows}
    except Exception:
        return None


_cached_quotes = {}
_read_lock = threading.Lock()


def read_quotes(custom=None):
    """Bound database waiting so an outage cannot hold up the chart."""
    if _read_lock.acquire(blocking=False):
        def read():
            global _cached_quotes
            try:
                result = _read_quotes(custom)
                if result is not None:
                    _cached_quotes = result
            finally:
                _read_lock.release()
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(timeout=0.3)
    return _cached_quotes


def valid_quote(price, timestamp, currency, source, unit=None):
    price = float(price)
    timestamp = float(timestamp)
    now = datetime.now(timezone.utc)
    observed = datetime.fromtimestamp(timestamp, timezone.utc)
    if not math.isfinite(price) or price <= 0 or timestamp <= 0 or timestamp > now.timestamp()+60:
        raise ValueError("Invalid quote")
    return {"price": price, "observed_at": observed.isoformat(),
            "currency": currency, "source": source, "unit": unit}


def fetch_quote(symbol):
    import requests
    if symbol in SYMBOLS:
        response = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/" + SYMBOLS[symbol],
            params={"range": "1d", "interval": "1m", "includePrePost": "true"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        meta = result["meta"]
        candidates = [(meta.get("regularMarketTime"), meta.get("regularMarketPrice"))]
        candidates += list(zip(result.get("timestamp") or [],
                               result["indicators"]["quote"][0].get("close") or []))
        candidates = [(t, p) for t, p in candidates if t and p is not None and math.isfinite(float(p)) and float(p)>0]
        timestamp, price = max(candidates, key=lambda pair: pair[0])
        return valid_quote(price, timestamp, meta.get("currency"), "Yahoo Finance",
                           "points" if symbol in ("VIX", "SOX") else None)
    # Custom benchmarks use their existing EODHD symbol, not a guessed Yahoo mapping.
    from data_providers import EODHD_KEY
    response = requests.get("https://eodhd.com/api/real-time/" + symbol,
                            params={"api_token": EODHD_KEY, "fmt": "json"}, timeout=12)
    response.raise_for_status()
    data = response.json()
    return valid_quote(data["close"], data["timestamp"],
                       data.get("currency") or ("USD" if symbol.endswith(".US") else None),
                       "EODHD", "points" if symbol.endswith(".INDX") else None)


def refresh_one(symbol):
    try:
        quote = fetch_quote(symbol)
        query("""INSERT INTO benchmark_quotes(symbol,payload,checked_at)
            VALUES (%s,%s::jsonb,now()) ON CONFLICT(symbol) DO UPDATE
            SET payload=excluded.payload,checked_at=now(),error=NULL""",
              (symbol, json.dumps(quote, allow_nan=False)))
    except Exception as exc:
        # Retain the last observation, but never call a failed check fresh.
        query("""INSERT INTO benchmark_quotes(symbol,checked_at,error)
            VALUES (%s,now(),%s) ON CONFLICT(symbol) DO UPDATE
            SET checked_at=now(),error=excluded.error""", (symbol, type(exc).__name__))


def run():
    while True:
        started = time.monotonic()
        try:
            custom = query("SELECT symbol FROM benchmark_quotes WHERE requested_at > now()-interval '1 day'", fetch=True)
            symbols = sorted(set(SYMBOLS) | {row[0] for row in custom})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(refresh_one, symbols))
        except Exception as exc:
            print("Benchmark quote worker:", type(exc).__name__, flush=True)
        time.sleep(max(1, 60-(time.monotonic()-started)))


if __name__ == "__main__":
    run()
