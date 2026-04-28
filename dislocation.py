import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

BETA_LOOKBACKS = [5, 10, 20, 60, 120]
RESIDUAL_WINDOWS = [1, 5, 10, 20]
STRUCTURAL_BETA = 3.3

# Z-score thresholds for verdict
Z_STRONG = 1.5   # |z| ≥ 1.5 = clear signal
Z_WEAK = 0.75    # |z| ≥ 0.75 = leaning


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


def _classify(z):
    """Convert a z-score to (verdict, color, emoji, plain-english)."""
    if not np.isfinite(z):
        return ("N/A", "#9e9e9e", "⚪", "Insufficient data")
    if z >= Z_STRONG:
        return ("SELL", "#c62828", "🔴",
                "SOXL is OVERBOUGHT relative to QQQ — likely to mean-revert DOWN")
    if z >= Z_WEAK:
        return ("WEAK SELL", "#ef6c00", "🟠",
                "SOXL is leaning overbought vs QQQ")
    if z <= -Z_STRONG:
        return ("BUY", "#2e7d32", "🟢",
                "SOXL is OVERSOLD relative to QQQ — likely to mean-revert UP")
    if z <= -Z_WEAK:
        return ("WEAK BUY", "#558b2f", "🟢",
                "SOXL is leaning oversold vs QQQ")
    return ("NEUTRAL", "#546e7a", "⚪",
            "SOXL is fairly priced vs QQQ — no clear edge")


