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


def _finite(value):
    """Keep missing and nonfinite model outputs out of the comparison table."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _method_help():
    st.markdown("#### Method and interpretation")
    st.markdown(
        """
- **Hurst exponent (H):** R/S analysis on **daily log-price increments**
  calculated from closing prices, not on price levels, which biases H.
  Rescaled-range statistics are computed across blocks at multiple scales;
  an ordinary least-squares (OLS) slope across log scales estimates H.
- **Interpretation:** H < 0.5 suggests anti-persistence, H around 0.5 suggests
  random behavior, and H > 0.5 suggests persistence. Estimates are approximate
  and noisy in finite samples; changing the lookback can change the result.
- **Score:** `clamp((0.5 - H) * 200, 0, 100)`. A higher score describes
  stronger estimated anti-persistence. It is **not a trading signal or a
  probability of profit**.
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
    with st.expander("Mean Reversion Score", expanded=True):
        st.caption(
            "Compare statistical anti-persistence across SOXL and your selected "
            "chart benchmarks. Descriptive research only; charts and signals "
            "remain unchanged."
        )
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
                        "H": f"{hurst:.4f}" if hurst is not None else "N/A",
                        "Score / 100": (
                            f"{min(100.0, max(0.0, score)):.1f} / 100"
                            if score is not None and hurst is not None
                            else "N/A"
                        ),
                        "Reversion speed": (
                            f"{half_life:,.1f} trading days"
                            if half_life is not None and half_life > 0
                            else "N/A"
                        ),
                        "Observation date": date,
                        "Observations": count,
                        "Explanation": reason,
                    }
                )
            except Exception:
                failed = True
                rows.append(
                    {
                        "Symbol": str(symbol),
                        "H": "N/A",
                        "Score / 100": "N/A",
                        "Reversion speed": "N/A",
                        "Observation date": "N/A",
                        "Observations": 0,
                        "Explanation": (
                            "Analysis unavailable for this symbol. Closing-price "
                            "data may be missing or unsupported; try again."
                        ),
                    }
                )

        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Symbol": st.column_config.TextColumn("Symbol"),
                "H": st.column_config.TextColumn("H", help=_H_HELP),
                "Score / 100": st.column_config.TextColumn(
                    "Score / 100", help=_SCORE_HELP
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
