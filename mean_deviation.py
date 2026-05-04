"""Mean Generator & Deviation system.

For any security:
  1. Fit log-linear regression: log(price) ~ time
  2. Convert back: trend_mean = exp(fitted)
  3. Deviation = log(price) - log(trend_mean)
  4. z = deviation / std(deviation)

For any *pair* of securities A, B:
  relative_z = z_A - z_B
  signal: < -2.5 → A oversold vs B; > +2.5 → A overbought vs B
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


ASSET_COLORS = {
    "SOXL": "#1976d2",
    "QQQ":  "#f57c00",
    "TQQQ": "#7b1fa2",
    "TLT":  "#388e3c",
    "XLU":  "#00897b",
    "VIX":  "#c62828",
}


def fit_log_linear_trend(dates: pd.DatetimeIndex, prices: np.ndarray):
    """Fit log_price = a + b * t (t in days from first observation).

    Returns:
        trend_price: np.ndarray (same length as prices) — fitted price level
        log_dev:     np.ndarray (log_price - fitted_log_price)
        z:           np.ndarray (log_dev standardized by its own std)
        params:      dict with {a, b, annual_growth_pct, std_log_dev}
    """
    prices = np.asarray(prices, dtype=float)
    valid = prices > 0
    log_p = np.log(prices[valid])
    t_days = (pd.DatetimeIndex(dates[valid]) - pd.DatetimeIndex(dates[valid])[0]).days.values.astype(float)

    if len(log_p) < 2:
        n = len(prices)
        return (np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan),
                {"a": np.nan, "b": np.nan, "annual_growth_pct": np.nan, "std_log_dev": np.nan})

    # OLS via polyfit
    b, a = np.polyfit(t_days, log_p, 1)  # slope, intercept
    fitted_log = a + b * t_days
    log_dev = log_p - fitted_log
    sigma = float(np.std(log_dev, ddof=1)) if len(log_dev) > 1 else 0.0
    z = log_dev / sigma if sigma > 0 else np.zeros_like(log_dev)

    # Pad back to original length (if any zero/neg prices got dropped)
    n = len(prices)
    trend_full = np.full(n, np.nan)
    log_dev_full = np.full(n, np.nan)
    z_full = np.full(n, np.nan)
    trend_full[valid] = np.exp(fitted_log)
    log_dev_full[valid] = log_dev
    z_full[valid] = z

    annual_growth = (np.exp(b * 252) - 1) * 100  # 252 trading days/yr ≈ calendar
    # Actually b is per calendar day — use 365.25
    annual_growth = (np.exp(b * 365.25) - 1) * 100

    return trend_full, log_dev_full, z_full, {
        "a": float(a),
        "b": float(b),
        "annual_growth_pct": float(annual_growth),
        "std_log_dev": sigma,
    }


def compute_relative_z(z_a: pd.Series, z_b: pd.Series) -> pd.Series:
    """Aligned cross-asset z difference: z_a - z_b on the intersection of dates."""
    return (z_a - z_b).dropna()


def _classify_relative(rz_today: float):
    if not np.isfinite(rz_today):
        return ("INSUFFICIENT DATA", "#666", "—")
    if rz_today < -2.5:
        return ("EXTREMELY OVERSOLD vs benchmark", "#1b5e20", "🟢🟢")
    if rz_today < -1.5:
        return ("OVERSOLD vs benchmark", "#2e7d32", "🟢")
    if rz_today < -0.5:
        return ("Mildly oversold vs benchmark", "#558b2f", "•")
    if rz_today > 2.5:
        return ("EXTREMELY OVERBOUGHT vs benchmark", "#b71c1c", "🔴🔴")
    if rz_today > 1.5:
        return ("OVERBOUGHT vs benchmark", "#c62828", "🔴")
    if rz_today > 0.5:
        return ("Mildly overbought vs benchmark", "#d84315", "•")
    return ("NEUTRAL", "#546e7a", "—")


def _classify_own_trend(z: float):
    """Classify deviation from an asset's own log-linear trend (no benchmark)."""
    if not np.isfinite(z):
        return ("INSUFFICIENT DATA", "#666", "—")
    if z < -2.5:
        return ("Far below trend", "#1b5e20", "🟢🟢")
    if z < -1.5:
        return ("Below trend", "#2e7d32", "🟢")
    if z < -0.5:
        return ("Slightly below trend", "#558b2f", "•")
    if z > 2.5:
        return ("Far above trend", "#b71c1c", "🔴🔴")
    if z > 1.5:
        return ("Above trend", "#c62828", "🔴")
    if z > 0.5:
        return ("Slightly above trend", "#d84315", "•")
    return ("On trend", "#546e7a", "—")


