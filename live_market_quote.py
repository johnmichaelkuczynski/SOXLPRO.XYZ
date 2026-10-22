"""Polygon last-trade quotes. Errors are data, never an alternate price."""
import os
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

import requests
import streamlit as st

ET = ZoneInfo("America/New_York")
ENDPOINT = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/"


def quote_error(message, now=None):
    now = now or datetime.now(timezone.utc)
    return {"source": "Polygon", "error": str(message), "price": None,
            "checked_at": now.isoformat()}


def parse_polygon_quote(data, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(data, dict):
        return quote_error("Polygon returned an invalid response.", now)
    if data.get("error") or str(data.get("status", "")).upper() in ("ERROR", "NOT_AUTHORIZED"):
        return quote_error(data.get("error") or data.get("message") or data["status"], now)
    ticker = data.get("ticker") or {}
    trade = ticker.get("lastTrade")
    if not isinstance(trade, dict) or not trade:
        return quote_error(data.get("message") or "Polygon returned no lastTrade.", now)
    try:
        price = float(trade["p"])
        # Polygon lastTrade.t is Unix nanoseconds, NOT seconds/milliseconds.
        timestamp = int(trade["t"])
        observed = datetime.fromtimestamp(timestamp / 1_000_000_000, timezone.utc)
        if not isfinite(price) or price <= 0 or timestamp < 1_000_000_000_000_000_000:
            raise ValueError()
        if (observed - now).total_seconds() > 60:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return quote_error("Polygon returned invalid lastTrade.p or lastTrade.t.", now)
    minutes = observed.astimezone(ET).hour * 60 + observed.astimezone(ET).minute
    state, session = (("PRE", "Pre-market") if minutes < 570 else
                      ("REGULAR", "Regular") if minutes < 960 else
                      ("POST", "After-hours"))
    previous = (ticker.get("prevDay") or {}).get("c")
    try:
        previous = float(previous)
        if not isfinite(previous) or previous <= 0:
            previous = None
    except (ValueError, TypeError):
        previous = None
    return {"source": "Polygon", "price": price, "error": None,
            "observed_at": observed.isoformat(),
            "observed_label": observed.astimezone(ET).strftime("%b %d, %Y %I:%M:%S %p ET"),
            "state": state, "session": session, "extended": state != "REGULAR",
            "prev_close": previous, "stale": (now-observed).total_seconds() > 900,
            "checked_at": now.isoformat()}


def fetch_polygon_quote(symbol="SOXL"):
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        return quote_error("POLYGON_API_KEY is not configured.")
    try:
        response = requests.get(ENDPOINT + symbol, params={"apiKey": key}, timeout=10)
        try:
            data = response.json()
        except ValueError:
            return quote_error("Polygon HTTP %s: %s" %
                               (response.status_code, response.text[:1000].replace(key, "[redacted]")))
        if not response.ok:
            detail = data.get("error") or data.get("message") or data.get("status") if isinstance(data, dict) else str(data)
            return quote_error(("Polygon HTTP %s: %s" %
                                (response.status_code, detail or "Request failed")).replace(key, "[redacted]"))
        quote = parse_polygon_quote(data)
        if quote.get("error"):
            quote["error"] = quote["error"].replace(key, "[redacted]")
        return quote
    except requests.RequestException as exc:
        # Request exception strings can contain the URL (and its API key).
        return quote_error("Polygon request failed: " + type(exc).__name__)


def polygon_only(quote):
    """Do not display legacy DB quotes during the first refresh after rollout."""
    if not isinstance(quote, dict) or quote.get("source") != "Polygon":
        return quote_error("Awaiting Polygon last trade; no substitute price is displayed.")
    return quote


@st.cache_data(ttl=50, show_spinner=False)
def fetch_live_quote():
    return fetch_polygon_quote("SOXL")
