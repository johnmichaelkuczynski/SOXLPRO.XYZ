"""Google sign-in for the published Streamlit application."""

from __future__ import annotations

import hashlib
import os
import types
from pathlib import Path

import streamlit as st

_SECRETS_PATH = Path(".streamlit/secrets.toml")
_GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
_PUBLIC_DOMAIN = "soxlpro.xyz"


def _primary_domain() -> str:
    public_app_url = os.environ.get("PUBLIC_APP_URL", "").strip().rstrip("/")
    if public_app_url:
        return public_app_url.removeprefix("https://").removeprefix("http://")
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return _PUBLIC_DOMAIN
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
    if dev_domain:
        return dev_domain
    domains = os.environ.get("REPLIT_DOMAINS", "")
    if domains:
        return domains.split(",")[0].strip()
    return "localhost:5000"


def _redirect_uri() -> str:
    return f"https://{_primary_domain()}/oauth2callback"


def _is_dev_env() -> bool:
    """Return whether this is a workspace preview rather than a deployment."""
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        return False
    return bool(os.environ.get("REPLIT_DEV_DOMAIN"))


def _dev_user() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        is_logged_in=True,
        name="Dev User",
        email="dev@localhost",
    )


def auth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
    )


def write_auth_secrets() -> bool:
    """Materialize Streamlit's OIDC configuration from protected environment secrets."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return False

    session_secret = os.environ.get("SESSION_SECRET") or client_secret
    cookie_secret = hashlib.sha256(
        (session_secret + "::soxl-auth-cookie").encode()
    ).hexdigest()
    content = (
        "[auth]\n"
        f'redirect_uri = "{_redirect_uri()}"\n'
        f'cookie_secret = "{cookie_secret}"\n\n'
        "[auth.google]\n"
        f'client_id = "{client_id}"\n'
        f'client_secret = "{client_secret}"\n'
        f'server_metadata_url = "{_GOOGLE_METADATA}"\n'
    )

    _SECRETS_PATH.parent.mkdir(exist_ok=True)
    if not _SECRETS_PATH.exists() or _SECRETS_PATH.read_text() != content:
        _SECRETS_PATH.write_text(content)
    return True


def _is_logged_in() -> bool:
    user = getattr(st, "user", None)
    if user is None:
        return False
    try:
        return bool(user.is_logged_in)
    except Exception:
        return False


def _render_login_screen() -> None:
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
    left, center, right = st.columns([1, 1, 1])
    with center:
        st.write("")
        if st.button("Sign in with Google", type="primary", width="stretch"):
            st.login("google")
        st.markdown(
            '<div style="text-align:center;margin-top:14px;font-size:0.85rem;color:#6b7280;">'
            'If sign-in is blocked inside an embedded preview, '
            '<a href="https://soxlpro.xyz/" target="_blank" rel="noopener" '
            'style="color:#2563eb;font-weight:600;">open SOXLPRO.XYZ in a new tab</a>.'
            "</div>",
            unsafe_allow_html=True,
        )


def require_login():
    """Require Google login in production and return the current user."""
    if _is_dev_env():
        return _dev_user()

    if not write_auth_secrets():
        st.error("Google sign-in is temporarily unavailable.")
        st.stop()

    if not _is_logged_in():
        _render_login_screen()
        st.stop()

    return st.user


def render_user_badge() -> None:
    """Render the signed-in account and logout control."""
    if _is_dev_env():
        st.caption("Dev mode")
        return
    if not _is_logged_in():
        return

    user = st.user
    name = getattr(user, "name", None) or getattr(user, "email", "Account")
    with st.popover(f"Account: {name}"):
        email = getattr(user, "email", "")
        if email:
            st.caption(email)
        if st.button("Sign out", width="stretch"):
            st.logout()