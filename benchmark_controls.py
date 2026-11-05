"""The original benchmark button row, with browser-only chart toggles."""
from pathlib import Path
import hashlib

import streamlit.components.v1 as components

_directory = Path(__file__).parent / "components/benchmark_controls"
_version = hashlib.sha256((_directory / "index.html").read_bytes()).hexdigest()[:12]
_controls = components.declare_component(f"benchmark_controls_{_version}", path=str(_directory))


def render_benchmark_controls(chart_component_name):
    _controls(
        visibility_script_url=f"/component/{chart_component_name}/benchmark_visibility.js",
        key="benchmark_display_controls",
        default=None,
    )
