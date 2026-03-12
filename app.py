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
if "analyze_result" not in st.session_state:
    st.session_state.analyze_result = None
if "show_qqq" not in st.session_state:
    st.session_state.show_qqq = False
if "show_tqqq" not in st.session_state:
    st.session_state.show_tqqq = False
if "show_tlt" not in st.session_state:
    st.session_state.show_tlt = False
if "show_short_interest" not in st.session_state:
    st.session_state.show_short_interest = False

chart_component = components.declare_component("chart_draw", path="components/chart_draw")


@st.cache_data(ttl=300)
def fetch_soxl_data():
    df = yf.Ticker("SOXL").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


@st.cache_data(ttl=300)
def fetch_qqq_data():
    df = yf.Ticker("QQQ").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


@st.cache_data(ttl=300)
def fetch_tqqq_data():
    df = yf.Ticker("TQQQ").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


@st.cache_data(ttl=300)
def fetch_tlt_data():
    df = yf.Ticker("TLT").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


@st.cache_data(ttl=3600)
def fetch_short_interest():
    ticker = yf.Ticker("SOXL")
    info = ticker.info
    result = {}
    fields = [
        ("sharesShort", "Shares Short"),
        ("shortRatio", "Short Ratio (Days to Cover)"),
        ("shortPercentOfFloat", "Short % of Float"),
        ("sharesShortPriorMonth", "Shares Short (Prior Month)"),
        ("sharesOutstanding", "Shares Outstanding"),
        ("floatShares", "Float Shares"),
    ]
    for key, label in fields:
        val = info.get(key)
        if val is not None:
            result[label] = val
    date_short = info.get("dateShortInterest")
    if date_short:
        result["_date"] = datetime.fromtimestamp(date_short).strftime("%Y-%m-%d")
    return result


@st.cache_data(ttl=3600)
def fetch_short_volume_history(symbol="SOXL", days_back=365):
    import requests
    import concurrent.futures

    dates_to_fetch = []
    d = datetime.now()
    for _ in range(days_back):
        d -= timedelta(days=1)
        if d.weekday() < 5:
            dates_to_fetch.append(d)

    def fetch_one(dt):
        url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{dt.strftime('%Y%m%d')}.txt"
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return None
            for line in r.text.strip().split("\n"):
                if f"|{symbol}|" in line:
                    parts = line.split("|")
                    if len(parts) >= 5:
                        short_vol = float(parts[2])
                        total_vol = float(parts[4])
                        return {
                            "date": dt.strftime("%Y-%m-%d"),
                            "short_volume": short_vol,
                            "total_volume": total_vol,
                            "short_ratio": round(short_vol / total_vol * 100, 1) if total_vol > 0 else 0,
                        }
        except Exception:
            pass
        return None

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_one, dt): dt for dt in dates_to_fetch}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda x: x["date"])
    return results


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
    st.markdown("### SOXL Analysis")
with col_refresh:
    if st.button("Refresh", help="Refresh data"):
        st.cache_data.clear()
        st.rerun()


def get_price_at_offset(df, days_ago):
    target_date = df.index[-1] - timedelta(days=days_ago)
    mask = df.index <= target_date
    if mask.any():
        return df.loc[mask, "Close"].iloc[-1]
    return None


current_price = data["Close"].iloc[-1]
latest_date = data.index[-1].strftime("%Y-%m-%d")

periods = [
    ("Today", 1),
    ("1W", 7),
    ("1M", 30),
    ("1Y", 365),
    ("5Y", 1825),
    ("All Time", None),
]

period_data = []
for label, days in periods:
    if days is None:
        old_price = data["Close"].iloc[0]
    else:
        old_price = get_price_at_offset(data, days)
    if old_price is not None and old_price > 0:
        pct = (current_price - old_price) / old_price * 100
        dollar = current_price - old_price
        period_data.append((label, pct, dollar))
    else:
        period_data.append((label, None, None))

price_cols = st.columns([1.5] + [1] * len(period_data))
with price_cols[0]:
    st.metric(label=f"SOXL ({latest_date})", value=f"${current_price:.2f}")

