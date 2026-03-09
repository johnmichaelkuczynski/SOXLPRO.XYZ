import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from streamlit_plotly_events import plotly_events

st.set_page_config(page_title="SOXL Analysis", page_icon="📈", layout="wide")

if "lines" not in st.session_state:
    st.session_state.lines = []
if "prob_result" not in st.session_state:
    st.session_state.prob_result = None
if "pending_click" not in st.session_state:
    st.session_state.pending_click = None
if "drawing_mode" not in st.session_state:
    st.session_state.drawing_mode = False


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

st.markdown("**SOXL Price** · Log Scale")

draw_col1, draw_col2, draw_col3 = st.columns([1, 1, 2])
with draw_col1:
    draw_clicked = st.button(
        "✏️ Start Drawing" if not st.session_state.drawing_mode else "🛑 Cancel Drawing",
        use_container_width=True,
        type="primary" if not st.session_state.drawing_mode else "secondary",
    )
    if draw_clicked:
        st.session_state.drawing_mode = not st.session_state.drawing_mode
        st.session_state.pending_click = None
        st.rerun()
with draw_col2:
    if st.session_state.lines:
        if st.button("🗑️ Clear All Lines", use_container_width=True):
            st.session_state.lines = []
            st.rerun()
with draw_col3:
    if st.session_state.drawing_mode:
        if st.session_state.pending_click:
            pt = st.session_state.pending_click
            st.info(f"Point A set: {pt['x'][:10]} at ${pt['y']:.2f} — Now click a second point on the chart.")
        else:
            st.info("Click on the price line to set Point A.")

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
            mode="lines+markers",
            showlegend=False,
            line=dict(color=color, width=2),
            marker=dict(size=6, color=color),
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

if st.session_state.pending_click:
    pt = st.session_state.pending_click
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp(pt["x"])],
            y=[pt["y"]],
            mode="markers",
            marker=dict(size=12, color="red", symbol="cross"),
            showlegend=False,
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
    dragmode="pan",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="#333333"),
)

config = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "drawline", "eraseshape"],
}

selected_points = plotly_events(
    fig,
    click_event=True,
    select_event=False,
    hover_event=False,
    override_height=700,
    override_width="100%",
    config=config,
)

if st.session_state.drawing_mode and selected_points:
    click = selected_points[0]
    click_x = click.get("x")
    click_y = click.get("y")

    if click_x is not None and click_y is not None:
        if st.session_state.pending_click is None:
            st.session_state.pending_click = {"x": str(click_x), "y": float(click_y)}
            st.rerun()
        else:
            pt_a = st.session_state.pending_click
            st.session_state.lines.append({
                "x1": pt_a["x"][:10],
                "x2": str(click_x)[:10],
                "y1": float(pt_a["y"]),
                "y2": float(click_y),
            })
            st.session_state.pending_click = None
            st.session_state.drawing_mode = False
            st.rerun()

if st.session_state.lines:
    st.markdown("**Active Trend Lines**")
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
