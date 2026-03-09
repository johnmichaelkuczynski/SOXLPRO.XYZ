import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

st.set_page_config(page_title="SOXL Analysis", page_icon="📈", layout="wide")

if "lines" not in st.session_state:
    st.session_state.lines = []
if "prob_result" not in st.session_state:
    st.session_state.prob_result = None


@st.cache_data(ttl=300)
def fetch_soxl_data():
    df = yf.Ticker("SOXL").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


def convert_to_trading_days(value, unit):
    if unit == "days":
        return max(1, value)
    elif unit == "weeks":
        return value * 5
    elif unit == "months":
        return value * 21
    elif unit == "years":
        return value * 252
    return value


def convert_to_timedelta(value, unit):
    if unit == "days":
        return timedelta(days=value)
    elif unit == "weeks":
        return timedelta(weeks=value)
    elif unit == "months":
        return relativedelta(months=value)
    elif unit == "years":
        return relativedelta(years=value)
    return timedelta(days=0)


try:
    data = fetch_soxl_data()
    if data.empty:
        st.error("No data returned from yfinance. Please try refreshing.")
        st.stop()
except Exception as e:
    st.error(f"Failed to fetch SOXL data: {e}")
    st.stop()

col_title, col_refresh = st.columns([8, 1])
with col_title:
    st.markdown("### 📈 SOXL Analysis")
with col_refresh:
    if st.button("🔄", help="Refresh data"):
        st.cache_data.clear()
        st.rerun()

st.markdown("**SOXL Price** · Log Scale  ·  *Use the line tool (📏) in the chart toolbar to draw directly on the chart. Use the eraser (🧹) to remove drawn lines.*")

today = datetime.now()
future_end = today + relativedelta(years=5)
line_colors = [
    "#666666", "#E53935", "#43A047", "#FB8C00", "#8E24AA", "#00ACC1",
    "#6D4C41", "#D81B60", "#00897B", "#FFB300",
]

fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=data.index,
        y=data["Close"],
        mode="lines",
        name="SOXL",
        line=dict(color="#1E88E5", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
    )
)

for i, ln in enumerate(st.session_state.lines):
    x1_dt = pd.Timestamp(ln["x1"])
    x2_dt = pd.Timestamp(ln["x2"])
    y1, y2 = ln["y1"], ln["y2"]

    dt_seconds = (x2_dt - x1_dt).total_seconds()
    if dt_seconds == 0:
        continue

    log_slope = (np.log10(y2) - np.log10(y1)) / dt_seconds
    color = line_colors[i % len(line_colors)]

    fig.add_trace(
        go.Scatter(
            x=[x1_dt, x2_dt],
            y=[y1, y2],
            mode="lines",
            showlegend=False,
            line=dict(color=color, width=2),
            hoverinfo="skip",
        )
    )

    fwd_dt = (pd.Timestamp(future_end) - x2_dt).total_seconds()
    fwd_log_y = np.log10(y2) + log_slope * fwd_dt
    if -10 < fwd_log_y < 10:
        fwd_y = 10**fwd_log_y
        fig.add_trace(
            go.Scatter(
                x=[x2_dt, future_end],
                y=[y2, fwd_y],
                mode="lines",
                showlegend=False,
                line=dict(color=color, width=2, dash="dash"),
                hoverinfo="skip",
            )
        )

    back_date = x1_dt - relativedelta(years=2)
    back_dt = (pd.Timestamp(back_date) - x1_dt).total_seconds()
    back_log_y = np.log10(y1) + log_slope * back_dt
    if -10 < back_log_y < 10:
        back_y = 10**back_log_y
        fig.add_trace(
            go.Scatter(
                x=[back_date, x1_dt],
                y=[back_y, y1],
                mode="lines",
                showlegend=False,
                line=dict(color=color, width=2, dash="dash"),
                hoverinfo="skip",
            )
        )

x_start = data.index[0]
if st.session_state.lines:
    earliest_back = min(
        pd.Timestamp(ln["x1"]) - relativedelta(years=2) for ln in st.session_state.lines
    )
    x_start = min(x_start, earliest_back)

fig.update_layout(
    yaxis=dict(type="log", tickprefix="$", title=""),
    xaxis=dict(range=[x_start, future_end], title=""),
    template="plotly_white",
    height=700,
    margin=dict(l=60, r=20, t=40, b=40),
    showlegend=False,
    hovermode="x unified",
    dragmode="drawline",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="#333333"),
    newshape=dict(
        line=dict(color="#888888", width=2, dash="solid"),
        drawdirection="diagonal",
    ),
)

config = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToAdd": ["drawline", "eraseshape"],
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}
st.plotly_chart(fig, use_container_width=True, config=config)