for i, (label, pct, dollar) in enumerate(period_data):
    with price_cols[i + 1]:
        if pct is not None:
            sign = "+" if dollar >= 0 else ""
            st.metric(
                label=label,
                value=f"{sign}{pct:.1f}%",
                delta=f"${sign}{dollar:.2f}",
            )
        else:
            st.metric(label=label, value="N/A")

tab_chart, tab_strategy = st.tabs(["📊 Chart & Probabilities", "🎯 Strategy Builder"])

with tab_chart:
    overlay_cols = st.columns([2, 2, 2, 2, 2, 2])
    with overlay_cols[0]:
        st.markdown("**SOXL Price** · Log Scale")
    with overlay_cols[1]:
        if st.button(
            "Hide QQQ" if st.session_state.show_qqq else "Show QQQ",
            type="primary" if st.session_state.show_qqq else "secondary",
        ):
            st.session_state.show_qqq = not st.session_state.show_qqq
            st.rerun()
    with overlay_cols[2]:
        if st.button(
            "Hide TQQQ" if st.session_state.show_tqqq else "Show TQQQ",
            type="primary" if st.session_state.show_tqqq else "secondary",
        ):
            st.session_state.show_tqqq = not st.session_state.show_tqqq
            st.rerun()
    with overlay_cols[3]:
        if st.button(
            "Hide TLT" if st.session_state.show_tlt else "Show TLT",
            type="primary" if st.session_state.show_tlt else "secondary",
        ):
            st.session_state.show_tlt = not st.session_state.show_tlt
            st.rerun()
    with overlay_cols[4]:
        if st.button(
            "Hide Short Interest" if st.session_state.show_short_interest else "Short Interest",
            type="primary" if st.session_state.show_short_interest else "secondary",
        ):
            st.session_state.show_short_interest = not st.session_state.show_short_interest
            st.rerun()

    future_end = (datetime.now() + relativedelta(years=5)).strftime("%Y-%m-%d")
    dates_list = [d.strftime("%Y-%m-%d") for d in data.index]
    prices_list = data["Close"].tolist()

    qqq_dates_list = []
    qqq_prices_list = []
    if st.session_state.show_qqq:
        try:
            qqq_data = fetch_qqq_data()
            if not qqq_data.empty:
                qqq_dates_list = [d.strftime("%Y-%m-%d") for d in qqq_data.index]
                qqq_prices_list = qqq_data["Close"].tolist()
        except Exception:
            pass

    tqqq_dates_list = []
    tqqq_prices_list = []
    if st.session_state.show_tqqq:
        try:
            tqqq_data = fetch_tqqq_data()
            if not tqqq_data.empty:
                tqqq_dates_list = [d.strftime("%Y-%m-%d") for d in tqqq_data.index]
                tqqq_prices_list = tqqq_data["Close"].tolist()
        except Exception:
            pass

    tlt_dates_list = []
    tlt_prices_list = []
    if st.session_state.show_tlt:
        try:
            tlt_data = fetch_tlt_data()
            if not tlt_data.empty:
                tlt_dates_list = [d.strftime("%Y-%m-%d") for d in tlt_data.index]
                tlt_prices_list = tlt_data["Close"].tolist()
        except Exception:
            pass

    result = chart_component(
        dates=dates_list,
        prices=prices_list,
        qqq_dates=qqq_dates_list,
        qqq_prices=qqq_prices_list,
        tqqq_dates=tqqq_dates_list,
        tqqq_prices=tqqq_prices_list,
        tlt_dates=tlt_dates_list,
        tlt_prices=tlt_prices_list,
        lines=st.session_state.lines,
        future_end=future_end,
        chart_height=900,
        key="soxl_chart",
        default=None,
    )

    if result is not None:
        action = result.get("action")
        if action == "set_all":
            st.session_state.lines = result.get("lines", [])
        elif action == "analyze":
            st.session_state.lines = result.get("lines", [])
            analyze_start = result.get("analyze_start")
            analyze_end = result.get("analyze_end")
            if analyze_start and analyze_end:
                start_dt = pd.to_datetime(analyze_start)
                end_dt = pd.to_datetime(analyze_end)
                window_data = data[(data.index >= start_dt) & (data.index <= end_dt)]
                if len(window_data) >= 5:
                    close_w = window_data["Close"].values
                    after_data = data[data.index > end_dt]
                    horizons = [
                        ("1 Week", 5), ("2 Weeks", 10), ("1 Month", 21),
                        ("3 Months", 63), ("6 Months", 126), ("1 Year", 252)
                    ]
                    magnitudes = [5, 10, 15, 20, 25, 30, 50]
                    predictions = []
                    for h_label, h_days in horizons:
                        total = len(close_w) - h_days
                        if total <= 0:
                            continue
                        returns = []
                        for i in range(total):
                            pct = (close_w[i + h_days] - close_w[i]) / close_w[i] * 100
                            returns.append(pct)
                        avg_ret = np.mean(returns)
                        med_ret = np.median(returns)
                        mag_probs = {}
                        for mag in magnitudes:
                            up_count = sum(1 for r in returns if r >= mag)
                            down_count = sum(1 for r in returns if r <= -mag)
                            mag_probs[mag] = {
                                "up": round(up_count / total * 100, 1),
                                "down": round(down_count / total * 100, 1)
                            }
                        actual_ret = None
                        if len(after_data) >= h_days:
                            end_price = window_data["Close"].iloc[-1]
                            future_price = after_data["Close"].iloc[min(h_days - 1, len(after_data) - 1)]
                            actual_ret = round((future_price - end_price) / end_price * 100, 1)
                        predictions.append({
                            "horizon": h_label,
                            "days": h_days,
                            "avg_return": round(avg_ret, 1),
                            "median_return": round(med_ret, 1),
                            "mag_probs": mag_probs,
                            "actual_return": actual_ret,
                            "total_periods": total
                        })
                    st.session_state.analyze_result = {
                        "start": analyze_start,
                        "end": analyze_end,
                        "data_points": len(window_data),
                        "start_price": round(window_data["Close"].iloc[0], 2),
                        "end_price": round(window_data["Close"].iloc[-1], 2),
                        "period_return": round((window_data["Close"].iloc[-1] - window_data["Close"].iloc[0]) / window_data["Close"].iloc[0] * 100, 1),
                        "predictions": predictions
                    }
                else:
                    st.session_state.analyze_result = None

    if st.session_state.analyze_result:
        ar = st.session_state.analyze_result
        st.divider()
        st.markdown(f"### Period Analysis: {ar['start']} to {ar['end']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Start Price", f"${ar['start_price']}")
        c2.metric("End Price", f"${ar['end_price']}")
        c3.metric("Period Return", f"{ar['period_return']}%")
        c4.metric("Data Points", ar['data_points'])

        st.markdown("**Predictions based on this period's data vs. what actually happened after:**")

        for pred in ar["predictions"]:
            with st.expander(f"{pred['horizon']} ({pred['days']} trading days) — {pred['total_periods']} samples", expanded=pred['horizon'] in ['1 Month', '3 Months']):
                col_pred, col_actual = st.columns(2)
                with col_pred:
                    st.markdown("**Predicted (from selected period)**")
                    st.markdown(f"- Average return: **{pred['avg_return']}%**")
                    st.markdown(f"- Median return: **{pred['median_return']}%**")
                    prob_lines = []
                    for mag, probs in pred["mag_probs"].items():
                        prob_lines.append(f"- ≥{mag}% up: **{probs['up']}%** prob | ≥{mag}% down: **{probs['down']}%** prob")
                    st.markdown("\n".join(prob_lines))
                with col_actual:
                    if pred["actual_return"] is not None:
                        actual = pred["actual_return"]
                        color = "green" if actual >= 0 else "red"
                        st.markdown("**What actually happened**")
                        st.markdown(f"- Actual return after {pred['horizon']}: :{color}[**{actual:+.1f}%**]")
                        if actual >= 0:
                            predicted_up_prob = pred["mag_probs"].get(5, {}).get("up", 0)
                            st.markdown(f"- Model gave {predicted_up_prob}% probability of ≥5% up move")
                        else:
                            predicted_down_prob = pred["mag_probs"].get(5, {}).get("down", 0)
                            st.markdown(f"- Model gave {predicted_down_prob}% probability of ≥5% down move")
                    else:
                        st.markdown("**What actually happened**")
                        st.markdown("*Not enough future data to verify*")

        if st.button("Clear Analysis"):
            st.session_state.analyze_result = None
            st.rerun()

    if st.session_state.show_short_interest:
        st.divider()
        st.markdown("### Short Interest — SOXL")
        try:
            si = fetch_short_interest()
            if si:
                report_date = si.pop("_date", "Unknown")
                st.markdown(f"*Latest FINRA report date: {report_date}*")
                si_cols = st.columns(len(si))
                for idx, (label, val) in enumerate(si.items()):
                    with si_cols[idx]:
                        if "%" in label or "Percent" in label.replace(" ", ""):
                            display_val = f"{val * 100:.2f}%" if val < 1 else f"{val:.2f}%"
                        elif val >= 1_000_000:
                            display_val = f"{val / 1_000_000:.2f}M"
                        elif val >= 1_000:
                            display_val = f"{val / 1_000:.1f}K"
                        else:
                            display_val = f"{val:.2f}"
                        st.metric(label=label, value=display_val)

                shares_short = si.get("Shares Short")
                prior = si.get("Shares Short (Prior Month)")
                if shares_short and prior and prior > 0:
                    change_pct = (shares_short - prior) / prior * 100
                    change_dir = "increased" if change_pct > 0 else "decreased"
                    st.info(
                        f"Short interest has **{change_dir}** by **{abs(change_pct):.1f}%** "
                        f"from the prior month ({prior / 1_000_000:.2f}M to {shares_short / 1_000_000:.2f}M shares)."
                    )
            else:
                st.warning("Short interest data not available.")
        except Exception as e:
            st.error(f"Failed to fetch short interest data: {e}")

        st.markdown("#### Daily Short Volume (FINRA) — Last 12 Months")
        with st.spinner("Fetching FINRA short volume data..."):
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots

                sv_data = fetch_short_volume_history("SOXL", days_back=365)
                if sv_data and len(sv_data) > 5:
                    sv_dates = [d["date"] for d in sv_data]
                    sv_short = [d["short_volume"] for d in sv_data]
                    sv_total = [d["total_volume"] for d in sv_data]
                    sv_ratio = [d["short_ratio"] for d in sv_data]

                    fig = make_subplots(specs=[[{"secondary_y": True}]])

                    fig.add_trace(
                        go.Bar(
                            x=sv_dates, y=sv_short,
                            name="Short Volume",
                            marker_color="#43A047",
                            opacity=0.7,
                        ),
                        secondary_y=False,
                    )

                    fig.add_trace(
                        go.Scatter(
                            x=sv_dates, y=sv_ratio,
                            name="Short Volume %",
                            line=dict(color="#1E88E5", width=2),
                            mode="lines",
                        ),
                        secondary_y=True,
                    )

                    fig.update_layout(
                        height=400,
                        template="plotly_white",
                        margin=dict(l=60, r=60, t=30, b=40),
                        legend=dict(x=0.01, y=0.99),
                        hovermode="x unified",
                        bargap=0.1,
                    )
                    fig.update_yaxes(title_text="Short Volume", secondary_y=False)
                    fig.update_yaxes(title_text="Short Vol %", ticksuffix="%", secondary_y=True)

                    st.plotly_chart(fig, use_container_width=True)

                    avg_ratio = sum(sv_ratio) / len(sv_ratio)
                    recent_ratio = sv_ratio[-1] if sv_ratio else 0
                    st.markdown(
                        f"**Current short volume ratio:** {recent_ratio}% · "
                        f"**12-month average:** {avg_ratio:.1f}% · "
                        f"**Data points:** {len(sv_data)} trading days"
                    )
                else:
                    st.warning("Could not fetch enough short volume data from FINRA.")
            except Exception as e:
                st.error(f"Failed to fetch short volume history: {e}")

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
