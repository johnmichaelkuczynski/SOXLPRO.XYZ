import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

BETA_LOOKBACKS = [5, 10, 20, 60, 120]
RESIDUAL_WINDOWS = [1, 5, 10, 20]
STRUCTURAL_BETA = 3.3


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_aligned_prices(years=3):
    end = datetime.now()
    start = end - pd.Timedelta(days=int(years * 365 + 30))
    soxl = yf.Ticker("SOXL").history(start=start, end=end, auto_adjust=True)
    qqq = yf.Ticker("QQQ").history(start=start, end=end, auto_adjust=True)
    if soxl.empty or qqq.empty:
        return pd.DataFrame()
    df = pd.DataFrame({
        "SOXL_close": soxl["Close"],
        "QQQ_close": qqq["Close"],
        "SOXL_volume": soxl["Volume"],
        "QQQ_volume": qqq["Volume"],
    }).dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df["SOXL_ret"] = np.log(df["SOXL_close"] / df["SOXL_close"].shift(1))
    df["QQQ_ret"] = np.log(df["QQQ_close"] / df["QQQ_close"].shift(1))
    return df.dropna()


def compute_rolling_betas(df, windows=BETA_LOOKBACKS):
    out = pd.DataFrame(index=df.index)
    sx = df["SOXL_ret"]
    qx = df["QQQ_ret"]
    for w in windows:
        cov = sx.rolling(w).cov(qx)
        var = qx.rolling(w).var()
        out[f"beta_{w}"] = cov / var
    return out


def compute_residuals(df, betas):
    res = pd.DataFrame(index=df.index)
    for w in BETA_LOOKBACKS:
        beta = betas[f"beta_{w}"]
        expected = beta * df["QQQ_ret"]
        residual = df["SOXL_ret"] - expected
        res[f"resid_b{w}"] = residual
        for n in RESIDUAL_WINDOWS:
            res[f"cumresid_b{w}_n{n}"] = residual.rolling(n).sum()
    return res


def compute_zscores(residuals, lookback_days=252):
    z = pd.DataFrame(index=residuals.index)
    for bw in BETA_LOOKBACKS:
        for nw in RESIDUAL_WINDOWS:
            col = f"cumresid_b{bw}_n{nw}"
            series = residuals[col]
            mean = series.rolling(lookback_days).mean()
            std = series.rolling(lookback_days).std(ddof=1)
            z[f"z_b{bw}_n{nw}"] = (series - mean) / std
    return z


@st.cache_data(ttl=3600, show_spinner=False)
def compute_reversion_table(_residuals_df, beta_window=20, resid_window=20,
                            z_lookback=252, trigger_z=1.5, neutral_z=0.5,
                            max_lookforward=60):
    residuals = _residuals_df
    col = f"cumresid_b{beta_window}_n{resid_window}"
    series = residuals[col].dropna()
    mean = series.rolling(z_lookback).mean()
    std = series.rolling(z_lookback).std(ddof=1)
    z_series = ((series - mean) / std).dropna()

    events = []
    z_arr = z_series.values
    idx_arr = z_series.index
    for i in range(len(z_arr) - max_lookforward):
        z0 = z_arr[i]
        if abs(z0) <= trigger_z:
            continue
        sign = 1 if z0 > 0 else -1
        days_to_revert = None
        for k in range(1, max_lookforward + 1):
            if abs(z_arr[i + k]) <= neutral_z:
                days_to_revert = k
                break
            if sign * z_arr[i + k] < 0:
                days_to_revert = k
                break
        magnitude = float(z_arr[i + (days_to_revert or max_lookforward)] - z0)
        events.append({
            "date": idx_arr[i],
            "start_z": float(z0),
            "abs_start_z": abs(float(z0)),
            "days_to_revert": days_to_revert if days_to_revert is not None else np.nan,
            "reverted": days_to_revert is not None,
            "z_move": magnitude,
        })
    if not events:
        return pd.DataFrame(), pd.DataFrame()
    ev = pd.DataFrame(events)
    bins = [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 99.0)]
    rows = []
    for lo, hi in bins:
        sub = ev[(ev["abs_start_z"] >= lo) & (ev["abs_start_z"] < hi)]
        if sub.empty:
            continue
        reverted_sub = sub.dropna(subset=["days_to_revert"])
        rows.append({
            "z_band": f"{lo:.1f} – {hi if hi < 99 else '∞'}",
            "n_events": int(len(sub)),
            "reversion_rate_%": round(100 * sub["reverted"].mean(), 1),
            "median_days_to_revert": (round(float(reverted_sub["days_to_revert"].median()), 1)
                                       if len(reverted_sub) else np.nan),
            "median_z_move": round(float(sub["z_move"].median()), 2),
        })
    return ev, pd.DataFrame(rows)


