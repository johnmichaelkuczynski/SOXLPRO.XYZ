import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from strategy_builder import generate_strategy, parse_strategy_json, render_strategy_html, STRATEGY_CSS

st.set_page_config(page_title="SOXL Analysis", page_icon="📈", layout="wide")

if "lines" not in st.session_state:
    st.session_state.lines = []
if "prob_result" not in st.session_state:
    st.session_state.prob_result = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "strategy_html" not in st.session_state:
    st.session_state.strategy_html = None

chart_component = components.declare_component("chart_draw", path="components/chart_draw")


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

tab_chart, tab_strategy = st.tabs(["📊 Chart & Probabilities", "🎯 Strategy Builder"])

with tab_chart:
    st.markdown("**SOXL Price** · Log Scale")

    future_end = (datetime.now() + relativedelta(years=5)).strftime("%Y-%m-%d")
    dates_list = [d.strftime("%Y-%m-%d") for d in data.index]
    prices_list = data["Close"].tolist()

    result = chart_component(
        dates=dates_list,
        prices=prices_list,
        lines=st.session_state.lines,
        future_end=future_end,
        chart_height=900,
        key="soxl_chart",
        default=None,
    )

    if result is not None:
        if result.get("action") == "set_all":
            st.session_state.lines = result.get("lines", [])

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

with tab_strategy:
    st.markdown("### 🎯 Strategy Builder")
    st.markdown(
        "Tell me about your situation — portfolio size, how much cash you have, "
        "your risk tolerance, and your goals. I'll build a personalized SOXL entry "
        "strategy backed by historical probability data."
    )

    if st.session_state.strategy_html:
        st.markdown(STRATEGY_CSS, unsafe_allow_html=True)
        st.markdown(st.session_state.strategy_html, unsafe_allow_html=True)
        st.markdown("")

        if st.button("Start New Strategy", type="secondary"):
            st.session_state.chat_messages = []
            st.session_state.strategy_html = None
            st.rerun()

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            display_text = msg["content"]
            if "===STRATEGY_START===" in display_text:
                display_text = display_text.split("===STRATEGY_START===")[0].strip()
            st.markdown(display_text)

    if prompt := st.chat_input("Describe your situation (portfolio, cash, goals...)"):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Analyzing your situation with SOXL historical data..."):
                close_prices = data["Close"].values
                api_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.chat_messages
                ]
                try:
                    response_text = generate_strategy(api_messages, close_prices)
                except Exception as e:
                    error_msg = str(e)
                    if "FREE_CLOUD_BUDGET_EXCEEDED" in error_msg:
                        st.error("Cloud budget exceeded. Please upgrade your Replit plan to continue using the AI strategy builder.")
                        st.stop()
                    st.error(f"Failed to generate strategy: {e}")
                    st.stop()

                st.session_state.chat_messages.append({"role": "assistant", "content": response_text})

                strategy_data = parse_strategy_json(response_text)
                if strategy_data:
                    display_text = response_text.split("===STRATEGY_START===")[0].strip()
                    if display_text:
                        st.markdown(display_text)
                    st.session_state.strategy_html = render_strategy_html(strategy_data)
                    st.markdown(STRATEGY_CSS, unsafe_allow_html=True)
                    st.markdown(st.session_state.strategy_html, unsafe_allow_html=True)
                elif "===STRATEGY_START===" in response_text:
                    display_text = response_text.split("===STRATEGY_START===")[0].strip()
                    if display_text:
                        st.markdown(display_text)
                    st.warning("The strategy document had a formatting issue. Please try saying 'generate the strategy again' to retry.")
                else:
                    st.markdown(response_text)
