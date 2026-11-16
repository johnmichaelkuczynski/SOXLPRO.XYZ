"""SOXL quotes from the owner's configured Tiingo API key."""
import streamlit as st


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_quote():
    # Do not catch failures here: callers must display an error, never substitute
    # another provider, a historical close, or a previously successful quote.
    from tiingo_market_data import fetch_quote
    return fetch_quote("SOXL")
