"""Real Streamlit component host, isolated from market data and background jobs."""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(layout="wide")
st.markdown("<div style='height:700px'>Before chart</div>", unsafe_allow_html=True)
chart = components.declare_component(
    "chart_rail_layout",
    path=str(Path(__file__).resolve().parents[2] / "components" / "chart_draw"),
)
chart(
    dates=["2024-01-01", "2025-01-01"],
    prices=[10, 20],
    lines=[],
    key="rail",
)
st.markdown("<div style='height:1400px'>After chart</div>", unsafe_allow_html=True)
