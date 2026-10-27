"""Local component for an in-drag probability readout above the price thumb."""
from pathlib import Path

import streamlit.components.v1 as components
import streamlit as st

from continuous_price_model import probability_curve


_slider = components.declare_component(
    "price_probability_slider",
    path=str(Path(__file__).parent / "components" / "price_probability_slider"),
)


@st.cache_data(show_spinner=False, max_entries=12)
def _curve(prepared, horizon):
    return probability_curve(prepared, horizon)


def probability_slider(prepared, value, horizon, horizon_label, reset_token=0):
    count, curve = _curve(prepared, horizon)
    return _slider(
        value=float(value), reset_token=reset_token, horizon=horizon,
        horizon_label=horizon_label, probability_curve=curve, model_count=count,
        model_error="",
        default=float(value), key=f"price_probability_thumb_{reset_token}",
    )
