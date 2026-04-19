import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

try:
    from py_vollib.black_scholes.implied_volatility import implied_volatility as bs_iv
    HAS_VOLLIB = True
except Exception:
    HAS_VOLLIB = False

RISK_FREE_RATE = 0.045


def _compute_iv_fallback(mid, spot, strike, t_years, flag):
    if not HAS_VOLLIB:
        return np.nan
    try:
        return bs_iv(mid, spot, strike, t_years, RISK_FREE_RATE, flag)
    except Exception:
        return np.nan


@st.cache_data(ttl=900, show_spinner=False)
def fetch_options_chain(ticker_symbol="SOXL"):
    ticker = yf.Ticker(ticker_symbol)
    expirations = ticker.options
    if not expirations:
        return pd.DataFrame(), 0.0, datetime.now()

    hist = ticker.history(period="5d", auto_adjust=True)
    spot = float(hist["Close"].iloc[-1])

    rows = []
    today = datetime.now().date()
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 7:
                continue
            t_years = max(dte, 1) / 365.0
            chain = ticker.option_chain(exp_str)
            for kind, df in [("c", chain.calls), ("p", chain.puts)]:
                for _, row in df.iterrows():
                    bid = float(row.get("bid", 0) or 0)
                    ask = float(row.get("ask", 0) or 0)
                    strike = float(row.get("strike", 0) or 0)
                    iv = float(row.get("impliedVolatility", 0) or 0)
                    vol = float(row.get("volume", 0) or 0)
                    oi = float(row.get("openInterest", 0) or 0)
                    if bid <= 0 or ask <= 0 or strike <= 0:
                        continue
                    mid = (bid + ask) / 2.0
                    if mid <= 0:
                        continue
                    spread_pct = (ask - bid) / mid
                    if spread_pct > 0.20:
                        continue
                    if vol == 0 and oi == 0:
                        continue
                    if iv <= 0 or np.isnan(iv):
                        iv = _compute_iv_fallback(mid, spot, strike, t_years, kind)
                    if not np.isfinite(iv) or iv < 0.05 or iv > 5.0:
                        continue
                    rows.append({
                        "kind": kind,
                        "strike": strike,
                        "moneyness": strike / spot,
                        "dte": dte,
                        "exp_date": exp_str,
                        "iv": iv,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "spread_pct": spread_pct,
                        "volume": vol,
                        "open_interest": oi,
                    })
        except Exception:
            continue

    df = pd.DataFrame(rows)
    return df, spot, datetime.now()


def filter_local_outliers(df, k=5, lo=0.5, hi=2.0):
    if len(df) < k + 1:
        return df
    money_scale = 0.05
    dte_scale = 30.0
    pts = np.column_stack([
        df["moneyness"].values / money_scale,
        df["dte"].values / dte_scale,
    ])
    tree = cKDTree(pts)
    _, idx = tree.query(pts, k=min(k + 1, len(df)))
    iv = df["iv"].values
    keep = np.ones(len(df), dtype=bool)
    for i in range(len(df)):
        neighbor_ivs = iv[idx[i][1:]]
        if len(neighbor_ivs) == 0:
            continue
        med = np.median(neighbor_ivs)
        if med <= 0:
            continue
        ratio = iv[i] / med
        if ratio > hi or ratio < lo:
            keep[i] = False
    return df[keep].reset_index(drop=True)


def next_monthly_opex(today=None):
    if today is None:
        today = date.today()
    year = today.year
    month = today.month + 1
    if month > 12:
        month = 1
        year += 1
    first = date(year, month, 1)
    days_to_friday = (4 - first.weekday()) % 7
    third_friday = first + timedelta(days=days_to_friday + 14)
    return third_friday


def filter_otm_blend(df):
    if df.empty:
        return df
    calls = df[(df["kind"] == "c") & (df["moneyness"] >= 1.0)]
    puts = df[(df["kind"] == "p") & (df["moneyness"] < 1.0)]
    return pd.concat([calls, puts], ignore_index=True)


