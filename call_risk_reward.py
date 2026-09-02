import math
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from vol_surface import RISK_FREE_RATE, fetch_raw_options_chain, fetch_options_chain


DEFAULT_SCENARIOS = (-30, -15, 0, 15, 30, 50, 100)


def _norm_cdf(value):
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _norm_pdf(value):
    return math.exp(-0.5 * float(value) ** 2) / math.sqrt(2.0 * math.pi)


def _risk_label(score):
    if not np.isfinite(score):
        return "Unavailable"
    if score < 45:
        return "Lower"
    if score < 60:
        return "Moderate"
    if score < 75:
        return "High"
    return "Very high"


def _moneyness_label(strike, spot):
    ratio = strike / spot
    if ratio < 0.98:
        return "ITM"
    if ratio <= 1.02:
        return "ATM"
    return "OTM"


def _model_metrics(spot, strike, ask, dte, iv, bid, open_interest):
    """Return transparent probability, decay, liquidity, and risk metrics."""
    t_years = max(float(dte), 1.0) / 365.0
    breakeven = strike + ask
    spread_pct = max(ask - max(bid, 0.0), 0.0) / ask
    oi_shortfall = 1.0 - min(max(open_interest, 0.0) / 500.0, 1.0)
    liquidity_component = 100.0 * (
        0.70 * min(spread_pct, 1.0) + 0.30 * oi_shortfall
    )

    if not np.isfinite(iv) or iv < 0.05 or iv > 5.0:
        return {
            "prob_profit_pct": np.nan,
            "prob_loss_pct": np.nan,
            "delta": np.nan,
            "theta_pct_day": np.nan,
            "liquidity_component": liquidity_component,
            "risk_score": np.nan,
        }

    sqrt_t = math.sqrt(t_years)
    sigma_sqrt_t = iv * sqrt_t

    d2_profit = (
        math.log(spot / breakeven)
        + (RISK_FREE_RATE - 0.5 * iv * iv) * t_years
    ) / sigma_sqrt_t
    prob_profit = _norm_cdf(d2_profit)
    prob_loss = 1.0 - prob_profit

    d1 = (
        math.log(spot / strike)
        + (RISK_FREE_RATE + 0.5 * iv * iv) * t_years
    ) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    delta = _norm_cdf(d1)
    theta_annual = (
        -(spot * _norm_pdf(d1) * iv) / (2.0 * sqrt_t)
        - RISK_FREE_RATE
        * strike
        * math.exp(-RISK_FREE_RATE * t_years)
        * _norm_cdf(d2)
    )
    theta_daily = theta_annual / 365.0
    theta_pct_day = abs(theta_daily) / ask * 100.0

    probability_component = prob_loss * 100.0
    theta_component = min(theta_pct_day / 3.0, 1.0) * 100.0
    risk_score = (
        0.70 * probability_component
        + 0.20 * theta_component
        + 0.10 * liquidity_component
    )

    return {
        "prob_profit_pct": prob_profit * 100.0,
        "prob_loss_pct": prob_loss * 100.0,
        "delta": delta,
        "theta_pct_day": theta_pct_day,
        "liquidity_component": liquidity_component,
        "risk_score": float(np.clip(risk_score, 0.0, 100.0)),
    }


