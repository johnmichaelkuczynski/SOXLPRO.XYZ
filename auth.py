"""Google identity boundary for the Streamlit application.

Production identity is supplied only by auth_gateway.py after it validates a
Google ID token and signed session cookie. The internal Streamlit server binds
to localhost, so browser-supplied identity headers cannot reach it directly.
"""

from __future__ import annotations

import os
import types

import streamlit as st


def _is_dev_env() -> bool:
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return False
    return bool(os.environ.get("REPLIT_DEV_DOMAIN"))


def _dev_user() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        is_logged_in=True,
        id="development",
        name="Dev User",
        email="dev@localhost",
    )


def _trusted_header(name: str) -> str | None:
    value = st.context.headers.get(name)
    return value.strip() if value and value.strip() else None


def _production_user() -> types.SimpleNamespace | None:
    user_id = _trusted_header("X-Soxlpro-User-Id")
    email = _trusted_header("X-Soxlpro-User-Email")
    if not user_id or not user_id.startswith("google_") or not email:
        return None
    return types.SimpleNamespace(
        is_logged_in=True,
        id=user_id,
        name=email.split("@", 1)[0],
        email=email,
    )


def _render_login_screen() -> None:
    failed = st.query_params.get("auth") == "failed"
    st.markdown(
        """
        <div style="max-width:560px;margin:8vh auto 0;text-align:center;">
          <div style="font-size:2.2rem;font-weight:700;color:#111827;">SOXL Analysis</div>
          <div style="color:#6b7280;margin-top:8px;font-size:1.05rem;">
            Quantitative analysis, probability tools, and AI strategy building.
          </div>
          <div style="color:#4b5563;margin-top:24px;">
            Sign in with Google to continue.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if failed:
        st.error("Google sign-in did not complete. Please try again.")
    st.markdown(
        """
        <div style="display:flex;justify-content:center;margin-top:24px;">
          <a href="/auth/google/start" target="_self"
             style="display:inline-flex;align-items:center;justify-content:center;
                    min-width:240px;padding:0.72rem 1rem;border-radius:0.5rem;
                    background:#2563eb;color:white;text-decoration:none;
                    font-weight:650;box-shadow:0 1px 2px rgba(0,0,0,.12);">
            Sign in with Google
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def require_login():
    """Require the gateway-verified Google identity in production."""
    if _is_dev_env():
        return _dev_user()

    user = _production_user()
    if user is None:
        _render_login_screen()
        st.stop()
    return user


def render_user_badge() -> None:
    if _is_dev_env():
        st.caption("Dev mode")
        return

    user = _production_user()
    if user is None:
        return
    with st.popover(f"Account: {user.name}"):
        st.caption(user.email)
        st.markdown(
            '<a href="/auth/logout" target="_self" '
            'style="color:#2563eb;font-weight:600;text-decoration:none;">'
            "Sign out</a>",
            unsafe_allow_html=True,
        )