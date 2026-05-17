"""Diagnostic self-check for the SOXL Streamlit app.

Produces a structured report (same shape as the reference AI-102 diagnostic)
covering: environment, data providers (yfinance + FINRA), AI integration,
backtest engine, probability engine, options pricer, and curriculum-like
registries (indicators / operators / files).

Each check is a dict:
    {
      "name": str,
      "group": "system" | "data" | "engine" | "ai" | "files",
      "status": "pass" | "fail" | "skip",
      "ms": int,
      "info": str (optional summary),
      "evidence": [ {kind, label, value}, ... ],
    }
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
import streamlit as st


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _redact(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "…" + s[-keep:]


def _ev(kind: str, label: str, value: Any) -> dict:
    return {"kind": kind, "label": label, "value": value}


def _run(name: str, group: str, fn: Callable[[], dict]) -> dict:
    """Run a single check. fn() must return {status, info?, evidence}."""
    t0 = time.perf_counter()
    try:
        result = fn() or {}
        status = result.get("status", "pass")
        info = result.get("info", "")
        evidence = result.get("evidence", [])
    except Exception as e:  # noqa: BLE001
        status = "fail"
        info = f"{type(e).__name__}: {e}"
        evidence = [_ev("error", "traceback", traceback.format_exc())]
    ms = int((time.perf_counter() - t0) * 1000)
    return {
        "name": name,
        "group": group,
        "status": status,
        "ms": ms,
        "info": info,
        "evidence": evidence,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────────
def _check_env(var: str, required: bool = True) -> dict:
    val = os.environ.get(var, "")
    present = bool(val)
    status = "pass" if present else ("fail" if required else "skip")
    info = f"length={len(val)} chars (value redacted)" if present else f"{var} not set"
    return {
        "status": status,
        "info": info,
        "evidence": [
            _ev("assertion", f"process.env.{var} is non-empty", {"present": present, "length": len(val)}),
        ] + ([_ev("output", f"{var} (redacted)", _redact(val))] if present else []),
    }


def _check_anthropic_ping() -> dict:
    try:
        from strategy_builder import get_client
    except Exception as e:  # noqa: BLE001
        return {"status": "fail", "info": f"import error: {e}", "evidence": []}

    api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"status": "skip", "info": "no Anthropic API key in environment", "evidence": []}

    try:
        client = get_client()
    except Exception as e:  # noqa: BLE001
        return {"status": "fail", "info": f"client init error: {e}", "evidence": []}

    probe = "Reply with exactly the single word: OK"
    t0 = time.perf_counter()
    try:
        resp = client.messages.create(
            model=os.environ.get("R1_ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            max_tokens=16,
            messages=[{"role": "user", "content": probe}],
        )
        rtt = int((time.perf_counter() - t0) * 1000)
        text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                text += getattr(block, "text", "")
        return {
            "status": "pass" if text.strip() else "fail",
            "info": f"reply={text.strip()[:60]!r} rtt={rtt}ms",
            "evidence": [
                _ev("input", "prompt", probe),
                _ev("output", "round-trip time (ms)", rtt),
                _ev("output", "model", getattr(resp, "model", "?")),
                _ev("output", "reply text", text),
                _ev("output", "stop_reason", getattr(resp, "stop_reason", "?")),
            ],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "status": "fail",
            "info": f"{type(e).__name__}: {e}",
            "evidence": [_ev("error", "exception", str(e))],
        }


def _check_yf_symbol(symbol: str) -> dict:
    import yfinance as yf

    t0 = time.perf_counter()
    end = datetime.now()
    start = end - timedelta(days=10)
    df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
    rtt = int((time.perf_counter() - t0) * 1000)
    rows = int(len(df))
    if rows == 0:
        return {
            "status": "fail",
            "info": f"no data returned for {symbol}",
            "evidence": [_ev("output", "rows", 0), _ev("output", "rtt_ms", rtt)],
        }
    last_close = float(df["Close"].iloc[-1].item()) if hasattr(df["Close"].iloc[-1], "item") else float(df["Close"].iloc[-1])
    last_date = str(df.index[-1].date())
    return {
        "status": "pass",
        "info": f"{rows} rows, last={last_date} close=${last_close:.2f}",
        "evidence": [
            _ev("query", "yfinance.download", {"symbol": symbol, "start": str(start.date()), "end": str(end.date())}),
            _ev("output", "rows returned", rows),
            _ev("output", "last bar", {"date": last_date, "close": round(last_close, 4)}),
            _ev("output", "round-trip time (ms)", rtt),
        ],
    }


def _check_finra_short_volume() -> dict:
    # Try yesterday then walk back up to 7 days (weekends/holidays)
    base = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
    last_err = None
    for back in range(1, 8):
        d = (datetime.now() - timedelta(days=back)).strftime("%Y%m%d")
        url = base.format(date=d)
        t0 = time.perf_counter()
        try:
            r = requests.get(url, timeout=10)
            rtt = int((time.perf_counter() - t0) * 1000)
            if r.status_code == 200 and "SOXL" in r.text:
                # Count SOXL rows
                lines = [ln for ln in r.text.splitlines() if "|SOXL|" in ln]
                return {
                    "status": "pass",
                    "info": f"FINRA reachable for {d}, {len(lines)} SOXL row(s)",
                    "evidence": [
                        _ev("query", "GET", url),
                        _ev("output", "HTTP status", r.status_code),
                        _ev("output", "round-trip time (ms)", rtt),
                        _ev("output", "SOXL row sample", lines[0] if lines else None),
                    ],
                }
            last_err = f"HTTP {r.status_code} for {d}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e} for {d}"
    return {
        "status": "fail",
        "info": f"no FINRA report reachable in last 7 days · last={last_err}",
        "evidence": [_ev("error", "last error", last_err)],
    }


def _check_bs_pricer() -> dict:
    from backtest_engine import _bs_call_price

    S, K, T, sigma = 100.0, 100.0, 30 / 365.0, 0.50
    price = _bs_call_price(S, K, T, sigma, r=0.0)
    # Sanity: ATM 30-day @ 50% vol on $100 underlying ≈ $5.50–$6.00, must be > 0 and < S
    ok = (price > 0) and (price < S) and (3.0 < price < 10.0)
    return {
        "status": "pass" if ok else "fail",
        "info": f"ATM 30d 50% vol price=${price:.4f}",
        "evidence": [
            _ev("input", "inputs", {"S": S, "K": K, "T_years": T, "sigma": sigma, "r": 0.0}),
            _ev("output", "call price", round(price, 6)),
            _ev("assertion", "0 < price < S and in plausible band [3, 10]", {"ok": ok}),
        ],
    }


def _check_call_sleeve_engine() -> dict:
    from backtest_engine import simulate_call_sleeve_engine

    # 60 trading days of synthetic data
    n = 60
    idx = pd.bdate_range(end=datetime.now(), periods=n)
    soxl = pd.Series(100.0 * (1 + 0.005 * (pd.Series(range(n)) - n / 2) / n).cumprod().values, index=idx, name="SOXL")
    qqq = pd.Series(300.0 * (1 + 0.001 * pd.Series(range(n)) / n).cumprod().values, index=idx, name="QQQ")
    result = simulate_call_sleeve_engine(soxl, qqq)
    keys = list(result.keys()) if isinstance(result, dict) else []
    required = ["equity_strategy", "sleeve_value", "cash_value",
                "sleeve_alloc_target", "sleeve_alloc_actual", "roll_events"]
    missing = [k for k in required if k not in keys]
    # Numeric sanity on equity curve
    eq = result.get("equity_strategy") if isinstance(result, dict) else None
    eq_len = len(eq) if eq is not None else 0
    eq_first = float(eq.iloc[0]) if eq is not None and eq_len else None
    eq_last = float(eq.iloc[-1]) if eq is not None and eq_len else None
    eq_ok = eq_len == n and eq_first is not None and eq_first > 0 and eq_last > 0
    ok = not missing and eq_ok
    return {
        "status": "pass" if ok else "fail",
        "info": f"{len(keys)} keys returned; equity len={eq_len} first=${eq_first} last=${eq_last}",
        "evidence": [
            _ev("input", "inputs", {"n_days": n, "soxl_start": float(soxl.iloc[0]), "qqq_start": float(qqq.iloc[0])}),
            _ev("output", "result keys", keys),
            _ev("output", "equity_strategy summary", {"len": eq_len, "first": eq_first, "last": eq_last}),
            _ev("output", "roll_events count", len(result.get("roll_events", [])) if isinstance(result, dict) else None),
            _ev("assertion", "required keys present & equity series valid",
                {"missing": missing, "eq_ok": eq_ok}),
        ],
    }


def _check_risk_metrics() -> dict:
    from backtest_engine import compute_risk_metrics

    eq = pd.Series([1.0, 1.01, 0.99, 1.02, 1.05, 1.03, 1.06])
    m = compute_risk_metrics(eq, label="probe", capital_at_risk=0.20)
    # Spec: 9 columns expected
    required = ["Total Return", "CAGR", "Vol", "Max Drawdown", "Sharpe", "Sortino", "Calmar", "Capital at Risk", "Return / At-Risk"]
    if isinstance(m, pd.DataFrame):
        cols = " | ".join(str(c) for c in list(m.columns) + list(m.index))
        present = [r for r in required if r.lower().split()[0] in cols.lower()]
    elif isinstance(m, dict):
        keys_text = " | ".join(m.keys()).lower()
        present = [r for r in required if r.lower().split()[0] in keys_text]
    else:
        present = []
    ok = len(present) >= 7
    return {
        "status": "pass" if ok else "fail",
        "info": f"{len(present)}/9 expected risk columns recognized",
        "evidence": [
            _ev("input", "equity series", eq.tolist()),
            _ev("output", "metrics", m.to_dict() if isinstance(m, pd.DataFrame) else m),
            _ev("assertion", "≥7 of 9 required columns present", {"matched": present}),
        ],
    }


def _check_probability_engine() -> dict:
    from strategy_builder import compute_probability_table

    # 200 random-walk days
    import numpy as np

    rng = pd.bdate_range(end=datetime.now(), periods=300)
    prices = pd.Series(100.0 * (1 + 0.01 * (pd.Series(range(300)) * 0 + 0.001).cumprod()).values, index=rng)
    # use real noise
    np_rng = np.random.default_rng(42)
    walk = pd.Series(100.0 * (1 + 0.02 * np_rng.standard_normal(300)).cumprod(), index=rng)
    table = compute_probability_table(walk, horizons_days=[5, 20, 60], magnitudes=[0.05, 0.10, 0.20])
    n_cells = sum(1 for row in (table or []) for c in row)
    return {
        "status": "pass" if n_cells > 0 else "fail",
        "info": f"{len(table or [])} rows × {len(table[0]) if table else 0} cols",
        "evidence": [
            _ev("input", "horizons_days", [5, 20, 60]),
            _ev("input", "magnitudes", [0.05, 0.10, 0.20]),
            _ev("output", "table", table),
        ],
    }


def _check_indicator_registry() -> dict:
    from custom_strategy import ALL_INDICATORS, OPERATORS

    inds = list(ALL_INDICATORS)
    ops = list(OPERATORS)
    expected_ops = {">", "<", "=", "crosses above", "crosses below"}
    ok = len(inds) >= 5 and set(ops) == expected_ops
    return {
        "status": "pass" if ok else "fail",
        "info": f"{len(inds)} indicators, {len(ops)} operators",
        "evidence": [
            _ev("output", "ALL_INDICATORS", inds),
            _ev("output", "OPERATORS", ops),
            _ev("assertion", "operators == expected set", {"expected": sorted(expected_ops), "actual": sorted(ops)}),
        ],
    }


def _check_files() -> dict:
    expected = ["app.py", "backtest_engine.py", "backtest_ui.py", "strategy_builder.py",
                "custom_strategy.py", "data_providers.py", "dislocation.py",
                "vol_surface.py", "replit.md", "BLUEPRINT.md", "README.md",
                ".streamlit/config.toml"]
    rows = []
    missing = []
    for p in expected:
        f = Path(p)
        if f.exists():
            rows.append({"path": p, "bytes": f.stat().st_size})
        else:
            rows.append({"path": p, "bytes": None, "missing": True})
            missing.append(p)
    return {
        "status": "pass" if not missing else "fail",
        "info": f"{len(expected) - len(missing)}/{len(expected)} files present",
        "evidence": [
            _ev("output", "files", rows),
            _ev("assertion", "no expected files missing", {"missing": missing}),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level runner
# ─────────────────────────────────────────────────────────────────────────────
def run_diagnostic() -> dict:
    checks: list[dict] = []

    # System / environment
    checks.append(_run("Environment: SESSION_SECRET present", "system", lambda: _check_env("SESSION_SECRET")))
    checks.append(_run("Environment: AI_INTEGRATIONS_ANTHROPIC_API_KEY present", "system",
                       lambda: _check_env("AI_INTEGRATIONS_ANTHROPIC_API_KEY")))
    checks.append(_run("Environment: AI_INTEGRATIONS_ANTHROPIC_BASE_URL present", "system",
                       lambda: _check_env("AI_INTEGRATIONS_ANTHROPIC_BASE_URL", required=False)))
    checks.append(_run("Files: project structure intact", "system", _check_files))
    checks.append(_run("Indicator registry: ALL_INDICATORS + OPERATORS", "system", _check_indicator_registry))

    # Data providers
    for sym in ["SOXL", "QQQ", "TQQQ", "TLT", "XLU", "^VIX"]:
        checks.append(_run(f"Data: yfinance {sym} (last 10 days)", "data",
                           lambda s=sym: _check_yf_symbol(s)))
    checks.append(_run("Data: FINRA short-volume daily report reachable", "data", _check_finra_short_volume))

    # Engines
    checks.append(_run("Engine: Black-Scholes call pricer (ATM 30d, σ=50%)", "engine", _check_bs_pricer))
    checks.append(_run("Engine: simulate_call_sleeve_engine smoke test", "engine", _check_call_sleeve_engine))
    checks.append(_run("Engine: compute_risk_metrics (9 columns)", "engine", _check_risk_metrics))
    checks.append(_run("Engine: probability table generator", "engine", _check_probability_engine))

    # AI
    checks.append(_run("AI: Anthropic round-trip ping", "ai", _check_anthropic_ping))

    totals = {
        "pass": sum(1 for c in checks if c["status"] == "pass"),
        "fail": sum(1 for c in checks if c["status"] == "fail"),
        "skip": sum(1 for c in checks if c["status"] == "skip"),
    }
    return {
        "ok": totals["fail"] == 0,
        "runAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.utcnow().microsecond // 1000:03d}Z",
        "totals": totals,
        "checks": checks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────
GROUP_TITLES = {
    "system": "1. System Check",
    "data": "2. Data Providers",
    "engine": "3. Engines",
    "ai": "4. AI Integration",
    "files": "5. Files",
}

GROUP_BLURBS = {
    "system": "Verifies environment variables, project files, and the strategy DSL registries.",
    "data": "Live calls to yfinance and FINRA to confirm market-data sources are reachable.",
    "engine": "Smoke-tests the Black-Scholes pricer, call-sleeve simulator, risk-metrics, and probability table.",
    "ai": "Round-trip ping to Anthropic via Replit AI Integrations.",
    "files": "Confirms expected source and documentation files exist on disk.",
}

STATUS_BADGE = {
    "pass": ("✅", "Pass"),
    "fail": ("❌", "Fail"),
    "skip": ("⏭️", "Skip"),
}


def render_diagnostic_tab() -> None:
    st.markdown("### 🩺 System & Functional Diagnostic")
    intro = st.container()
    with intro:
        col_text, col_btn = st.columns([4, 1])
        with col_text:
            st.markdown(
                "Press the button to run a full system + functional self-check. "
                "Results appear below. Total runtime: roughly **5–20 seconds**."
            )
            st.caption(
                "The functional test issues a tiny Anthropic ping and fetches recent market data. "
                "No real strategies are saved and no user state is modified."
            )
        with col_btn:
            run_clicked = st.button("Run diagnostic", type="primary", use_container_width=True)

    if run_clicked:
        with st.spinner("Running diagnostic — probing environment, data sources, engines, and AI…"):
            st.session_state["diagnostic_report"] = run_diagnostic()

    report = st.session_state.get("diagnostic_report")
    if not report:
        st.info("No diagnostic has been run yet in this session. Click **Run diagnostic** to start.")
        return

    totals = report["totals"]
    ok = report["ok"]

    summary_cols = st.columns([3, 1])
    with summary_cols[0]:
        if ok:
            st.success(
                f"All checks passed.  \n"
                f"{totals['pass']} passed · {totals['fail']} failed · {totals['skip']} skipped · "
                f"run at {report['runAt']}"
            )
        else:
            st.error(
                f"{totals['fail']} check(s) failed.  \n"
                f"{totals['pass']} passed · {totals['fail']} failed · {totals['skip']} skipped · "
                f"run at {report['runAt']}"
            )
    with summary_cols[1]:
        json_blob = json.dumps(report, indent=2, default=str)
        ts = report["runAt"].replace(":", "-").replace(".", "-")
        st.download_button(
            "Download full report (.json)",
            data=json_blob,
            file_name=f"diagnostic-{ts}.json",
            mime="application/json",
            use_container_width=True,
        )

    # Group by group
    by_group: dict[str, list[dict]] = {}
    for c in report["checks"]:
        by_group.setdefault(c["group"], []).append(c)

    for group_key in ["system", "data", "engine", "ai", "files"]:
        if group_key not in by_group:
            continue
        st.markdown(f"#### {GROUP_TITLES.get(group_key, group_key.title())}")
        st.caption(GROUP_BLURBS.get(group_key, ""))
        for c in by_group[group_key]:
            icon, label = STATUS_BADGE[c["status"]]
            row_cols = st.columns([8, 1])
            with row_cols[0]:
                st.markdown(f"{icon} **{c['name']}**")
                if c.get("info"):
                    st.caption(c["info"])
            with row_cols[1]:
                st.markdown(f"<div style='text-align:right;color:#888'>{c['ms']}ms</div>",
                            unsafe_allow_html=True)
            if c.get("evidence"):
                with st.expander(f"Show evidence ({len(c['evidence'])} item{'s' if len(c['evidence']) != 1 else ''})"):
                    for ev in c["evidence"]:
                        st.markdown(f"**{ev.get('kind', '?').title()} — {ev.get('label', '')}**")
                        v = ev.get("value")
                        if isinstance(v, (dict, list)):
                            st.json(v, expanded=False)
                        else:
                            st.code(str(v))
            st.divider()
