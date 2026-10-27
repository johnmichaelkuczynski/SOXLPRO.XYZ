"""Local component for an in-drag probability readout above the price thumb."""
from pathlib import Path

import numpy as np
import streamlit.components.v1 as components

from landing_signal import TIMEFRAMES, TIMEFRAME_WEIGHTS


_slider = components.declare_component(
    "price_probability_slider",
    path=str(Path(__file__).parent / "components" / "price_probability_slider"),
)


def probability_slider(prepared, value, horizon, horizon_label, reset_token=0):
    ranges = []
    if not prepared.empty:
        latest = prepared.iloc[-1]
        for label in TIMEFRAMES:
            low, high = latest[f"low:{label}"], latest[f"high:{label}"]
            if np.isfinite(low) and np.isfinite(high) and high > low:
                ranges.append(dict(low=float(low), high=float(high),
                                   weight=TIMEFRAME_WEIGHTS[label]))
    return _slider(
        value=float(value), reset_token=reset_token, horizon=horizon,
        horizon_label=horizon_label, ranges=ranges,
        closes=prepared["close"].tolist(),
        scores=[float(v) if np.isfinite(v) else None for v in prepared["score"]],
        min_price=float(prepared["close"].min()) if len(prepared) else None,
        max_price=float(prepared["close"].max()) if len(prepared) else None,
        default=float(value), key=f"price_probability_thumb_{reset_token}",
    )
