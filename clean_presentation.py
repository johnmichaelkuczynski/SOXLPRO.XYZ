"""Neutral presentation for operational messages; no warning-colored panels."""

CLEAN_NOTICE_STYLE = """<style>
[data-testid="stAlert"],
[data-testid="stAlert"] > div,
[data-testid="stAlertContainer"] {
  background: transparent !important;
  background-color: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
  color: #334155 !important;
  padding: 0 !important;
}
[data-testid="stAlert"] * {
  color: inherit !important;
  background-color: transparent !important;
}
[data-testid="stAlert"] svg { display: none !important; }
</style>"""


def apply_clean_presentation():
    import streamlit as st
    st.html(CLEAN_NOTICE_STYLE)
