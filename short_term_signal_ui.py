"""Short-horizon card backed by the frozen study, never an unvalidated buy."""
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

from short_term_signal import load_manifest, short_term_ratings

REPORT_PATH = Path(__file__).parent / "reports/signal_validation/report.html"


def toggle_full_report():
    st.session_state["show_full_signal_report"] = not st.session_state.get("show_full_signal_report", False)


def render_full_signal_report():
    """Display the exact downloadable document outside the narrow signal column."""
    if not st.session_state.get("show_full_signal_report", False):
        return
    st.markdown("#### Full frozen validation report")
    if not REPORT_PATH.exists():
        st.warning("The full validation report is currently unavailable.")
        return
    st.caption("This is the complete downloadable report. Scroll inside it to read every table; "
               "wide tables also scroll horizontally.")
    components.html(REPORT_PATH.read_text(encoding="utf-8"), height=760, scrolling=True)


def render_short_term_signal(closes):
    st.markdown("#### Short-term signal (1 month)")
    try:
        manifest = load_manifest()
        rating = short_term_ratings(closes, manifest).iloc[-1]
    except Exception:
        st.markdown("### NO EDGE")
        st.warning("Frozen validation results unavailable. Buy signals are disabled.")
        return
    st.markdown(f"### {rating}")
    st.caption(f"21 trading days · Close through {closes.index[-1]:%Y-%m-%d}")
    if not manifest["passed"]:
        st.info("NO EDGE on every day: the frozen rule did not meet the out-of-sample acceptance criteria.")
    else:
        st.caption("BUY only when the frozen rule fires; otherwise NO EDGE. No separate Possible Buy rule was approved.")
    stats = manifest.get("test_metrics", {})
    if stats:
        st.write(
            f"Frozen rule, out of sample: {stats['observations']} non-overlapping observations; "
            f"{stats['finished_higher_pct']:.1f}% finished higher versus "
            f"{stats['baseline_pct']:.1f}% baseline "
            f"({stats['difference_pp']:+.1f} pp)."
        )
        st.write(f"Median return: {stats['median_return_pct']:+.1f}%. "
                 f"Average worst dip below entry: {stats['average_worst_dip_pct']:.1f}%.")
        if stats["observations"] < 20:
            st.warning("Too thin to trust: fewer than 20 non-overlapping observations.")
    with st.expander("Frozen short-term rule and validation"):
        st.write(manifest["rule_text"])
        st.caption("Selected using 2010–2018 only; frozen before 2019–2026 evaluation. "
                   "Required: at least 30 non-overlapping observations and +10 percentage points versus baseline.")
        st.caption("Historical conditional outcomes, not a guaranteed probability for the next trade. "
                   "Drawdowns use closing prices, not intraday lows. No costs or slippage.")
        report = REPORT_PATH
        if report.exists():
            st.button(
                "Hide full report" if st.session_state.get("show_full_signal_report", False) else "View full report",
                key="view_full_signal_report", on_click=toggle_full_report,
            )
            st.download_button("Download full frozen validation report", report.read_bytes(),
                               "soxl_signal_validation.html", "text/html",
                               key="signal_validation_report")
