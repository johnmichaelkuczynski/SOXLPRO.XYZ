from collections import OrderedDict

import numpy as np
import pandas as pd
import streamlit as st


RETURN_PERIODS = OrderedDict([
    ("Week", pd.DateOffset(weeks=1)),
    ("Month", pd.DateOffset(months=1)),
    ("Year", pd.DateOffset(years=1)),
    ("3 Years", pd.DateOffset(years=3)),
    ("5 Years", pd.DateOffset(years=5)),
    ("10 Years", pd.DateOffset(years=10)),
])


def _clean_closes(price_data):
    if price_data is None or price_data.empty:
        return pd.Series(dtype=float, name="Close")
    column = "Close" if "Close" in price_data.columns else price_data.columns[0]
    closes = pd.to_numeric(price_data[column], errors="coerce")
    closes = closes.replace([np.inf, -np.inf], np.nan).dropna()
    closes = closes[closes > 0]
    index = pd.to_datetime(closes.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    closes.index = index
    return closes[~closes.index.duplicated(keep="last")].sort_index()


def _return_percent(current_price, baseline):
    if baseline is None or not np.isfinite(baseline) or baseline <= 0:
        return np.nan
    return (current_price / float(baseline) - 1.0) * 100.0


def _price_at_or_before(closes, target):
    eligible = closes[closes.index <= target]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1])


def compute_market_snapshot(price_data, quote=None):
    closes = _clean_closes(price_data)
    if closes.empty:
        return None

    latest_close = float(closes.iloc[-1])
    quote_price = (quote or {}).get("price")
    current_price = (
        float(quote_price)
        if quote_price is not None and np.isfinite(quote_price) and quote_price > 0
        else latest_close
    )

    previous_close = (quote or {}).get("prev_close")
    if previous_close is None or not np.isfinite(previous_close) or previous_close <= 0:
        previous_close = float(closes.iloc[-2]) if len(closes) > 1 else None

    returns = OrderedDict()
    returns["Day"] = _return_percent(current_price, previous_close)
    latest_date = closes.index[-1]
    for label, offset in RETURN_PERIODS.items():
        target = latest_date - offset
        if closes.index[0] > target:
            returns[label] = np.nan
        else:
            returns[label] = _return_percent(
                current_price, _price_at_or_before(closes, target)
            )
    returns["All Time"] = _return_percent(current_price, float(closes.iloc[0]))

    cutoff = latest_date - pd.DateOffset(weeks=52)
    trailing = closes[closes.index >= cutoff]
    if current_price != latest_close:
        trailing = pd.concat([
            trailing,
            pd.Series([current_price], index=[latest_date + pd.Timedelta(microseconds=1)]),
        ])

    state = (quote or {}).get("state", "")
    if (quote or {}).get("extended"):
        price_context = "Pre-market" if state == "PRE" else "After hours"
    elif quote_price is not None:
        price_context = "Live market price"
    else:
        price_context = f"Close · {latest_date:%b %-d, %Y}"

    return {
        "current_price": current_price,
        "price_context": price_context,
        "returns": returns,
        "week_52_high": float(trailing.max()),
        "week_52_low": float(trailing.min()),
    }


def _return_card(label, value):
    if not np.isfinite(value):
        display, color, css_class = "N/A", "#64748b", ""
    else:
        display = f"{value:+.1f}%"
        color = "#059669" if value >= 0 else "#dc2626"
        css_class = "up" if value >= 0 else "down"
    return f"""
      <div class="soxl-stat">
        <div class="soxl-stat-label">{label}</div>
        <div class="soxl-stat-value {css_class}" style="color:{color};">{display}</div>
      </div>
    """


def _price_card(label, value, css_class):
    return (
        f'<div class="soxl-stat {css_class}">'
        f'<div class="soxl-stat-label">{label}</div>'
        f'<div class="soxl-stat-value">${value:,.2f}</div>'
        "</div>"
    )


def render_market_snapshot(price_data, quote=None):
    snapshot = compute_market_snapshot(price_data, quote=quote)
    if snapshot is None:
        st.warning("Current SOXL market statistics are unavailable.")
        return

    return_cards = "".join(
        _return_card(label, value)
        for label, value in snapshot["returns"].items()
    )
    range_cards = (
        _price_card("52-Week High", snapshot["week_52_high"], "high")
        + _price_card("52-Week Low", snapshot["week_52_low"], "low")
    )
    html = f"""
        <style>
          .soxl-market-strip {{
            border:1px solid #dbe4ee;border-radius:14px;background:#fff;
            padding:14px 16px 12px;margin:0 0 14px;
            box-shadow:0 1px 3px rgba(15,23,42,.05);
          }}
          .soxl-market-heading {{
            display:flex;align-items:baseline;gap:10px;margin-bottom:10px;
          }}
          .soxl-market-heading strong {{font-size:1rem;color:#0f172a;}}
          .soxl-market-heading span {{font-size:.72rem;color:#64748b;}}
          .soxl-stat-grid {{
            display:grid;grid-template-columns:repeat(6,minmax(105px,1fr));
            gap:8px;
          }}
          .soxl-stat {{
            min-width:0;border-left:3px solid #dbe4ee;padding:4px 8px;
          }}
          .soxl-stat.primary {{border-left-color:#2563eb;}}
          .soxl-stat.high {{border-left-color:#059669;}}
          .soxl-stat.low {{border-left-color:#dc2626;}}
          .soxl-stat-label {{
            color:#64748b;font-size:.66rem;line-height:1.1;
            font-weight:750;text-transform:uppercase;letter-spacing:.04em;
          }}
          .soxl-stat-value {{
            color:#0f172a;font-size:1.03rem;line-height:1.35;font-weight:800;
            white-space:nowrap;
          }}
          .soxl-stat-value.price {{font-size:1.18rem;color:#0f172a;}}
          @media (max-width:900px) {{
            .soxl-stat-grid {{grid-template-columns:repeat(3,minmax(90px,1fr));}}
          }}
          @media (max-width:520px) {{
            .soxl-stat-grid {{grid-template-columns:repeat(2,minmax(90px,1fr));}}
          }}
        </style>
        <div class="soxl-market-strip">
          <div class="soxl-market-heading">
            <strong>SOXL Market Snapshot</strong>
            <span>{snapshot["price_context"]}</span>
          </div>
          <div class="soxl-stat-grid">
            <div class="soxl-stat primary">
              <div class="soxl-stat-label">Current Price</div>
              <div class="soxl-stat-value price">${snapshot["current_price"]:,.2f}</div>
            </div>
            {return_cards}
            {range_cards}
          </div>
        </div>
        """
    st.markdown(html.replace("\n", ""), unsafe_allow_html=True)