def build_surface_grid(df):
    if len(df) < 10:
        return None, None, None

    df = df[(df["moneyness"] >= 0.4) & (df["moneyness"] <= 1.6)].copy()
    if len(df) < 10:
        return None, None, None

    points = df[["moneyness", "dte"]].values
    values = df["iv"].values

    money_min = max(0.5, df["moneyness"].min())
    money_max = min(1.5, df["moneyness"].max())
    days_min = max(7, int(df["dte"].min()))
    days_max = min(730, int(df["dte"].max()))

    grid_money = np.arange(money_min, money_max + 0.02, 0.02)
    grid_days = np.arange(days_min, days_max + 30, 30)
    mg, dg = np.meshgrid(grid_money, grid_days)

    iv_grid = griddata(points, values, (mg, dg), method="cubic")
    nan_mask = np.isnan(iv_grid)
    if nan_mask.any():
        iv_linear = griddata(points, values, (mg, dg), method="linear")
        iv_grid[nan_mask] = iv_linear[nan_mask]
    nan_mask = np.isnan(iv_grid)
    if nan_mask.any():
        iv_nearest = griddata(points, values, (mg, dg), method="nearest")
        iv_grid[nan_mask] = iv_nearest[nan_mask]

    iv_grid = np.clip(iv_grid, 0.1, 3.0)
    return grid_money, grid_days, iv_grid


def atm_iv_for_dte(df, target_dte, tol_money=0.05, tol_dte=15):
    if df.empty:
        return None
    sub = df[(np.abs(df["moneyness"] - 1.0) <= tol_money) &
             (np.abs(df["dte"] - target_dte) <= tol_dte)]
    if len(sub) == 0:
        sub = df[(np.abs(df["moneyness"] - 1.0) <= tol_money * 2) &
                 (np.abs(df["dte"] - target_dte) <= tol_dte * 2)]
    if len(sub) == 0:
        return None
    return float(sub["iv"].median())


def skew_25d(df, target_dte=30, tol_dte=15):
    if df.empty:
        return None
    sub = df[np.abs(df["dte"] - target_dte) <= tol_dte]
    if len(sub) < 4:
        return None
    puts = sub[(sub["kind"] == "p") & (sub["moneyness"].between(0.85, 0.95))]
    calls = sub[(sub["kind"] == "c") & (sub["moneyness"].between(1.05, 1.15))]
    if len(puts) == 0 or len(calls) == 0:
        return None
    return float(puts["iv"].median() - calls["iv"].median())


def detect_anomalies(df, z_thresh=3.0, min_oi=50, max_spread=0.20,
                     money_window=0.05, dte_window=14):
    if df.empty or len(df) < 8:
        return [], []

    money = df["moneyness"].values
    dte = df["dte"].values
    iv = df["iv"].values

    fitted = np.full(len(df), np.nan)
    local_std = np.full(len(df), np.nan)

    for i in range(len(df)):
        nbr_mask = (
            (np.abs(money - money[i]) <= money_window) &
            (np.abs(dte - dte[i]) <= dte_window)
        )
        nbr_mask[i] = False
        nbr_iv = iv[nbr_mask]
        if len(nbr_iv) >= 3:
            fitted[i] = np.median(nbr_iv)
            local_std[i] = np.std(nbr_iv, ddof=1) if len(nbr_iv) > 1 else np.nan

    residuals = iv - fitted
    z = np.where(local_std > 0, residuals / local_std, 0.0)

    sells, buys = [], []
    for i in range(len(df)):
        if not np.isfinite(z[i]):
            continue
        row = df.iloc[i]
        if row["open_interest"] < min_oi:
            continue
        if row["spread_pct"] > max_spread:
            continue
        signal = {
            "strike": float(row["strike"]),
            "exp_date": row["exp_date"],
        }
        if z[i] >= z_thresh:
            sells.append(signal)
        elif z[i] <= -z_thresh:
            buys.append(signal)

    def sort_key(s):
        return (s["exp_date"], s["strike"])
    sells.sort(key=sort_key)
    buys.sort(key=sort_key)
    return buys, sells


def _format_signal_line(sig):
    try:
        d = datetime.strptime(sig["exp_date"], "%Y-%m-%d").strftime("%b %d %Y")
    except Exception:
        d = sig["exp_date"]
    return f"${sig['strike']:.0f} strike | {d} expiry"


