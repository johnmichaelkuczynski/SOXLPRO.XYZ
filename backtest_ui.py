import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from data_providers import (
    get_equity_history, get_options_snapshot, get_option_history,
    equity_max_start_date, options_max_start_date,
    EQUITY_MAX_YEARS, OPTIONS_MAX_YEARS,
)
from backtest_engine import (
    equity_curve_from_returns, buy_and_hold_curve, compute_stats,
    random_entry_baseline, render_equity_chart, render_calibration_chart,
    DISCLAIMER, TRADING_DAYS,
    build_report_text, build_report_csv, build_report_docx, build_report_pdf,
    safe_filename,
)
from datetime import datetime as _dt2
from custom_strategy import (
    ALL_INDICATORS, INDICATORS_NEEDS_N, OPERATORS, DEFAULT_N, DEFAULT_N2,
    APP_SIGNALS_CATEGORICAL, APP_SIGNALS_NUMERIC_TWO_PARAM,
    NEEDS_OPTIONS_DATA, OPTIONS_WINDOW_START, SIGNAL_VERSION,
    compute_indicator, simulate_custom_strategy, describe_panel,
    load_all_strategies, save_strategy, delete_strategy,
    panel_uses_options_signals, is_categorical_signal, strategy_uses_app_signals,
)


def _date_range_picker(key_prefix, max_years=EQUITY_MAX_YEARS):
    today = datetime.now().date()
    min_date = today - timedelta(days=max_years * 365)
    c1, c2 = st.columns(2)
    with c1:
        start = st.date_input(
            "Backtest start", value=min_date,
            min_value=min_date, max_value=today - timedelta(days=30),
            key=f"{key_prefix}_start",
        )
    with c2:
        end = st.date_input(
            "Backtest end", value=today,
            min_value=start + timedelta(days=30), max_value=today,
            key=f"{key_prefix}_end",
        )
    return start, end


def _slice(df, start, end):
    return df[(df.index.date >= start) & (df.index.date <= end)]


def _load_equities(start, end):
    soxl = get_equity_history("SOXL")
    qqq = get_equity_history("QQQ")
    return _slice(soxl, start, end), _slice(qqq, start, end)


def _render_results(strategy_eq, soxl_df, qqq_df, trade_returns, holding_days, title,
                    params=None, methodology=None):
    soxl_bh = buy_and_hold_curve(soxl_df["adj_close"])
    qqq_bh = buy_and_hold_curve(qqq_df["adj_close"])
    rand_eq, rand_trades = random_entry_baseline(
        soxl_df["adj_close"], n_trades=max(len(trade_returns), 1),
        holding_days=max(holding_days, 1),
    )
    fig = render_equity_chart({
        "Strategy": strategy_eq,
        "SOXL Buy & Hold": soxl_bh,
        "QQQ Buy & Hold": qqq_bh,
        "Random Entry Baseline": rand_eq,
    }, title=title)
    st.plotly_chart(fig, use_container_width=True)

    stats_rows = [
        {"Series": "Strategy",                **compute_stats(strategy_eq, returns=pd.Series(trade_returns), n_trades=len(trade_returns))},
        {"Series": "SOXL Buy & Hold",         **compute_stats(soxl_bh)},
        {"Series": "QQQ Buy & Hold",          **compute_stats(qqq_bh)},
        {"Series": "Random Entry Baseline",   **compute_stats(rand_eq, returns=pd.Series(rand_trades), n_trades=len(rand_trades))},
    ]
    st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)
    st.caption(DISCLAIMER)
    _render_download_buttons(title, params, methodology, stats_rows,
                              date_range=(soxl_df.index.min().date(), soxl_df.index.max().date()))


