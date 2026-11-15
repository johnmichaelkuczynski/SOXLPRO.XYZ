"""SOXL quotes exclusively from the owner's authorized Schwab market-data API."""
import streamlit as st


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_quote():
    # Do not catch failures here: callers must display an error, never substitute
    # another provider, a historical close, or a previously successful quote.
    from schwab_market_data import fetch_quote
    return fetch_quote("SOXL")
