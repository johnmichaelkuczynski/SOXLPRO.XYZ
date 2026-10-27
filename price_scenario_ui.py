"""Interactive historical price scenarios, separate from the daily signal."""

import math

import pandas as pd
import streamlit as st


_PRICE_KEY = "price_scenario_selected_price"
_HORIZON_KEY = "price_scenario_horizon"
_TIMEFRAMES = {"One month": 21, "Six months": 126, "Twelve months": 252}


@st.cache_data(show_spinner=False)
def _prepare_history(closes: pd.Series) -> pd.DataFrame:
    """Cache historical preparation independently of slider interactions."""
    from price_scenario_model import prepare_history

    return prepare_history(closes)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _return_description(price, value):
    return f"${price * (1 + value):,.2f} ({price * value:+,.2f} USD; {value:+.1%})"


def _method_help():
    with st.expander("How this historical scenario works"):
        st.markdown(
            """
Historical dates are matched within **10 composite percentile points** of
the selected price's composite historical-range percentile. Each historical
date uses only the trailing ranges available at that date.

- Observations are non-overlapping for the selected horizon: **21, 126, or
  252 trading sessions**.
- Outcomes use close-to-close returns. At least **10 observations** are needed
  before odds or price estimates are displayed.
- The finishing-higher frequency counts positive returns. Its **95% Wilson
  interval** describes sampling uncertainty, not a guaranteed probability range
  for your next trade.
- The estimated range uses the **10th and 90th return percentiles**, not
  absolute minimum and maximum outcomes. Losses can exceed the displayed range.
- Conditional upside is the median return among positive outcomes only; it
  excludes losses and is not the overall expected return.
- Fees, slippage, taxes, and financing costs are not included.

Historical analogues are not a guarantee. SOXL is a leveraged ETF; path
dependence and changing market conditions can make future outcomes materially
different. This is hypothetical entry-price research, not the probability that
SOXL will reach the selected entry price.
            """
        )


@st.fragment
def render_price_scenario(closes, current_price, quote_label):
    """Render an automatically updating scenario without changing signal state."""
    st.markdown("### What if SOXL were this price?")
    st.caption(
        "Explore a hypothetical starting price against historical evidence. "
        "This is not the probability that SOXL will hit that price."
    )
    if quote_label is not None:
        st.caption(str(quote_label))
    st.info(
        "Exploratory historical frequencies — NOT validated next-trade "
        "probabilities. The daily signal, including NO EDGE, is unchanged."
    )

    latest = _finite(current_price)
    valid_latest = latest is not None and latest > 0
    default_price = round(min(500.0, max(1.0, latest)), 2) if valid_latest else 1.0
    if valid_latest and not 1.0 <= latest <= 500.0:
        st.warning(
            f"The current quote (${latest:,.2f}) is outside the $1.00–$500.00 "
            f"slider range. The latest-price default is clamped to "
            f"${default_price:,.2f}; any existing selection is preserved until "
            "you choose Use latest price."
        )
    elif not valid_latest:
        st.warning(
            "The current quote is unavailable. Start with a hypothetical price "
            "of $1.00 or adjust the slider; Use latest price is unavailable."
        )

    # The reset must happen before the slider is instantiated on this run.
    if st.button(
        "Use latest price",
        key="price_scenario_use_latest",
        disabled=not valid_latest,
    ):
        st.session_state[_PRICE_KEY] = default_price
    if _PRICE_KEY not in st.session_state:
        st.session_state[_PRICE_KEY] = default_price

    selected_price = st.slider(
        "Hypothetical entry price (USD)",
        min_value=1.0,
        max_value=500.0,
        step=0.01,
        format="$%.2f",
        key=_PRICE_KEY,
        help="Release the slider to update the historical scenario. No submit needed.",
    )
    left_endpoint, right_endpoint = st.columns(2)
    left_endpoint.caption("$1 per share")
    right_endpoint.markdown('<div style="text-align:right;font-size:.85rem;color:#64748b">$500 per share</div>',
                            unsafe_allow_html=True)
    timeframe = st.selectbox(
        "Timeframe",
        options=list(_TIMEFRAMES),
        index=1,
        key=_HORIZON_KEY,
    )
    horizon = _TIMEFRAMES[timeframe]

    try:
        from price_scenario_model import estimate

        prepared = _prepare_history(closes)
        result = estimate(prepared, selected_price=float(selected_price), horizon=horizon)
    except Exception:
        st.error(
            "Historical scenario research is unavailable right now. "
            "No odds or price estimates are shown. The daily signal is unchanged."
        )
        st.button("Retry scenario", key="price_scenario_retry")
        _method_help()
        return

    count = result.get("count", 0)
    history_date = result.get("history_date") or "unavailable"
    st.caption(
        f"{count} non-overlapping historical observations · "
        f"{horizon} trading sessions · History through {history_date}"
    )

    if not result.get("supported", False):
        st.warning(
            result.get("reason")
            or "There is not enough historical evidence for this scenario."
        )
        st.caption(
            "No numeric odds or forecasts are shown for unsupported scenarios. "
            "Try another entry price or timeframe."
        )
        _method_help()
        return

    probability = _finite(result.get("probability"))
    median = _finite(result.get("median_return"))
    low = _finite(result.get("low_return"))
    high = _finite(result.get("high_return"))
    upside = _finite(result.get("upside_return"))
    ci_low = _finite(result.get("ci_low"))
    ci_high = _finite(result.get("ci_high"))

    st.markdown(f"#### Historical outcomes from a ${selected_price:,.2f} entry")
    frequency_column, median_column = st.columns(2)
    with frequency_column:
        st.metric(
            "Historical probability of finishing higher",
            f"{probability:.1%}" if probability is not None else "Unavailable",
        )
        if ci_low is not None and ci_high is not None:
            st.caption(f"95% Wilson interval: {ci_low:.1%}–{ci_high:.1%}")
        else:
            st.caption("95% Wilson interval unavailable.")
    with median_column:
        st.metric(
            "Median future price",
            f"${selected_price * (1 + median):,.2f}" if median is not None else "Unavailable",
        )
        if median is not None:
            st.caption(
                f"Change from entry: {selected_price * median:+,.2f} USD "
                f"({median:+.1%})"
            )

    if low is not None and high is not None:
        st.markdown("**Estimated outcome range · 10th–90th percentile**")
        st.text(
            f"Lower outcome: {_return_description(selected_price, low)}\n"
            f"Upper outcome: {_return_description(selected_price, high)}"
        )
        st.caption(
            "This range includes losses when present in the matched outcomes. "
            "It is not a floor or ceiling: losses can fall below it, and SOXL "
            "can lose substantially more."
        )
    else:
        st.caption("Estimated outcome range unavailable.")

    if upside is not None:
        st.markdown("**Conditional upside · positive outcomes only**")
        st.text(_return_description(selected_price, upside))
        st.caption(
            "Median among historical gains only. Losing and flat outcomes are "
            "excluded; this is not the expected return for all observations."
        )

    st.caption(
        "These are exploratory historical frequencies, NOT validated "
        "next-trade probabilities or a recommendation. The existing daily "
        "rating is not a guarantee; NO EDGE and all daily signal readings "
        "remain unchanged."
    )
    _method_help()
