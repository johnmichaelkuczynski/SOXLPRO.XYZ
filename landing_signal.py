from collections import OrderedDict
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st


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

SIGNAL_COLORS = {
    "STRONG SELL": "#b91c1c",
    "SELL": "#f97316",
    "DO NOTHING": "#64748b",
    "BUY": "#4ade80",
    "STRONG BUY": "#047857",
}


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


DEFAULT_THRESHOLDS = (15.0, 35.0, 65.0, 85.0)


def signal_from_percentile(percentile, thresholds=DEFAULT_THRESHOLDS):
    if not np.isfinite(percentile):
        return "INSUFFICIENT HISTORY"
    strong_buy, buy, sell, strong_sell = thresholds
    if percentile < strong_buy:
        return "STRONG BUY"
    if percentile < buy:
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
    return f"""
    <div style="border:1px solid #e2e8f0;border-radius:14px;padding:20px 22px;
                background:#ffffff;margin:8px 0 12px;">
      <div style="font-size:.78rem;color:#64748b;letter-spacing:.09em;
                  font-weight:800;">TODAY'S SOXL SIGNAL</div>
      <div style="font-size:2.25rem;font-weight:850;color:{color};margin:2px 0;">
        {signal}
      </div>
      <div style="font-size:.94rem;color:#475569;margin-bottom:14px;">
        Composite historical-range percentile:
        <strong>{percentile:.1f}%</strong> · Close through {close_date}
      </div>
      <div style="position:relative;padding-top:14px;">
        <div style="display:flex;height:20px;border-radius:10px;overflow:hidden;">
          <div style="width:15%;background:#047857;"></div>
          <div style="width:20%;background:#4ade80;"></div>
          <div style="width:30%;background:#cbd5e1;"></div>
          <div style="width:20%;background:#fb923c;"></div>
          <div style="width:15%;background:#b91c1c;"></div>
        </div>
        <div style="position:absolute;left:calc({marker:.2f}% - 8px);top:4px;
                    width:16px;height:34px;border-radius:5px;background:#111827;
                    border:3px solid white;box-shadow:0 1px 5px rgba(0,0,0,.4);">
        </div>
      </div>
      <div style="display:grid;grid-template-columns:15% 20% 30% 20% 15%;
                  margin-top:7px;font-size:.68rem;font-weight:750;color:#475569;
                  text-align:center;">
        <span>STRONG BUY</span><span>BUY</span><span>DO NOTHING</span>
        <span>SELL</span><span>STRONG SELL</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:4px;
                  color:#94a3b8;font-size:.68rem;">
        <span>0% · period lows</span><span>100% · period highs</span>
      </div>
    </div>
    """


def render_landing_signal(price_data):
    readings, closes = compute_timeframe_readings(price_data)
    result = composite_signal(readings)
    if closes.empty or not np.isfinite(result["percentile"]):
        st.warning("The daily SOXL signal is unavailable until price history loads.")
        return

    st.markdown("### SOXL Daily Signal")
    st.markdown(
        _signal_card(
            result["percentile"],
            result["signal"],
            closes.index[-1].strftime("%Y-%m-%d"),
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Mean-reversion reading: lower percentiles are closer to historical lows "
        "and produce buy-side signals; higher percentiles are closer to historical "
        "highs and produce sell-side signals. The broad 35%–65% middle is Do Nothing."
    )

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
            """
For every timeframe:

`(current close − minimum close) ÷ (maximum close − minimum close) × 100`

**Condition labels:** Oversold below 20%; Neutral from 20% through 80%;
Overbought above 80%.

**Composite signal:** Strong Buy from 0% to below 15%; Buy from 15% to below
35%; Do Nothing from 35% to below 65%; Sell from 65% to below 85%; Strong Sell
from 85% through 100%.

The dashboard uses completed daily closing prices beginning in 2010. It is a
historical mean-reversion indicator, not a guarantee or personalized investment
advice.
            """
        )