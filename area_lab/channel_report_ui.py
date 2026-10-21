"""Read-only presentation of the separately frozen walk-forward report."""
from pathlib import Path
import json
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports/channel_validation"


def render_channel_validation():
    with st.expander("Have the area method and channel projections been tested?"):
        st.caption(
            "A separate walk-forward study refits the automatic log-price channels at every "
            "historical start date. It tests a fixed 20-session area rule—not your manually "
            "drawn boxes, selected fitting periods, or the existing daily rating."
        )
        report = REPORT_DIR / "report.html"
        if not report.exists():
            st.info("The walk-forward report is not available. No predictive edge is established.")
            return
        st.warning(
            "Exploratory evidence only—not a proven trading edge. The chart still shows its "
            "lognormal model estimates; this study does not silently recalibrate those popups."
        )
        st.info(json.loads((REPORT_DIR / "conclusion.json").read_text())["text"])
        st.caption(
            "A hit means reaching the fixed projected price on a later daily close within "
            "1, 3, 6 or 12 months. Lower Brier score means better probability accuracy. "
            "The calibrated baseline separates any benefit from area from ordinary recalibration. "
            "The full report includes overlap-aware uncertainty, non-overlapping results, "
            "calibration bins, every forecast and its training cutoff."
        )
        summary = pd.read_csv(REPORT_DIR / "summary.csv")
        display = summary[["horizon_sessions", "line", "model", "forecasts",
                           "observed_hit_rate", "mean_predicted_probability", "brier"]].copy()
        display.columns = ["Trading sessions ahead", "Line", "Model", "Forecasts",
                           "Actual hit rate", "Average predicted chance", "Brier score"]
        st.dataframe(display, hide_index=True, use_container_width=True)
        show = st.checkbox("Read the complete walk-forward report here", key="channel_report_visible")
        content = report.read_text(encoding="utf-8")
        st.download_button("Download full area and channel validation report", content,
                           file_name="area_channel_walk_forward_report.html", mime="text/html",
                           key="channel_report_download")
        if show:
            components.html(content, height=760, scrolling=True)
        with st.expander("Download the underlying evidence"):
            for filename, label in (
                ("predictions.csv", "Every matched forecast"),
                ("windows.csv", "All causal windows, including training history"),
                ("summary.csv", "Results and uncertainty"),
                ("calibration.csv", "Probability calibration"),
                ("protocol.json", "Frozen rules and source fingerprint"),
            ):
                path = REPORT_DIR / filename
                st.download_button(label, path.read_bytes(), file_name=filename,
                                   key=f"channel_evidence_{filename}")
