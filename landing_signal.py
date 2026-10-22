from collections import OrderedDict
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from signal_config import (
    DEFAULT_THRESHOLDS,
    OLD_THRESHOLDS,
    RATING_THRESHOLDS,
    SIGNAL_COLORS,
    SIGNAL_DISPLAY_LABELS,
    rating_bands,
    rating_threshold_description,
)


TIMEFRAMES = OrderedDict([
    ("1 Week", 5),
    ("1 Month", 21),
    ("3 Months", 63),
    ("6 Months", 126),
    ("1 Year", 252),
    ("2 Years", 504),
    ("3 Years", 756),
    ("5 Years", 1260),
    ("10 Years", 2520),
    ("All Time", None),
])

# Long periods intentionally carry more influence than short-term noise.
TIMEFRAME_WEIGHTS = {
    "1 Week": 1.0,
    "1 Month": 1.0,
    "3 Months": 1.25,
    "6 Months": 1.25,
    "1 Year": 1.5,
    "2 Years": 1.5,
    "3 Years": 1.75,
    "5 Years": 1.75,
    "10 Years": 2.0,
    "All Time": 2.0,
}

def display_signal_label(signal):
    return SIGNAL_DISPLAY_LABELS.get(signal, signal)


def completed_close_history(price_data, now=None):
    """Return SOXL closes through the latest completed regular session."""
    if price_data is None or price_data.empty:
        return pd.Series(dtype=float, name="Close")
    column = "Close" if "Close" in price_data.columns else price_data.columns[0]
    closes = pd.to_numeric(price_data[column], errors="coerce").dropna()
    index = pd.to_datetime(closes.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    closes.index = index
    closes = closes[
        ~closes.index.duplicated(keep="last")
    ].sort_index()
    closes = closes[(closes > 0) & (closes.index >= pd.Timestamp("2010-01-01"))]

    eastern_now = now or datetime.now(ZoneInfo("America/New_York"))
    if eastern_now.tzinfo is None:
        eastern_now = eastern_now.replace(tzinfo=ZoneInfo("America/New_York"))
    if (
        not closes.empty
        and closes.index[-1].date() >= eastern_now.date()
        and eastern_now.time() < time(16, 0)
    ):
        closes = closes.iloc[:-1]
    return closes.copy()


def price_range_percentile(closes):
    values = pd.Series(closes).dropna()
    if values.empty:
        return np.nan, np.nan, np.nan, np.nan
    current = float(values.iloc[-1])
    low = float(values.min())
    high = float(values.max())
    if not np.isfinite(low) or not np.isfinite(high):
        return np.nan, current, low, high
    if len(values) < 2 or high <= low:
        return np.nan, current, low, high
    percentile = (current - low) / (high - low) * 100.0
    return float(np.clip(percentile, 0.0, 100.0)), current, low, high


def condition_from_percentile(percentile):
    if not np.isfinite(percentile):
        return "Insufficient history"
    if percentile < 20:
        return "Oversold"
    if percentile > 80:
        return "Overbought"
    return "Neutral"


def signal_from_percentile(percentile, thresholds=DEFAULT_THRESHOLDS):
    if not np.isfinite(percentile):
        return "INSUFFICIENT HISTORY"
    strong_buy, buy, sell, strong_sell = thresholds
    if percentile <= strong_buy:
        return "STRONG BUY"
    if percentile <= buy:
        return "BUY"
    if percentile < sell:
        return "DO NOTHING"
    if percentile < strong_sell:
        return "SELL"
    return "STRONG SELL"


def compute_timeframe_readings(price_data, now=None):
    closes = completed_close_history(price_data, now=now)
    rows = []
    for label, sessions in TIMEFRAMES.items():
        if sessions is None:
            period = closes
        elif len(closes) >= sessions:
            period = closes.iloc[-sessions:]
        else:
            period = pd.Series(dtype=float)
        percentile, current, low, high = price_range_percentile(period)
        rows.append({
            "Timeframe": label,
            "Percentile": percentile,
            "Condition": condition_from_percentile(percentile),
            "Signal": signal_from_percentile(percentile).title(),
            "Current close": current,
            "Period low": low,
            "Period high": high,
            "Sessions": len(period),
        })
    return pd.DataFrame(rows), closes


def composite_signal(readings, weights=None, thresholds=DEFAULT_THRESHOLDS):
    valid = readings[pd.to_numeric(
        readings["Percentile"], errors="coerce"
    ).notna()]
    if valid.empty:
        return {"percentile": np.nan, "signal": "INSUFFICIENT HISTORY"}
    weight_map = weights or TIMEFRAME_WEIGHTS
    weights = np.array([
        weight_map[row["Timeframe"]]
        for _, row in valid.iterrows()
    ])
    percentile = float(np.average(valid["Percentile"], weights=weights))
    return {
        "percentile": percentile,
        "signal": signal_from_percentile(percentile, thresholds),
    }


def _signal_card(percentile, signal, close_date):
    marker = float(np.clip(percentile, 0.0, 100.0))
    color = SIGNAL_COLORS.get(signal, "#64748b")
    display_signal = display_signal_label(signal)
    bands = rating_bands()
    bar_segments = "".join(
        f'<div style="width:{band["width"]:g}%;background:{band["color"]};"></div>'
        for band in bands
    )
    grid_columns = " ".join(f'{band["width"]:g}%' for band in bands)
    band_labels = "".join(f'<span>{band["label"]}</span>' for band in bands)
    return f"""
    <div style="border:1px solid #e2e8f0;border-radius:14px;padding:20px 22px;
                background:#ffffff;margin:8px 0 12px;">
      <div style="font-size:.78rem;color:#64748b;letter-spacing:.09em;
                  font-weight:800;">Long-term signal (6–12 months)</div>
      <div style="font-size:2.25rem;font-weight:850;color:{color};margin:2px 0;">
        {display_signal}
      </div>
      <div style="font-size:.94rem;color:#475569;margin-bottom:14px;">
        Composite historical-range percentile:
        <strong>{percentile:.1f}%</strong> · Close through {close_date}
      </div>
      <div style="position:relative;padding-top:14px;">
        <div style="display:flex;height:20px;border-radius:10px;overflow:hidden;">
          {bar_segments}
        </div>
        <div style="position:absolute;left:calc({marker:.2f}% - 8px);top:4px;
                    width:16px;height:34px;border-radius:5px;background:#111827;
                    border:3px solid white;box-shadow:0 1px 5px rgba(0,0,0,.4);">
        </div>
      </div>
      <div style="display:grid;grid-template-columns:{grid_columns};
                  margin-top:7px;font-size:.68rem;font-weight:750;color:#475569;
                  text-align:center;">
        {band_labels}
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:4px;
                  color:#94a3b8;font-size:.68rem;">
        <span>0% · period lows</span><span>100% · period highs</span>
      </div>
    </div>
    """


def render_landing_signal(price_data, saved=None):
    if saved is None:
        readings, closes = compute_timeframe_readings(price_data)
        result = composite_signal(readings)
    else:
        readings = pd.DataFrame(saved["readings"])
        closes = price_data["Close"].loc[:saved["close_date"]]
        result = saved["composite"]
    if closes.empty or not np.isfinite(result["percentile"]):
        st.warning("The daily SOXL signal is unavailable until price history loads.")
        return

    st.markdown("### SOXL Daily Signal")
    from short_term_signal_ui import render_short_term_signal, render_full_signal_report

    long_term, short_term = st.columns(2)
    with long_term:
        st.markdown(
            _signal_card(
                result["percentile"],
                result["signal"],
                closes.index[-1].strftime("%Y-%m-%d"),
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "Mean-reversion reading for 6–12 months: lower percentiles are closer "
            "to historical lows and produce buy-side signals; higher percentiles "
            "are closer to historical highs and produce sell-side signals. "
            + rating_threshold_description()
        )
    with short_term:
        if saved is None:
            render_short_term_signal(closes)
        else:
            render_short_term_signal(closes, saved=saved)
    render_full_signal_report()
    from signal_scorecard_ui import render_rating_scorecard
    render_rating_scorecard(closes, display_signal_label(result["signal"]))

    st.markdown("#### Multi-timeframe overbought/oversold")
    display = readings.copy()
    display["Percentile"] = display["Percentile"].map(
        lambda value: f"{value:.1f}%" if np.isfinite(value) else "N/A"
    )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_order=["Timeframe", "Percentile", "Condition"],
        column_config={
            "Percentile": st.column_config.TextColumn(
                help="(Current close − period low) ÷ (period high − period low) × 100"
            ),
            "Condition": st.column_config.TextColumn(
                help="Oversold below 20%; Neutral from 20% through 80%; Overbought above 80%."
            ),
        },
    )
    st.caption(
        "Composite weighting increases with the lookback period. Ten-year and "
        "all-time readings each receive twice the weight of the one-week reading. "
        "Updated from the latest completed SOXL daily close."
    )
    with st.expander("Calculation and signal thresholds"):
        st.markdown(
            f"""
For every timeframe:

`(current close − minimum close) ÷ (maximum close − minimum close) × 100`

**Condition labels:** Oversold below 20%; Neutral from 20% through 80%;
Overbought above 80%.

**Long-term signal (6–12 months):** {rating_threshold_description()}

The dashboard uses completed daily closing prices beginning in 2010. It is a
historical mean-reversion indicator, not a guarantee or personalized investment
advice.
            """
        )