def prepare_call_metrics(raw_chain, spot, scenarios=DEFAULT_SCENARIOS):
    """Create one row per call with a usable purchase ask.

    Dollar fields are always for one standard 100-share contract. Scenario P/L
    is expiration value minus today's ask premium, with no early sale or IV
    assumption hidden in the result.
    """
    if raw_chain is None or raw_chain.empty or spot <= 0:
        return pd.DataFrame()

    calls = raw_chain[raw_chain["kind"] == "c"].copy()
    numeric = [
        "strike", "dte", "bid", "ask", "yf_iv", "volume", "open_interest"
    ]
    for column in numeric:
        calls[column] = pd.to_numeric(calls[column], errors="coerce")

    calls = calls[
        (calls["strike"] > 0)
        & (calls["dte"] >= 1)
        & (calls["ask"] > 0)
        & ((calls["bid"].fillna(0) <= calls["ask"]))
    ].copy()
    if calls.empty:
        return pd.DataFrame()

    result_rows = []
    for _, row in calls.iterrows():
        strike = float(row["strike"])
        ask = float(row["ask"])
        bid = max(float(row["bid"]) if np.isfinite(row["bid"]) else 0.0, 0.0)
        dte = int(row["dte"])
        iv = float(row["yf_iv"]) if np.isfinite(row["yf_iv"]) else np.nan
        oi = float(row["open_interest"]) if np.isfinite(row["open_interest"]) else 0.0
        volume = float(row["volume"]) if np.isfinite(row["volume"]) else 0.0

        metrics = _model_metrics(spot, strike, ask, dte, iv, bid, oi)
        intrinsic = max(spot - strike, 0.0)
        base = {
            "contract_symbol": str(row.get("contract_symbol", "") or ""),
            "expiration": str(row["exp_date"]),
            "dte": dte,
            "strike": strike,
            "moneyness_pct": strike / spot * 100.0,
            "money_label": _moneyness_label(strike, spot),
            "bid": bid,
            "ask": ask,
            "spread_pct": max(ask - bid, 0.0) / ask * 100.0,
            "iv_pct": iv * 100.0 if np.isfinite(iv) else np.nan,
            "volume": int(max(volume, 0.0)),
            "open_interest": int(max(oi, 0.0)),
            "intrinsic": intrinsic,
            "extrinsic": max(ask - intrinsic, 0.0),
            "cost_contract": ask * 100.0,
            "max_loss_contract": ask * 100.0,
            "breakeven": strike + ask,
            **metrics,
        }
        base["risk_label"] = _risk_label(base["risk_score"])

        for scenario in scenarios:
            ending_spot = spot * (1.0 + float(scenario) / 100.0)
            value_contract = max(ending_spot - strike, 0.0) * 100.0
            pnl_contract = value_contract - base["cost_contract"]
            base[f"pnl_{scenario:+d}"] = pnl_contract
            base[f"roi_{scenario:+d}"] = (
                pnl_contract / base["cost_contract"] * 100.0
            )
        result_rows.append(base)

    return pd.DataFrame(result_rows).sort_values(
        ["dte", "strike"], ascending=[True, True]
    ).reset_index(drop=True)


def _representative_expirations(expirations):
    if not expirations:
        return []
    parsed = [(value, (datetime.strptime(value, "%Y-%m-%d").date()
                       - datetime.now().date()).days) for value in expirations]
    targets = (14, 90, 365)
    selected = [min(parsed, key=lambda item: abs(item[1] - target))[0]
                for target in targets]
    selected.append(parsed[-1][0])
    return list(dict.fromkeys(selected))