with st.expander("📏 Add Auto-Extending Trend Line (by coordinates)"):
    st.caption("Lines added here auto-extend into the future (dashed) and backward (dashed).")
    min_date = data.index[0].date()
    max_date = date.today()

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Point A**")
        date_a = st.date_input(
            "Date A",
            value=min_date,
            min_value=min_date,
            max_value=max_date,
            key="date_a",
            label_visibility="collapsed",
        )
        ts_a = pd.Timestamp(date_a)
        idx_a = data.index.get_indexer([ts_a], method="nearest")[0]
        price_a_default = float(data.iloc[idx_a]["Close"])
        price_a = st.number_input(
            "Price A ($)",
            value=price_a_default,
            min_value=0.01,
            format="%.2f",
            key="price_a",
        )

    with col_b:
        st.markdown("**Point B**")
        date_b = st.date_input(
            "Date B",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key="date_b",
            label_visibility="collapsed",
        )
        ts_b = pd.Timestamp(date_b)
        idx_b = data.index.get_indexer([ts_b], method="nearest")[0]
        price_b_default = float(data.iloc[idx_b]["Close"])
        price_b = st.number_input(
            "Price B ($)",
            value=price_b_default,
            min_value=0.01,
            format="%.2f",
            key="price_b",
        )

    if st.button("Add Line", use_container_width=True, type="primary"):
        if date_a == date_b:
            st.error("Point A and Point B must have different dates.")
        else:
            st.session_state.lines.append(
                {"x1": str(date_a), "x2": str(date_b), "y1": price_a, "y2": price_b}
            )
            st.rerun()

if st.session_state.lines:
    st.markdown("**Auto-Extending Lines**")
    for i, ln in enumerate(st.session_state.lines):
        col_info, col_del = st.columns([5, 1])
        with col_info:
            st.caption(
                f"Line {i + 1}: {ln['x1']} (${ln['y1']:.2f}) → {ln['x2']} (${ln['y2']:.2f})"
            )
        with col_del:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.lines.pop(i)
                st.rerun()

st.divider()

st.markdown("### Probability Engine")

col_h, col_d = st.columns(2)

with col_h:
    st.markdown("**Prediction Horizon**")
    h1, h2 = st.columns(2)
    with h1:
        horizon_value = st.number_input(
            "Horizon value", min_value=1, value=1, key="horizon_val", label_visibility="collapsed"
        )
    with h2:
        horizon_unit = st.selectbox(
            "Horizon unit",
            ["days", "weeks", "months", "years"],
            index=1,
            key="horizon_unit",
            label_visibility="collapsed",
        )

with col_d:
    st.markdown("**Historical Dataset Window**")
    d1, d2 = st.columns(2)
    with d1:
        dataset_value = st.number_input(
            "Dataset value", min_value=1, value=6, key="dataset_val", label_visibility="collapsed"
        )
    with d2:
        dataset_unit = st.selectbox(
            "Dataset unit",
            ["days", "weeks", "months", "years", "all available"],
            index=2,
            key="dataset_unit",
            label_visibility="collapsed",
        )

st.markdown("**Magnitude**")
m1, m2 = st.columns(2)
with m1:
    magnitude = st.number_input(
        "Magnitude %", min_value=0.1, value=15.0, step=0.5, key="magnitude", label_visibility="collapsed"
    )
with m2:
    direction = st.selectbox(
        "Direction", ["DOWN", "UP", "EITHER"], index=0, key="direction", label_visibility="collapsed"
    )

if st.button("Calculate Probability", use_container_width=True, type="primary"):
    horizon_td = convert_to_trading_days(horizon_value, horizon_unit)

    if dataset_unit == "all available":
        filtered = data
    else:
        cutoff = datetime.now() - convert_to_timedelta(dataset_value, dataset_unit)
        filtered = data[data.index >= cutoff]

    if len(filtered) < horizon_td + 1:
        st.error("Not enough data for the selected parameters.")
    else:
        close = filtered["Close"].values
        total = len(close) - horizon_td
        count = 0

        for i in range(total):
            pct = (close[i + horizon_td] - close[i]) / close[i] * 100
            if direction == "UP" and pct >= magnitude:
                count += 1
            elif direction == "DOWN" and pct <= -magnitude:
                count += 1
            elif direction == "EITHER" and abs(pct) >= magnitude:
                count += 1

        prob = count / total * 100 if total > 0 else 0
        st.session_state.prob_result = {
            "count": count,
            "total": total,
            "prob": prob,
            "magnitude": magnitude,
            "direction": direction,
        }

if st.session_state.prob_result:
    r = st.session_state.prob_result
    dir_word = (
        "dropped" if r["direction"] == "DOWN" else "rose" if r["direction"] == "UP" else "moved"
    )
    st.info(
        f"In **{r['count']}** out of **{r['total']}** comparable periods, "
        f"SOXL **{dir_word} {r['magnitude']}%** or more.\n\n"
        f"Historical probability: **{r['prob']:.1f}%**"
    )
