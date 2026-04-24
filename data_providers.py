import os
import requests
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

EODHD_KEY = os.environ.get("EODHD_API_KEY", "")
POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")

EQUITY_MAX_YEARS = 16
OPTIONS_MAX_YEARS = 4


@st.cache_data(ttl=86400, show_spinner=False)
def get_equity_history(symbol="SOXL", years=EQUITY_MAX_YEARS):
    end = datetime.now().date()
    start = end - timedelta(days=int(years * 365 + 30))
    url = (f"https://eodhd.com/api/eod/{symbol}.US"
           f"?api_token={EODHD_KEY}&fmt=json"
           f"&from={start.isoformat()}&to={end.isoformat()}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(columns={
        "open": "open", "high": "high", "low": "low",
        "close": "close", "adjusted_close": "adj_close", "volume": "volume",
    })
    keep = [c for c in ["open", "high", "low", "close", "adj_close", "volume"] if c in df.columns]
    df = df[keep].astype(float)
    df["ret"] = df["adj_close"].pct_change()
    df["log_ret"] = np.log(df["adj_close"] / df["adj_close"].shift(1))
    return df


@st.cache_data(ttl=86400, show_spinner=False)
def get_options_snapshot(symbol="SOXL", limit=250):
    """Current options chain snapshot from Polygon. Returns DataFrame of contracts."""
    url = f"https://api.polygon.io/v3/snapshot/options/{symbol}?apiKey={POLYGON_KEY}&limit={limit}"
    rows = []
    while url:
        r = requests.get(url, timeout=30)
        if not r.ok:
            break
        j = r.json()
        for item in j.get("results", []):
            details = item.get("details", {}) or {}
            day = item.get("day", {}) or {}
            greeks = item.get("greeks", {}) or {}
            quote = item.get("last_quote", {}) or {}
            rows.append({
                "ticker": details.get("ticker"),
                "kind": details.get("contract_type"),
                "strike": details.get("strike_price"),
                "exp_date": details.get("expiration_date"),
                "iv": item.get("implied_volatility"),
                "delta": greeks.get("delta"),
                "open_interest": item.get("open_interest"),
                "volume": day.get("volume"),
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
            })
        nxt = j.get("next_url")
        url = f"{nxt}&apiKey={POLYGON_KEY}" if nxt else None
        if len(rows) > 5000:
            break
    return pd.DataFrame(rows)


@st.cache_data(ttl=86400, show_spinner=False)
def get_option_history(option_ticker, from_date, to_date):
    """Per-contract historical daily aggregates."""
    url = (f"https://api.polygon.io/v2/aggs/ticker/{option_ticker}"
           f"/range/1/day/{from_date}/{to_date}?apiKey={POLYGON_KEY}&limit=5000")
    r = requests.get(url, timeout=30)
    if not r.ok:
        return pd.DataFrame()
    j = r.json()
    res = j.get("results") or []
    if not res:
        return pd.DataFrame()
    df = pd.DataFrame(res)
    df["date"] = pd.to_datetime(df["t"], unit="ms")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                            "c": "close", "v": "volume", "vw": "vwap"})
    return df.set_index("date")[["open", "high", "low", "close", "volume", "vwap"]]


def options_max_start_date():
    return (datetime.now().date() - timedelta(days=OPTIONS_MAX_YEARS * 365)).isoformat()


def equity_max_start_date():
    return (datetime.now().date() - timedelta(days=EQUITY_MAX_YEARS * 365)).isoformat()