def render_signal_panel(signals, side):
    if side == "sell":
        bg = "#FFEBEE"
        border = "#D32F2F"
        title_color = "#B71C1C"
        title = "SELLS"
    else:
        bg = "#E8F5E9"
        border = "#2E7D32"
        title_color = "#1B5E20"
        title = "BUYS"

    if signals:
        items = "".join(
            f"<div style='font-size:12px; padding:4px 6px; border-bottom:1px solid rgba(0,0,0,0.06); "
            f"font-family: ui-monospace, Menlo, monospace; color:#222;'>"
            f"{_format_signal_line(s)}</div>"
            for s in signals
        )
    else:
        items = "<div style='font-size:13px; padding:10px; color:#888; text-align:center;'>None</div>"

    html = (
        f"<div style='background:{bg}; border:1px solid {border}; border-radius:8px; "
        f"padding:8px; height:720px; overflow-y:auto;'>"
        f"<div style='font-size:14px; font-weight:800; color:{title_color}; "
        f"text-align:center; padding:6px 0 8px 0; border-bottom:2px solid {border}; "
        f"margin-bottom:6px;'>{title}</div>"
        f"{items}</div>"
    )
    return html


def render_surface_figure(grid_money, grid_days, iv_grid, spot, title):
    today = date.today()

    mg, dg = np.meshgrid(grid_money, grid_days)
    strike_grid = mg * spot
    exp_dates = np.array([
        [(today + timedelta(days=int(d))).strftime("%b %d, %Y") for _ in grid_money]
        for d in grid_days
    ])
    customdata = np.dstack([strike_grid, exp_dates])

    fig = go.Figure(data=[go.Surface(
        x=grid_money,
        y=grid_days,
        z=iv_grid * 100,
        colorscale="RdYlBu_r",
        cmin=20,
        cmax=180,
        colorbar=dict(title="IV %"),
        customdata=customdata,
        hovertemplate=(
            "<b>Expiration:</b> %{customdata[1]}<br>"
            "<b>Days to expiry:</b> %{y:.0f}<br>"
            "<b>Strike:</b> $%{customdata[0]:.2f}<br>"
            "<b>Moneyness:</b> %{x:.3f}<br>"
            "<b>IV:</b> %{z:.1f}%"
            "<extra></extra>"
        ),
    )])

    candidate_ticks = [30, 60, 90, 180, 365, 540, 730]
    y_lo, y_hi = float(grid_days.min()), float(grid_days.max())
    tick_vals = [d for d in candidate_ticks if y_lo <= d <= y_hi]
    if not tick_vals:
        tick_vals = [int(round(y_lo)), int(round(y_hi))]
    tick_text = [
        f"{d}d<br>{(today + timedelta(days=d)).strftime('%b %d, %Y')}"
        for d in tick_vals
    ]

    opex_date = next_monthly_opex(today)
    opex_dte = (opex_date - today).days
    if y_lo <= opex_dte <= y_hi:
        x_line = np.linspace(float(grid_money.min()), float(grid_money.max()), 2)
        opex_z_top = 180
        fig.add_trace(go.Scatter3d(
            x=list(x_line) + list(x_line[::-1]),
            y=[opex_dte] * 4,
            z=[0, 0, opex_z_top, opex_z_top],
            mode="lines",
            line=dict(color="rgba(80, 80, 80, 0.55)", width=4, dash="dash"),
            name=f"Next Monthly OPEX: {opex_date.strftime('%b %d, %Y')}",
            hovertemplate=f"Next Monthly OPEX<br>{opex_date.strftime('%b %d, %Y')} ({opex_dte}d)<extra></extra>",
            showlegend=True,
        ))
        fig.add_trace(go.Scatter3d(
            x=[float(grid_money.mean())],
            y=[opex_dte],
            z=[opex_z_top],
            mode="text",
            text=[f"OPEX {opex_date.strftime('%b %d')}"],
            textfont=dict(size=11, color="#333"),
            showlegend=False,
            hoverinfo="skip",
        ))

    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="Moneyness (Strike / Spot)",
            yaxis=dict(
                title="Days to Expiration",
                tickmode="array",
                tickvals=tick_vals,
                ticktext=tick_text,
                tickfont=dict(size=10),
            ),
            zaxis=dict(
                title="Implied Volatility (%)",
                range=[0, 180],
            ),
            camera=dict(eye=dict(x=1.6, y=-1.6, z=0.9)),
        ),
        height=720,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=0.0, xanchor="center", x=0.5),
    )
    return fig


