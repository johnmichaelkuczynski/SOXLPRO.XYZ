"""Public options scenario UI; provider access occurs only on explicit request."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


_PREFIX = "options_projection_"


@st.cache_data(show_spinner=False, max_entries=64, ttl=60)
def _cached_project(history, contract, premium, horizon_date, contracts,
                    iv_factor, rate, dividend):
    # All assumptions participate in the cache key, including history and quote.
    from options_projection_model import project

    return project(
        history, contract, premium, horizon_date, contracts=contracts,
        iv_factor=iv_factor, rate=rate, dividend=dividend,
    )


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _money(value):
    number = _number(value)
    return f"${number:,.2f}" if number is not None else "Unavailable"


def _contract_label(contract):
    return (
        f"{contract.get('ticker', 'Contract')} · "
        f"{contract.get('type', '').title()} "
        f"{_money(contract.get('strike'))} · {contract.get('expiration', '')}"
    )


def _fan_chart(result, premium, contracts, horizon_date, position_view):
    dates = pd.to_datetime(result["dates"])
    quantiles = np.asarray(result["quantiles"], dtype=float)
    probabilities = np.asarray(result["profit_probability"], dtype=float)
    if quantiles.shape != (5, len(dates)) or probabilities.shape != (len(dates),):
        raise ValueError("Invalid projection dimensions")
    if not np.isfinite(quantiles).all() or not np.isfinite(probabilities).all():
        raise ValueError("Invalid projection values")
    scale = float(result["multiplier"]) * contracts
    values = (quantiles - premium) * scale if position_view else quantiles
    value_name = "Position P/L" if position_view else "Option premium"
    fig = go.Figure()
    # Draw the outer interval before the inner interval, with no boundary lines.
    for low, high, name, color in (
        (0, 4, "90% interval (5th–95th)", "rgba(59,130,166,0.14)"),
        (1, 3, "50% interval (25th–75th)", "rgba(59,130,166,0.28)"),
    ):
        fig.add_trace(go.Scatter(
            x=dates, y=values[low], mode="lines", line={"width": 0},
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=values[high], mode="lines", line={"width": 0},
            fill="tonexty", fillcolor=color, name=name, hoverinfo="skip",
        ))
    for index, name in ((0, "5th percentile"), (1, "25th percentile"),
                        (3, "75th percentile"), (4, "95th percentile"),
                        (2, "Median")):
        fig.add_trace(go.Scatter(
            x=dates, y=values[index], mode="lines", name=name,
            line={"color": "#267191", "width": 2.5 if index == 2 else 0},
            showlegend=index == 2, customdata=probabilities[:, None],
            hovertemplate=(
                "%{x|%b %d, %Y}<br>" + name + " " + value_name
                + ": $%{y:,.2f}<br>Model probability of profit: "
                "%{customdata[0]:.1%}<extra></extra>"
            ),
        ))
    fig.add_hline(
        y=0 if position_view else premium, line_dash="dash",
        line_color="#ad7544",
        annotation_text="Purchase cost / break-even" if position_view else "Purchase premium",
        annotation_position="top left",
    )
    # Using a shape rather than add_vline avoids datetime annotation arithmetic
    # incompatibilities across Plotly/Pandas versions.
    fig.add_shape(
        type="line", x0=pd.Timestamp(horizon_date), x1=pd.Timestamp(horizon_date),
        y0=0, y1=1, yref="paper",
        line={"color": "#ad7544", "width": 1.5, "dash": "dot"},
    )
    fig.add_annotation(
        x=pd.Timestamp(horizon_date), y=1, yref="paper", text="Selling date",
        showarrow=False, yshift=12,
    )
    fig.update_layout(
        height=440, margin={"l": 12, "r": 12, "t": 36, "b": 16},
        hovermode="x unified", yaxis_title=f"{value_name} (USD)",
        xaxis_title="Projection through expiration",
        legend={"orientation": "h", "y": -0.22},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(tickprefix="$", gridcolor="rgba(128,128,128,0.16)")
    fig.update_xaxes(range=[dates[0], dates[-1]], showgrid=False)
    return fig


def _disclosure():
    st.caption(
        "Experimental, unvalidated model; not investment advice. Approximate "
        "Black–Scholes European pricing is used for American options and does not "
        "capture early exercise or assignment. IV scenarios are assumptions, not "
        "calibrated probabilities. Quotes are snapshots, not a live-price or "
        "execution guarantee. Profit estimates exclude fees, slippage and taxes."
    )


@st.dialog("Options projection", width="large")
def _projection_dialog(history, contract):
    st.markdown(f"**{_contract_label(contract)}**")
    st.caption(
        f"Bid {_money(contract.get('bid'))} · Ask {_money(contract.get('ask'))} · "
        f"Quote timestamp: {contract.get('quote_time') or 'Unavailable'}"
    )
    try:
        expiration = pd.Timestamp(contract["expiration"]).date()
    except (KeyError, TypeError, ValueError):
        st.error("This contract has no usable expiration. Load options again.")
        return
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if expiration <= today:
        st.info("Choose a contract expiring after today to project a future selling date.")
        return
    ask = _number(contract.get("ask"))
    if ask is None or ask <= 0:
        st.warning("An executable ask is unavailable. Enter your own purchase premium.")

    # Contract-specific widget identities prevent carrying another contract's ask.
    identity = "|".join(str(contract.get(field, "")) for field in
                        ("ticker", "expiration", "type", "strike", "quote_time"))
    key = _PREFIX + identity
    left, right = st.columns(2)
    with left:
        horizon = st.date_input(
            "Selling date", value=expiration, min_value=today + timedelta(days=1),
            max_value=expiration, key=key + "_horizon",
            help="Metrics use this date; the graph continues through expiration.",
        )
        premium = st.number_input(
            "Purchase premium per share ($)", min_value=0.01,
            value=ask if ask is not None and ask > 0 else None,
            step=0.01, format="%.2f", key=key + "_premium",
        )
        contracts = st.number_input(
            "Contracts", min_value=1, value=1, step=1, key=key + "_contracts",
        )
    with right:
        rate = st.number_input(
            "Annual risk-free rate (%)", value=4.0, step=0.25, key=key + "_rate",
        )
        dividend = st.number_input(
            "Annual dividend yield (%)", min_value=0.0, value=0.0,
            step=0.25, key=key + "_dividend",
        )
        iv_factor = st.selectbox(
            "IV scenario", options=[0.8, 1.0, 1.2], index=1,
            format_func=lambda value: {
                0.8: "Lower IV · 0.8× quoted IV",
                1.0: "Quoted IV · 1.0×",
                1.2: "Higher IV · 1.2× quoted IV",
            }[value], key=key + "_iv",
        )
    st.caption(
        "Rate and dividend yield above are editable annual assumptions, not "
        "provider observations. Premium is per share; position amounts use "
        "the contract's supplied multiplier."
    )
    view = st.radio(
        "Chart view", ["Option premium", "Position P/L"], horizontal=True,
        key=key + "_view",
    )
    _disclosure()
    if premium is None:
        st.info("Enter a purchase premium to calculate this scenario.")
        return
    if not today < horizon <= expiration:
        st.error("Selling date must be after today and no later than expiration.")
        return
    try:
        with st.spinner("Calculating option scenarios…"):
            result = _cached_project(
                history, contract, float(premium), horizon, int(contracts),
                float(iv_factor), float(rate) / 100, float(dividend) / 100,
            )
        fig = _fan_chart(result, premium, contracts, horizon, view == "Position P/L")
        profit = np.asarray(result["horizon_profit_quantiles"], dtype=float)
        if profit.shape != (5,) or not np.isfinite(profit).all():
            raise ValueError("Invalid horizon quantiles")
        st.markdown(f"**Selected selling date · {horizon:%b %d, %Y}**")
        a, b = st.columns(2)
        a.metric("Median position P/L", _money(profit[2]))
        b.metric("Model probability of profit", f"{float(result['horizon_profit_probability']):.1%}")
        st.caption(
            f"90% position P/L interval: {_money(profit[0])} to {_money(profit[4])} · "
            f"50% interval: {_money(profit[1])} to {_money(profit[3])}"
        )
        st.plotly_chart(fig, width="stretch", key=key + "_chart")
        st.caption(
            f"{int(result['samples']):,} simulated paths · "
            f"Multiplier: {float(result['multiplier']):g} · "
            f"Purchase cost: {_money(premium * contracts * float(result['multiplier']))}"
        )
        with st.expander("Daily sampled path extremes"):
            low, high = st.columns(2)
            low.metric("5th percentile of path lows", _money(result["path_low05"]))
            high.metric("95th percentile of path highs", _money(result["path_high95"]))
            st.caption(
                "Option prices per share across daily sampled paths through your selected selling date. "
                "These are percentile summaries, not absolute bounds or intraday "
                "extremes, and do not represent the probability of hitting a target."
            )
        st.caption(
            "The historical SOXL log-return model is reused, not a validated options "
            "forecast. Volatility transitions toward the selected IV scenario by expiry. "
            "Today's modeled premium may differ from the market bid/ask. Calendar-day "
            "points include weekends and are not necessarily executable trading quotes."
        )
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error(
            "This projection could not be calculated. Check the quote, price history "
            "and assumptions, then try again. No simulated values are shown."
        )
        if st.button("Retry projection", key=key + "_retry"):
            st.rerun(scope="fragment")


def render_options_projection(history: pd.DataFrame):
    """Render the existing app's public options tab without implicit quote fetches."""
    st.subheader("Options")
    st.caption(
        "Load a quoted contract, set your purchase premium, and explore its "
        "modeled value through expiration in a popup."
    )
    today = datetime.now(ZoneInfo("America/New_York")).date()
    default_expiration = today + timedelta(days=28)
    default_expiration += timedelta(days=(4-default_expiration.weekday()) % 7)
    with st.form(_PREFIX + "load_form"):
        left, right = st.columns(2)
        with left:
            expiration = st.date_input(
                "Expiration", value=default_expiration,
                min_value=today + timedelta(days=1), key=_PREFIX + "expiration",
            )
        with right:
            kind = st.selectbox(
                "Option type", ["call", "put"], format_func=str.title,
                key=_PREFIX + "kind",
            )
        load = st.form_submit_button("Load options", type="primary")

    if load:
        # Never retain a previous chain after a failed/empty replacement request.
        st.session_state.pop(_PREFIX + "chain", None)
        st.session_state.pop(_PREFIX + "loaded_for", None)
        st.session_state.pop(_PREFIX + "load_error", None)
        try:
            from options_projection_data import OptionsDataError, load_chain
        except ImportError:
            st.session_state[_PREFIX + "load_error"] = (
                "Options data is unavailable: the data integration is not installed."
            )
        else:
            try:
                with st.spinner("Loading option quotes…"):
                    chain = load_chain(expiration, kind)
                st.session_state[_PREFIX + "chain"] = chain
                st.session_state[_PREFIX + "loaded_for"] = (expiration, kind)
            except OptionsDataError as exc:
                st.session_state[_PREFIX + "load_error"] = str(exc)
            except Exception:
                st.session_state[_PREFIX + "load_error"] = (
                    "Options data is unavailable right now. Try Load options again."
                )

    error = st.session_state.get(_PREFIX + "load_error")
    if error:
        st.info(f"Options unavailable. {error}")
        return
    chain = st.session_state.get(_PREFIX + "chain")
    if chain is None:
        st.info(
            "Choose an expiration and option type, then select Load options. "
            "No options provider is contacted before you request quotes. "
            "Configured provider credentials are required; no sample quotes are used."
        )
        return
    loaded_expiration, loaded_kind = st.session_state[_PREFIX + "loaded_for"]
    if (expiration, kind) != (loaded_expiration, loaded_kind):
        st.warning(
            "Inputs changed. Load options to replace the snapshot below; it still "
            f"shows {loaded_kind}s expiring {loaded_expiration:%Y-%m-%d}."
        )
    if not chain:
        st.info("No contracts were returned for this expiration and option type. Try another selection.")
        return

    st.markdown(f"**{loaded_kind.title()} quotes · {loaded_expiration:%b %d, %Y}**")
    fields = [
        "ticker", "strike", "expiration", "type", "bid", "ask", "iv",
        "quote_time", "spot", "spot_time", "multiplier",
    ]
    table = pd.DataFrame(chain).reindex(columns=fields).rename(columns={
        "ticker": "Contract", "strike": "Strike ($)", "expiration": "Expiration",
        "type": "Type", "bid": "Bid ($)", "ask": "Ask ($)",
        "iv": "IV (decimal)", "quote_time": "Quote timestamp",
        "spot": "Underlying ($)", "spot_time": "Underlying timestamp",
        "multiplier": "Multiplier",
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption(
        "Timestamps are supplied by the provider. Quotes may be delayed or stale; "
        "underlying and option observations may have different timestamps."
    )
    selected = st.selectbox(
        "Select contract", range(len(chain)),
        format_func=lambda index: _contract_label(chain[index]),
        key=_PREFIX + f"contract_{loaded_expiration}_{loaded_kind}",
    )
    contract = chain[selected]
    missing = [label for field, label in (
        ("spot", "underlying price"), ("spot_time", "underlying timestamp"),
        ("iv", "implied volatility"), ("quote_time", "option quote timestamp"),
    ) if not contract.get(field)]
    if contract.get("bid") is None or contract.get("ask") is None:
        missing.append("bid/ask quotes")
    if missing:
        st.warning(
            "The provider returned this contract but omitted: " + ", ".join(missing)
            + ". Check Polygon options-quote and underlying-data entitlements, or "
            "select another contract. A trustworthy quote-based projection cannot "
            "be generated from these missing fields."
        )
    valid_history = (
        isinstance(history, pd.DataFrame) and not history.empty and "Close" in history.columns
    )
    if not valid_history:
        st.info("Underlying Close price history is unavailable. Projection requires price history.")
    if st.button(
        "Open projection", type="primary", disabled=not valid_history or bool(missing),
        key=_PREFIX + "open",
    ):
        _projection_dialog(history, dict(chain[selected]))
