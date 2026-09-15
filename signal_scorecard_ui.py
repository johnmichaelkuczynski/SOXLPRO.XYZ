"""A plain-language audit of the exact daily rating displayed on the homepage."""
import pandas as pd
import streamlit as st

from daily_signal_scorecard import build_rating_history, summarize_ratings


HORIZONS = {
    "1 week (5 trading days)": 5,
    "1 month (21 trading days)": 21,
    "3 months (63 trading days)": 63,
    "6 months (126 trading days)": 126,
    "1 year (252 trading days)": 252,
}


@st.cache_data(show_spinner=False, ttl=3600)
def _history(closes, horizon):
    return build_rating_history(closes, horizon)


def _percent(value, signed=False):
    if pd.isna(value):
        return "Not available"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def render_rating_scorecard(closes, current_rating):
    st.markdown("#### How accurate were these ratings?")
    if st.button("Evaluate past daily ratings", key="daily_rating_scorecard_run"):
        st.session_state["_daily_rating_scorecard_open"] = True
    if not st.session_state.get("_daily_rating_scorecard_open", False):
        st.caption("Compare past Buy and Possible Buy readings with later SOXL prices.")
        return

    st.caption(
        "Reconstructed historical ratings using exactly today's daily-signal formula—not "
        "an archive of recommendations actually issued. Each rating uses only prices "
        "available by that date. The rating formula is not retuned for this scorecard."
    )
    period_col, rating_col = st.columns(2)
    with period_col:
        period = st.selectbox("Check price after", list(HORIZONS), index=1,
                              key="daily_rating_horizon")
    with rating_col:
        rating = st.selectbox(
            "Rating to evaluate", ["BUY", "POSSIBLE BUY"],
            index=1 if current_rating == "POSSIBLE BUY" else 0,
            key="daily_rating_category",
        )
    spaced = st.checkbox(
        "Use non-overlapping holding periods",
        key="daily_rating_spaced",
        help="Samples one common calendar schedule for every rating and the baseline. "
             "This reduces repeated exposure to the same price move; it does not "
             "make market outcomes statistically independent.",
    )
    horizon = HORIZONS[period]
    try:
        with st.spinner("Evaluating historical daily ratings…"):
            history = _history(closes, horizon)
            summary = summarize_ratings(history, non_overlapping=spaced)
    except Exception:
        st.error("The rating scorecard could not be calculated. No performance estimate is available.")
        return
    if history.empty or summary.empty:
        st.info("There is not enough completed SOXL history to evaluate these ratings.")
        return

    selected = summary.loc[summary["Rating"] == rating].iloc[0]
    baseline = summary.loc[summary["Rating"] == "All rated days"].iloc[0]
    count = int(selected["Completed"])
    pending = int(selected["Pending"])
    st.caption(
        f"History: {history.index.min():%Y-%m-%d}–{history.index.max():%Y-%m-%d}. "
        f"Entry: the next trading day's close after the rating. "
        f"Exit: {horizon} trading days after entry. "
        "All-day comparisons use the same historical period and execution convention."
    )
    if count:
        st.info(
            f"After {rating}, SOXL finished higher in {_percent(selected['Win rate'])} "
            f"of {count:,} completed observations. Buying on any rated day finished "
            f"higher {_percent(baseline['Win rate'])} of the time. "
            f"Difference: {selected['Win-rate lift'] * 100:+.1f} percentage points."
        )
        metrics = st.columns(4)
        metrics[0].metric("Finished higher", _percent(selected["Win rate"]))
        metrics[1].metric("Average return", _percent(selected["Average return"], True))
        metrics[2].metric("Median return", _percent(selected["Median return"], True))
        metrics[3].metric("Worst ending return", _percent(selected["Worst return"], True))
        spread = selected["Average-return lift"] * 100
        comparison = "above" if spread >= 0 else "below"
        st.write(
            f"Average return after {rating} was "
            f"{abs(spread):.1f} percentage points {comparison} "
            f"the all-day average of {_percent(baseline['Average return'], True)}. "
            f"The average worst dip below entry during the holding period was "
            f"{_percent(selected['Average drawdown'])}."
        )
    else:
        st.info(f"No completed {rating} observations are available for this holding period.")
    if count < 30:
        st.warning("Fewer than 30 completed observations: too little evidence to judge this rating.")
    st.caption(f"{pending:,} selected-rating observations are still awaiting their full outcome and are excluded from performance statistics.")
    st.warning(
        "These are historical conditional outcomes, not a proven success probability for the "
        "next trade. Daily observations can overlap and share the same rally or decline. "
        "The comparison is descriptive, not proof that the rating adds predictive value."
    )

    with st.expander("Compare every rating"):
        table = summary.copy()
        for column in ("Win rate", "Average return", "Median return", "Worst return", "Average drawdown"):
            table[column] = table[column].map(_percent)
        for column in ("Win-rate lift", "Average-return lift"):
            table[column] = table[column].map(
                lambda value: "—" if pd.isna(value) else f"{value * 100:+.1f} pp"
            )
        table = table.rename(columns={"Win rate": "Finished higher", "Completed": "Completed outcomes"})
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption("“Finished higher” means a positive price return, including for sell ratings. It is not a measure of sell-rating correctness.")

    with st.expander("Inspect historical ratings and subsequent prices"):
        selected_history = history[history["Rating"] == rating].copy()
        st.caption(
            "The ledger contains every reconstructed daily rating. When non-overlapping "
            "sampling is enabled above, only the common spaced schedule contributes to the summary."
        )
        ledger_display = selected_history.sort_index(ascending=False).copy()
        for column in ("Return", "Worst drawdown"):
            ledger_display[column] = ledger_display[column].map(_percent)
        st.dataframe(ledger_display, width="stretch")
        st.download_button(
            "Download all historical ratings and outcomes (CSV)",
            history.to_csv(index=True), "soxl_daily_rating_outcomes.csv", "text/csv",
            key="daily_rating_history_download",
        )
        st.download_button(
            "Download rating scorecard (CSV)",
            summary.assign(
                Horizon_sessions=horizon,
                Sampling="Non-overlapping common schedule" if spaced else "Every rated day",
                Entry_convention="Next session close",
                History_source="Reconstructed current formula",
            ).to_csv(index=False),
            "soxl_daily_rating_scorecard.csv", "text/csv",
            key="daily_rating_summary_download",
        )
    with st.expander("What this evaluation can and cannot establish"):
        st.write(
            "The price source and current historical adjustments are the same as the daily "
            "signal. Only completed sessions are included. Partial lookback windows are "
            "excluded exactly as on the signal card. Returns are measured from the next "
            "session's close to a later close; this avoids assuming that a closing-price "
            "rating could be acted on at that same close."
        )
        st.write(
            "Returns exclude trading costs, slippage, taxes and any cash distributions not "
            "already reflected in the source prices. Worst dip is based on daily closes, "
            "not intraday lows. This is not a portfolio backtest: repeated ratings are not "
            "independent trades, and compounded strategy returns are not calculated. "
            "A reconstructed history cannot establish what an older app version actually displayed."
        )