def render_vol_surface_tab():
    st.markdown("### SOXL Implied Volatility Surface")
    st.caption(
        "Interactive 3D surface of implied volatility across strikes and expirations. "
        "Drag to rotate, scroll to zoom, hover for details. Cached for 15 minutes."
    )

    col_mode, col_refresh = st.columns([3, 1])
    with col_mode:
        mode = st.radio(
            "Surface basis",
            ["OTM Blend (cleanest)", "Calls only", "Puts only"],
            horizontal=True,
            key="vol_surface_mode",
        )
    with col_refresh:
        st.write("")
        if st.button("🔄 Refresh now", use_container_width=True):
            fetch_options_chain.clear()
            st.rerun()

    with st.spinner("Fetching SOXL option chain..."):
        df, spot, fetched_at = fetch_options_chain("SOXL")

    if df.empty:
        st.error("No usable options data returned. The chain may be empty or the source is unavailable.")
        return

    if mode == "Calls only":
        surface_df = df[df["kind"] == "c"].copy()
    elif mode == "Puts only":
        surface_df = df[df["kind"] == "p"].copy()
    else:
        surface_df = filter_otm_blend(df)

    pre_outlier = len(surface_df)
    surface_df = filter_local_outliers(surface_df)
    outliers_dropped = pre_outlier - len(surface_df)

    info_cols = st.columns(4)
    iv30 = atm_iv_for_dte(surface_df, 30)
    iv90 = atm_iv_for_dte(surface_df, 90)
    iv365 = atm_iv_for_dte(surface_df, 365)
    sk25 = skew_25d(surface_df, 30)

    with info_cols[0]:
        st.metric("Spot", f"${spot:.2f}", help="Current SOXL price")
    with info_cols[1]:
        v = f"{iv30*100:.1f}%" if iv30 else "N/A"
        v90 = f"{iv90*100:.1f}%" if iv90 else "N/A"
        v365 = f"{iv365*100:.1f}%" if iv365 else "N/A"
        st.metric("ATM IV — 30d", v, help=f"90d: {v90} · 365d: {v365}")
    with info_cols[2]:
        if sk25 is not None:
            st.metric("25Δ Skew (30d)", f"{sk25*100:+.1f}%",
                      help="Put IV minus Call IV. Positive = downside fear.")
        else:
            st.metric("25Δ Skew (30d)", "N/A")
    with info_cols[3]:
        if iv30 and iv90:
            slope = (iv90 - iv30) * 100
            st.metric("Term Slope (90d−30d)", f"{slope:+.1f}%",
                      help="Positive = upward-sloping term structure (contango).")
        else:
            st.metric("Term Slope (90d−30d)", "N/A")

    st.caption(
        f"Fetched: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')} · "
        f"Contracts after hygiene filtering: {len(surface_df)} "
        f"({outliers_dropped} local outliers dropped) · "
        f"py_vollib available: {HAS_VOLLIB}"
    )

    grid_money, grid_days, iv_grid = build_surface_grid(surface_df)
    if iv_grid is None:
        st.warning(f"Not enough clean contracts ({len(surface_df)}) to build a surface. Try a different mode.")
        return

    title = f"SOXL Implied Volatility Surface — {fetched_at.strftime('%Y-%m-%d %H:%M')}"
    fig = render_surface_figure(grid_money, grid_days, iv_grid, spot, title)

    buys, sells = detect_anomalies(surface_df)

    if not buys and not sells:
        st.info("No definitive buy/sell signals. All surface deviations within noise margin.")

    panel_col_l, plot_col, panel_col_r = st.columns([15, 70, 15])
    with panel_col_l:
        st.markdown(render_signal_panel(sells, "sell"), unsafe_allow_html=True)
    with plot_col:
        st.plotly_chart(fig, use_container_width=True)
    with panel_col_r:
        st.markdown(render_signal_panel(buys, "buy"), unsafe_allow_html=True)

    with st.expander("Show raw filtered contracts"):
        st.dataframe(
            surface_df[["kind", "strike", "moneyness", "dte", "iv", "bid", "ask", "volume", "open_interest"]]
            .sort_values(["dte", "strike"])
            .assign(iv=lambda d: (d["iv"] * 100).round(1)),
            use_container_width=True,
            hide_index=True,
        )