def _render_verdict_card(verdict, color, emoji, message, z, sub):
    st.markdown(
        f"""
        <div style="background:{color}; padding:24px 28px; border-radius:12px;
                    color:white; margin-bottom:16px;">
            <div style="font-size:14px; opacity:0.85; letter-spacing:1px;">
                TODAY'S SOXL vs QQQ VERDICT
            </div>
            <div style="font-size:42px; font-weight:800; margin:6px 0;">
                {emoji} {verdict}
            </div>
            <div style="font-size:18px; line-height:1.4;">
                {message}
            </div>
            <div style="font-size:14px; opacity:0.9; margin-top:10px;">
                Composite dislocation score: <b>{z:+.2f}σ</b> · {sub}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_z_surface_3d(matrix_df):
    """3D surface of today's z-score matrix.
    X = beta lookback, Y = residual aggregation horizon, Z = z-score.
    Color: red=SELL (z>0), blue=BUY (z<0)."""
    beta_windows = BETA_LOOKBACKS
    resid_windows = RESIDUAL_WINDOWS
    Z = np.array([
        [float(matrix_df.loc[f"resid {n}d", f"β {b}d"]) for b in beta_windows]
        for n in resid_windows
    ])
    fig = go.Figure(data=[go.Surface(
        x=beta_windows,
        y=resid_windows,
        z=Z,
        colorscale="RdBu_r",
        cmin=-3, cmax=3,
        colorbar=dict(
            title=dict(text="z-score", font=dict(size=14)),
            tickvals=[-3, -1.5, -0.75, 0, 0.75, 1.5, 3],
            ticktext=["−3<br>BUY", "−1.5", "−0.75", "0", "+0.75", "+1.5", "+3<br>SELL"],
            tickfont=dict(size=12),
        ),
        contours=dict(
            z=dict(show=True, start=-3, end=3, size=0.5, color="rgba(0,0,0,0.3)"),
        ),
        hovertemplate=(
            "β lookback: %{x}d<br>"
            "Residual horizon: %{y}d<br>"
            "z-score: %{z:+.2f}σ"
            "<extra></extra>"
        ),
    )])

    # Add reference planes at +1.5 (SELL) and -1.5 (BUY)
    bx = np.array(beta_windows, dtype=float)
    ry = np.array(resid_windows, dtype=float)
    BX, RY = np.meshgrid(bx, ry)
    flat_pos = np.full_like(BX, Z_STRONG, dtype=float)
    flat_neg = np.full_like(BX, -Z_STRONG, dtype=float)
    fig.add_trace(go.Surface(
        x=bx, y=ry, z=flat_pos,
        showscale=False, opacity=0.12,
        colorscale=[[0, "#c62828"], [1, "#c62828"]],
        hoverinfo="skip", name="SELL threshold (+1.5σ)",
    ))
    fig.add_trace(go.Surface(
        x=bx, y=ry, z=flat_neg,
        showscale=False, opacity=0.12,
        colorscale=[[0, "#2e7d32"], [1, "#2e7d32"]],
        hoverinfo="skip", name="BUY threshold (−1.5σ)",
    ))

    AXIS_TITLE = dict(size=15, color="#1a2332", family="Arial Black")
    AXIS_TICK = dict(size=13, color="#222")

    fig.update_layout(
        title=dict(
            text="Today's dislocation z-score across (β lookback × residual horizon)",
            font=dict(size=16, color="#1a2332"),
        ),
        scene=dict(
            xaxis=dict(
                title=dict(text="β lookback (days)", font=AXIS_TITLE),
                tickfont=AXIS_TICK,
                tickmode="array", tickvals=beta_windows,
                ticktext=[f"{b}d" for b in beta_windows],
                gridcolor="#cfd8dc", showbackground=True,
                backgroundcolor="rgba(248,249,250,0.6)",
            ),
            yaxis=dict(
                title=dict(text="Cumulative residual horizon", font=AXIS_TITLE),
                tickfont=AXIS_TICK,
                tickmode="array", tickvals=resid_windows,
                ticktext=[f"{n}d" for n in resid_windows],
                gridcolor="#cfd8dc", showbackground=True,
                backgroundcolor="rgba(248,249,250,0.6)",
            ),
            zaxis=dict(
                title=dict(text="z-score (− = BUY,  + = SELL)", font=AXIS_TITLE),
                tickfont=AXIS_TICK,
                range=[-3.5, 3.5],
                gridcolor="#cfd8dc", showbackground=True,
                backgroundcolor="rgba(248,249,250,0.6)",
            ),
            camera=dict(eye=dict(x=1.7, y=1.7, z=0.85)),
            aspectratio=dict(x=1.4, y=1.2, z=0.9),
        ),
        height=700,
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=False,
    )
    return fig


def render_dislocation_tab():
    st.markdown("### SOXL vs QQQ — Buy or Sell Signal")
    st.caption(
        "Compares SOXL's recent returns to what they *should* have been given QQQ's moves "
        "(SOXL ≈ 3.3× QQQ). When SOXL trades far from that expected path, the gap usually "
        "closes — that's a signal."
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

    # ---- Compute z-score matrix ----
    betas = compute_rolling_betas(df)
    residuals = compute_residuals(df, betas)
    z = compute_zscores(residuals, lookback_days=252)
    matrix = pd.DataFrame(
        index=[f"resid {n}d" for n in RESIDUAL_WINDOWS],
        columns=[f"β {w}d" for w in BETA_LOOKBACKS],
        dtype=float,
    )
    for bw in BETA_LOOKBACKS:
        for nw in RESIDUAL_WINDOWS:
            val = z[f"z_b{bw}_n{nw}"].iloc[-1]
            matrix.loc[f"resid {nw}d", f"β {bw}d"] = float(val) if np.isfinite(val) else np.nan

    # ---- Headline verdict (composite = median across 20d cells, the canonical horizon) ----
    canonical_row = matrix.loc["resid 20d"].dropna()
    composite_z = float(canonical_row.median()) if len(canonical_row) else np.nan
    verdict, color, emoji, message = _classify(composite_z)

    # Historical reversion stats for context
    events, lookup = compute_reversion_table(residuals, beta_window=20, resid_window=20)
    sub_text = "Based on the 20-day cumulative residual (canonical mean-reversion horizon)."
    if not lookup.empty and abs(composite_z) >= Z_WEAK:
        abs_z = abs(composite_z)
        bin_match = None
        for _, row in lookup.iterrows():
            band = row["z_band"]
            try:
                lo_str, hi_str = band.split("–")
                lo = float(lo_str.strip())
                hi_raw = hi_str.strip()
                hi = 99.0 if hi_raw in ("∞", "inf") else float(hi_raw)
                if lo <= abs_z < hi:
                    bin_match = row
                    break
            except Exception:
                continue
        if bin_match is not None:
            sub_text = (
                f"History (3y): events at this magnitude reverted "
                f"<b>{bin_match['reversion_rate_%']:.0f}%</b> of the time, "
                f"median <b>{bin_match['median_days_to_revert']:.0f} days</b> "
                f"to neutral."
            )

    _render_verdict_card(verdict, color, emoji, message, composite_z, sub_text)

    # ---- Per-horizon mini-cards ----
    st.markdown("#### Verdict by horizon")
    st.caption("Each horizon answers: *over the last N days, has SOXL drifted from its QQQ-implied path?*")
    horizon_cols = st.columns(len(RESIDUAL_WINDOWS))
    for i, n in enumerate(RESIDUAL_WINDOWS):
        row = matrix.loc[f"resid {n}d"].dropna()
        z_med = float(row.median()) if len(row) else np.nan
        v, c, e, _ = _classify(z_med)
        with horizon_cols[i]:
            st.markdown(
                f"""
                <div style="background:{c}; padding:14px; border-radius:8px; color:white;
                            text-align:center;">
                    <div style="font-size:12px; opacity:0.85;">Last {n} day{'s' if n>1 else ''}</div>
                    <div style="font-size:22px; font-weight:700; margin:4px 0;">{e} {v}</div>
                    <div style="font-size:14px;">z = {z_med:+.2f}σ</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("")  # spacing

    # ---- 3D surface ----
    st.markdown("#### 3D Dislocation Surface")
    st.caption(
        "Each point is a z-score: how far today's SOXL outperformance/underperformance vs QQQ "
        "stands in its own 1-year history. **Red peaks above the red plane = SELL** "
        "(SOXL overbought). **Blue valleys below the green plane = BUY** (SOXL oversold). "
        "Drag to rotate."
    )
    fig = _render_z_surface_3d(matrix)
    st.plotly_chart(fig, use_container_width=True)

    # ---- Underlying data layer (collapsed) ----
    with st.expander("🔬 Underlying calculations (data layer)", expanded=False):
        _render_data_layer(df, betas, residuals, matrix, events, lookup)


def _render_data_layer(df, betas, residuals, matrix, events, lookup):
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
    with st.expander("Daily residuals + cumulative residuals (last 30 days)"):
        cols_show = [f"resid_b{w}" for w in BETA_LOOKBACKS] + \
                    [f"cumresid_b20_n{n}" for n in RESIDUAL_WINDOWS]
        st.dataframe(residuals[cols_show].tail(30).round(4), use_container_width=True)

    st.markdown("#### 4. Z-score matrix (current cum-residual vs 1y distribution)")
    st.caption("Same data shown in the 3D surface above, in tabular form. "
               "Negative = SOXL underperformed (BUY); positive = SOXL outperformed (SELL).")
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
    if lookup.empty:
        st.info("No qualifying historical events in the 3-year window.")
    else:
        st.dataframe(lookup, use_container_width=True, hide_index=True)
        with st.expander(f"All {len(events)} historical dislocation events"):
            st.dataframe(events.sort_values("date", ascending=False).round(3),
                         use_container_width=True, hide_index=True)
