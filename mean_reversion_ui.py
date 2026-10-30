"""Read-only mean-reversion comparisons using the app's existing price frames."""

import math

import pandas as pd
import streamlit as st


_H_HELP = (
    "H < 0.5 suggests mean-reverting (anti-persistent) moves; H around 0.5 suggests "
    "random behavior; H > 0.5 suggests trending (persistent) moves. "
    "These are approximate, noisy finite-sample estimates."
)
_SCORE_HELP = (
    "Score = clamp((0.5 - H) * 200, 0, 100). "
    "This is a descriptive statistical score, not a trading signal or "
    "a probability of profit."
)
_TREND_HELP = (
    "Trend Direction Score = clamp(MA200 60-session percent change, -10, 10) * 10; "
    "absolute changes below 0.5% score zero. Positive means upward drift; negative "
    "means downward drift. Requires 260 observations, independently of the Hurst lookback."
)
_K_HELP = (
    "Signed K = Mean Reversion Score * Trend Direction Score / 100. "
    "Edge-only K = max(0, Signed K). This is an unvalidated heuristic factor, "
    "not a profit probability or proven alpha. It does not replace either "
    "component or the daily signal. A zero edge-only value can still conceal "
    "a downtrend; read the label."
)
_CROSS_HELP = (
    "Current moving-average state: Yes when MA50 > MA200, No when MA50 <= MA200. "
    "This is not a newly observed crossover event. Requires 200 observations; "
    "N/A means insufficient or unavailable history."
)


def _finite(value):
    """Keep missing and nonfinite model outputs out of the comparison table."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _method_help():
    with st.expander("Method and interpretation", expanded=False):
        st.markdown(
            """
- **Hurst exponent (H):** R/S analysis on **daily log-price increments**
  calculated from closing prices, not on price levels, which biases H.
  Rescaled-range statistics are computed across blocks at multiple scales;
  an ordinary least-squares (OLS) slope across log scales estimates H.
- **Interpretation:** H < 0.5 suggests anti-persistence, H around 0.5 suggests
  random behavior, and H > 0.5 suggests persistence. Estimates are approximate
  and noisy in finite samples; changing the lookback can change the result.
- **Mean Reversion Score:** `clamp((0.5 - H) * 200, 0, 100)`. A higher score describes
  stronger estimated anti-persistence. It is **not a trading signal or a
  probability of profit**.
- **Trend Direction Score:** the MA200's 60-session percent change, clamped
  to -10% through +10%, then multiplied by 10. Absolute changes below 0.5%
  score zero. Positive means upward drift; negative means downward drift.
  This requires **260 observations**, independently of the Hurst lookback.
- **K Metric:** Signed K = Mean Reversion Score × Trend Direction Score / 100;
  Edge-only K = max(0, Signed K). This **unvalidated heuristic factor is not
  a profit probability or proven alpha** and replaces neither component nor
  the daily signal. Edge-only zero can conceal downward drift: read the label.
- **Golden cross:** current MA50 > MA200 state, not a newly observed crossover.
  Yes means above; No means at or below. Requires **200 observations**.
- **Reversion speed (half-life):** estimated by regressing price change on
  lagged price level. A half-life is reported only for positive mean-reversion
  rate theta; failed or unsupported estimates are **N/A**. This separate
  regression is not proof of mean reversion.
- **Coverage:** observation date and count are reported separately for each
  symbol. Missing, insufficient, or constant data can prevent estimation;
  unavailable estimates are not zero scores.