def _stratified_limit(frame, maximum):
    """Keep a broad strike range within each selected expiry."""
    if len(frame) <= maximum:
        return frame.sort_values(["dte", "strike"]).reset_index(drop=True)

    groups = [group.sort_values("strike") for _, group
              in frame.groupby("expiration", sort=True)]
    chosen_indices = []
    remaining = maximum
    for group_number, group in enumerate(groups):
        groups_left = len(groups) - group_number
        quota = min(len(group), max(1, remaining // groups_left))
        positions = np.linspace(0, len(group) - 1, quota).round().astype(int)
        chosen_indices.extend(group.iloc[np.unique(positions)].index.tolist())
        remaining = maximum - len(set(chosen_indices))

    if remaining > 0:
        omitted = frame.drop(index=list(set(chosen_indices))).copy()
        omitted["_quality"] = (
            omitted["open_interest"].clip(upper=1000)
            + omitted["volume"].clip(upper=500)
            - omitted["spread_pct"] * 5
        )
        chosen_indices.extend(
            omitted.sort_values("_quality", ascending=False)
            .head(remaining).index.tolist()
        )

    return frame.loc[list(dict.fromkeys(chosen_indices))].sort_values(
        ["dte", "strike"]
    ).head(maximum).reset_index(drop=True)


def _heatmap_contract_label(row):
    risk = (
        f"{row['risk_score']:.0f}"
        if np.isfinite(row["risk_score"])
        else "Unavailable"
    )
    expiration = pd.to_datetime(row["expiration"]).strftime("%b %d, %Y")
    return (
        f"STRIKE ${row['strike']:g} · {expiration} · "
        f"Risk {risk} · {row['money_label']}"
    )


def build_return_heatmap(frame, spot, scenarios=DEFAULT_SCENARIOS):
    scenario_labels = [f"{value:+d}%" if value != 0 else "Flat"
                       for value in scenarios]
    z = frame[[f"roi_{value:+d}" for value in scenarios]].to_numpy()
    text = np.array([
        [f"{value:+,.0f}%" for value in row]
        for row in z
    ])

    y_labels = frame.apply(_heatmap_contract_label, axis=1).tolist()

    hovertext = []
    for _, row in frame.iterrows():
        risk_text = (
            f"{row['risk_score']:.1f}/100"
            if np.isfinite(row["risk_score"])
            else "Unavailable"
        )
        hovertext.append([
            (
                f"<b>{row['expiration']} · ${row['strike']:.2f} Call</b><br>"
                f"{row['dte']} DTE · {row['money_label']}<br>"
                f"Buy at ask: ${row['ask']:.2f} "
                f"(${row['cost_contract']:,.0f}/contract)<br>"
                f"Break-even: ${row['breakeven']:.2f}<br>"
                f"Risk Score: {risk_text}<br>"
                f"SOXL at expiry: ${spot * (1.0 + scenario / 100.0):.2f}<br>"
                f"Option return: {row[f'roi_{scenario:+d}']:+,.1f}%<br>"
                f"P/L per contract: ${row[f'pnl_{scenario:+d}']:+,.0f}"
            )
            for scenario in scenarios
        ])

    colorscale = [
        [0.00, "#ef4444"],
        [0.18, "#fca5a5"],
        [0.25, "#fff7ed"],
        [0.40, "#dcfce7"],
        [1.00, "#16a34a"],
    ]
    fig = go.Figure(go.Heatmap(
        z=z,
        x=scenario_labels,
        y=y_labels,
        text=text,
        texttemplate="%{text}",
        textfont={"size": 11, "color": "#111827"},
        hovertext=hovertext,
        colorscale=colorscale,
        zmin=-100,
        zmax=300,
        colorbar={
            "title": "Return",
            "ticksuffix": "%",
            "tickvals": [-100, 0, 100, 200, 300],
        },
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=(
            f"Expiration payoff if SOXL moves from ${spot:,.2f} "
            "(purchase at current ask)"
        ),
        xaxis_title="SOXL move by each call's expiration",
        yaxis_title="Call contract — STRIKE shown first",
        height=max(540, min(1700, 31 * len(frame) + 190)),
        margin={"l": 20, "r": 20, "t": 70, "b": 35},
        font={"family": "Arial, sans-serif", "color": "#111827"},
    )
    fig.update_xaxes(side="top")
    return fig


def _table_frame(frame):
    table = pd.DataFrame({
        "Contract": frame.apply(
            lambda row: f"{row['expiration']} · ${row['strike']:g} Call", axis=1
        ),
        "DTE": frame["dte"],
        "Type": frame["money_label"],
        "Strike / Spot %": frame["moneyness_pct"],
        "Bid": frame["bid"],
        "Ask": frame["ask"],
        "Spread / Ask %": frame["spread_pct"],
        "IV %": frame["iv_pct"],
        "Cost / Contract": frame["cost_contract"],
        "Max Loss": frame["max_loss_contract"],
        "Break-even": frame["breakeven"],
        "Profit Prob. %": frame["prob_profit_pct"],
        "Loss Prob. %": frame["prob_loss_pct"],
        "Theta Burn % / Day": frame["theta_pct_day"],
        "Risk Score": frame["risk_score"],
        "Risk": frame["risk_label"],
        "P/L +30%": frame["pnl_+30"],
        "Return +30%": frame["roi_+30"],
        "P/L +50%": frame["pnl_+50"],
        "Return +50%": frame["roi_+50"],
        "P/L +100%": frame["pnl_+100"],
        "Return +100%": frame["roi_+100"],
        "Open Interest": frame["open_interest"],
        "Volume": frame["volume"],
    })
    return table.sort_values(
        ["Risk Score", "DTE", "Contract"], na_position="last"
    ).reset_index(drop=True)


def render_call_risk_reward_tab():
    st.markdown("### SOXL Call Risk/Reward")
    st.caption(
        "Compare the full premium at risk with expiration payoff across explicit "
        "SOXL price scenarios. Every price uses the displayed ask—the cost a buyer "
        "would currently need to pay—not the midpoint or a stale last trade."
    )

    header_left, header_right = st.columns([4, 1])
    with header_right:
        if st.button("Refresh chain", key="call_rr_refresh", width="stretch"):
            fetch_raw_options_chain.clear()
            fetch_options_chain.clear()
            st.rerun()

    with st.spinner("Loading the shared SOXL option-chain snapshot..."):
        raw, spot, fetched_at, fetch_log = fetch_raw_options_chain("SOXL")

    if raw.empty or spot <= 0:
        failed = sum(1 for value in fetch_log.values()
                     if value.get("status") == "error")
        detail = f" ({failed} expirations failed)" if failed else ""
        st.error(
            "No SOXL option-chain data is available right now"
            f"{detail}. Refresh after the market-data source recovers."
        )
        return

    calls = prepare_call_metrics(raw, spot)
    if calls.empty:
        st.error(
            "The chain loaded, but no call has a valid positive ask quote. "
            "No stale last-price fallback was used."
        )
        return

    expirations = calls["expiration"].drop_duplicates().sort_values().tolist()
    defaults = _representative_expirations(expirations)

    metric_cols = st.columns(4)
    metric_cols[0].metric("SOXL spot", f"${spot:,.2f}")
    metric_cols[1].metric("Calls with usable ask", f"{len(calls):,}")
    metric_cols[2].metric("Expirations", f"{len(expirations)}")
    metric_cols[3].metric("Chain fetched", fetched_at.strftime("%H:%M:%S"))
    st.caption(
        f"Snapshot fetched {fetched_at.strftime('%Y-%m-%d %H:%M:%S')} local server time. "
        "Quotes may be delayed; bid/ask quality varies outside regular market hours."
    )

    with st.container(border=True):
        st.markdown("**Choose the contracts to compare**")
        selected_expirations = st.multiselect(
            "Expirations",
            expirations,
            default=defaults,
            key="call_rr_expirations",
            help=(
                "Representative short-, medium-, one-year, and longest-dated "
                "expirations are selected initially."
            ),
        )
        filter_cols = st.columns([2, 2, 1])
        min_dte = int(calls["dte"].min())
        max_dte = int(calls["dte"].max())
        with filter_cols[0]:
            if min_dte < max_dte:
                default_dte_low = max(7, min_dte)
                if default_dte_low > max_dte:
                    default_dte_low = min_dte
                dte_range = st.slider(
                    "Days to expiration",
                    min_value=min_dte,
                    max_value=max_dte,
                    value=(default_dte_low, max_dte),
                    key="call_rr_dte",
                )
            else:
                dte_range = (min_dte, max_dte)
                st.caption(f"Days to expiration: {min_dte}")
        with filter_cols[1]:
            money_min = int(math.floor(calls["moneyness_pct"].min() / 5.0) * 5)
            money_max = int(math.ceil(calls["moneyness_pct"].max() / 5.0) * 5)
            if money_min < money_max:
                default_money_low = max(money_min, 50)
                default_money_high = min(money_max, 150)
                if default_money_low > default_money_high:
                    default_money_low, default_money_high = money_min, money_max
                money_range = st.slider(
                    "Strike as % of SOXL spot",
                    min_value=money_min,
                    max_value=money_max,
                    value=(default_money_low, default_money_high),
                    key="call_rr_money",
                )
            else:
                money_range = (money_min, money_max)
                st.caption(f"Strike as % of spot: {money_min}%")
        with filter_cols[2]:
            max_contracts = st.number_input(
                "Max contracts",
                min_value=10,
                max_value=150,
                value=60,
                step=10,
                key="call_rr_max",
            )

    if not selected_expirations:
        st.info("Select at least one expiration to build the comparison.")
        return

    matching = calls[
        calls["expiration"].isin(selected_expirations)
        & calls["dte"].between(dte_range[0], dte_range[1])
        & calls["moneyness_pct"].between(money_range[0], money_range[1])
    ].copy()
    if matching.empty:
        st.warning(
            "No valid ask quotes match these filters. Widen the DTE or strike range."
        )
        return

    shown = _stratified_limit(matching, int(max_contracts))
    if len(shown) < len(matching):
        st.caption(
            f"Showing {len(shown)} representative contracts from {len(matching)} matches. "
            "The sampling preserves each selected expiration and its strike range; "
            "raise Max contracts to show more."
        )
    else:
        st.caption(f"Showing all {len(shown)} matching contracts.")

    st.info(
        "**Where is the strike price?** Each heatmap row starts with it in bold-style "
        "text—for example, **STRIKE $185**. The rest of the row shows expiration, "
        "Risk Score, and whether the call is in or out of the money."
    )
    st.plotly_chart(
        build_return_heatmap(shown, spot),
        width="stretch",
        key="call_rr_heatmap",
    )
    st.caption(
        "Cells are option returns at expiration. −100% means the premium is lost. "
        "Positive cells show profit after recovering the ask premium. Dollar P/L is "
        "available on hover. Returns above +300% share the darkest green so extreme "
        "outliers do not wash out the rest of the map."
    )

    st.markdown("#### Exact contract numbers")
    st.dataframe(
        _table_frame(shown),
        width="stretch",
        hide_index=True,
        height=min(900, 38 * len(shown) + 40),
        column_config={
            "Strike / Spot %": st.column_config.NumberColumn(format="%.1f%%"),
            "Bid": st.column_config.NumberColumn(format="$%.2f"),
            "Ask": st.column_config.NumberColumn(format="$%.2f"),
            "Spread / Ask %": st.column_config.NumberColumn(format="%.1f%%"),
            "IV %": st.column_config.NumberColumn(format="%.1f%%"),
            "Cost / Contract": st.column_config.NumberColumn(format="$%.0f"),
            "Max Loss": st.column_config.NumberColumn(format="$%.0f"),
            "Break-even": st.column_config.NumberColumn(format="$%.2f"),
            "Profit Prob. %": st.column_config.NumberColumn(format="%.1f%%"),
            "Loss Prob. %": st.column_config.NumberColumn(format="%.1f%%"),
            "Theta Burn % / Day": st.column_config.NumberColumn(format="%.2f%%"),
            "Risk Score": st.column_config.NumberColumn(format="%.1f"),
            "P/L +30%": st.column_config.NumberColumn(format="$%.0f"),
            "Return +30%": st.column_config.NumberColumn(format="%.0f%%"),
            "P/L +50%": st.column_config.NumberColumn(format="$%.0f"),
            "Return +50%": st.column_config.NumberColumn(format="%.0f%%"),
            "P/L +100%": st.column_config.NumberColumn(format="$%.0f"),
            "Return +100%": st.column_config.NumberColumn(format="%.0f%%"),
        },
    )

    with st.expander("How the Risk Score and payoff math work"):
        st.markdown(
            """
**Expiration payoff**

- Purchase cost = ask × 100 shares.
- Maximum loss = the full purchase cost.
- Break-even = strike + ask per share.
- Scenario P/L = `[max(SOXL at expiration − strike, 0) − ask] × 100`.

**Risk Score (0–100; higher means more model risk)**

- **70% probability component:** Black-Scholes/lognormal estimate that SOXL
  finishes below the break-even at expiration.
- **20% time-decay component:** current Black-Scholes one-day theta as a
  percentage of premium, scaled to its maximum penalty at 3% premium burn/day.
- **10% liquidity component:** 70% bid/ask spread relative to the ask and 30%
  open-interest shortfall versus 500 contracts.

The probability uses the contract's current implied volatility and a constant
risk-free rate. It is a risk-neutral model estimate—not a forecast of SOXL's
actual return and not a guarantee. Contracts with missing or implausible IV keep
their exact payoff scenarios but show no probability or Risk Score.
            """
        )

    st.warning(
        "Model limitations: unchanged inputs, no dividends or borrow effects, no "
        "volatility-skew evolution, no jumps or leveraged-ETF path decay, no early "
        "exercise, commissions, taxes, or slippage beyond buying at the ask. "
        "This is scenario analysis, not investment advice."
    )