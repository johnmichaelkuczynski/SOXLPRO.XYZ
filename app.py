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
if "show_xlu" not in st.session_state:
    st.session_state.show_xlu = False
if "show_vix" not in st.session_state:
    st.session_state.show_vix = False
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


@st.cache_data(ttl=300)
def fetch_xlu_data():
    df = yf.Ticker("XLU").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df[["Close"]].copy()


@st.cache_data(ttl=300)
def fetch_vix_data():
    df = yf.Ticker("^VIX").history(period="max", auto_adjust=True)
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
    overlay_cols = st.columns([2, 1, 1, 1, 1, 1, 1, 2])
    with overlay_cols[0]:
        st.markdown("**SOXL Price** · Log Scale")
    with overlay_cols[1]:
        if st.button(
            "Hide QQQ" if st.session_state.show_qqq else "QQQ",
            type="primary" if st.session_state.show_qqq else "secondary",
        ):
            st.session_state.show_qqq = not st.session_state.show_qqq
            st.rerun()
    with overlay_cols[2]:
        if st.button(
            "Hide TQQQ" if st.session_state.show_tqqq else "TQQQ",
            type="primary" if st.session_state.show_tqqq else "secondary",
        ):
            st.session_state.show_tqqq = not st.session_state.show_tqqq
            st.rerun()
    with overlay_cols[3]:
        if st.button(
            "Hide TLT" if st.session_state.show_tlt else "TLT",
            type="primary" if st.session_state.show_tlt else "secondary",
        ):
            st.session_state.show_tlt = not st.session_state.show_tlt
            st.rerun()
    with overlay_cols[4]:
        if st.button(
            "Hide XLU" if st.session_state.show_xlu else "XLU",
            type="primary" if st.session_state.show_xlu else "secondary",
        ):
            st.session_state.show_xlu = not st.session_state.show_xlu
            st.rerun()
    with overlay_cols[5]:
        if st.button(
            "Hide VIX" if st.session_state.show_vix else "VIX",
            type="primary" if st.session_state.show_vix else "secondary",
        ):
            st.session_state.show_vix = not st.session_state.show_vix
            st.rerun()
    with overlay_cols[6]:
        if st.button(
            "Hide Short Int." if st.session_state.show_short_interest else "Short Int.",
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

    xlu_dates_list = []
    xlu_prices_list = []
    if st.session_state.show_xlu:
        try:
            xlu_data = fetch_xlu_data()
            if not xlu_data.empty:
                xlu_dates_list = [d.strftime("%Y-%m-%d") for d in xlu_data.index]
                xlu_prices_list = xlu_data["Close"].tolist()
        except Exception:
            pass

    vix_dates_list = []
    vix_prices_list = []
    if st.session_state.show_vix:
        try:
            vix_data = fetch_vix_data()
            if not vix_data.empty:
                vix_dates_list = [d.strftime("%Y-%m-%d") for d in vix_data.index]
                vix_prices_list = vix_data["Close"].tolist()
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
        xlu_dates=xlu_dates_list,
        xlu_prices=xlu_prices_list,
        vix_dates=vix_dates_list,
        vix_prices=vix_prices_list,
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
        import plotly.graph_objects as go

        ar = st.session_state.analyze_result
        st.divider()
        st.markdown(f"### Period Analysis: {ar['start']} to {ar['end']}")

        ret_color = "#2E7D32" if ar['period_return'] >= 0 else "#D32F2F"
        summary_html = f"""
        <div style="display:flex; gap:12px; margin-bottom:16px;">
          <div style="flex:1; background:#f8f9fa; border-radius:10px; padding:14px; text-align:center; border-left:4px solid #1E88E5;">
            <div style="font-size:12px; color:#888;">Start Price</div>
            <div style="font-size:22px; font-weight:700;">${ar['start_price']}</div>
          </div>
          <div style="flex:1; background:#f8f9fa; border-radius:10px; padding:14px; text-align:center; border-left:4px solid #1E88E5;">
            <div style="font-size:12px; color:#888;">End Price</div>
            <div style="font-size:22px; font-weight:700;">${ar['end_price']}</div>
          </div>
          <div style="flex:1; background:#f8f9fa; border-radius:10px; padding:14px; text-align:center; border-left:4px solid {ret_color};">
            <div style="font-size:12px; color:#888;">Period Return</div>
            <div style="font-size:22px; font-weight:700; color:{ret_color};">{ar['period_return']:+.1f}%</div>
          </div>
          <div style="flex:1; background:#f8f9fa; border-radius:10px; padding:14px; text-align:center; border-left:4px solid #666;">
            <div style="font-size:12px; color:#888;">Data Points</div>
            <div style="font-size:22px; font-weight:700;">{ar['data_points']}</div>
          </div>
        </div>
        """
        st.markdown(summary_html, unsafe_allow_html=True)

        st.markdown("**Based on this period's patterns, here's what historically happens next:**")

        for pred in ar["predictions"]:
            with st.expander(f"{pred['horizon']} ({pred['days']} trading days) — {pred['total_periods']} samples", expanded=pred['horizon'] in ['1 Month', '3 Months']):

                mags = sorted(pred["mag_probs"].keys())
                up_probs = [pred["mag_probs"][m]["up"] for m in mags]
                down_probs = [pred["mag_probs"][m]["down"] for m in mags]
                mag_labels = [f"{m}%" for m in mags]

                fig_bars = go.Figure()
                fig_bars.add_trace(go.Bar(
                    x=mag_labels, y=up_probs,
                    name="Probability of GAIN",
                    marker_color="#66BB6A",
                    text=[f"{p:.0f}%" for p in up_probs],
                    textposition="outside",
                    textfont=dict(size=11, color="#2E7D32"),
                ))
                fig_bars.add_trace(go.Bar(
                    x=mag_labels, y=[-d for d in down_probs],
                    name="Probability of LOSS",
                    marker_color="#EF5350",
                    text=[f"{p:.0f}%" for p in down_probs],
                    textposition="outside",
                    textfont=dict(size=11, color="#D32F2F"),
                ))
                fig_bars.update_layout(
                    title=dict(text=f"Probability of Moves After {pred['horizon']}", font=dict(size=14)),
                    xaxis_title="Move Size",
                    yaxis_title="Probability %",
                    template="plotly_white",
                    height=320,
                    margin=dict(l=50, r=20, t=40, b=50),
                    barmode="relative",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                    yaxis=dict(zeroline=True, zerolinecolor="#333", zerolinewidth=2,
                               tickvals=list(range(-100, 101, 10)),
                               ticktext=[f"{abs(v)}%" for v in range(-100, 101, 10)]),
                )
                st.plotly_chart(fig_bars, use_container_width=True)

                avg_ret = pred["avg_return"]
                med_ret = pred["median_return"]
                avg_color = "#2E7D32" if avg_ret >= 0 else "#D32F2F"
                med_color = "#2E7D32" if med_ret >= 0 else "#D32F2F"

                gauge_val = 50 + min(max(avg_ret, -50), 50)

                info_html = f"""
                <div style="display:flex; gap:15px; margin:5px 0 10px 0; align-items:stretch;">
                  <div style="flex:2; position:relative;">
                    <div style="text-align:center; font-size:12px; color:#888; margin-bottom:4px;">Historical Outlook</div>
                    <div style="height:36px; border-radius:18px; overflow:hidden;
                                background:linear-gradient(to right, #D32F2F, #E53935, #FF7043, #FFB74D, #FFF176, #AED581, #66BB6A, #43A047, #2E7D32);
                                box-shadow: 0 1px 4px rgba(0,0,0,0.12);">
                      <div style="position:absolute; top:20px; left:{gauge_val}%; transform:translateX(-50%);
                                  width:4px; height:36px; background:#111; border-radius:2px; z-index:3;"></div>
                      <div style="position:absolute; top:20px; left:{gauge_val}%; transform:translateX(-50%);
                                  width:16px; height:36px; background:rgba(255,255,255,0.3); border-radius:8px; z-index:2;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:10px; color:#999; margin-top:2px;">
                      <span style="color:#D32F2F; font-weight:700;">BEARISH</span>
                      <span style="color:#2E7D32; font-weight:700;">BULLISH</span>
                    </div>
                  </div>
                  <div style="flex:1; background:#f8f9fa; border-radius:8px; padding:10px; text-align:center;">
                    <div style="font-size:11px; color:#888;">Avg Return</div>
                    <div style="font-size:20px; font-weight:700; color:{avg_color};">{avg_ret:+.1f}%</div>
                  </div>
                  <div style="flex:1; background:#f8f9fa; border-radius:8px; padding:10px; text-align:center;">
                    <div style="font-size:11px; color:#888;">Median Return</div>
                    <div style="font-size:20px; font-weight:700; color:{med_color};">{med_ret:+.1f}%</div>
                  </div>
                """

                if pred["actual_return"] is not None:
                    actual = pred["actual_return"]
                    act_color = "#2E7D32" if actual >= 0 else "#D32F2F"
                    act_icon = "&#9650;" if actual >= 0 else "&#9660;"
                    info_html += f"""
                  <div style="flex:1; background:{'#E8F5E9' if actual >= 0 else '#FFEBEE'}; border-radius:8px; padding:10px; text-align:center;
                              border:2px solid {act_color};">
                    <div style="font-size:11px; color:#888;">Actual Result</div>
                    <div style="font-size:20px; font-weight:700; color:{act_color};">{act_icon} {actual:+.1f}%</div>
                  </div>
                    """
                else:
                    info_html += """
                  <div style="flex:1; background:#f5f5f5; border-radius:8px; padding:10px; text-align:center;">
                    <div style="font-size:11px; color:#888;">Actual Result</div>
                    <div style="font-size:14px; color:#aaa; margin-top:2px;">Pending</div>
                  </div>
                    """

                info_html += "</div>"
                st.markdown(info_html, unsafe_allow_html=True)

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
            all_returns = []

            for i in range(total):
                pct = (close[i + horizon_td] - close[i]) / close[i] * 100
                all_returns.append(pct)
                if direction == "UP" and pct >= magnitude:
                    count += 1
                elif direction == "DOWN" and pct <= -magnitude:
                    count += 1
                elif direction == "EITHER" and abs(pct) >= magnitude:
                    count += 1

            prob = count / total * 100 if total > 0 else 0

            up_count = sum(1 for r in all_returns if r > 0)
            down_count = sum(1 for r in all_returns if r < 0)
            avg_return = sum(all_returns) / len(all_returns) if all_returns else 0
            median_return = sorted(all_returns)[len(all_returns) // 2] if all_returns else 0
            best = max(all_returns) if all_returns else 0
            worst = min(all_returns) if all_returns else 0

            percentile_5 = sorted(all_returns)[int(len(all_returns) * 0.05)] if all_returns else 0
            percentile_25 = sorted(all_returns)[int(len(all_returns) * 0.25)] if all_returns else 0
            percentile_75 = sorted(all_returns)[int(len(all_returns) * 0.75)] if all_returns else 0
            percentile_95 = sorted(all_returns)[int(len(all_returns) * 0.95)] if all_returns else 0

            st.session_state.prob_result = {
                "count": count,
                "total": total,
                "prob": prob,
                "magnitude": magnitude,
                "direction": direction,
                "horizon_label": f"{horizon_value} {horizon_unit}",
                "avg_return": round(avg_return, 1),
                "median_return": round(median_return, 1),
                "best": round(best, 1),
                "worst": round(worst, 1),
                "up_count": up_count,
                "down_count": down_count,
                "up_pct": round(up_count / total * 100, 1) if total > 0 else 0,
                "all_returns": all_returns,
                "p5": round(percentile_5, 1),
                "p25": round(percentile_25, 1),
                "p75": round(percentile_75, 1),
                "p95": round(percentile_95, 1),
            }

    if st.session_state.prob_result:
        import plotly.graph_objects as go

        r = st.session_state.prob_result
        dir_word = (
            "dropped" if r["direction"] == "DOWN" else "rose" if r["direction"] == "UP" else "moved"
        )
        prob_val = r["prob"]
        up_pct = r["up_pct"]

        if r["direction"] == "DOWN":
            gauge_pct = 100 - prob_val
            gauge_label = f"{100 - prob_val:.0f}% chance it does NOT drop {r['magnitude']}%+"
        elif r["direction"] == "UP":
            gauge_pct = prob_val
            gauge_label = f"{prob_val:.0f}% chance it rises {r['magnitude']}%+"
        else:
            gauge_pct = 50
            gauge_label = f"{prob_val:.0f}% chance of {r['magnitude']}%+ move either way"

        st.markdown("---")

        gauge_html = f"""
        <div style="margin: 10px 0 25px 0;">
          <div style="text-align:center; font-size:16px; font-weight:600; margin-bottom:8px; color:#333;">
            SOXL over {r['horizon_label']} — How likely is a {r['magnitude']}%+ {'drop' if r['direction']=='DOWN' else 'gain' if r['direction']=='UP' else 'move'}?
          </div>
          <div style="position:relative; height:60px; border-radius:30px; overflow:hidden;
                      background: linear-gradient(to right, #D32F2F, #E53935, #FF7043, #FFB74D, #FFF176, #AED581, #66BB6A, #43A047, #2E7D32);
                      box-shadow: 0 2px 8px rgba(0,0,0,0.15);">
            <div style="position:absolute; top:0; left:{gauge_pct}%; transform:translateX(-50%);
                        width:6px; height:60px; background:#111; border-radius:3px; z-index:3;"></div>
            <div style="position:absolute; top:0; left:{gauge_pct}%; transform:translateX(-50%);
                        width:22px; height:60px; background:rgba(255,255,255,0.35); border-radius:11px; z-index:2;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; margin-top:4px; font-size:13px; color:#888;">
            <span style="color:#D32F2F; font-weight:700;">BEARISH</span>
            <span style="color:#2E7D32; font-weight:700;">BULLISH</span>
          </div>
          <div style="text-align:center; margin-top:6px; font-size:22px; font-weight:800;
                      color:{'#2E7D32' if gauge_pct > 60 else '#D32F2F' if gauge_pct < 40 else '#E65100'};">
            {gauge_label}
          </div>
        </div>
        """
        st.markdown(gauge_html, unsafe_allow_html=True)

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            returns = r["all_returns"]
            neg_returns = [x for x in returns if x < 0]
            pos_returns = [x for x in returns if x >= 0]

            fig_hist = go.Figure()
            if neg_returns:
                fig_hist.add_trace(go.Histogram(
                    x=neg_returns, name="Losses",
                    marker_color="#EF5350",
                    opacity=0.85,
                    nbinsx=40,
                ))
            if pos_returns:
                fig_hist.add_trace(go.Histogram(
                    x=pos_returns, name="Gains",
                    marker_color="#66BB6A",
                    opacity=0.85,
                    nbinsx=40,
                ))

            mag = r["magnitude"]
            if r["direction"] == "DOWN":
                fig_hist.add_vline(x=-mag, line_dash="dash", line_color="#D32F2F", line_width=2,
                                   annotation_text=f"-{mag}%", annotation_position="top")
            elif r["direction"] == "UP":
                fig_hist.add_vline(x=mag, line_dash="dash", line_color="#2E7D32", line_width=2,
                                   annotation_text=f"+{mag}%", annotation_position="top")
            else:
                fig_hist.add_vline(x=-mag, line_dash="dash", line_color="#D32F2F", line_width=2,
                                   annotation_text=f"-{mag}%", annotation_position="top")
                fig_hist.add_vline(x=mag, line_dash="dash", line_color="#2E7D32", line_width=2,
                                   annotation_text=f"+{mag}%", annotation_position="top")

            fig_hist.add_vline(x=0, line_color="#333", line_width=1)

            fig_hist.update_layout(
                title=dict(text=f"Return Distribution ({r['horizon_label']})", font=dict(size=14)),
                xaxis_title="Return %",
                yaxis_title="Frequency",
                template="plotly_white",
                height=350,
                margin=dict(l=50, r=20, t=40, b=40),
                showlegend=False,
                bargap=0.05,
            )
            st.plotly_chart(fig_hist, use_container_width=True)

        with chart_col2:
            labels = ["Gains", "Losses"]
            values = [r["up_count"], r["down_count"]]
            colors = ["#66BB6A", "#EF5350"]

            fig_donut = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=0.6,
                marker=dict(colors=colors),
                textinfo="label+percent",
                textfont=dict(size=14),
                hovertemplate="%{label}: %{value} periods (%{percent})<extra></extra>",
            )])
            fig_donut.update_layout(
                title=dict(text=f"Win/Loss Split ({r['total']:,} periods)", font=dict(size=14)),
                template="plotly_white",
                height=350,
                margin=dict(l=20, r=20, t=40, b=20),
                showlegend=False,
                annotations=[dict(
                    text=f"<b>{r['up_pct']:.0f}%</b><br>Win Rate",
                    x=0.5, y=0.5, font_size=18, showarrow=False,
                    font=dict(color="#2E7D32" if r["up_pct"] >= 50 else "#D32F2F"),
                )],
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        range_html = f"""
        <div style="background:#f8f9fa; border-radius:12px; padding:16px 20px; margin:5px 0 15px 0;
                    border: 1px solid #e0e0e0;">
          <div style="text-align:center; font-weight:600; font-size:14px; color:#555; margin-bottom:10px;">
            Historical Return Range over {r['horizon_label']}
          </div>
          <div style="position:relative; height:40px; margin:0 40px;">
            <div style="position:absolute; top:16px; left:0; right:0; height:8px;
                        background:linear-gradient(to right, #EF5350, #FFEE58, #66BB6A);
                        border-radius:4px;"></div>
            <div style="position:absolute; top:12px; left:{max(0, min(100, (r['p5'] - r['worst']) / (r['best'] - r['worst']) * 100)) if r['best'] != r['worst'] else 5}%;
                        transform:translateX(-50%); font-size:11px; color:#D32F2F; font-weight:700; text-align:center;">
              <div style="width:2px; height:16px; background:#D32F2F; margin:0 auto;"></div>
              {r['p5']:+.0f}%<br><span style="font-size:9px;">5th pctl</span>
            </div>
            <div style="position:absolute; top:12px; left:{max(0, min(100, (r['median_return'] - r['worst']) / (r['best'] - r['worst']) * 100)) if r['best'] != r['worst'] else 50}%;
                        transform:translateX(-50%); font-size:11px; color:#333; font-weight:700; text-align:center;">
              <div style="width:3px; height:16px; background:#333; margin:0 auto;"></div>
              {r['median_return']:+.0f}%<br><span style="font-size:9px;">Median</span>
            </div>
            <div style="position:absolute; top:12px; left:{max(0, min(100, (r['p95'] - r['worst']) / (r['best'] - r['worst']) * 100)) if r['best'] != r['worst'] else 95}%;
                        transform:translateX(-50%); font-size:11px; color:#2E7D32; font-weight:700; text-align:center;">
              <div style="width:2px; height:16px; background:#2E7D32; margin:0 auto;"></div>
              {r['p95']:+.0f}%<br><span style="font-size:9px;">95th pctl</span>
            </div>
          </div>
          <div style="display:flex; justify-content:space-between; margin:20px 40px 0 40px; font-size:12px;">
            <span style="color:#D32F2F; font-weight:700;">Worst: {r['worst']:+.1f}%</span>
            <span style="color:#555;">Avg: {r['avg_return']:+.1f}%</span>
            <span style="color:#2E7D32; font-weight:700;">Best: {r['best']:+.1f}%</span>
          </div>
        </div>
        """
        st.markdown(range_html, unsafe_allow_html=True)

        if r["direction"] == "DOWN":
            if r["prob"] < 25:
                verdict = f"Historically unlikely. SOXL dropped {r['magnitude']}%+ only {r['prob']:.0f}% of the time over {r['horizon_label']}. The odds favor holding."
                st.success(f"**Verdict:** {verdict}")
            elif r["prob"] < 50:
                verdict = f"Moderate risk. About 1 in {int(round(100/r['prob']))} chance of a {r['magnitude']}%+ drop over {r['horizon_label']}. Consider position sizing accordingly."
                st.warning(f"**Verdict:** {verdict}")
            else:
                verdict = f"Elevated risk. SOXL has dropped {r['magnitude']}%+ in {r['prob']:.0f}% of historical {r['horizon_label']} periods. Proceed with caution."
                st.error(f"**Verdict:** {verdict}")
        elif r["direction"] == "UP":
            if r["prob"] > 60:
                verdict = f"Strong historical tailwind. SOXL rose {r['magnitude']}%+ in {r['prob']:.0f}% of {r['horizon_label']} periods."
                st.success(f"**Verdict:** {verdict}")
            elif r["prob"] > 35:
                verdict = f"Decent odds. SOXL rose {r['magnitude']}%+ about {r['prob']:.0f}% of the time over {r['horizon_label']}."
                st.info(f"**Verdict:** {verdict}")
            else:
                verdict = f"That's a big move. SOXL rose {r['magnitude']}%+ only {r['prob']:.0f}% of the time over {r['horizon_label']}."
                st.warning(f"**Verdict:** {verdict}")
        else:
            if r["prob"] > 60:
                st.warning(f"**Verdict:** High volatility expected. A {r['magnitude']}%+ move in either direction happened {r['prob']:.0f}% of the time.")
            else:
                st.info(f"**Verdict:** A {r['magnitude']}%+ move in either direction happened {r['prob']:.0f}% of the time over {r['horizon_label']}.")

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
