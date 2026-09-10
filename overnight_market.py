"""Extended-hours observations, kept independent of the drawing component."""

from datetime import datetime, timezone
import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

ET = "America/New_York"
LOGGER = logging.getLogger(__name__)


def clean_prices(frame):
    if frame is None or frame.empty or "Close" not in frame:
        return pd.DataFrame(columns=["Close"])
    result = frame.copy()
    index = pd.DatetimeIndex(result.index)
    if index.tz is None:
        raise ValueError("Intraday timestamps have no timezone.")
    result.index = index.tz_convert(ET)
    result["Close"] = pd.to_numeric(result["Close"], errors="coerce")
    result = result[np.isfinite(result["Close"]) & (result["Close"] > 0)]
    return result[~result.index.duplicated(keep="last")].sort_index()


def build_overnight_rows(intraday, daily, periods):
    """Use exchange-session metadata, including early closes, not wall-clock guesses."""
    bars = clean_prices(intraday)
    closes = clean_prices(daily)
    if bars.empty or closes.empty:
        return pd.DataFrame()
    if not isinstance(periods, pd.DataFrame) or not {
        "pre_start", "start", "end", "post_end"
    }.issubset(periods.columns):
        raise ValueError("Provider session schedule unavailable.")
    daily_closes = {timestamp.date(): float(row.Close) for timestamp, row in closes.iterrows()}
    rows = []
    for _, session in periods.iterrows():
        start, end = pd.Timestamp(session["start"]), pd.Timestamp(session["end"])
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Provider session schedule has no timezone.")
        start, end = start.tz_convert(ET), end.tz_convert(ET)
        for label, lower, upper in (
            ("Pre-market", session["pre_start"], start),
            ("After-hours", end, session["post_end"]),
        ):
            if pd.isna(lower) or pd.isna(upper):
                continue
            eligible_dates = [
                date for date in daily_closes
                if date < start.date() or (label == "After-hours" and date == start.date())
            ]
            if not eligible_dates:
                continue
            baseline_date = max(eligible_dates)
            # Never substitute an older close for a missing same-day after-hours close.
            if label == "After-hours" and baseline_date != start.date():
                continue
            baseline = daily_closes[baseline_date]
            for timestamp, bar in bars[(bars.index >= lower) & (bars.index < upper)].iterrows():
                price = float(bar.Close)
                rows.append({
                    "time": timestamp, "price": price, "session": label,
                    "baseline_date": baseline_date.isoformat(), "baseline": baseline,
                    "change": price - baseline, "change_pct": (price / baseline - 1) * 100,
                })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates("time").sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=55, show_spinner=False)
def fetch_overnight_market():
    checked = datetime.now(timezone.utc)
    try:
        ticker = yf.Ticker("SOXL")
        bars = ticker.history(period="5d", interval="5m", prepost=True, auto_adjust=False,
                              timeout=15)
        periods = ticker.get_history_metadata().get("tradingPeriods")
        daily = yf.Ticker("SOXL").history(period="1mo", interval="1d", auto_adjust=False,
                                          timeout=15)
        rows = build_overnight_rows(bars, daily, periods)
        if rows.empty:
            return {"rows": rows, "checked": checked,
                    "error": "No extended-hours prices were returned. Regular-session prices have not been substituted."}
        return {"rows": rows, "checked": checked, "error": None}
    except Exception as exc:
        LOGGER.warning("SOXL extended-hours fetch failed (%s)", type(exc).__name__)
        return {"rows": pd.DataFrame(), "checked": checked,
                "error": "Extended-hours data is temporarily unavailable. The next refresh will retry."}


def time_label(value):
    return pd.Timestamp(value).tz_convert(ET).strftime("%b %d, %Y %I:%M %p %Z")


