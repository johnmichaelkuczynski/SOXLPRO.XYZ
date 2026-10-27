"""Interactive model-based price scenarios, separate from the daily signal."""

import math

import pandas as pd
import streamlit as st


_PRICE_KEY = "price_scenario_selected_price"
_HORIZON_KEY = "price_scenario_horizon"
_TIMEFRAMES = {"One month": 21, "Six months": 126, "Twelve months": 252}


@st.cache_data(show_spinner=False)
def _prepare_history(closes: pd.Series) -> pd.DataFrame:
    """Cache historical preparation independently of slider interactions."""
    from continuous_price_model import prepare_history

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
    with st.expander("How this price model works"):
        st.markdown(
            """
The model regresses **forward log return** on **log entry price relative to
the trailing 252-session geometric mean**.

- Training uses nonoverlapping, completed historical periods for the selected
  horizon: **21, 126, or 252 trading sessions**. At least **8 training periods**
  are required globally for that horizon, not separately at each entry price.
- A **Student-t prediction** includes residual and coefficient uncertainty.
  The probability of finishing higher is a model estimate, not an observed
  historical frequency.
- The **approximate 95% parameter-uncertainty interval** describes uncertainty
  in the estimated probability under the model assumptions. It is not a
  prediction interval for the next trade's outcome.
- The **80% model prediction range** spans the model's 10th–90th percentiles,
  not absolute minimum and maximum outcomes. Losses can exceed this range.
- Conditional upside is the median among **modeled gains** only; it excludes
  losing and flat outcomes and is not the overall expected return.
- Entry prices beyond the observed relative-price range are marked
  **extrapolation**, not rejected.
- Fees, slippage, taxes, and financing costs are not included.

These estimates rely purely on model assumptions and are **NOT validated
predictive probabilities**. This method is separate from the old analogue
validation; that validation does not validate this model. SOXL is a leveraged
ETF; path dependence and changing market conditions can make future outcomes
materially different. This is hypothetical entry-price research, not the
probability that SOXL will reach the selected entry price. The original daily
signal, including **NO EDGE**, remains unchanged.
            """
        )


@st.fragment
def render_price_scenario(closes, current_price, quote_label):
    """Render an automatically updating scenario without changing signal state."""
    st.markdown("### What if SOXL were this price?")
    st.caption(
        "Explore model estimates for a hypothetical starting price. "
        "This is not the probability that SOXL will hit that price."
    )
    if quote_label is not None:
        st.caption(str(quote_label))

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
        st.session_state["price_scenario_reset_token"] = st.session_state.get("price_scenario_reset_token", 0) + 1
    if _PRICE_KEY not in st.session_state:
        st.session_state[_PRICE_KEY] = default_price

    timeframe = st.selectbox(
        "Timeframe",
        options=list(_TIMEFRAMES),
        index=1,
        key=_HORIZON_KEY,
    )
    horizon = _TIMEFRAMES[timeframe]

    try:
        from continuous_price_model import estimate
        from price_probability_slider import probability_slider

        prepared = _prepare_history(closes)
        selected_price = probability_slider(
            prepared, st.session_state[_PRICE_KEY], horizon, timeframe,
            st.session_state.get("price_scenario_reset_token", 0),
        )
        st.session_state[_PRICE_KEY] = float(selected_price)
        result = estimate(prepared, float(selected_price), horizon)
    except Exception:
        st.error(
            "Model unavailable right now. "
            "No model probabilities or price estimates are shown. The daily signal is unchanged."
        )
        st.button("Retry scenario", key="price_scenario_retry")
        _method_help()
        return

    count = result.get("count", 0)
    history_date = result.get("history_date") or "unavailable"
    st.caption(
        f"{count} nonoverlapping completed training periods · "
        f"{horizon} trading sessions · History through {history_date}"
    )

    if not result.get("supported", False):
        st.warning(
            result.get("reason")
            or "Model unavailable: insufficient completed training periods for this horizon."
        )
        st.caption(
            "No numeric model estimates are shown when the model is unavailable. "
            "At least 8 completed training periods are required for the selected "
            "horizon, regardless of entry price. Try another timeframe."
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

    st.markdown(f"#### Model estimates from a ${selected_price:,.2f} entry")
    st.caption(str(result.get("model_label") or "Continuous price model"))
    if result.get("extrapolated", False):
        st.warning(
            "Extrapolated model estimate: this entry price is beyond the observed "
            "relative-price range. The model still provides an estimate, but its "
            "assumptions may be less reliable here."
        )
    frequency_column, median_column = st.columns(2)
    with frequency_column:
        st.metric(
            "Model-estimated probability of finishing higher",
            f"{probability:.4%}" if probability is not None else "Unavailable",
        )
        if ci_low is not None and ci_high is not None:
            st.caption(
                f"Approximate 95% parameter-uncertainty interval: "
                f"{ci_low:.1%}–{ci_high:.1%}"
            )
        else:
            st.caption("Approximate 95% parameter-uncertainty interval unavailable.")
    with median_column:
        st.metric(
            "Model-estimated median future price",
            f"${selected_price * (1 + median):,.2f}" if median is not None else "Unavailable",
        )
        if median is not None:
            st.caption(
                f"Change from entry: {selected_price * median:+,.2f} USD "
                f"({median:+.1%})"
            )

    if low is not None and high is not None:
        st.markdown("**80% model prediction range · 10th–90th percentile**")
        st.text(
            f"Lower outcome: {_return_description(selected_price, low)}\n"
            f"Upper outcome: {_return_description(selected_price, high)}"
        )
        st.caption(
            "This range includes losses when implied by the model. "
            "It is not a floor or ceiling: losses can fall below it, and SOXL "
            "can lose substantially more."
        )
    else:
        st.caption("80% model prediction range unavailable.")

    if upside is not None:
        st.markdown("**Conditional upside · modeled gains only**")
        st.text(_return_description(selected_price, upside))
        st.caption(
            "Median among modeled gains only. Losing and flat outcomes are "
            "excluded; this is not the overall modeled expected return."
        )

    st.caption(
        "These estimates rely purely on model assumptions, NOT validated "
        "predictive probabilities or a recommendation. This method is separate "
        "from the old analogue validation. The existing daily "
        "rating is not a guarantee; NO EDGE and all daily signal readings "
        "remain unchanged."
    )
    _method_help()