def render_mean_deviation_section(assets: dict):
    """Render the full Mean & Deviation UI.

    assets: dict of {ticker_str: pd.Series of close prices indexed by date}
            Must contain at least 2 assets to enable cross-asset comparison.
    """
    st.markdown("---")
    st.markdown("## 📐 Mean Generator & Cross-Asset Deviation")
    st.caption(
        "**Trend-adjusted mean** (log-linear fit) for each visible asset, plus standardized "
        "deviation from that trend. Toggle assets above to add or remove them. The relative "
        "z-score panel measures how stretched one asset is *vs another* — a key signal that "
        "filters out moves that are just market-wide."
    )

    # Build a clean dict of (dates, prices, fit) per asset
    fits = {}
    for ticker, series in assets.items():
        s = series.dropna()
        if len(s) < 60:
            continue
        trend, log_dev, z, params = fit_log_linear_trend(s.index, s.values)
        fits[ticker] = {
            "dates": s.index,
            "prices": s.values,
            "trend": trend,
            "log_dev": log_dev,
            "z": pd.Series(z, index=s.index),
            "params": params,
        }

    if not fits:
        st.info("No assets with enough history. Toggle SOXL, QQQ, TQQQ, etc. above.")
        return

    # =========== 1. PRICE + TREND-MEAN CHART ===========
    st.markdown("### 1. Price vs trend mean (log scale)")
    st.caption("Solid lines = actual price. Dashed lines = fitted log-linear trend. "
               "When the solid is well below dashed → oversold vs its own trend. "
               "Above → overbought.")

    price_fig = go.Figure()
    for ticker, f in fits.items():
        c = ASSET_COLORS.get(ticker, "#666")
        price_fig.add_trace(go.Scatter(
            x=f["dates"], y=f["prices"], mode="lines", name=ticker,
            line=dict(color=c, width=1.8),
            hovertemplate=f"<b>{ticker}</b><br>%{{x|%Y-%m-%d}}<br>$%{{y:.2f}}<extra></extra>",
        ))
        price_fig.add_trace(go.Scatter(
            x=f["dates"], y=f["trend"], mode="lines",
            name=f"{ticker} trend ({f['params']['annual_growth_pct']:+.1f}%/yr)",
            line=dict(color=c, width=1.2, dash="dash"),
            opacity=0.85,
            hovertemplate=f"<b>{ticker} trend</b><br>%{{x|%Y-%m-%d}}<br>$%{{y:.2f}}<extra></extra>",
        ))
    price_fig.update_layout(
        height=520,
        yaxis=dict(type="log", title="Price (log scale)", gridcolor="#e0e0e0"),
        xaxis=dict(gridcolor="#e0e0e0"),
        plot_bgcolor="white",
        margin=dict(l=50, r=20, t=20, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
    )
    st.plotly_chart(price_fig, use_container_width=True)

    # =========== 2. PER-ASSET DEVIATION TABLE ===========
    st.markdown("### 2. Per-asset deviation from own trend (today)")
    st.caption("z is measured against each asset's *own* log-linear trend over its full visible history (in-sample).")
    rows = []
    for ticker, f in fits.items():
        z_today = float(f["z"].iloc[-1]) if len(f["z"]) and np.isfinite(f["z"].iloc[-1]) else np.nan
        verdict_text, _, emoji = _classify_own_trend(z_today)
        rows.append({
            "Asset": ticker,
            "Annual trend %": round(f["params"]["annual_growth_pct"], 2),
            "Today price": round(float(f["prices"][-1]), 2),
            "Trend price": round(float(f["trend"][-1]), 2),
            "Above/below trend %": round((float(f["prices"][-1]) / float(f["trend"][-1]) - 1) * 100, 1),
            "z (own trend)": round(z_today, 2) if np.isfinite(z_today) else None,
            "Signal": f"{emoji} {verdict_text}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # =========== 3. CROSS-ASSET RELATIVE Z ===========
    if len(fits) < 2:
        st.info("Toggle on at least one more asset (QQQ, TQQQ, TLT, etc.) to enable "
                "cross-asset comparison.")
        return

    st.markdown("### 3. Cross-asset relative z-score")
    st.caption("`relative_z = z_target − z_benchmark`. Filters out market-wide moves so you "
               "can see when one asset is dislocated *relative to* another.")

    tickers = list(fits.keys())
    sel_cols = st.columns(2)
    with sel_cols[0]:
        target = st.selectbox("Target asset", tickers,
                                index=tickers.index("SOXL") if "SOXL" in tickers else 0,
                                key="md_target")
    with sel_cols[1]:
        bench_opts = [t for t in tickers if t != target]
        if not bench_opts:
            st.warning("Need at least 2 different assets.")
            return
        default_bench = "QQQ" if "QQQ" in bench_opts else bench_opts[0]
        benchmark = st.selectbox("Benchmark", bench_opts,
                                   index=bench_opts.index(default_bench),
                                   key="md_bench")

    # Refit BOTH assets on their common overlap window so the z-score scales
    # come from the same sample and are directly comparable. Avoids regime bias
    # when one asset has substantially longer history than the other.
    s_t = pd.Series(fits[target]["prices"], index=fits[target]["dates"])
    s_b = pd.Series(fits[benchmark]["prices"], index=fits[benchmark]["dates"])
    overlap = s_t.index.intersection(s_b.index)
    if len(overlap) < 60:
        st.warning(f"Only {len(overlap)} overlapping dates between {target} and {benchmark} — "
                   f"need at least 60 for a meaningful comparison.")
        return

    s_t_o = s_t.loc[overlap]
    s_b_o = s_b.loc[overlap]
    _, _, z_t_o, params_t_o = fit_log_linear_trend(s_t_o.index, s_t_o.values)
    _, _, z_b_o, params_b_o = fit_log_linear_trend(s_b_o.index, s_b_o.values)
    z_t_series = pd.Series(z_t_o, index=overlap)
    z_b_series = pd.Series(z_b_o, index=overlap)
    rz = compute_relative_z(z_t_series, z_b_series)

    if rz.empty:
        st.warning(f"No overlapping dates between {target} and {benchmark}.")
        return

    rz_today = float(rz.iloc[-1])
    verdict, color, emoji = _classify_relative(rz_today)
    last_date = rz.index[-1]
    z_t_last = float(z_t_series.loc[last_date])
    z_b_last = float(z_b_series.loc[last_date])

    # Verdict card — all three z's are pinned to the SAME date (last overlap)
    st.markdown(
        f"""
        <div style="background:{color}; padding:20px 24px; border-radius:10px;
                    color:white; margin:8px 0 16px 0;">
            <div style="font-size:12px; opacity:0.85; letter-spacing:1px;">
                {target} vs {benchmark}  ·  RELATIVE DISLOCATION  ·  {last_date.strftime('%Y-%m-%d')}
            </div>
            <div style="display:flex; align-items:baseline; gap:24px; margin-top:8px;">
                <div style="font-size:48px; font-weight:800; line-height:1;">
                    {emoji} {rz_today:+.2f}σ
                </div>
                <div style="font-size:18px; font-weight:600;">{verdict}</div>
            </div>
            <div style="font-size:13px; opacity:0.9; margin-top:6px;">
                {target} z = {z_t_last:+.2f}σ  &nbsp;·&nbsp;
                {benchmark} z = {z_b_last:+.2f}σ  &nbsp;·&nbsp;
                Difference = {rz_today:+.2f}σ
            </div>
            <div style="font-size:11px; opacity:0.75; margin-top:4px;">
                Both z's refit on the common {len(overlap)}-bar overlap window
                ({overlap[0].strftime('%Y-%m-%d')} → {overlap[-1].strftime('%Y-%m-%d')})
                so their scales are directly comparable.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Relative-z chart with bands
    rz_fig = go.Figure()

    # Bands (drawn first so they're behind the line)
    band_specs = [
        (3, "rgba(198, 40, 40, 0.10)", "+3σ"),
        (2.5, "rgba(198, 40, 40, 0.18)", "+2.5σ"),
        (2, "rgba(244, 117, 96, 0.10)", "+2σ"),
        (1, "rgba(244, 117, 96, 0.05)", "+1σ"),
        (-1, "rgba(46, 125, 50, 0.05)", "-1σ"),
        (-2, "rgba(46, 125, 50, 0.10)", "-2σ"),
        (-2.5, "rgba(46, 125, 50, 0.18)", "-2.5σ"),
        (-3, "rgba(46, 125, 50, 0.10)", "-3σ"),
    ]
    for level in [1, 2, 3]:
        rz_fig.add_hline(y=level, line=dict(color="#bbb", width=0.8, dash="dot"),
                          annotation_text=f"+{level}σ", annotation_position="right",
                          annotation=dict(font=dict(size=10, color="#888")))
        rz_fig.add_hline(y=-level, line=dict(color="#bbb", width=0.8, dash="dot"),
                          annotation_text=f"-{level}σ", annotation_position="right",
                          annotation=dict(font=dict(size=10, color="#888")))
    # Signal threshold lines
    rz_fig.add_hline(y=2.5, line=dict(color="#c62828", width=1.4, dash="dash"),
                      annotation_text="OVERBOUGHT (+2.5σ)", annotation_position="left",
                      annotation=dict(font=dict(size=11, color="#c62828")))
    rz_fig.add_hline(y=-2.5, line=dict(color="#2e7d32", width=1.4, dash="dash"),
                      annotation_text="OVERSOLD (-2.5σ)", annotation_position="left",
                      annotation=dict(font=dict(size=11, color="#2e7d32")))
    rz_fig.add_hline(y=0, line=dict(color="#666", width=1))

    rz_fig.add_trace(go.Scatter(
        x=rz.index, y=rz.values, mode="lines",
        name=f"z({target}) − z({benchmark})",
        line=dict(color="#1565c0", width=1.8),
        hovertemplate="%{x|%Y-%m-%d}<br>relative z = %{y:+.2f}σ<extra></extra>",
    ))

    # Mark today
    rz_fig.add_trace(go.Scatter(
        x=[rz.index[-1]], y=[rz_today], mode="markers",
        marker=dict(size=12, color=color, line=dict(width=2, color="white")),
        showlegend=False,
        hovertemplate=f"<b>Today: {rz_today:+.2f}σ</b><extra></extra>",
    ))

    rz_fig.update_layout(
        height=420,
        yaxis=dict(title=f"z({target}) − z({benchmark})",
                   range=[max(-4, rz.min() - 0.5), min(4, rz.max() + 0.5)],
                   gridcolor="#e0e0e0", zeroline=False),
        xaxis=dict(gridcolor="#e0e0e0"),
        plot_bgcolor="white",
        margin=dict(l=60, r=80, t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(rz_fig, use_container_width=True)

    # Stats
    st.markdown("##### Historical relative-z extremes")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("Mean", f"{rz.mean():+.2f}σ")
    with s2:
        st.metric("Std dev", f"{rz.std():.2f}σ")
    with s3:
        st.metric("All-time min", f"{rz.min():+.2f}σ",
                  delta=f"{rz.idxmin().date()}", delta_color="off")
    with s4:
        st.metric("All-time max", f"{rz.max():+.2f}σ",
                  delta=f"{rz.idxmax().date()}", delta_color="off")

    pct_oversold = (rz < -2.5).mean() * 100
    pct_overbought = (rz > 2.5).mean() * 100
    st.caption(
        f"Relative z dropped below −2.5σ on **{pct_oversold:.1f}%** of days "
        f"({int((rz < -2.5).sum())} of {len(rz)}) — historical OVERSOLD setups for "
        f"buying {target} vs {benchmark}.  Rose above +2.5σ on **{pct_overbought:.1f}%** "
        f"of days ({int((rz > 2.5).sum())} of {len(rz)}) — historical OVERBOUGHT setups."
    )
    st.caption(
        "⚠️ **In-sample disclaimer.** Trends and standard deviations are fit on the full visible "
        "history including today's price. Useful as a descriptive dislocation gauge, but "
        "thresholds are optimistic if interpreted as a strict out-of-sample trading rule."
    )
