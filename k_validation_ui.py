"""Read the immutable historical study; never launch research during rendering."""
import io
import json
from pathlib import Path
import zipfile

import pandas as pd
import streamlit as st


def render_k_validation():
    with st.expander("K historical evidence", expanded=False):
        root = Path(__file__).resolve().parent / "reports/k_validation"
        names = ("protocol.json", "conclusion.json", "snapshots.csv", "outcomes.csv",
                 "summary.csv", "comparisons.csv")
        try:
            files = {name: (root/name).read_bytes() for name in names}
            conclusion = json.loads(files["conclusion.json"])
            frozen = json.loads(files["protocol.json"])
            summary = pd.read_csv(io.BytesIO(files["summary.csv"]))
            comparisons = pd.read_csv(io.BytesIO(files["comparisons.csv"]))
        except (OSError, ValueError):
            st.warning("K historical evidence is unavailable. K remains an unvalidated screening heuristic.")
            return
        st.warning(conclusion["text"].replace("nan percentage points", "unavailable"))
        st.caption(
            "Observed failure: at 21 sessions, high K has 10 overlapping observations "
            "and only 2 on the non-overlapping grid. The high-trend group is empty: "
            "its training upper cutoff equals the maximum score of 100, and ties stay "
            "in the lower bucket. The primary comparison is therefore unavailable. "
            "The frozen ranks were not changed after evaluation."
        )
        st.caption(
            "Fixed 252-session Hurst lookback, MA200 slope over 60 sessions, and training-only "
            "tercile boundaries frozen before K outcomes were computed. Training ends 2018; "
            "held-out K evaluation runs from 2019 through October 20, 2026. These dates were "
            "used in other studies: this is not a genuinely untouched holdout. This SOXL-only "
            "study compares ranks over time, not stocks against each other. Current chart "
            "selections and lookback controls do not change this study."
        )
        horizon = st.selectbox("Historical outcome horizon (sessions)", [21, 5, 63],
                               key="k_evidence_horizon")
        st.dataframe(summary.loc[summary.horizon == horizon], hide_index=True, width="stretch")
        st.dataframe(comparisons.loc[comparisons.horizon == horizon], hide_index=True, width="stretch")
        st.caption(
            "Returns enter at the next session close and exit after the stated horizon. "
            "Drawdown is the worst daily-close peak-to-trough decline during that holding period "
            "(negative; closer to zero is better). Baselines use the same eligible dates. "
            "All tied scores stay in one rank; empty ranks and labels remain visible. "
            "Non-overlapping counts use a fixed disjoint time grid, not independently selected "
            "trades for each group. Intervals use paired time-block resampling of overlapping "
            "windows; fewer than 20 non-overlapping observations in either group suppresses "
            "the interval. Intervals are exploratory, not adjusted for multiple comparisons. "
            "No costs, taxes, intraday drawdowns or executable trading strategy are tested. "
            "Single-ticker selection, revised historical prices and regime dependence limit generalization. "
            "Blank statistics mean unavailable, not zero. No holdout tuning or live-signal changes."
        )
        st.json(frozen)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name, content in files.items():
                bundle.writestr(name, content)
        st.download_button("Download K evidence and frozen rules", archive.getvalue(),
                           "k-historical-evidence.zip", "application/zip",
                           key="k_evidence_download")
