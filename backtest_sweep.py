"""Exhaustive backtest sweep — answers the question:
"Is this app ever actually right?"

For each (window length × start offset × parameter combo) we run the call-sleeve
engine on real SOXL + QQQ data and compare to SOXL buy-and-hold and QQQ
buy-and-hold. We then aggregate hit-rates: % of windows where the strategy beat
SOXL on total return, on Sharpe, on Calmar, on max drawdown; % of windows with
positive returns; broken down by market regime (bull / bear / sideways) and by
parameter combo.

Designed to run in 30–120 seconds and to always produce *some* result so the
diagnostic is useful even with stale data.
"""

from __future__ import annotations

import io
import json
import math
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st


# ─────────────────────────────────────────────────────────────────────────────
# Data loader (cached for the session)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_sweep_data() -> dict:
    """Load full SOXL + QQQ history once and cache it."""
    import yfinance as yf

    out: dict[str, Any] = {"errors": []}
    for sym in ["SOXL", "QQQ"]:
        try:
            df = yf.download(sym, start="2010-01-01", progress=False, auto_adjust=False)
            if df is None or df.empty:
                out["errors"].append(f"{sym}: empty download")
                out[sym] = pd.Series(dtype=float)
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            out[sym] = close.dropna().astype(float)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{sym}: {type(e).__name__}: {e}")
            out[sym] = pd.Series(dtype=float)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Sweep grid
# ─────────────────────────────────────────────────────────────────────────────
# Trading-day window lengths. Roughly: 6mo, 1y, 2y, 5y, full-since-2015.
WINDOW_LENGTHS = [126, 252, 504, 1260, 2520]
# Step between window starts (trading days). Larger = fewer windows = faster.
STEP_DAYS = 126

# Parameter combos to sweep. Each is a kwargs dict passed to the engine.
PARAM_GRID = [
    {"sleeve_pct": 0.10, "label": "10% sleeve"},
    {"sleeve_pct": 0.20, "label": "20% sleeve (default)"},
    {"sleeve_pct": 0.30, "label": "30% sleeve"},
]


def _regime(soxl_bh_return: float) -> str:
    if soxl_bh_return > 0.20:
        return "bull"
    if soxl_bh_return < -0.20:
        return "bear"
    return "sideways"


def _safe_metric(d: dict, key: str, default: float = 0.0) -> tuple[float, bool]:
    """Return (value, ok). ok=False if missing or non-finite — caller can flag the row."""
    try:
        v = float(d.get(key, default))
        if not math.isfinite(v):
            return default, False
        return v, True
    except Exception:  # noqa: BLE001
        return default, False


