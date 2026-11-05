"""One-click diagnostics, independent of Streamlit widget reruns."""
from pathlib import Path
import hashlib
import streamlit.components.v1 as components

_path = Path(__file__).parent / "components/app_diagnostics"
_version = hashlib.sha256((_path / "index.html").read_bytes()).hexdigest()[:12]
_component = components.declare_component(f"app_diagnostics_{_version}", path=str(_path))


def render_full_diagnostics():
    _component(key="full_app_diagnostics", default=None)
