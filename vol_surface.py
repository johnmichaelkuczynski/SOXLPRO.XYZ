import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from scipy.interpolate import griddata, CubicSpline
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
def fetch_options_chain(ticker_symbol="SOXL", spread_cap=0.15, min_oi=50, min_vol=1):
    ticker = yf.Ticker(ticker_symbol)
    expirations = ticker.options
    if not expirations:
        return pd.DataFrame(), 0.0, datetime.now(), {}

    hist = ticker.history(period="5d", auto_adjust=True)
    spot = float(hist["Close"].iloc[-1])

    rows = []
    rejection_log = {}
    today = datetime.now().date()
    for exp_str in expirations:
        rej = {"spread": 0, "liquidity": 0, "iv_fail": 0, "no_quote": 0, "kept": 0}
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 7:
                continue
            t_years = max(dte, 1) / 365.0
            forward = spot * np.exp(RISK_FREE_RATE * t_years)
            chain = ticker.option_chain(exp_str)
            for kind, df in [("c", chain.calls), ("p", chain.puts)]:
                for _, row in df.iterrows():
                    bid = float(row.get("bid", 0) or 0)
                    ask = float(row.get("ask", 0) or 0)
                    strike = float(row.get("strike", 0) or 0)
                    yf_iv = float(row.get("impliedVolatility", 0) or 0)
                    vol = float(row.get("volume", 0) or 0)
                    oi = float(row.get("openInterest", 0) or 0)
                    if bid <= 0 or ask <= 0 or strike <= 0:
                        rej["no_quote"] += 1
                        continue
                    mid = (bid + ask) / 2.0
                    if mid <= 0:
                        rej["no_quote"] += 1
                        continue
                    spread_pct = (ask - bid) / mid
                    if spread_pct > spread_cap:
                        rej["spread"] += 1
                        continue
                    if oi < min_oi or vol < min_vol:
                        rej["liquidity"] += 1
                        continue
                    iv = _compute_iv_fallback(mid, spot, strike, t_years, kind)
                    if not np.isfinite(iv) or iv <= 0:
                        if yf_iv > 0:
                            iv = yf_iv
                    if not np.isfinite(iv) or iv < 0.05 or iv > 5.0:
                        rej["iv_fail"] += 1
                        continue
                    rej["kept"] += 1
                    rows.append({
                        "kind": kind,
                        "strike": strike,
                        "moneyness": strike / spot,
                        "log_moneyness": float(np.log(strike / forward)),
                        "forward": forward,
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
            rejection_log[exp_str] = rej
        except Exception:
            continue

    df = pd.DataFrame(rows)
    return df, spot, datetime.now(), rejection_log


def apply_no_arb_filters(df):
    if df.empty:
        return df, {"call_mono": 0, "put_mono": 0, "calendar": 0}

    dropped = {"call_mono": 0, "put_mono": 0, "calendar": 0}
    keep_idx = set(df.index.tolist())

    for (kind, exp), grp in df.groupby(["kind", "exp_date"]):
        grp = grp.sort_values("strike")
        prev_mid = None
        prev_idx = None
        violators = []
        for idx, r in grp.iterrows():
            if prev_mid is not None:
                if kind == "c" and r["mid"] > prev_mid + 1e-6:
                    violators.append(idx)
                    continue
                if kind == "p" and r["mid"] < prev_mid - 1e-6:
                    violators.append(idx)
                    continue
            prev_mid = r["mid"]
            prev_idx = idx
        for idx in violators:
            if idx in keep_idx:
                keep_idx.discard(idx)
                dropped["call_mono" if kind == "c" else "put_mono"] += 1

    for (kind, strike), grp in df.groupby(["kind", "strike"]):
        grp = grp.sort_values("dte")
        prev_mid = None
        for idx, r in grp.iterrows():
            if idx not in keep_idx:
                continue
            if prev_mid is not None and r["mid"] < prev_mid - 0.05:
                keep_idx.discard(idx)
                dropped["calendar"] += 1
                continue
            prev_mid = r["mid"]

    return df.loc[sorted(keep_idx)].reset_index(drop=True), dropped


def fit_per_expiry_spline(df):
    if df.empty:
        return df.assign(fitted_iv=np.nan, residual_pct=np.nan)
    df = df.copy()
    df["fitted_iv"] = np.nan
    for exp, grp in df.groupby("exp_date"):
        grp = grp.sort_values("log_moneyness")
        x = grp["log_moneyness"].values
        y = grp["iv"].values
        if len(x) < 4:
            continue
        ux, ui = np.unique(x, return_index=True)
        if len(ux) < 4:
            continue
        uy = y[ui]
        try:
            spline = CubicSpline(ux, uy, bc_type="natural", extrapolate=False)
            for idx in grp.index:
                lm = df.loc[idx, "log_moneyness"]
                fit_val = float(spline(lm))
                if np.isfinite(fit_val) and fit_val > 0:
                    df.loc[idx, "fitted_iv"] = fit_val
        except Exception:
            continue
    df["residual_pct"] = (df["iv"] - df["fitted_iv"]) / df["fitted_iv"]
    return df


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


def detect_anomalies(df_fitted, residual_thresh=0.05):
    if df_fitted.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = df_fitted.dropna(subset=["fitted_iv", "residual_pct"]).copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    sd = df["residual_pct"].std(ddof=1)
    if not sd or not np.isfinite(sd) or sd == 0:
        df["z"] = 0.0
    else:
        df["z"] = df["residual_pct"] / sd

    buys = df[df["residual_pct"] < -residual_thresh].copy()
    sells = df[df["residual_pct"] > residual_thresh].copy()

    buys = buys.sort_values("z", ascending=True)
    sells = sells.sort_values("z", ascending=False)
    return buys, sells


def _kind_label(kind):
    return "Call" if kind == "c" else "Put"


def render_signals_table(df_signals, side):
    if side == "sell":
        bg = "#FFEBEE"
        border = "#D32F2F"
        title_color = "#B71C1C"
        title = "SELL CANDIDATES (overpriced — market IV > fitted)"
    else:
        bg = "#E8F5E9"
        border = "#2E7D32"
        title_color = "#1B5E20"
        title = "BUY CANDIDATES (underpriced — market IV < fitted)"

    st.markdown(
        f"<div style='background:{bg}; border-left:5px solid {border}; padding:8px 14px; "
        f"border-radius:6px; margin:8px 0 4px 0;'>"
        f"<span style='font-weight:800; color:{title_color}; font-size:14px;'>{title}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if df_signals.empty:
        st.markdown(
            f"<div style='padding:8px 14px; color:#888; font-style:italic;'>None</div>",
            unsafe_allow_html=True,
        )
        return

    show = df_signals.copy()
    show["Contract"] = show.apply(
        lambda r: f"${r['strike']:.0f} {_kind_label(r['kind'])} "
                  f"{datetime.strptime(r['exp_date'], '%Y-%m-%d').strftime('%b %Y')}",
        axis=1,
    )
    show["Expiry"] = show["exp_date"].apply(
        lambda s: datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    )
    show["DTE"] = show["dte"].astype(int)
    show["Bid"] = show["bid"].round(2)
    show["Ask"] = show["ask"].round(2)
    show["Mid"] = show["mid"].round(2)
    show["Mkt IV %"] = (show["iv"] * 100).round(1)
    show["Fit IV %"] = (show["fitted_iv"] * 100).round(1)
    show["Residual %"] = (show["residual_pct"] * 100).round(1)
    show["Z"] = show["z"].round(2)
    show["OI"] = show["open_interest"].astype(int)
    show["Vol"] = show["volume"].astype(int)
    cols = ["Contract", "Expiry", "DTE", "Bid", "Ask", "Mid",
            "Mkt IV %", "Fit IV %", "Residual %", "Z", "OI", "Vol"]
    st.dataframe(show[cols], use_container_width=True, hide_index=True)


@st.cache_data(ttl=3600, show_spinner=False)
def compute_iv_rank_panel(ticker_symbol="SOXL"):
    try:
        hist = yf.Ticker(ticker_symbol).history(period="2y", auto_adjust=True)
        if len(hist) < 60:
            return None
        ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        rv30 = ret.rolling(30).std() * np.sqrt(252)
        rv30 = rv30.dropna()
        if len(rv30) < 30:
            return None
        recent = rv30.tail(252)
        current = float(rv30.iloc[-1])
        lo = float(recent.min())
        hi = float(recent.max())
        if hi - lo <= 0:
            rank = 50.0
        else:
            rank = (current - lo) / (hi - lo) * 100
        return {
            "current_rv30": current,
            "year_low": lo,
            "year_high": hi,
            "rank_pct": rank,
        }
    except Exception:
        return None


def render_iv_rank_panel(rv_info, atm_iv30):
    if rv_info is None:
        st.info("Realized vol history unavailable.")
        return
    current_rv = rv_info["current_rv30"] * 100
    lo = rv_info["year_low"] * 100
    hi = rv_info["year_high"] * 100
    rank = rv_info["rank_pct"]
    if rank < 25:
        verdict = "CHEAP"
        color = "#2E7D32"
    elif rank > 75:
        verdict = "EXPENSIVE"
        color = "#D32F2F"
    else:
        verdict = "MID-RANGE"
        color = "#F57C00"

    iv_text = f"{atm_iv30*100:.1f}%" if atm_iv30 else "N/A"

    st.markdown(
        f"<div style='background:#F5F5F5; border-left:5px solid {color}; "
        f"padding:10px 14px; border-radius:6px; margin:6px 0 12px 0;'>"
        f"<span style='font-weight:800; color:{color}; font-size:14px;'>"
        f"VOL REGIME: {verdict}</span>"
        f"<span style='float:right; font-size:13px; color:#555;'>"
        f"30d ATM IV: <b>{iv_text}</b> · "
        f"30d Realized: <b>{current_rv:.1f}%</b> · "
        f"1y range: {lo:.1f}% – {hi:.1f}% · "
        f"Rank: <b>{rank:.0f}</b>/100</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


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


def _process_kind(df_kind):
    pre = len(df_kind)
    cleaned = filter_local_outliers(df_kind)
    after_outlier = len(cleaned)
    cleaned, no_arb_dropped = apply_no_arb_filters(cleaned)
    after_noarb = len(cleaned)
    fitted = fit_per_expiry_spline(cleaned)
    return fitted, {
        "pre": pre,
        "outliers": pre - after_outlier,
        "no_arb": after_outlier - after_noarb,
        "final": after_noarb,
        "no_arb_breakdown": no_arb_dropped,
    }


def render_vol_surface_tab():
    st.markdown("### SOXL Implied Volatility Surface")
    st.caption(
        "Calls and puts are fit as separate surfaces in (log-moneyness, time) space using "
        "per-expiry cubic splines. Recommendations are flagged when market IV diverges from "
        "the fitted surface by more than 5% AND the contract passes liquidity / no-arbitrage gates."
    )

    col_mode, col_refresh = st.columns([3, 1])
    with col_mode:
        mode = st.radio(
            "Surface to display",
            ["Calls", "Puts"],
            horizontal=True,
            key="vol_surface_mode",
        )
    with col_refresh:
        st.write("")
        if st.button("🔄 Refresh now", use_container_width=True):
            fetch_options_chain.clear()
            compute_iv_rank_panel.clear()
            st.rerun()

    with st.spinner("Fetching SOXL option chain..."):
        df, spot, fetched_at, rejection_log = fetch_options_chain("SOXL")

    if df.empty:
        st.error("No usable options data returned. The chain may be empty or the source is unavailable.")
        return

    calls_df = df[df["kind"] == "c"].copy()
    puts_df = df[df["kind"] == "p"].copy()
    calls_fitted, calls_stats = _process_kind(calls_df)
    puts_fitted, puts_stats = _process_kind(puts_df)

    rv_info = compute_iv_rank_panel("SOXL")
    atm_iv30 = atm_iv_for_dte(calls_fitted if mode == "Calls" else puts_fitted, 30)
    render_iv_rank_panel(rv_info, atm_iv30)

    info_cols = st.columns(4)
    surface_df = calls_fitted if mode == "Calls" else puts_fitted
    iv30 = atm_iv_for_dte(surface_df, 30)
    iv90 = atm_iv_for_dte(surface_df, 90)
    iv365 = atm_iv_for_dte(surface_df, 365)

    with info_cols[0]:
        st.metric("Spot", f"${spot:.2f}", help="Current SOXL price")
    with info_cols[1]:
        v = f"{iv30*100:.1f}%" if iv30 else "N/A"
        v90 = f"{iv90*100:.1f}%" if iv90 else "N/A"
        v365 = f"{iv365*100:.1f}%" if iv365 else "N/A"
        st.metric(f"{mode} ATM IV — 30d", v, help=f"90d: {v90} · 365d: {v365}")
    with info_cols[2]:
        st.metric(f"{mode} contracts", f"{len(surface_df)}",
                  help=f"After mid-IV, 15% spread cap, OI≥50, vol≥1, no-arb, outlier filters")
    with info_cols[3]:
        if iv30 and iv90:
            slope = (iv90 - iv30) * 100
            st.metric(f"{mode} Term Slope (90d−30d)", f"{slope:+.1f}%",
                      help="Positive = contango.")
        else:
            st.metric(f"{mode} Term Slope (90d−30d)", "N/A")

    st.caption(
        f"Fetched: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')} · "
        f"Calls: {calls_stats['final']} kept ({calls_stats['outliers']} outliers, "
        f"{calls_stats['no_arb']} no-arb) · "
        f"Puts: {puts_stats['final']} kept ({puts_stats['outliers']} outliers, "
        f"{puts_stats['no_arb']} no-arb) · "
        f"py_vollib mid-IV: {HAS_VOLLIB}"
    )

    grid_money, grid_days, iv_grid = build_surface_grid(surface_df)
    if iv_grid is None:
        st.warning(f"Not enough clean {mode.lower()} contracts ({len(surface_df)}) to build a surface.")
    else:
        title = f"SOXL {mode} IV Surface — {fetched_at.strftime('%Y-%m-%d %H:%M')}"
        fig = render_surface_figure(grid_money, grid_days, iv_grid, spot, title)
        st.plotly_chart(fig, use_container_width=True)

    calls_buys, calls_sells = detect_anomalies(calls_fitted)
    puts_buys, puts_sells = detect_anomalies(puts_fitted)
    all_buys = pd.concat([calls_buys, puts_buys], ignore_index=True) if not (calls_buys.empty and puts_buys.empty) else pd.DataFrame()
    all_sells = pd.concat([calls_sells, puts_sells], ignore_index=True) if not (calls_sells.empty and puts_sells.empty) else pd.DataFrame()

    if not all_buys.empty:
        all_buys = all_buys.sort_values("z", ascending=True)
    if not all_sells.empty:
        all_sells = all_sells.sort_values("z", ascending=False)

    if all_buys.empty and all_sells.empty:
        st.info("No definitive buy/sell signals. All surface deviations within noise margin "
                "(|residual| < 5%) or filtered out by liquidity / no-arb gates.")

    bcol, scol = st.columns(2)
    with bcol:
        render_signals_table(all_buys, "buy")
    with scol:
        render_signals_table(all_sells, "sell")

    with st.expander("Per-expiry rejection diagnostics"):
        if rejection_log:
            rej_df = pd.DataFrame(rejection_log).T.fillna(0).astype(int)
            rej_df.index.name = "expiry"
            rej_df = rej_df.reset_index()
            st.dataframe(rej_df, use_container_width=True, hide_index=True)

    with st.expander("Show raw fitted contracts (current surface)"):
        if not surface_df.empty:
            show = surface_df.copy()
            show["iv_pct"] = (show["iv"] * 100).round(1)
            show["fit_pct"] = (show["fitted_iv"] * 100).round(1)
            show["resid_pct"] = (show["residual_pct"] * 100).round(1)
            cols = ["kind", "strike", "exp_date", "dte", "moneyness", "log_moneyness",
                    "bid", "ask", "mid", "iv_pct", "fit_pct", "resid_pct",
                    "volume", "open_interest"]
            st.dataframe(
                show[cols].sort_values(["dte", "strike"]),
                use_container_width=True, hide_index=True,
            )
