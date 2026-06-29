"""Google sign-in gating for the whole app via Streamlit's native OIDC auth.

Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET secrets. The OAuth client in
Google Cloud Console must list this app's `/oauth2callback` URL as an authorized
redirect URI. The auth config is written to .streamlit/secrets.toml at startup
from the environment so no secrets are committed to source control.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import streamlit as st

_SECRETS_PATH = Path(".streamlit/secrets.toml")
_GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"


def _primary_domain() -> str:
    domains = os.environ.get("REPLIT_DOMAINS", "")
    if domains:
        return domains.split(",")[0].strip()
    dev = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if dev:
        return dev
    return "localhost:5000"


def _redirect_uri() -> str:
    return f"https://{_primary_domain()}/oauth2callback"


def auth_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def write_auth_secrets() -> bool:
    """Write the [auth] block to .streamlit/secrets.toml from env vars.

    Returns True if auth is configured and the file is in place.
    """
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not cid or not csec:
        return False

    # Stable cookie secret derived from the client secret so sessions survive
    # restarts without storing an extra secret.
    cookie_secret = hashlib.sha256((csec + "::soxl-auth-cookie").encode()).hexdigest()
    redirect_uri = _redirect_uri()

    content = (
        "[auth]\n"
        f'redirect_uri = "{redirect_uri}"\n'
        f'cookie_secret = "{cookie_secret}"\n\n'
        "[auth.google]\n"
        f'client_id = "{cid}"\n'
        f'client_secret = "{csec}"\n'
        f'server_metadata_url = "{_GOOGLE_METADATA}"\n'
    )

    _SECRETS_PATH.parent.mkdir(exist_ok=True)
    # Only rewrite when changed to avoid Streamlit reload churn.
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
        "<div style='max-width:520px;margin:8vh auto 0;text-align:center;'>"
        "<div style='font-size:2.2rem;font-weight:700;color:#111827;'>📈 SOXL Analysis</div>"
        "<div style='color:#6b7280;margin-top:8px;font-size:1.05rem;'>"
        "Quantitative analysis, probability engine, and AI strategy builder.</div>"
        "<div style='color:#6b7280;margin-top:24px;'>Please sign in with Google to continue.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1, 1])
    with cols[1]:
        st.write("")
        if st.button("Sign in with Google", type="primary", use_container_width=True):
            st.login("google")


def require_login():
    """Gate the entire app. Returns the logged-in user, or stops rendering.

    Call this immediately after st.set_page_config.
    """
    if not write_auth_secrets():
        st.error(
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in Secrets to enable login."
        )
        st.stop()

    if not _is_logged_in():
        _render_login_screen()
        st.stop()

    return st.user


def render_user_badge() -> None:
    """Small signed-in indicator + logout button for the header."""
    if not _is_logged_in():
        return
    user = st.user
    name = getattr(user, "name", None) or getattr(user, "email", "Account")
    with st.popover(f"👤 {name}", use_container_width=False):
        email = getattr(user, "email", "")
        if email:
            st.caption(email)
        if st.button("Sign out", use_container_width=True):
            st.logout()