This comparison uses only the supplied historical frames. It does not fetch
prices or change charts, daily signals, or benchmark selections.
            """
        )


@st.fragment
def render_mean_reversion(frames: dict):
    """Compare supplied symbols without mutating price frames or signal state."""
    with st.expander("K Metric · Reversion & Trend", expanded=True):
        st.caption(
            "Compare memory versus drift across SOXL and your selected chart "
            "benchmarks. Screening heuristics, not proven recommendations; "
            "charts and daily signals remain unchanged."
        )
        k_mode = st.radio(
            "K calculation",
            ["Edge-only K", "Signed K"],
            horizontal=True,
            key="mean_reversion_k_mode",
            help=_K_HELP,
        )
        ranking = st.selectbox(
            "Rank by",
            ["K Metric", "Mean Reversion Score", "Trend Direction Score"],
            key="mean_reversion_ranking",
            help="Descending numeric ranking; unavailable values appear last.",
        )
        k_key = "k_signed" if k_mode == "Signed K" else "k_edge"
        lookback = int(
            st.number_input(
                "Lookback (trading sessions)",
                min_value=100,
                max_value=500,
                value=252,
                step=1,
                key="mean_reversion_lookback",
                help=(
                    "Use the same requested lookback for every supplied symbol. "
                    "Actual usable observations and dates can differ."
                ),
            )
        )

        if not frames:
            st.info(
                "No closing-price history is available to compare. Once SOXL "
                "or a selected chart benchmark has history, its estimates "
                "and observation coverage will appear here."
            )
            _method_help()
            return

        try:
            from mean_reversion_model import analyze
        except ImportError:
            st.error(
                "Mean-reversion analysis is unavailable. No estimates are "
                "shown; charts and daily signals remain unchanged."
            )
            st.button("Retry analysis", key="mean_reversion_retry")
            _method_help()
            return

        rows = []
        failed = False
        for symbol, frame in frames.items():
            try:
                # Isolate the existing chart data from any model preparation.
                result = analyze(
                    frame.copy(deep=True) if frame is not None else frame,
                    lookback,
                )
                hurst = _finite(result.get("H"))
                score = _finite(result.get("score"))
                half_life = _finite(result.get("half_life"))
                trend = _finite(result.get("trend"))
                slope = _finite(result.get("slope"))
                k_value = _finite(result.get(k_key))
                k_label = str(result.get("k_label") or "N/A")
                golden_cross = result.get("golden_cross")
                trend_reason = str(result.get("trend_reason") or "").strip()
                if trend is None and not trend_reason:
                    trend_reason = "Trend unavailable: requires 260 usable observations."
                count = max(0, int(result.get("count") or 0))
                date = str(result.get("date") or "N/A")
                reason = str(result.get("reason") or "").strip()
                if hurst is None and not reason:
                    reason = (
                        "H unavailable: missing, insufficient, or constant "
                        "closing-price data."
                    )
                elif half_life is None or half_life <= 0:
                    reason = reason or (
                        "Half-life unavailable: no supported positive theta estimate."
                    )
                else:
                    reason = reason or "Estimates available; finite-sample uncertainty applies."
                rows.append(
                    {
                        "Symbol": str(symbol),
                        "Mean Reversion Score": (
                            min(100.0, max(0.0, score))
                            if score is not None and hurst is not None
                            else None
                        ),
                        "Trend Direction Score": trend,
                        "K Metric": k_value,
                        "K label": k_label,
                        "Golden cross": (
                            "Yes" if golden_cross is True
                            else "No" if golden_cross is False else "N/A"
                        ),
                        "H": hurst,
                        "MA200 change (60 sessions)": slope,
                        "Reversion speed": (
                            f"{half_life:,.1f} trading days"
                            if half_life is not None and half_life > 0
                            else "N/A"
                        ),
                        "Observation date": date,
                        "Observations": count,
                        "Explanation": " ".join(part for part in (reason, trend_reason) if part),
                    }
                )
            except Exception:
                failed = True
                rows.append(
                    {
                        "Symbol": str(symbol),
                        "Mean Reversion Score": None,
                        "Trend Direction Score": None,
                        "K Metric": None,
                        "K label": "N/A",
                        "Golden cross": "N/A",
                        "H": None,
                        "MA200 change (60 sessions)": None,
                        "Reversion speed": "N/A",
                        "Observation date": "N/A",
                        "Observations": 0,
                        "Explanation": (
                            "Analysis unavailable for this symbol. Closing-price "
                            "data may be missing or unsupported; try again."
                        ),
                    }
                )

        # Sort numeric model values before display formatting; N/A is never zero.
        rows.sort(
            key=lambda row: (
                row[ranking] is None,
                -row[ranking] if row[ranking] is not None else 0,
            )
        )
        for row in rows:
            for column in ("Mean Reversion Score", "Trend Direction Score", "K Metric"):
                value = row[column]
                row[column] = f"{value:.1f}" if value is not None else "N/A"
            hurst = row["H"]
            row["H"] = f"{hurst:.4f}" if hurst is not None else "N/A"
            slope = row["MA200 change (60 sessions)"]
            row["MA200 change (60 sessions)"] = (
                f"{slope:+.2f}%" if slope is not None else "N/A"
            )

        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Symbol": st.column_config.TextColumn("Symbol"),
                "H": st.column_config.TextColumn("H", help=_H_HELP),
                "Mean Reversion Score": st.column_config.TextColumn(
                    "Mean Reversion Score", help=_SCORE_HELP
                ),
                "Trend Direction Score": st.column_config.TextColumn(
                    "Trend Direction Score", help=_TREND_HELP
                ),
                "K Metric": st.column_config.TextColumn(
                    "K Metric", help=_K_HELP
                ),
                "K label": st.column_config.TextColumn(
                    "K label",
                    help="Model interpretation, including downtrend warnings even when Edge-only K is zero.",
                ),
                "Golden cross": st.column_config.TextColumn(
                    "Golden cross", help=_CROSS_HELP
                ),
                "MA200 change (60 sessions)": st.column_config.TextColumn(
                    "MA200 change (60 sessions)",
                    help="Raw percent change in MA200 over 60 sessions, before clamping or the 0.5% neutral threshold.",
                ),
                "Reversion speed": st.column_config.TextColumn(
                    "Reversion speed",
                    help=(
                        "Estimated half-life in trading days from regression of "
                        "price change on lagged level. Positive theta only; "
                        "N/A is not evidence for or against mean reversion."
                    ),
                ),
                "Observation date": st.column_config.TextColumn(
                    "Observation date",
                    help="Latest observation date reported by the model for this symbol.",
                ),
                "Observations": st.column_config.NumberColumn(
                    "Observations", format="%d",
                    help="Usable observation count reported by the model.",
                ),
                "Explanation": st.column_config.TextColumn(
                    "Explanation", width="large"
                ),
            },
        )
        if failed:
            st.warning(
                "Some symbols could not be analyzed. Other rows remain "
                "available; no chart or signal data was changed."
            )
            st.button("Retry analysis", key="mean_reversion_retry")
        st.caption(
            "N/A means unavailable, not zero. Hover over column headings for "
            "definitions. Dates and usable history may differ by symbol."
        )
        _method_help()