def _render_download_buttons(title, params, methodology, stats_rows, date_range=None, key_suffix=""):
    st.markdown("**Download report**")
    fname = safe_filename(title)
    stamp = _dt2.now().strftime("%Y%m%d_%H%M%S")
    base = f"{fname}_{stamp}"
    txt = build_report_text(title, params, methodology, stats_rows, date_range)
    csv = build_report_csv(stats_rows)
    docx_bytes = build_report_docx(title, params, methodology, stats_rows, date_range)
    pdf_bytes = build_report_pdf(title, params, methodology, stats_rows, date_range)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.download_button("📄 TXT", txt, file_name=f"{base}.txt",
                           mime="text/plain", key=f"dl_txt_{base}{key_suffix}")
    with c2:
        st.download_button("📊 CSV (stats)", csv, file_name=f"{base}.csv",
                           mime="text/csv", key=f"dl_csv_{base}{key_suffix}")
    with c3:
        st.download_button("📝 Word (.docx)", docx_bytes, file_name=f"{base}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           key=f"dl_docx_{base}{key_suffix}")
    with c4:
        st.download_button("📕 PDF", pdf_bytes, file_name=f"{base}.pdf",
                           mime="application/pdf", key=f"dl_pdf_{base}{key_suffix}")


# ----------------------------------------------------------------------------
# 1. Period Analysis backtest
# ----------------------------------------------------------------------------
def _period_analysis_tab():
    st.markdown("#### Period Analysis Backtest")
    st.caption(
        "Strategy: at every historical day, look at SOXL's trailing-window performance and "
        "go LONG if the trailing window had a drawdown beyond the threshold (mean-reversion bet). "
        "Hold for `horizon` days, then exit."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        lookback = st.number_input("Lookback window (days)", 5, 252, 30, key="pa_lookback")
    with c2:
        threshold = st.number_input("Drawdown trigger (%)", 1.0, 50.0, 15.0, step=1.0, key="pa_thresh")
    with c3:
        horizon = st.number_input("Holding period (days)", 1, 252, 21, key="pa_horizon")
    start, end = _date_range_picker("pa")

    if st.button("Run backtest", key="pa_run", type="primary"):
        soxl_df, qqq_df = _load_equities(start, end)
        if soxl_df.empty:
            st.error("No SOXL data in the selected range.")
            return
        prices = soxl_df["adj_close"].values
        idx = soxl_df.index
        timeline = pd.Series(0.0, index=idx)
        trade_returns = []
        i = lookback
        while i < len(prices) - horizon - 1:
            window_ret = (prices[i] - prices[i - lookback]) / prices[i - lookback] * 100
            if window_ret <= -threshold:
                entry = prices[i]
                exit_ = prices[i + horizon]
                r = exit_ / entry - 1
                trade_returns.append(float(r))
                daily = (1 + r) ** (1 / horizon) - 1
                for k in range(1, horizon + 1):
                    timeline.iloc[i + k] += daily
                i += horizon
            else:
                i += 1
        if not trade_returns:
            st.warning("No qualifying triggers in this range. Loosen threshold or extend dates.")
            return
        eq = (1 + timeline).cumprod()
        _render_results(eq, soxl_df, qqq_df, trade_returns, horizon,
                        f"Period Analysis — buy after −{threshold}% in {lookback}d, hold {horizon}d",
                        params={"lookback_days": lookback, "drawdown_trigger_%": threshold,
                                "holding_days": horizon, "start": start, "end": end},
                        methodology=(
                            "At every trading day, look at SOXL's trailing-window return over "
                            f"the last {lookback} days. If the trailing return is at or below "
                            f"−{threshold}%, enter long at that day's adjusted close and hold "
                            f"for {horizon} trading days. Returns are compounded multiplicatively "
                            "to preserve the path-dependent behavior of the leveraged ETF. "
                            "Random Entry Baseline draws the same number of entries at random "
                            "from the same date range with identical holding period."
                        ))


# ----------------------------------------------------------------------------
# 2. Probability Engine backtest — calibration / Brier (NOT P&L)
# ----------------------------------------------------------------------------
def _probability_engine_tab():
    st.markdown("#### Probability Engine Backtest")
    st.caption(
        "Forecast accuracy test. At every historical date, the engine estimates the probability that "
        "SOXL will move at least M% in EITHER direction over the next H days, using only data available "
        "at that point. We then compare those forecasts to what actually happened."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        magnitude = st.number_input("Move size M (%)", 1.0, 50.0, 15.0, step=1.0, key="pe_mag")
    with c2:
        horizon = st.number_input("Horizon H (days)", 1, 126, 21, key="pe_h")
    with c3:
        train_window = st.number_input("Rolling train window (days)", 60, 1500, 504, step=21, key="pe_tw")
    start, end = _date_range_picker("pe")

    if st.button("Run backtest", key="pe_run", type="primary"):
        soxl_df, _ = _load_equities(start, end)
        if soxl_df.empty:
            st.error("No SOXL data.")
            return
        prices = soxl_df["adj_close"].values
        idx = soxl_df.index
        preds, outcomes, dates = [], [], []
        for i in range(train_window, len(prices) - horizon - 1):
            train = prices[i - train_window:i]
            n_train_periods = len(train) - horizon
            if n_train_periods < 30:
                continue
            train_returns = (train[horizon:] - train[:-horizon]) / train[:-horizon] * 100
            p_hit = float((np.abs(train_returns) >= magnitude).mean())
            actual = (prices[i + horizon] - prices[i]) / prices[i] * 100
            outcome = 1.0 if abs(actual) >= magnitude else 0.0
            preds.append(p_hit)
            outcomes.append(outcome)
            dates.append(idx[i])
        if not preds:
            st.warning("Not enough data — extend date range or shorten train window.")
            return
        fig, brier = render_calibration_chart(preds, outcomes, n_bins=10)
        st.plotly_chart(fig, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Forecasts evaluated", f"{len(preds):,}")
        c2.metric("Brier score", f"{brier:.4f}", help="Lower is better. Naïve always-50% = 0.25.")
        naive_brier = float(np.mean((np.full_like(outcomes, np.mean(outcomes)) - outcomes) ** 2))
        c3.metric("Climatology Brier", f"{naive_brier:.4f}",
                  help="Brier score of always predicting the historical base rate. Beat this to add value.")
        st.markdown(f"**Mean predicted probability:** {np.mean(preds):.2%} · "
                    f"**Realized base rate:** {np.mean(outcomes):.2%}")
        forecast_df = pd.DataFrame({
            "date": dates,
            "predicted_prob": np.round(preds, 4),
            "realized": np.array(outcomes, dtype=int),
        })
        with st.expander("Show forecast log"):
            st.dataframe(forecast_df.tail(200), use_container_width=True, hide_index=True)
        st.caption(DISCLAIMER)

        title = f"Probability Engine — {magnitude}% move within {horizon}d"
        stats_rows = [
            {"Series": "Engine forecast",       "forecasts": len(preds),
             "Brier_score": round(brier, 4),    "mean_predicted_%": round(np.mean(preds) * 100, 2),
             "realized_base_rate_%": round(np.mean(outcomes) * 100, 2)},
            {"Series": "Climatology baseline",  "forecasts": len(preds),
             "Brier_score": round(naive_brier, 4), "mean_predicted_%": round(np.mean(outcomes) * 100, 2),
             "realized_base_rate_%": round(np.mean(outcomes) * 100, 2)},
        ]
        _render_download_buttons(
            title,
            params={"magnitude_%": magnitude, "horizon_days": horizon,
                    "rolling_train_window_days": train_window, "start": start, "end": end,
                    "n_bins": 10},
            methodology=(
                "Forecast accuracy test (NOT a P&L test). At every historical date t, the "
                f"engine uses only the prior {train_window} days of SOXL data to estimate "
                f"P(|return_{horizon}d| ≥ {magnitude}%) by counting empirical exceedances. "
                "We then observe the actual outcome over the next "
                f"{horizon} days. Calibration plot bins predicted probabilities and compares "
                "to observed frequencies. Brier score = mean((predicted − realized)²); "
                "lower is better. The climatology baseline always predicts the historical "
                "base rate of the same outcome — beat it to demonstrate skill."
            ),
            stats_rows=stats_rows,
            date_range=(start, end),
        )


# ----------------------------------------------------------------------------
# 3. Vol Regime backtest
# ----------------------------------------------------------------------------
def _vol_regime_tab():
    st.markdown("#### Vol Regime Backtest")
    st.caption(
        "Strategy: classify each day's 30-day realized vol into LOW/MID/HIGH percentile bands "
        "(vs trailing 1y). Go long SOXL when in the LOW band; cash otherwise. Compare to buy-and-hold."
    )
    c1, c2 = st.columns(2)
    with c1:
        lo_pct = st.slider("LOW threshold (percentile)", 10, 50, 25, key="vr_lo")
    with c2:
        hi_pct = st.slider("HIGH threshold (percentile)", 50, 90, 75, key="vr_hi")
    start, end = _date_range_picker("vr")

    if st.button("Run backtest", key="vr_run", type="primary"):
        soxl_df, qqq_df = _load_equities(start, end)
        if soxl_df.empty:
            st.error("No SOXL data.")
            return
        rets = soxl_df["log_ret"].dropna()
        rv30 = rets.rolling(30).std() * np.sqrt(252)
        signals = pd.Series(0, index=soxl_df.index, dtype=float)
        for i in range(252, len(rv30)):
            window = rv30.iloc[i - 252:i].dropna()
            if len(window) < 60:
                continue
            cur = rv30.iloc[i]
            if not np.isfinite(cur):
                continue
            lo = np.percentile(window, lo_pct)
            hi = np.percentile(window, hi_pct)
            if cur <= lo:
                signals.iloc[i] = 1.0
        # Strategy returns: long SOXL when signal == 1 (use prior day's signal to avoid lookahead)
        positions = signals.shift(1).fillna(0.0)
        strat_returns = positions * soxl_df["ret"].fillna(0.0)
        eq = (1 + strat_returns).cumprod()
        # synthesize trade list as runs of in-position
        in_pos = positions > 0
        runs = (in_pos != in_pos.shift()).cumsum()[in_pos]
        trade_returns = []
        if len(runs) > 0:
            for _, grp in soxl_df["ret"].groupby(runs):
                trade_returns.append(float((1 + grp).prod() - 1))
        avg_holding = max(int(in_pos.sum() / max(len(set(runs)), 1)), 1) if len(runs) else 1
        _render_results(eq, soxl_df, qqq_df, trade_returns, avg_holding,
                        f"Vol Regime — long SOXL when 30d realized vol ≤ {lo_pct}th pct (1y)",
                        params={"low_threshold_pctile": lo_pct, "high_threshold_pctile": hi_pct,
                                "realized_vol_window_days": 30, "lookback_for_pctile_days": 252,
                                "start": start, "end": end},
                        methodology=(
                            "Compute SOXL's 30-day realized volatility (annualized). At each "
                            "day, classify it against the trailing 252-day distribution. Hold "
                            f"long SOXL on days where current RV ≤ {lo_pct}th percentile; "
                            "cash otherwise. Uses prior-day signal (lag 1) to avoid lookahead."
                        ))


# ----------------------------------------------------------------------------
# 4. SOXL-QQQ Dislocation backtest
# ----------------------------------------------------------------------------
def _dislocation_tab():
    st.markdown("#### SOXL-QQQ Dislocation Backtest")
    st.caption(
        "Strategy: compute rolling-beta residual z-score (β=20d, residual=20d). "
        "Enter LONG SOXL when z < −entry, exit when |z| < exit_thresh OR after max_days. "
        "Models leverage decay catch-up trades."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        z_entry = st.number_input("Entry z-score (long when z < −X)", 1.0, 4.0, 2.0, step=0.1, key="dx_entry")
    with c2:
        z_exit = st.number_input("Exit z-score (close when |z| < X)", 0.0, 2.0, 0.5, step=0.1, key="dx_exit")
    with c3:
        max_days = st.number_input("Max holding days", 1, 60, 10, key="dx_max")
    start, end = _date_range_picker("dx")

    if st.button("Run backtest", key="dx_run", type="primary"):
        soxl_df, qqq_df = _load_equities(start, end)
        if soxl_df.empty or qqq_df.empty:
            st.error("Missing data.")
            return
        common = soxl_df.index.intersection(qqq_df.index)
        soxl_r = soxl_df.loc[common, "log_ret"]
        qqq_r = qqq_df.loc[common, "log_ret"]
        soxl_p = soxl_df.loc[common, "adj_close"]
        beta = soxl_r.rolling(20).cov(qqq_r) / qqq_r.rolling(20).var()
        residual = soxl_r - beta * qqq_r
        cumres = residual.rolling(20).sum()
        z = (cumres - cumres.rolling(252).mean()) / cumres.rolling(252).std(ddof=1)

        timeline = pd.Series(0.0, index=common)
        trade_returns = []
        i = 252
        while i < len(z) - max_days - 1:
            zi = z.iloc[i]
            if np.isfinite(zi) and zi < -z_entry:
                entry_p = soxl_p.iloc[i]
                exit_idx = None
                for k in range(1, max_days + 1):
                    zk = z.iloc[i + k]
                    if np.isfinite(zk) and abs(zk) < z_exit:
                        exit_idx = i + k
                        break
                if exit_idx is None:
                    exit_idx = i + max_days
                exit_p = soxl_p.iloc[exit_idx]
                r = exit_p / entry_p - 1
                trade_returns.append(float(r))
                hd = exit_idx - i
                daily = (1 + r) ** (1 / hd) - 1
                for k in range(1, hd + 1):
                    timeline.iloc[i + k] += daily
                i = exit_idx + 1
            else:
                i += 1
        if not trade_returns:
            st.warning("No qualifying entries in this range.")
            return
        eq = (1 + timeline).cumprod()
        _render_results(eq, soxl_df.loc[common], qqq_df.loc[common], trade_returns, max_days,
                        f"Dislocation — long when z < −{z_entry}, exit |z| < {z_exit} or {max_days}d",
                        params={"entry_z": z_entry, "exit_z": z_exit,
                                "max_holding_days": max_days, "beta_window_days": 20,
                                "residual_window_days": 20, "z_lookback_days": 252,
                                "start": start, "end": end},
                        methodology=(
                            "Estimate SOXL's rolling 20-day beta to QQQ. Compute the daily "
                            "log-return residual = SOXL_logret − β × QQQ_logret. Sum residuals "
                            "over a 20-day rolling window and z-score against the 252-day "
                            f"history. Enter long SOXL when z < −{z_entry} (SOXL has "
                            f"underperformed its beta-adjusted expectation). Exit when |z| < "
                            f"{z_exit} or after {max_days} days, whichever comes first."
                        ))


# ----------------------------------------------------------------------------
# 5. Strategy Builder backtest (walk-forward, level-based)
# ----------------------------------------------------------------------------
def _strategy_builder_tab():
    st.markdown("#### Strategy Builder Backtest")
    st.caption(
        "The Strategy Builder produces structured entry/stop/target levels via Claude. "
        "Rather than re-running Claude at every historical date (slow + expensive), this "
        "backtest grades a generic level-based strategy: enter when SOXL falls to your entry, "
        "exit at target OR stop OR after max horizon. Provide the same level structure Claude returns."
    )
    walk_fwd = st.checkbox("Walk-forward test (recommended)", value=True, key="sb_wf",
                          help="Splits the date range 70/30 train/test and evaluates only on the held-out 30%.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        entry_pct = st.number_input("Entry: % below recent high", 0.0, 80.0, 20.0, step=1.0, key="sb_entry")
    with c2:
        target_pct = st.number_input("Target: % above entry", 1.0, 200.0, 30.0, step=1.0, key="sb_target")
    with c3:
        stop_pct = st.number_input("Stop: % below entry", 1.0, 50.0, 15.0, step=1.0, key="sb_stop")
    with c4:
        max_hold = st.number_input("Max horizon (days)", 5, 504, 126, key="sb_hold")
    high_window = st.slider("Recent-high lookback window (days)", 20, 252, 90, key="sb_hw")
    start, end = _date_range_picker("sb")

    if st.button("Run backtest", key="sb_run", type="primary"):
        soxl_df, qqq_df = _load_equities(start, end)
        if soxl_df.empty:
            st.error("No SOXL data.")
            return
        full_idx = soxl_df.index
        if walk_fwd:
            split = int(len(full_idx) * 0.7)
            test_start = full_idx[split]
            st.info(f"Walk-forward: training on {full_idx[0].date()} → {test_start.date()}, "
                    f"testing on {test_start.date()} → {full_idx[-1].date()}")
            test_df = soxl_df.loc[test_start:]
        else:
            test_df = soxl_df

        prices = test_df["adj_close"].values
        idx = test_df.index
        timeline = pd.Series(0.0, index=idx)
        trade_returns = []
        i = high_window
        while i < len(prices) - max_hold - 1:
            recent_high = max(prices[max(0, i - high_window):i])
            entry_target = recent_high * (1 - entry_pct / 100)
            if prices[i] <= entry_target:
                entry = prices[i]
                target = entry * (1 + target_pct / 100)
                stop = entry * (1 - stop_pct / 100)
                exit_idx = i + max_hold
                for k in range(1, max_hold + 1):
                    p = prices[i + k]
                    if p >= target or p <= stop:
                        exit_idx = i + k
                        break
                exit_p = prices[exit_idx]
                r = exit_p / entry - 1
                trade_returns.append(float(r))
                hd = exit_idx - i
                daily = (1 + r) ** (1 / hd) - 1
                for k in range(1, hd + 1):
                    timeline.iloc[i + k] += daily
                i = exit_idx + 1
            else:
                i += 1
        if not trade_returns:
            st.warning("No entry triggers in this range.")
            return
        eq = (1 + timeline).cumprod()
        _render_results(eq, test_df, qqq_df.loc[test_df.index[0]:], trade_returns, max_hold,
                        f"Strategy Builder — entry {entry_pct}% below {high_window}d high, "
                        f"target +{target_pct}%, stop −{stop_pct}%, max {max_hold}d",
                        params={"entry_pct_below_high": entry_pct, "target_pct": target_pct,
                                "stop_pct": stop_pct, "max_holding_days": max_hold,
                                "high_window_days": high_window, "walk_forward": walk_fwd,
                                "start": start, "end": end},
                        methodology=(
                            "Level-based entry/exit grader for the Strategy Builder skeleton. "
                            f"At each day, find the highest close over the trailing "
                            f"{high_window} days. If today's close has retraced ≥{entry_pct}% "
                            f"from that high, enter long. Exit when price reaches +{target_pct}% "
                            f"(target), or falls −{stop_pct}% (stop), or after {max_hold} days. "
                            + ("Walk-forward: 70% of date range used as training (excluded); "
                               "results shown only for the held-out 30% test window."
                               if walk_fwd else "Full-period in-sample evaluation (no walk-forward).")
                        ))


# ----------------------------------------------------------------------------
# 6. Vol Surface BUY/SELL backtest (LIMITED — 4y options history)
# ----------------------------------------------------------------------------
def _vol_surface_tab():
    st.markdown("#### Vol Surface Signals Backtest")
    st.warning("**Limited — 4 years options history only (2022–present).** "
               "Results may not generalize across regimes.")
    st.caption(
        "Approximation backtest: for each of N current BUY/SELL signals, pulls Polygon's daily "
        "history for that contract and measures realized vs entry mid-price after the user-set "
        "holding period. Note: this grades CURRENT signals against past data — not a true "
        "walk-forward of historical surface fits, which would require building the IV surface "
        "at every past date (computationally enormous)."
    )
    c1, c2 = st.columns(2)
    with c1:
        max_contracts = st.number_input("Max contracts to evaluate", 5, 100, 20, key="vs_n")
    with c2:
        holding_days = st.number_input("Holding period (calendar days)", 1, 60, 10, key="vs_h")
    today = datetime.now().date()
    min_date = today - timedelta(days=OPTIONS_MAX_YEARS * 365)
    eval_end = st.date_input("Evaluation cutoff", value=today - timedelta(days=holding_days + 5),
                              min_value=min_date, max_value=today - timedelta(days=holding_days + 1),
                              key="vs_end")

    if st.button("Run backtest", key="vs_run", type="primary"):
        with st.spinner("Pulling SOXL options snapshot..."):
            chain = get_options_snapshot("SOXL", limit=250)
        if chain.empty:
            st.error("No options snapshot returned.")
            return
        # Pick the most active liquid contracts as proxy for "signals"
        chain = chain.dropna(subset=["bid", "ask", "open_interest", "volume", "ticker"])
        chain = chain[(chain["bid"] > 0) & (chain["ask"] > 0) &
                      (chain["open_interest"] >= 50) & (chain["volume"] >= 1)]
        chain["mid"] = (chain["bid"] + chain["ask"]) / 2
        chain = chain.sort_values("volume", ascending=False).head(int(max_contracts))
        if chain.empty:
            st.warning("No liquid contracts to test.")
            return

        from_date = (eval_end - timedelta(days=holding_days + 30)).isoformat()
        to_date = eval_end.isoformat()
        results = []
        progress = st.progress(0.0)
        for j, (_, row) in enumerate(chain.iterrows(), 1):
            hist = get_option_history(row["ticker"], from_date, to_date)
            if hist.empty or len(hist) < 2:
                results.append({**row.to_dict(), "realized_close": np.nan, "pnl_pct": np.nan})
            else:
                entry = float(hist["close"].iloc[0])
                exit_ = float(hist["close"].iloc[-1])
                results.append({
                    **row.to_dict(),
                    "entry_close": round(entry, 3),
                    "exit_close": round(exit_, 3),
                    "pnl_pct": round((exit_ / entry - 1) * 100, 2) if entry > 0 else np.nan,
                    "days_observed": len(hist),
                })
            progress.progress(j / len(chain))
        progress.empty()
        rdf = pd.DataFrame(results)
        if "pnl_pct" in rdf.columns and rdf["pnl_pct"].notna().any():
            mean_pnl = rdf["pnl_pct"].mean()
            win_rate = (rdf["pnl_pct"] > 0).mean() * 100
            c1, c2, c3 = st.columns(3)
            c1.metric("Contracts evaluated", f"{rdf['pnl_pct'].notna().sum()}")
            c2.metric("Mean P&L", f"{mean_pnl:+.2f}%")
            c3.metric("Win rate", f"{win_rate:.0f}%")
        show_cols = [c for c in ["ticker", "kind", "strike", "exp_date", "open_interest",
                                  "volume", "mid", "entry_close", "exit_close", "days_observed",
                                  "pnl_pct"] if c in rdf.columns]
        st.dataframe(rdf[show_cols], use_container_width=True, hide_index=True)
        st.caption(DISCLAIMER)

        title = f"Vol Surface signals — {int(max_contracts)} contracts, {int(holding_days)}d hold"
        valid = rdf.dropna(subset=["pnl_pct"]) if "pnl_pct" in rdf.columns else pd.DataFrame()
        stats_rows = [{
            "Series": "Vol Surface signals (proxy)",
            "contracts_evaluated": int(len(valid)),
            "mean_pnl_%": round(float(valid["pnl_pct"].mean()), 2) if len(valid) else 0.0,
            "median_pnl_%": round(float(valid["pnl_pct"].median()), 2) if len(valid) else 0.0,
            "win_rate_%": round(float((valid["pnl_pct"] > 0).mean() * 100), 1) if len(valid) else 0.0,
            "best_%": round(float(valid["pnl_pct"].max()), 2) if len(valid) else 0.0,
            "worst_%": round(float(valid["pnl_pct"].min()), 2) if len(valid) else 0.0,
        }]
        _render_download_buttons(
            title,
            params={"max_contracts": int(max_contracts), "holding_days_calendar": int(holding_days),
                    "evaluation_cutoff": eval_end,
                    "filters": "OI ≥ 50, volume ≥ 1, bid > 0, ask > 0",
                    "ranking": "by trade volume (desc)"},
            methodology=(
                "Approximation backtest. Pulls the current SOXL options snapshot, filters to "
                "liquid contracts (OI ≥ 50, volume ≥ 1, valid bid/ask), ranks by volume, and "
                f"takes the top {int(max_contracts)}. For each, fetches Polygon's daily aggregates "
                "between (cutoff − holding − 30d) and the cutoff, and measures close-to-close "
                f"P&L over a {int(holding_days)}-calendar-day window. Note: this grades CURRENT "
                "signals against past data; a true walk-forward of historical IV-surface fits "
                "would require rebuilding the surface at every past date, which is out of scope."
            ),
            stats_rows=stats_rows,
            date_range=(eval_end, eval_end),
        )


# ----------------------------------------------------------------------------
# 7. CUSTOM STRATEGY BUILDER
# ----------------------------------------------------------------------------
def _default_condition():
    return {
        "lhs": {"kind": "indicator", "indicator": "SOXL price", "n": None},
        "op": ">",
        "rhs": {"kind": "value", "value": 0.0, "indicator": None, "n": None},
    }


def _default_panel():
    return {"combinator": "AND", "conditions": [_default_condition()]}


def _init_cs_state():
    if "cs_entry" not in st.session_state:
        st.session_state.cs_entry = _default_panel()
    if "cs_exit" not in st.session_state:
        st.session_state.cs_exit = {"combinator": "AND", "conditions": []}
    if "cs_controls" not in st.session_state:
        st.session_state.cs_controls = {
            "max_hold": 60, "stop_pct": 15.0, "tp_pct": 30.0, "direction": "Long",
        }


def _render_condition_row(panel_key, idx):
    cond = st.session_state[panel_key]["conditions"][idx]
    base = f"{panel_key}_{idx}"

    cols = st.columns([2.6, 1.4, 1.3, 1.4, 1.6, 0.5])

    with cols[0]:
        lhs_ind = st.selectbox(
            "Indicator", ALL_INDICATORS,
            index=ALL_INDICATORS.index(cond["lhs"].get("indicator", "SOXL price")),
            key=f"{base}_lhs_ind", label_visibility="collapsed",
        )
        cond["lhs"]["kind"] = "indicator"
        cond["lhs"]["indicator"] = lhs_ind

    is_cat = is_categorical_signal(lhs_ind)
    is_two_param = lhs_ind in APP_SIGNALS_NUMERIC_TWO_PARAM

    with cols[1]:
        if is_two_param:
            sub = st.columns(2)
            with sub[0]:
                m_val = st.number_input(
                    "M%", 0.5, 100.0,
                    value=float(cond["lhs"].get("n") or DEFAULT_N.get(lhs_ind, 10.0)),
                    step=0.5, key=f"{base}_lhs_m", label_visibility="collapsed",
                )
                cond["lhs"]["n"] = float(m_val)
            with sub[1]:
                h_val = st.number_input(
                    "Hd", 1, 252,
                    value=int(cond["lhs"].get("n2") or DEFAULT_N2.get(lhs_ind, 30)),
                    key=f"{base}_lhs_h", label_visibility="collapsed",
                )
                cond["lhs"]["n2"] = int(h_val)
        elif lhs_ind in INDICATORS_NEEDS_N:
            n_val = st.number_input(
                "N", 2, 504, value=int(cond["lhs"].get("n") or DEFAULT_N.get(lhs_ind, 14)),
                key=f"{base}_lhs_n", label_visibility="collapsed",
            )
            cond["lhs"]["n"] = int(n_val)
            cond["lhs"]["n2"] = None
        else:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            cond["lhs"]["n"] = None
            cond["lhs"]["n2"] = None

    with cols[2]:
        if is_cat:
            st.selectbox("Op", ["="], index=0, disabled=True,
                          key=f"{base}_op_cat", label_visibility="collapsed")
            cond["op"] = "="
        else:
            op = st.selectbox("Op", OPERATORS,
                              index=OPERATORS.index(cond.get("op", ">")) if cond.get("op", ">") in OPERATORS else 0,
                              key=f"{base}_op", label_visibility="collapsed")
            cond["op"] = op

    if is_cat:
        # Hide RHS-kind column; categorical RHS is locked to a category dropdown
        with cols[3]:
            st.markdown("&nbsp;equals", unsafe_allow_html=True)
        with cols[4]:
            categories = APP_SIGNALS_CATEGORICAL[lhs_ind]
            current = cond["rhs"].get("value") if cond["rhs"].get("kind") == "category" else categories[0]
            if current not in categories:
                current = categories[0]
            cat = st.selectbox("Category", categories,
                                index=categories.index(current),
                                key=f"{base}_rhs_cat", label_visibility="collapsed")
            cond["rhs"] = {"kind": "category", "value": cat,
                           "indicator": None, "n": None, "n2": None}
    else:
        with cols[3]:
            rhs_kind = st.selectbox("RHS", ["value", "indicator"],
                                     index=0 if cond["rhs"].get("kind", "value") == "value" else 1,
                                     key=f"{base}_rhs_kind", label_visibility="collapsed")
            cond["rhs"]["kind"] = rhs_kind
        with cols[4]:
            if rhs_kind == "value":
                v = st.number_input("Value",
                                    value=float(cond["rhs"].get("value") if cond["rhs"].get("value") is not None else 0.0),
                                    key=f"{base}_rhs_v", label_visibility="collapsed",
                                    format="%.4f")
                cond["rhs"]["value"] = float(v)
                cond["rhs"]["indicator"] = None
                cond["rhs"]["n"] = None
                cond["rhs"]["n2"] = None
            else:
                rhs_options = [i for i in ALL_INDICATORS
                               if not is_categorical_signal(i) and i not in APP_SIGNALS_NUMERIC_TWO_PARAM]
                cur = cond["rhs"].get("indicator") or "SOXL price"
                if cur not in rhs_options:
                    cur = "SOXL price"
                rhs_ind = st.selectbox("Indicator2", rhs_options,
                                        index=rhs_options.index(cur),
                                        key=f"{base}_rhs_ind", label_visibility="collapsed")
                cond["rhs"]["indicator"] = rhs_ind
                cond["rhs"]["value"] = None
                if rhs_ind in INDICATORS_NEEDS_N:
                    n2 = st.number_input("N2", 2, 504,
                                          value=int(cond["rhs"].get("n") or DEFAULT_N.get(rhs_ind, 14)),
                                          key=f"{base}_rhs_n", label_visibility="collapsed")
                    cond["rhs"]["n"] = int(n2)
                else:
                    cond["rhs"]["n"] = None

    with cols[5]:
        if st.button("✕", key=f"{base}_del", help="Remove condition"):
            st.session_state[panel_key]["conditions"].pop(idx)
            st.rerun()


def _render_panel(panel_key, label):
    st.markdown(f"##### {label}")
    panel = st.session_state[panel_key]
    if len(panel["conditions"]) > 1:
        c1, _ = st.columns([1, 4])
        with c1:
            panel["combinator"] = st.radio(
                "Combine with", ["AND", "OR"],
                index=0 if panel["combinator"] == "AND" else 1,
                horizontal=True, key=f"{panel_key}_comb",
            )
    head = st.columns([2.4, 1.0, 1.4, 1.6, 1.4, 0.6])
    head[0].caption("Indicator")
    head[1].caption("N")
    head[2].caption("Operator")
    head[3].caption("RHS type")
    head[4].caption("Value / Indicator")
    head[5].caption("")
    for i in range(len(panel["conditions"])):
        _render_condition_row(panel_key, i)
    if st.button(f"➕ Add condition", key=f"{panel_key}_add"):
        panel["conditions"].append(_default_condition())
        st.rerun()


def _custom_strategy_tab():
    st.markdown("#### Custom Strategy Builder")
    st.caption(
        "Compose your own entry/exit rules from the indicator library. "
        "Each rule is a list of conditions combined with AND or OR. "
        "Common stop loss / take profit / max-hold guards apply on top of the exit rule."
    )
    _init_cs_state()

    # Save/Load row
    saved = load_all_strategies()
    sl1, sl2, sl3, sl4 = st.columns([2, 2, 1, 1])
    with sl1:
        new_name = st.text_input("Save strategy as", placeholder="e.g. VIX < 15 long",
                                  key="cs_save_name")
    with sl2:
        load_choice = st.selectbox("Load saved strategy",
                                    ["—"] + sorted(saved.keys()), key="cs_load_pick")
    with sl3:
        if st.button("💾 Save", use_container_width=True, key="cs_save_btn"):
            if not new_name.strip():
                st.warning("Provide a name first.")
            else:
                save_strategy(new_name.strip(), {
                    "entry": st.session_state.cs_entry,
                    "exit": st.session_state.cs_exit,
                    "controls": st.session_state.cs_controls,
                })
                st.success(f"Saved '{new_name.strip()}'.")
                st.rerun()
    with sl4:
        if st.button("📂 Load", use_container_width=True, key="cs_load_btn"):
            if load_choice and load_choice != "—":
                entry = saved[load_choice]
                cfg = entry["config"]
                saved_ver = entry.get("signal_version", "unknown")
                st.session_state.cs_entry = cfg.get("entry", _default_panel())
                st.session_state.cs_exit = cfg.get("exit", {"combinator": "AND", "conditions": []})
                st.session_state.cs_controls = cfg.get("controls", st.session_state.cs_controls)
                if (saved_ver != SIGNAL_VERSION and strategy_uses_app_signals(cfg)):
                    st.warning(
                        f"This strategy was built against an earlier version of the "
                        f"app-generated signals (saved v{saved_ver}, current v{SIGNAL_VERSION}). "
                        f"Results may differ from the original backtest."
                    )
                else:
                    st.success(f"Loaded '{load_choice}' (signal v{saved_ver}).")
    if load_choice and load_choice != "—":
        if st.button(f"🗑 Delete '{load_choice}'", key="cs_del_btn"):
            delete_strategy(load_choice)
            st.success(f"Deleted '{load_choice}'.")
            st.rerun()

    st.divider()
    _render_panel("cs_entry", "📈 Entry Rule")
    st.divider()
    _render_panel("cs_exit", "📉 Exit Rule (optional — may rely solely on stop/TP/max-hold)")

    st.divider()
    st.markdown("##### Controls")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.session_state.cs_controls["max_hold"] = st.number_input(
            "Max holding period (days)", 1, 504,
            value=int(st.session_state.cs_controls.get("max_hold") or 60),
            key="cs_maxhold",
        )
    with c2:
        st.session_state.cs_controls["stop_pct"] = st.number_input(
            "Stop loss (%)", 0.0, 100.0,
            value=float(st.session_state.cs_controls.get("stop_pct") or 0.0),
            step=1.0, key="cs_stop",
        )
    with c3:
        st.session_state.cs_controls["tp_pct"] = st.number_input(
            "Take profit (%)", 0.0, 500.0,
            value=float(st.session_state.cs_controls.get("tp_pct") or 0.0),
            step=1.0, key="cs_tp",
        )
    with c4:
        st.session_state.cs_controls["direction"] = st.selectbox(
            "Position direction", ["Long", "Short", "Both"],
            index=["Long", "Short", "Both"].index(st.session_state.cs_controls.get("direction", "Long")),
            key="cs_dir",
            help="'Both' currently behaves as Long when entry rule fires; bidirectional rule pairs are a future extension.",
        )

    st.divider()
    # Auto-restrict date range if any panel uses options-data signals
    uses_options = (panel_uses_options_signals(st.session_state.cs_entry)
                    or panel_uses_options_signals(st.session_state.cs_exit))
    if uses_options:
        st.warning(
            "⚠️ Strategy uses Vol Surface signals; backtest limited to "
            f"{OPTIONS_WINDOW_START}–present due to options data availability."
        )
        max_yrs = max(1, (datetime.now().date()
                          - datetime.strptime(OPTIONS_WINDOW_START, "%Y-%m-%d").date()).days // 365)
        start, end = _date_range_picker("cs", max_years=max_yrs)
        # Hard-clamp the start
        opt_start = datetime.strptime(OPTIONS_WINDOW_START, "%Y-%m-%d").date()
        if start < opt_start:
            start = opt_start
    else:
        start, end = _date_range_picker("cs", max_years=EQUITY_MAX_YEARS)

    if st.button("Run custom backtest", type="primary", key="cs_run"):
        with st.spinner("Loading data and computing indicators..."):
            soxl_full = get_equity_history("SOXL")
            qqq_full = get_equity_history("QQQ")
            try:
                vix_full = get_equity_history("VIX", suffix=".INDX")
            except Exception:
                vix_full = pd.DataFrame()
        soxl = _slice(soxl_full, start, end)
        qqq = _slice(qqq_full, start, end)
        vix = _slice(vix_full, start, end) if not vix_full.empty else pd.DataFrame()
        if soxl.empty:
            st.error("No SOXL data in this range.")
            return

        equity, trade_returns, trade_log = simulate_custom_strategy(
            soxl, qqq, vix, st.session_state.cs_entry, st.session_state.cs_exit,
            st.session_state.cs_controls,
        )

        if not trade_returns:
            st.warning("This rule produced no trades in the selected period. "
                        "Try loosening conditions.")
            return

        avg_hold = max(int(np.mean([d for d in trade_log["days_held"]]) if not trade_log.empty else 1), 1)
        title = f"Custom Strategy — {st.session_state.cs_controls['direction']}"
        params = {
            "direction": st.session_state.cs_controls["direction"],
            "max_hold_days": st.session_state.cs_controls["max_hold"],
            "stop_loss_%": st.session_state.cs_controls["stop_pct"],
            "take_profit_%": st.session_state.cs_controls["tp_pct"],
            "entry_combinator": st.session_state.cs_entry["combinator"],
            "exit_combinator": st.session_state.cs_exit["combinator"],
            "start": start, "end": end,
        }
        methodology = (
            "Custom user-defined rule.\n"
            f"  Entry: {describe_panel(st.session_state.cs_entry)}\n"
            f"  Exit:  {describe_panel(st.session_state.cs_exit) if st.session_state.cs_exit['conditions'] else '(none — uses stop/TP/max-hold only)'}\n"
            "Indicators are computed on EODHD adjusted-close data. VIX is sourced from "
            "EODHD ticker VIX.INDX. Returns are compounded multiplicatively across each "
            "trade's holding window. Random Entry Baseline draws the same number of entries "
            "at random dates with the same average holding period."
        )
        _render_results(equity, soxl, qqq, trade_returns, avg_hold, title,
                        params=params, methodology=methodology)

        st.markdown("##### Trade log")
        st.dataframe(trade_log, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# Main render
# ----------------------------------------------------------------------------
def render_backtest_tab():
    st.markdown("### 🔬 Backtest")
    st.caption(
        f"Each existing analytical function below has its own backtest. "
        f"Equity-history backtests use up to {EQUITY_MAX_YEARS} years of data via EODHD. "
        f"Options backtests are capped at {OPTIONS_MAX_YEARS} years via Polygon. "
        f"All API responses cached for 24h."
    )
    sub = st.tabs([
        "Period Analysis", "Probability Engine", "Vol Regime",
        "SOXL-QQQ Dislocation", "Strategy Builder", "Vol Surface (limited)",
        "🛠 Custom Strategy",
    ])
    with sub[0]: _period_analysis_tab()
    with sub[1]: _probability_engine_tab()
    with sub[2]: _vol_regime_tab()
    with sub[3]: _dislocation_tab()
    with sub[4]: _strategy_builder_tab()
    with sub[5]: _vol_surface_tab()
    with sub[6]: _custom_strategy_tab()
