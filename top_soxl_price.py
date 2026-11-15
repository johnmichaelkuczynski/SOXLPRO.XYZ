"""Prominent, independently refreshed price using the existing saved market feed."""
from datetime import datetime, timezone
from html import escape
from math import isfinite

import streamlit as st


def price_display(saved):
    """Choose the newest timestamped quote, falling back to the last daily close."""
    saved = saved or {}
    candidates = []
    for quote in (saved.get("quote"), (saved.get("market_feed") or {}).get("quote")):
        if not isinstance(quote, dict):
            continue
        try:
            price = float(quote["price"])
            observed = datetime.fromisoformat(quote["observed_at"].replace("Z", "+00:00"))
            if observed.tzinfo is None or not isfinite(price) or price <= 0:
                continue
            if (observed - datetime.now(timezone.utc)).total_seconds() > 60:
                continue
            candidates.append((observed, price, quote))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    history = saved.get("history") or {}
    try:
        close = float(history["prices"][-1])
        date = str(history["dates"][-1])[:10]
        close_date = datetime.fromisoformat(date).date()
        if not isfinite(close) or close <= 0:
            raise ValueError("Invalid close")
    except (KeyError, IndexError, TypeError, ValueError):
        close, date, close_date = None, None, None
    if candidates:
        observed, price, quote = max(candidates, key=lambda item: item[0])
        if close_date is None or observed.date() >= close_date:
            context = " · ".join(str(part) for part in (
                quote.get("session"), quote.get("source"),
                quote.get("observed_label") or observed.isoformat(),
                "Last available quote (not live)"
                if (datetime.now(timezone.utc) - observed).total_seconds() > 900
                else "May be delayed",
            ) if part)
            return price, context
    if close is not None:
        return close, f"Last available daily close · {date} · Not a live quote"
    return None, "Price temporarily unavailable; waiting for a market update."


@st.fragment(run_every="30s")
def render_top_soxl_price():
    from market_state_store import load_state
    saved = load_state() or st.session_state.get("_market_state")
    price, context = price_display(saved)
    if price is not None:
        st.session_state["_top_soxl_price"] = (price, context)
    elif st.session_state.get("_top_soxl_price"):
        price, context = st.session_state["_top_soxl_price"]
        context = "Saved price · " + context
    display = f"${price:,.2f}" if price is not None else "—"
    st.markdown(
        '<section aria-label="Latest SOXL price" style="margin:0 0 16px;">'
        '<div style="font-size:1rem;font-weight:750;color:#475569;">SOXL</div>'
        f'<div style="font-size:clamp(3.5rem,8vw,6rem);font-weight:800;'
        f'line-height:1.1;color:#0f172a;font-variant-numeric:tabular-nums;">{display}</div>'
        f'<div style="font-size:.85rem;color:#475569;margin-top:6px;">'
        f'{escape(context)}</div></section>',
        unsafe_allow_html=True,
    )
