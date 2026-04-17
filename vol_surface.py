import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from scipy.interpolate import griddata

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
                        "iv": iv,
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "volume": vol,
                        "open_interest": oi,
                    })
        except Exception:
            continue

    df = pd.DataFrame(rows)
    return df, spot, datetime.now()


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


def render_surface_figure(grid_money, grid_days, iv_grid, title):
    fig = go.Figure(data=[go.Surface(
        x=grid_money,
        y=grid_days,
        z=iv_grid * 100,
        colorscale="RdYlBu_r",
        colorbar=dict(title="IV %"),
        hovertemplate="Moneyness: %{x:.2f}<br>Days: %{y:.0f}<br>IV: %{z:.1f}%<extra></extra>",
    )])
    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="Moneyness (Strike / Spot)",
            yaxis_title="Days to Expiration",
            zaxis_title="Implied Volatility (%)",
            camera=dict(eye=dict(x=1.6, y=-1.6, z=0.9)),
        ),
        height=700,
        margin=dict(l=10, r=10, t=50, b=10),
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
        surface_df = df[df["kind"] == "c"]
    elif mode == "Puts only":
        surface_df = df[df["kind"] == "p"]
    else:
        surface_df = filter_otm_blend(df)

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
        f"Contracts after hygiene filtering: {len(surface_df)} · "
        f"py_vollib available: {HAS_VOLLIB}"
    )

    grid_money, grid_days, iv_grid = build_surface_grid(surface_df)
    if iv_grid is None:
        st.warning(f"Not enough clean contracts ({len(surface_df)}) to build a surface. Try a different mode.")
        return

    title = f"SOXL Implied Volatility Surface — {fetched_at.strftime('%Y-%m-%d %H:%M')}"
    fig = render_surface_figure(grid_money, grid_days, iv_grid, title)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Show raw filtered contracts"):
        st.dataframe(
            surface_df[["kind", "strike", "moneyness", "dte", "iv", "bid", "ask", "volume", "open_interest"]]
            .sort_values(["dte", "strike"])
            .assign(iv=lambda d: (d["iv"] * 100).round(1)),
            use_container_width=True,
            hide_index=True,
        )