def overnight_chart(rows):
    figure = go.Figure()
    # Separate segments avoid inventing trading between the evening and morning.
    for label, color in (("After-hours", "#8b5cf6"), ("Pre-market", "#0ea5e9")):
        segment = rows[rows.session == label]
        if segment.empty:
            continue
        figure.add_trace(go.Scatter(
            x=segment.time.dt.strftime("%Y-%m-%d %H:%M"), y=segment.price,
            mode="lines+markers", name=label, line={"color": color},
            marker={"size": 4},
            hovertemplate=label + "<br>%{x} ET<br>$%{y:.4f}<extra></extra>",
        ))
    figure.add_hline(y=float(rows.iloc[0].baseline), line_dash="dot",
                    annotation_text="Regular-session close", annotation_position="top left")
    figure.update_layout(
        height=290, margin={"l": 10, "r": 10, "t": 25, "b": 15},
        yaxis={"title": "SOXL price ($)", "tickprefix": "$"},
        xaxis={"title": "New York time", "type": "date"},
        legend={"orientation": "h"}, uirevision=str(rows.iloc[0].baseline_date),
    )
    return figure


@st.fragment(run_every="60s")
def render_overnight_market():
    with st.container(border=True):
        st.subheader("SOXL Overnight · After-hours & Pre-market")
        st.caption("Automatic refresh every 60 seconds while this page is open. "
                   "Source: Yahoo Finance · 5-minute price bars, which may be delayed. "
                   "Not a real-time quote or a continuous 24-hour feed.")
        if st.button("Refresh overnight prices", key="refresh_overnight"):
            fetch_overnight_market.clear()
        payload = fetch_overnight_market()
        st.caption("Feed last checked: " + time_label(payload["checked"]))
        if payload["error"]:
            st.warning(payload["error"])
            return

        rows = payload["rows"]
        nights = sorted(rows.baseline_date.unique(), reverse=True)
        choice = st.selectbox(
            "Overnight session", ["Latest available"] + nights, key="overnight_session",
            format_func=lambda value: value if value == "Latest available" else "After the " + value + " close",
            help="An overnight session combines after-hours trading after one close with the next pre-market session.",
        )
        selected = nights[0] if choice == "Latest available" else choice
        night = rows[rows.baseline_date == selected]
        if night.empty:
            st.info("That session is no longer in the feed. Choose Latest available.")
            return
        latest = night.iloc[-1]
        st.write(f"Latest available {latest.session.lower()} price: ${latest.price:,.4f} · "
                 f"{latest.change_pct:+.2f}% from the {selected} close")
        col_close, col_move, col_range = st.columns(3)
        col_close.metric("Regular-session close", f"${latest.baseline:,.2f}")
        col_move.metric("Overnight move", f"${latest.change:+,.4f}", f"{latest.change_pct:+.2f}%")
        col_range.metric("Observed 5-minute closing range",
                         f"${night.price.min():,.2f} – ${night.price.max():,.2f}")
        st.caption("Latest price bar starts: " + time_label(latest.time) +
                   ". Bar timestamps are not trade-by-trade quote timestamps.")
        age_minutes = (pd.Timestamp.now(tz=ET) - latest.time).total_seconds() / 60
        if age_minutes > 15:
            st.info("Historical session data: the latest available price bar is more than 15 minutes old. "
                    "The extended-hours session may be closed, or the feed may be delayed.")
        for column, label in zip(st.columns(2), ("After-hours", "Pre-market")):
            segment = night[night.session == label]
            if segment.empty:
                column.metric(label, "No data yet")
            else:
                last = segment.iloc[-1]
                column.metric(label + " · latest bar", f"${last.price:,.4f}", f"{last.change_pct:+.2f}% vs close")
                column.caption(time_label(last.time))
        st.plotly_chart(overnight_chart(night), width="stretch", key="overnight_price_chart")
        st.caption("Coverage follows the provider's exchange-session schedule (normally 4–9:30 a.m. "
                   "and 4–8 p.m. New York time). No 8 p.m.–4 a.m. trading coverage. "
                   "A missing segment means no data was returned, not zero price movement. "
                   "Extended-hours prices can differ from executable prices because of low liquidity and wider spreads.")
        with st.expander("Price history & data details"):
            evidence = night.copy()
            evidence["time"] = evidence.time.map(time_label)
            st.dataframe(evidence.rename(columns={
                "time": "Bar start (New York)", "price": "Price ($)", "session": "Session",
                "baseline_date": "Close date", "baseline": "Regular close ($)",
                "change": "Change ($)", "change_pct": "Change (%)",
            }), hide_index=True, width="stretch")
            st.download_button("Download overnight prices (CSV)", evidence.to_csv(index=False),
                               file_name=f"SOXL-overnight-{selected}.csv", mime="text/csv",
                               key="download_overnight")