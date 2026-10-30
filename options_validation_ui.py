"""Explicit, local historical-data upload; no implicit provider calls or jobs."""
import hashlib
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from options_validation import StudyConfig, report_json, run_study


def render_validation():
    with st.expander("Historical probability validation"):
        st.caption(
            "Probability claims remain unvalidated. Upload real historical option "
            "bid/ask snapshots, point-in-time SOXL history, and an independent session "
            "calendar to measure outcomes. Live snapshots alone cannot establish accuracy."
        )
        st.download_button(
            "Download historical data requirements",
            Path(__file__).with_name("docs").joinpath("options-validation.md").read_text(),
            file_name="options-validation-requirements.md", mime="text/markdown",
            key="options_study_requirements",
        )
        history = st.file_uploader("Historical SOXL observations (CSV)", type=["csv"],
                                   key="options_study_history")
        quotes = st.file_uploader("Historical option bid/ask snapshots (CSV)", type=["csv"],
                                  key="options_study_quotes")
        sessions = st.file_uploader("Regular-close session calendar (CSV)", type=["csv"],
                                    key="options_study_sessions")
        fee = st.number_input("Fee per contract per side ($)", min_value=0., value=.65,
                              step=.05, key="options_study_fee")
        slip = st.number_input("Slippage per share per side ($)", min_value=0., value=.01,
                               step=.01, key="options_study_slippage")
        st.caption(
            "Fixed 5-, 10-, and 20-session horizons; 2,000 simulated paths. "
            "Buy at ask, sell at bid, with costs on both sides. Uploads are processed "
            "only when you press Run historical study. No data is sent to a provider."
        )
        files = [history, quotes, sessions]
        payloads = [f.getvalue() for f in files] if all(f is not None for f in files) else []
        identity = hashlib.sha256(b"".join(payloads)+f"{fee}:{slip}".encode()).hexdigest()
        if st.button("Run historical study", disabled=not payloads, key="options_study_run"):
            st.session_state.pop("options_study_result", None)
            try:
                if any(len(p) > 10_000_000 for p in payloads):
                    raise ValueError("Each upload must be smaller than 10 MB.")
                h, q, s = [pd.read_csv(io.BytesIO(p)) for p in payloads]
                if len(q) > 1000:
                    raise ValueError("Interactive studies support at most 1,000 quotes. Use the CLI for larger studies.")
                if "timestamp" not in s:
                    raise ValueError("Session CSV requires a timestamp column.")
                with st.spinner("Evaluating point-in-time forecasts…"):
                    report = run_study(h, q, s.timestamp, StudyConfig(
                        fee_per_contract=float(fee), slippage_per_share=float(slip)))
                st.session_state["options_study_result"] = (identity, report)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                st.error(f"Historical study unavailable: {exc}")
        saved = st.session_state.get("options_study_result")
        if not saved or saved[0] != identity:
            st.info("No study for the current inputs. Missing historical quotes are never replaced by sample data.")
            return
        report = saved[1]
        st.info(report["status"].capitalize())
        if report["overall"]:
            summary = report["overall"]
            a, b, c = st.columns(3)
            a.metric("Observed profitable trades", f'{summary["observed_profit_rate"]:.1%}')
            b.metric("Mean forecast probability", f'{summary["mean_predicted"]:.1%}')
            c.metric("Scored trade horizons", summary["n"])
            st.caption("These are historical measurements, not a recommendation or validated future success rate.")
            st.dataframe(pd.DataFrame(summary["calibration_bins"]), hide_index=True)
            st.json({"overall": summary, "by_expiry_regime_and_horizon":
                     report["groups"].get("expiry_regime_horizon", {})}, expanded=False)
        st.caption(f'{len(report["exclusions"]):,} excluded entry/horizon records; all reasons are included in the download.')
        for limitation in report["limitations"]:
            st.caption(limitation)
        st.download_button("Download complete study (JSON)", report_json(report),
                           file_name="options-historical-study.json", mime="application/json",
                           key="options_study_download")