# ─────────────────────────────────────────────────────────────────────────────
# Single-window runner
# ─────────────────────────────────────────────────────────────────────────────
def _run_one_window(soxl_win: pd.Series, qqq_win: pd.Series, params: dict) -> dict | None:
    """Run a single backtest and return a row of stats. None on hard failure."""
    from backtest_engine import simulate_call_sleeve_engine, compute_risk_metrics

    kwargs = {k: v for k, v in params.items() if k != "label"}
    try:
        res = simulate_call_sleeve_engine(soxl_win, qqq_win, **kwargs)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}

    eq_strat = res.get("equity_strategy")
    eq_soxl = res.get("equity_soxl_bh")
    eq_qqq = res.get("equity_qqq_bh")
    sleeve_pct = float(res.get("sleeve_pct", kwargs.get("sleeve_pct", 0.20)))

    if eq_strat is None or eq_soxl is None or len(eq_strat) < 2:
        return None

    m_strat = compute_risk_metrics(eq_strat, label="strategy", capital_at_risk=sleeve_pct)
    m_soxl = compute_risk_metrics(eq_soxl, label="soxl_bh", capital_at_risk=1.0)
    m_qqq = compute_risk_metrics(eq_qqq, label="qqq_bh", capital_at_risk=1.0) if eq_qqq is not None else {}

    (tr_strat, ok1), (tr_soxl, ok2) = _safe_metric(m_strat, "Total Return %"), _safe_metric(m_soxl, "Total Return %")
    tr_qqq, _ = _safe_metric(m_qqq, "Total Return %")
    (sh_strat, ok3), (sh_soxl, ok4) = _safe_metric(m_strat, "Sharpe"), _safe_metric(m_soxl, "Sharpe")
    (ca_strat, ok5), (ca_soxl, ok6) = _safe_metric(m_strat, "Calmar"), _safe_metric(m_soxl, "Calmar")
    (dd_strat, ok7), (dd_soxl, ok8) = _safe_metric(m_strat, "Max Drawdown %"), _safe_metric(m_soxl, "Max Drawdown %")
    (rar_strat, _), (rar_soxl, _) = _safe_metric(m_strat, "Return / At-Risk %"), _safe_metric(m_soxl, "Return / At-Risk %")
    (cagr_strat, _), (cagr_soxl, _) = _safe_metric(m_strat, "CAGR %"), _safe_metric(m_soxl, "CAGR %")
    metrics_ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8])
    if not metrics_ok:
        return {"error": "non-finite metric in compute_risk_metrics output", "trace": ""}

    return {
        "start": str(soxl_win.index[0].date()),
        "end": str(soxl_win.index[-1].date()),
        "n_days": int(len(soxl_win)),
        "param_label": params.get("label", ""),
        "sleeve_pct": sleeve_pct,
        "tr_strat_%": round(tr_strat, 2),
        "tr_soxl_%": round(tr_soxl, 2),
        "tr_qqq_%": round(tr_qqq, 2),
        "cagr_strat_%": round(cagr_strat, 2),
        "cagr_soxl_%": round(cagr_soxl, 2),
        "sharpe_strat": sh_strat,
        "sharpe_soxl": sh_soxl,
        "calmar_strat": ca_strat,
        "calmar_soxl": ca_soxl,
        "maxdd_strat_%": dd_strat,
        "maxdd_soxl_%": dd_soxl,
        "rar_strat_%": rar_strat,
        "rar_soxl_%": rar_soxl,
        "beat_soxl_tr": tr_strat > tr_soxl,
        "beat_qqq_tr": tr_strat > tr_qqq,
        "beat_soxl_sharpe": sh_strat > sh_soxl,
        "beat_soxl_calmar": ca_strat > ca_soxl,
        "lower_dd_than_soxl": dd_strat > dd_soxl,  # both negative; closer to 0 wins
        "strat_positive": tr_strat > 0,
        "soxl_positive": tr_soxl > 0,
        "regime": _regime(tr_soxl / 100.0),
        "roll_events": len(res.get("roll_events", []) or []),
        "error": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level sweep
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest_sweep(progress_cb=None) -> dict:
    """Run every backtest in the grid. progress_cb(done, total) optional."""
    t0 = time.perf_counter()
    data = _load_sweep_data()
    soxl_full: pd.Series = data.get("SOXL", pd.Series(dtype=float))
    qqq_full: pd.Series = data.get("QQQ", pd.Series(dtype=float))
    load_errs = data.get("errors", [])

    if soxl_full.empty or qqq_full.empty:
        return {
            "ok": False,
            "runAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "n_windows": 0,
            "n_runs": 0,
            "errors": load_errs or ["yfinance returned no data"],
            "summary": {},
            "by_regime": {},
            "by_param": {},
            "by_window_length": {},
            "rows": [],
        }

    # Align both series to common dates
    common = soxl_full.index.intersection(qqq_full.index)
    soxl_full = soxl_full.loc[common]
    qqq_full = qqq_full.loc[common]
    total_days = len(common)

    # Build (window_length, start_idx) plan. Off-by-one safe (include terminal
    # window) and deduplicated so a short history doesn't double-weight the
    # full-history window across multiple configured lengths.
    seen: set[tuple[int, int]] = set()
    plan: list[tuple[int, int]] = []
    for wlen in WINDOW_LENGTHS:
        if wlen >= total_days:
            key = (total_days, 0)
            if key not in seen:
                seen.add(key)
                plan.append(key)
            continue
        # Inclusive terminal: +1 so range covers start = total_days - wlen
        for start in range(0, total_days - wlen + 1, STEP_DAYS):
            key = (wlen, start)
            if key not in seen:
                seen.add(key)
                plan.append(key)
        # Also force-include the exact terminal start if STEP_DAYS skipped it
        terminal = (wlen, total_days - wlen)
        if terminal not in seen:
            seen.add(terminal)
            plan.append(terminal)

    total_runs = len(plan) * len(PARAM_GRID)
    rows: list[dict] = []
    errors: list[str] = list(load_errs)
    done = 0

    for wlen, start in plan:
        soxl_win = soxl_full.iloc[start : start + wlen]
        qqq_win = qqq_full.iloc[start : start + wlen]
        if len(soxl_win) < 2:
            done += len(PARAM_GRID)
            if progress_cb:
                progress_cb(done, total_runs)
            continue
        for params in PARAM_GRID:
            row = _run_one_window(soxl_win, qqq_win, params)
            done += 1
            if row is None:
                continue
            if row.get("error"):
                errors.append(f"{row['error']} @ {soxl_win.index[0].date()} len={wlen} {params.get('label')}")
                continue
            row["window_len"] = wlen
            rows.append(row)
            if progress_cb and (done % 20 == 0 or done == total_runs):
                progress_cb(done, total_runs)

    if progress_cb:
        progress_cb(total_runs, total_runs)

    # ── Aggregate ───────────────────────────────────────────────────────────
    def _agg(subset: list[dict]) -> dict:
        if not subset:
            return {
                "n": 0,
                "beat_soxl_tr_%": 0.0, "beat_qqq_tr_%": 0.0,
                "beat_soxl_sharpe_%": 0.0, "beat_soxl_calmar_%": 0.0,
                "lower_dd_than_soxl_%": 0.0, "strat_positive_%": 0.0,
                "avg_tr_strat_%": 0.0, "avg_tr_soxl_%": 0.0,
                "avg_rar_strat_%": 0.0, "avg_rar_soxl_%": 0.0,
                "median_excess_vs_soxl_%": 0.0,
            }
        n = len(subset)
        excess = [r["tr_strat_%"] - r["tr_soxl_%"] for r in subset]
        return {
            "n": n,
            "beat_soxl_tr_%": round(100.0 * sum(r["beat_soxl_tr"] for r in subset) / n, 1),
            "beat_qqq_tr_%": round(100.0 * sum(r["beat_qqq_tr"] for r in subset) / n, 1),
            "beat_soxl_sharpe_%": round(100.0 * sum(r["beat_soxl_sharpe"] for r in subset) / n, 1),
            "beat_soxl_calmar_%": round(100.0 * sum(r["beat_soxl_calmar"] for r in subset) / n, 1),
            "lower_dd_than_soxl_%": round(100.0 * sum(r["lower_dd_than_soxl"] for r in subset) / n, 1),
            "strat_positive_%": round(100.0 * sum(r["strat_positive"] for r in subset) / n, 1),
            "avg_tr_strat_%": round(float(np.mean([r["tr_strat_%"] for r in subset])), 2),
            "avg_tr_soxl_%": round(float(np.mean([r["tr_soxl_%"] for r in subset])), 2),
            "avg_rar_strat_%": round(float(np.mean([r["rar_strat_%"] for r in subset])), 2),
            "avg_rar_soxl_%": round(float(np.mean([r["rar_soxl_%"] for r in subset])), 2),
            "median_excess_vs_soxl_%": round(float(np.median(excess)), 2),
        }

    summary = _agg(rows)
    by_regime = {reg: _agg([r for r in rows if r["regime"] == reg]) for reg in ("bull", "bear", "sideways")}
    by_param = {p["label"]: _agg([r for r in rows if r["param_label"] == p["label"]]) for p in PARAM_GRID}
    # Group by *actual observed* window lengths (handles short-history cases
    # where multiple configured lengths collapse to the same actual length).
    observed_lengths = sorted({r["window_len"] for r in rows})
    by_window_length = {str(wlen): _agg([r for r in rows if r["window_len"] == wlen]) for wlen in observed_lengths}

    # Verdict heuristic
    verdict = "inconclusive"
    if rows:
        bs = summary["beat_soxl_tr_%"]
        rar_edge = summary["avg_rar_strat_%"] - summary["avg_rar_soxl_%"]
        if bs >= 50 or rar_edge > 5:
            verdict = "strategy has meaningful edge"
        elif bs >= 35 and rar_edge > 0:
            verdict = "strategy competitive on capital-efficiency"
        elif bs < 25 and rar_edge <= 0:
            verdict = "strategy underperforms SOXL B&H on both raw and risk-adjusted basis"
        else:
            verdict = "mixed — beats SOXL in some regimes, lags in others"

    return {
        "ok": len(rows) > 0,
        "runAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "n_windows": len(plan),
        "n_runs": len(rows),
        "n_planned": total_runs,
        "errors": errors[:50],
        "verdict": verdict,
        "summary": summary,
        "by_regime": by_regime,
        "by_param": by_param,
        "by_window_length": by_window_length,
        "rows": rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────
def _render_summary_card(title: str, agg: dict) -> None:
    if agg["n"] == 0:
        st.caption(f"**{title}** — no runs")
        return
    cols = st.columns([2, 1, 1, 1, 1, 1])
    cols[0].markdown(f"**{title}** ({agg['n']} runs)")
    cols[1].metric("Beat SOXL", f"{agg['beat_soxl_tr_%']:.0f}%")
    cols[2].metric("Strat > 0", f"{agg['strat_positive_%']:.0f}%")
    cols[3].metric("Beat Sharpe", f"{agg['beat_soxl_sharpe_%']:.0f}%")
    cols[4].metric("Lower DD", f"{agg['lower_dd_than_soxl_%']:.0f}%")
    cols[5].metric("Median Δ", f"{agg['median_excess_vs_soxl_%']:+.1f}%")


def render_backtest_sweep_tab() -> None:
    st.markdown("### 🔁 Exhaustive Backtest Sweep")
    st.markdown(
        "Runs the **call-sleeve engine** on every rolling window we can fit out "
        "of SOXL/QQQ history, across multiple `sleeve_pct` parameter values, and "
        "reports how often the strategy actually beats buy-and-hold."
    )
    n_windows_estimate = sum(
        1
        for wlen in WINDOW_LENGTHS
        for _ in range(0, max(1, 4000 - wlen), STEP_DAYS)  # rough estimate
    )
    st.caption(
        f"Plan: window lengths = {WINDOW_LENGTHS} trading days, step = {STEP_DAYS} days, "
        f"{len(PARAM_GRID)} parameter combos → ~{n_windows_estimate * len(PARAM_GRID)} backtests. "
        f"Typical runtime: **30–120 seconds**."
    )

    col_btn, col_dl = st.columns([1, 1])
    with col_btn:
        run = st.button("Run exhaustive sweep", type="primary", use_container_width=True,
                        key="sweep_run_btn")

    if run:
        progress = st.progress(0.0, text="Loading SOXL + QQQ history…")

        def cb(done: int, total: int) -> None:
            if total > 0:
                progress.progress(min(1.0, done / total),
                                  text=f"Running backtests… {done}/{total}")

        report = run_backtest_sweep(progress_cb=cb)
        st.session_state["sweep_report"] = report
        progress.empty()

    report = st.session_state.get("sweep_report")
    if not report:
        st.info("No sweep has been run yet in this session.  Click **Run exhaustive sweep** to start.")
        return

    # ── Header summary ──────────────────────────────────────────────────────
    if not report["ok"]:
        st.error(
            f"Sweep produced 0 valid runs.  Planned: {report.get('n_planned', 0)}.  "
            f"Errors: {report['errors'][:3] or ['(none captured)']}"
        )
    else:
        summary = report["summary"]
        verdict = report["verdict"]
        verdict_color = {
            "strategy has meaningful edge": "success",
            "strategy competitive on capital-efficiency": "success",
            "mixed — beats SOXL in some regimes, lags in others": "warning",
            "strategy underperforms SOXL B&H on both raw and risk-adjusted basis": "error",
            "inconclusive": "info",
        }.get(verdict, "info")
        getattr(st, verdict_color)(
            f"**Verdict:** {verdict}.  \n"
            f"{report['n_runs']:,} backtests over {report['n_windows']:,} windows in "
            f"{report['elapsed_s']:.1f}s.  \n"
            f"Strategy beat SOXL B&H on total return in "
            f"**{summary['beat_soxl_tr_%']:.0f}%** of windows · "
            f"beat QQQ in **{summary['beat_qqq_tr_%']:.0f}%** · "
            f"posted positive returns **{summary['strat_positive_%']:.0f}%** · "
            f"better Sharpe **{summary['beat_soxl_sharpe_%']:.0f}%** · "
            f"better Calmar **{summary['beat_soxl_calmar_%']:.0f}%** · "
            f"lower max drawdown **{summary['lower_dd_than_soxl_%']:.0f}%**."
        )

    # Downloads
    col_j, col_c = st.columns(2)
    with col_j:
        st.download_button(
            "Download full report (.json)",
            data=json.dumps(report, indent=2, default=str),
            file_name=f"backtest-sweep-{report['runAt'].replace(':', '-')}.json",
            mime="application/json",
            use_container_width=True,
            key="sweep_json_dl",
        )
    with col_c:
        if report["rows"]:
            csv_buf = io.StringIO()
            pd.DataFrame(report["rows"]).to_csv(csv_buf, index=False)
            st.download_button(
                "Download per-window rows (.csv)",
                data=csv_buf.getvalue(),
                file_name=f"backtest-sweep-rows-{report['runAt'].replace(':', '-')}.csv",
                mime="text/csv",
                use_container_width=True,
                key="sweep_csv_dl",
            )

    if not report["ok"]:
        if report.get("errors"):
            with st.expander(f"Errors ({len(report['errors'])})"):
                for e in report["errors"]:
                    st.code(e)
        return

    # ── Overall ─────────────────────────────────────────────────────────────
    st.markdown("#### Overall")
    _render_summary_card("All windows × all params", report["summary"])
    st.divider()

    # ── By regime ───────────────────────────────────────────────────────────
    st.markdown("#### By market regime (classified by SOXL B&H return in the window)")
    for reg in ["bull", "bear", "sideways"]:
        _render_summary_card(reg.title(), report["by_regime"].get(reg, {"n": 0}))
    st.divider()

    # ── By parameter ────────────────────────────────────────────────────────
    st.markdown("#### By parameter combo")
    for label in [p["label"] for p in PARAM_GRID]:
        _render_summary_card(label, report["by_param"].get(label, {"n": 0}))
    st.divider()

    # ── By window length ────────────────────────────────────────────────────
    st.markdown("#### By window length (trading days)")
    for wlen_key, agg in sorted(report["by_window_length"].items(), key=lambda kv: int(kv[0])):
        wlen = int(wlen_key)
        _render_summary_card(f"{wlen}d (~{wlen / 252:.1f}y)", agg)
    st.divider()

    # ── Per-window rows ─────────────────────────────────────────────────────
    st.markdown("#### Per-window results")
    df = pd.DataFrame(report["rows"]).sort_values(["window_len", "start", "param_label"])
    st.dataframe(df, use_container_width=True, hide_index=True, height=400)

    if report.get("errors"):
        with st.expander(f"Errors ({len(report['errors'])})"):
            for e in report["errors"]:
                st.code(e)
