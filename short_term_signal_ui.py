"""Short-horizon card backed by the frozen study, never an unvalidated buy."""
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from html import escape

from short_term_signal import load_manifest, short_term_ratings
from forecast_horizons import earliest_historical_outlook

REPORT_PATH = Path(__file__).parent / "reports/signal_validation/report.html"


@st.cache_data(show_spinner=False, max_entries=32)
def _earliest_outlook(closes):
    return earliest_historical_outlook(closes)


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


def render_short_term_signal(closes, saved=None):
    manifest = None
    try:
        manifest = saved["manifest"] if saved else load_manifest()
        rating = saved["short_rating"] if saved else short_term_ratings(closes, manifest).iloc[-1]
    except Exception:
        rating = "NO EDGE"
    passed = bool(manifest and manifest.get("passed"))
    outlook = _earliest_outlook(closes)
    selected = outlook["selected"]
    if selected:
        label = selected["label"].upper()
        frequency = f'{selected["higher_pct"]:.0f}% finished higher'
        sentence = (
            f'After {escape(outlook["rating"])} readings · '
            f'{selected["observations"]:,} non-overlapping outcomes'
        )
    else:
        label = "OUTCOME HISTORY"
        frequency = "Sample target: 30"
        largest = max((row["observations"] for row in outlook["candidates"]), default=0)
        sentence = f'{largest:,} matching completed outcomes available'
    st.markdown(
        '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;'
        'background:white;margin:4px 0 6px;">'
        '<div style="font-size:1rem;color:#475569;letter-spacing:.03em;font-weight:800;">'
        'EARLIEST HISTORICAL OUTLOOK</div>'
        f'<div style="font-size:1.6rem;line-height:1.15;font-weight:850;color:#334155;margin:3px 0;">{label}</div>'
        f'<div style="font-size:2rem;line-height:1.15;font-weight:850;color:#334155;margin:3px 0;">{frequency}</div>'
        f'<p style="font-size:1.125rem;line-height:1.3;color:#334155;margin:4px 0 0;">{sentence}</p></div>',
        unsafe_allow_html=True,
    )
    with st.expander("Outlook evidence and frozen monthly rule", expanded=False):
        st.write(
            f'Historical evaluation: {outlook["evaluation_start"]} through '
            f'{outlook["evaluation_end"]}. Entry at the next session close; '
            'the displayed holding period starts at entry.'
        )
        if selected:
            st.write(
                f'Historical frequency: {selected["wins"]} of {selected["observations"]} '
                f'finished higher. Baseline: {selected["baseline_pct"]:.1f}%; '
                f'difference: {selected["difference_pp"]:+.1f} percentage points.'
            )
            st.write(
                f'95% Wilson interval: {selected["interval_low_pct"]:.1f}%–'
                f'{selected["interval_high_pct"]:.1f}%.'
            )
        st.write("The shortest horizon with at least 30 non-overlapping matching outcomes is shown.")
        st.dataframe([{
            "Horizon": row["label"], "Matching outcomes": row["observations"],
            "Finished higher (%)": row["higher_pct"], "Baseline (%)": row["baseline_pct"],
        } for row in outlook["candidates"]], hide_index=True)
        st.markdown("**Frozen one-month rule**")
        st.write(f"Close through {closes.index[-1]:%Y-%m-%d}")
        if manifest is None:
            st.warning("Frozen validation results are unavailable. Buy signals are disabled.")
            return
        if not passed:
            st.write("The frozen rule did not meet the out-of-sample acceptance criteria.")
        else:
            st.write(f"Current frozen monthly rule: {rating}.")
        stats = manifest.get("test_metrics", {})
        if stats:
            st.write(
                f"Frozen rule, out of sample: {stats['observations']} non-overlapping observations; "
                f"{stats['finished_higher_pct']:.1f}% finished higher versus "
                f"{stats['baseline_pct']:.1f}% baseline ({stats['difference_pp']:+.1f} pp).")
            st.write(f"Median return: {stats['median_return_pct']:+.1f}%. "
                     f"Average worst dip below entry: {stats['average_worst_dip_pct']:.1f}%.")
            if stats["observations"] < 20:
                st.warning("Too thin to trust: fewer than 20 non-overlapping observations.")
        st.write(manifest["rule_text"])
        st.caption("Selected using 2010–2018 only; frozen before 2019–2026 evaluation. "
                   "Required: at least 30 non-overlapping observations and +10 percentage points versus baseline.")
        st.caption("Historical conditional outcomes. "
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
