"""Google OIDC using Streamlit's server-verified identity and signed cookies."""
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import streamlit as st
import toml

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"


def is_development_preview(environ=None):
    env = os.environ if environ is None else environ
    # Published instances can retain workspace markers. Fail closed for any
    # unexpected deployment flag; never trust URL parameters or client headers.
    return env.get("REPLIT_DEPLOYMENT", "") in ("", "0") and bool(env.get("REPLIT_DEV_DOMAIN"))


def get_current_user():
    if is_development_preview():
        if st.session_state.get("preview_signed_out", False):
            return {"is_logged_in": False, "auth_provider": "development"}
        return {
            "is_logged_in": True,
            "sub": "development-preview",
            "name": "Developer",
            "auth_provider": "development",
        }
    return dict(st.user)


def redirect_uri(environ=None):
    env = os.environ if environ is None else environ
    if env.get("REPLIT_DEPLOYMENT") == "1":
        origin = env.get("PUBLIC_APP_URL", "")
    elif env.get("REPLIT_DEV_DOMAIN"):
        origin = "https://" + env["REPLIT_DEV_DOMAIN"]
    else:
        origin = env.get("PUBLIC_APP_URL", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("A valid HTTPS app origin is required for Google sign-in.")
    return origin.rstrip("/") + "/oauth2callback"


def auth_settings(environ=None):
    env = os.environ if environ is None else environ
    required = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SESSION_SECRET")
    if any(not env.get(key) for key in required):
        raise ValueError("Google sign-in configuration is incomplete.")
    return {
        "redirect_uri": redirect_uri(env),
        "cookie_secret": env["SESSION_SECRET"],
        "google": {
            "client_id": env["GOOGLE_CLIENT_ID"],
            "client_secret": env["GOOGLE_CLIENT_SECRET"],
            "server_metadata_url": GOOGLE_METADATA,
            "client_kwargs": {"prompt": "select_account", "scope": "openid email profile"},
        },
    }


@st.cache_resource(show_spinner=False)
def configure_google_auth():
    """Create Streamlit's ignored config at runtime, never expose credentials."""
    settings = auth_settings()
    path = Path(".streamlit/secrets.toml")
    path.parent.mkdir(exist_ok=True)
    existing = toml.loads(path.read_text()) if path.exists() else {}
    existing["auth"] = settings
    # Atomically replace a private file, preserving any unrelated settings.
    fd, temporary = tempfile.mkstemp(prefix=".auth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(toml.dumps(existing))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # Streamlit may have loaded the previously empty config before app startup.
    st.secrets._reset()
    return settings["redirect_uri"]


def render_google_login():
    if is_development_preview():
        if st.session_state.get("preview_signed_out", False):
            if st.button("Sign in", key="preview_login", width="stretch"):
                st.session_state["preview_signed_out"] = False
                st.rerun()
        else:
            if st.button("Sign out", key="preview_logout", width="stretch",
                         help="Sign out of this development session. New preview sessions start signed in."):
                st.session_state.clear()
                st.session_state["preview_signed_out"] = True
                st.rerun()
        return
    try:
        configure_google_auth()
    except Exception:
        st.button("Sign in with Google", disabled=True, width="stretch")
        st.info("Please try signing in again shortly. You can keep using the app.")
        return
    if st.user.is_logged_in:
        st.caption(f"Signed in as {st.user.get('name') or st.user.get('email') or 'Google user'}")
        if st.button("Sign out", key="google_logout", width="stretch"):
            st.session_state.clear()
            st.logout()
    elif st.button("Sign in with Google", key="google_login", width="stretch"):
        try:
            st.login("google")
        except Exception:
            st.info("Please try signing in again. Your current app access remains available.")