def render_dislocation_tab():
    st.markdown("### SOXL–QQQ Relative Dislocation (Sections 1–5: data layer)")
    st.caption(
        "Validation build. Sections 1–5 only: data ingestion → rolling betas → residuals → "
        "z-scores → mean-reversion lookup. Visualization, recommendations, and backtest are "
        "intentionally NOT built yet — review the raw data first and confirm the betas land in "
        "the expected ~2.8 to ~3.5 range before proceeding."
    )

    if st.button("🔄 Refresh data", key="disloc_refresh"):
        fetch_aligned_prices.clear()
        compute_reversion_table.clear()
        st.rerun()

    with st.spinner("Pulling 3 years of SOXL/QQQ daily bars..."):
        df = fetch_aligned_prices(years=3)
    if df.empty:
        st.error("Could not fetch SOXL/QQQ price data.")
        return

    st.markdown("#### 1. Aligned price data")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Trading days", f"{len(df)}")
    with c2:
        st.metric("Date range", f"{df.index.min().date()} → {df.index.max().date()}")
    with c3:
        st.metric("SOXL last close", f"${df['SOXL_close'].iloc[-1]:.2f}")
    with c4:
        st.metric("QQQ last close", f"${df['QQQ_close'].iloc[-1]:.2f}")

    with st.expander("Raw aligned OHLC + log returns (last 30 days)"):
        st.dataframe(df.tail(30).round(4), use_container_width=True)

    st.markdown("#### 2. Rolling betas (SOXL ↔ QQQ)")
    betas = compute_rolling_betas(df)
    latest_betas = betas.iloc[-1]
    cols = st.columns(len(BETA_LOOKBACKS))
    for i, w in enumerate(BETA_LOOKBACKS):
        b = latest_betas[f"beta_{w}"]
        delta = b - STRUCTURAL_BETA
        with cols[i]:
            st.metric(
                f"β ({w}d)",
                f"{b:.2f}" if np.isfinite(b) else "N/A",
                delta=f"{delta:+.2f} vs 3.3" if np.isfinite(b) else None,
                delta_color="off",
            )
    summary = pd.DataFrame({
        "window": [f"{w}d" for w in BETA_LOOKBACKS],
        "current": [round(float(latest_betas[f'beta_{w}']), 3) for w in BETA_LOOKBACKS],
        "mean (3y)": [round(float(betas[f'beta_{w}'].mean()), 3) for w in BETA_LOOKBACKS],
        "median (3y)": [round(float(betas[f'beta_{w}'].median()), 3) for w in BETA_LOOKBACKS],
        "min (3y)": [round(float(betas[f'beta_{w}'].min()), 3) for w in BETA_LOOKBACKS],
        "max (3y)": [round(float(betas[f'beta_{w}'].max()), 3) for w in BETA_LOOKBACKS],
        "stddev (3y)": [round(float(betas[f'beta_{w}'].std(ddof=1)), 3) for w in BETA_LOOKBACKS],
    })
    st.markdown("**Beta summary statistics (validate these are roughly 2.8–3.5):**")
    st.dataframe(summary, use_container_width=True, hide_index=True)

    with st.expander("Full rolling beta history (last 60 days)"):
        st.dataframe(betas.tail(60).round(3), use_container_width=True)

    st.markdown("#### 3. Residuals (actual − β × QQQ_ret)")
    residuals = compute_residuals(df, betas)
    with st.expander("Daily residuals + cumulative residuals (last 30 days)"):
        cols_show = [f"resid_b{w}" for w in BETA_LOOKBACKS] + \
                    [f"cumresid_b20_n{n}" for n in RESIDUAL_WINDOWS]
        st.dataframe(residuals[cols_show].tail(30).round(4), use_container_width=True)

    st.markdown("#### 4. Z-score matrix (current cum-residual vs 1y distribution)")
    z = compute_zscores(residuals, lookback_days=252)
    matrix = pd.DataFrame(
        index=[f"resid {n}d" for n in RESIDUAL_WINDOWS],
        columns=[f"β {w}d" for w in BETA_LOOKBACKS],
        dtype=float,
    )
    for bw in BETA_LOOKBACKS:
        for nw in RESIDUAL_WINDOWS:
            val = z[f"z_b{bw}_n{nw}"].iloc[-1]
            matrix.loc[f"resid {nw}d", f"β {bw}d"] = round(float(val), 2) if np.isfinite(val) else np.nan
    st.markdown("**Today's z-score matrix:**")
    st.dataframe(
        matrix.style.background_gradient(cmap="RdBu_r", vmin=-3, vmax=3, axis=None)
                    .format("{:+.2f}"),
        use_container_width=True,
    )

    st.markdown("#### 5. Historical mean-reversion lookup table")
    st.caption(
        "For events where |z| > 1.5 on the (β=20d, resid=20d) cell, time until z returns to "
        "within ±0.5 (or flips sign), within a 60-day forward window."
    )
    events, lookup = compute_reversion_table(
        residuals, beta_window=20, resid_window=20,
    )
    if lookup.empty:
        st.info("No qualifying historical events in the 3-year window.")
    else:
        st.dataframe(lookup, use_container_width=True, hide_index=True)
        with st.expander(f"All {len(events)} historical dislocation events"):
            st.dataframe(events.sort_values("date", ascending=False).round(3),
                         use_container_width=True, hide_index=True)

    st.success(
        "Sections 1–5 complete. Inspect the beta summary table — if values cluster in the "
        "2.8–3.5 range and the z-score matrix and reversion lookup look sane, give the go-ahead "
        "to build sections 6–9 (3D surface, recommendation panel, diagnostic panel, backtest)."
    )
