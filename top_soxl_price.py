"""Prominent, independently refreshed price using the existing saved market feed."""
from datetime import datetime, timezone
from html import escape
from math import isfinite

import streamlit as st
from price_labels import public_price_text


def price_display(saved):
    """Format only the current Tiingo request result; never use stored fallbacks."""
    saved = saved or {}
    candidates = []
    for quote in (saved.get("quote"),):
        if not isinstance(quote, dict):
            continue
        if quote.get("source") != "Tiingo":
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
    if candidates:
        observed, price, quote = max(candidates, key=lambda item: item[0])
        context = " · ".join(str(part) for part in (
            quote.get("session"),
            quote.get("observed_label") or observed.isoformat(),
            "Last available price (not live)"
            if (datetime.now(timezone.utc) - observed).total_seconds() > 900
            else ("Delayed" if quote.get("delayed") else None),
        ) if part)
        return price, public_price_text(context)
    return None, "Current price unavailable."


@st.fragment(run_every="30s")
def render_top_soxl_price():
    from live_market_quote import fetch_live_quote
    from tiingo_market_data import TiingoError
    try:
        price, context = price_display({"quote": fetch_live_quote()})
    except TiingoError as exc:
        price, context = None, "Current price unavailable. " + public_price_text(exc)
    except OSError:
        price, context = None, "Current price unavailable. Token storage cannot be read."
    if price is None:
        st.error(context)
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
