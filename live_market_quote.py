"""Timestamped public quotes; an overnight observation is not a continuous feed."""
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import yfinance as yf

ET = ZoneInfo("America/New_York")


def select_quote(yahoo, robinhood, now=None):
    now = now or datetime.now(timezone.utc)
    candidates = []

    def add(price, timestamp, state, source, previous=None):
        try:
            price = float(price)
            if isinstance(timestamp, (float, int)):
                observed = datetime.fromtimestamp(timestamp, timezone.utc)
            elif isinstance(timestamp, str):
                observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                return
            if observed.tzinfo is None or not isfinite(price) or price <= 0:
                return
            if (observed - now).total_seconds() > 60:
                return
            if state is None:
                local = observed.astimezone(ET)
                minutes = local.hour * 60 + local.minute
                state = ("OVERNIGHT" if minutes >= 1200 or minutes < 240 else
                         "PRE" if minutes < 570 else
                         "POST" if minutes >= 960 else "NONREGULAR")
            candidates.append(dict(price=price, observed_at=observed.isoformat(),
                                   state=state, source=source, prev_close=previous,
                                   extended=state != "REGULAR"))
        except (ValueError, TypeError, OverflowError, OSError):
            return

    add(yahoo.get("regularMarketPrice"), yahoo.get("regularMarketTime"),
        "REGULAR", "Yahoo Finance", yahoo.get("regularMarketPreviousClose"))
    add(yahoo.get("preMarketPrice"), yahoo.get("preMarketTime"), "PRE", "Yahoo Finance")
    add(yahoo.get("postMarketPrice"), yahoo.get("postMarketTime"), "POST", "Yahoo Finance")
    add(robinhood.get("last_trade_price"), robinhood.get("venue_last_trade_time"),
        "REGULAR", "Robinhood", robinhood.get("previous_close"))
    add(robinhood.get("last_non_reg_trade_price"),
        robinhood.get("venue_last_non_reg_trade_time"), None, "Robinhood")
    if not candidates:
        return None
    result = max(candidates, key=lambda q: datetime.fromisoformat(q["observed_at"])).copy()
    observed = datetime.fromisoformat(result["observed_at"])
    if result["extended"]:
        regular = [q for q in candidates if not q["extended"]
                   and datetime.fromisoformat(q["observed_at"]) <= observed]
        if regular:
            result["prev_close"] = max(
                regular, key=lambda q: datetime.fromisoformat(q["observed_at"]))["price"]
    result["session"] = {"REGULAR": "Regular session", "PRE": "Pre-market",
                         "POST": "After-hours", "OVERNIGHT": "Overnight",
                         "NONREGULAR": "Non-regular session"}[result["state"]]
    result["stale"] = (now - observed).total_seconds() > 900
    result["observed_label"] = observed.astimezone(ET).strftime("%b %d, %Y %I:%M:%S %p ET")
    result["checked_at"] = now.isoformat()
    return result


@st.cache_data(ttl=50, show_spinner=False)
def fetch_live_quote():
    errors = []
    try:
        yahoo = yf.Ticker("SOXL").info
    except Exception:
        yahoo = {}
        errors.append("Yahoo Finance unavailable")
    try:
        response = requests.get("https://api.robinhood.com/quotes/",
                                params={"symbols": "SOXL"}, timeout=8)
        response.raise_for_status()
        robinhood = response.json()["results"][0] or {}
    except Exception:
        robinhood = {}
        errors.append("Robinhood quote unavailable")
    quote = select_quote(yahoo, robinhood)
    if quote:
        quote["feed_warning"] = "; ".join(errors)
    return quote
