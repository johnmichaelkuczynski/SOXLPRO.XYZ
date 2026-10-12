"""Refresh the existing chart's price trace without rerunning its drawing component."""
import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

from overnight_market import clean_prices, ET
from live_market_quote import fetch_live_quote


def make_market_payload(bars, periods, checked):
    bars = clean_prices(bars)
    if bars.empty:
        raise ValueError("No intraday prices")
    if not isinstance(periods, pd.DataFrame) or not {
        "pre_start", "start", "end", "post_end"
    }.issubset(periods.columns):
        raise ValueError("No session schedule")
    points = []
    for _, day in periods.iterrows():
        for session, start, end in (
            ("Pre-market", day.pre_start, day.start),
            ("Regular session", day.start, day.end),
            ("After-hours", day.end, day.post_end),
        ):
            if pd.isna(start) or pd.isna(end):
                continue
            selected = bars[(bars.index >= start) & (bars.index < end)]
            for timestamp, row in selected.iterrows():
                points.append({
                    # Plotly date axes are wall-clock based: keep ALL intraday
                    # coordinates in New York time, not a mix of UTC and local.
                    "date": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "time": timestamp.isoformat(),
                    "price": float(row.Close),
                    "session": session,
                })
    points.sort(key=lambda point: point["time"])
    if not points:
        raise ValueError("No session prices")
    return {"points": points, "checked": checked, "error": None}


@st.cache_data(ttl=50, show_spinner=False)
def fetch_chart_market_feed():
    checked = datetime.now(timezone.utc).isoformat()
    quote = fetch_live_quote()
    try:
        ticker = yf.Ticker("SOXL")
        bars = ticker.history(period="5d", interval="5m", prepost=True,
                              auto_adjust=True, timeout=15)
        payload = make_market_payload(bars, ticker.get_history_metadata().get("tradingPeriods"), checked)
        payload["quote"] = quote
        return payload
    except Exception:
        return {"points": [], "checked": checked, "quote": quote,
                "error": "Price update unavailable — retaining the last chart prices."}


@st.fragment(run_every="60s")
def update_chart_market_feed():
    # Public market data only. Send directly to the existing chart iframe;
    # replacing/rerunning that iframe would discard the user's prepared view.
    payload = json.dumps(fetch_chart_market_feed()).replace("<", "\\u003c")
    components.html(
        """<script>
        const message = {type: 'soxl:market-update', payload: """ + payload + """};
        for (const frame of window.parent.document.querySelectorAll('iframe')) {
          if (frame.contentWindow !== window) frame.contentWindow.postMessage(message, '*');
        }
        </script>""",
        height=0, scrolling=False,
    )