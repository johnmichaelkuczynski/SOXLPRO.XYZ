"""Direct Google OAuth, staged free access, and live Stripe controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

from billing import (
    anonymous_usage,
    consume_usage_action,
    create_checkout_url,
    create_portal_url,
    get_access_record,
    paid_from_record,
    refresh_live_subscription,
    signed_in_actions,
    stripe_live_configured,
    verify_checkout_return,
)


ANONYMOUS_SECONDS = 180
ANONYMOUS_ACTIONS = 3
SIGNED_IN_FREE_ACTIONS = 5

_auth_component = components.declare_component(
    "soxlpro_access", path="components/soxlpro_access"
)


@dataclass(frozen=True)
class AccessState:
    authenticated: bool = False
    user_id: str | None = None
    visitor_id: str | None = None
    anonymous_actions: int = 0
    signed_in_actions: int = 0
    elapsed_seconds: int = 0


def _is_deployment() -> bool:
    return os.environ.get("REPLIT_DEPLOYMENT") == "1"


def google_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
        and len(os.environ.get("SESSION_SECRET", "")) >= 32
    )


def _base_url() -> str:
    configured = os.environ.get("PUBLIC_APP_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme == "https" and parsed.netloc:
            return configured
    if _is_deployment():
        return "https://soxlpro.xyz"
    dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
    return f"https://{dev_domain}" if dev_domain else "http://localhost:5000"


def _track_event(name: str, data: dict | None = None, dedupe_key: str | None = None):
    session_key = f"_analytics_{dedupe_key or name}"
    if st.session_state.get(session_key):
        return
    payload = json.dumps(data or {}, separators=(",", ":")).replace("<", "\\u003c")
    event_name = json.dumps(name)
    components.html(
        f"""<script>
        try {{
          const tracker = window.parent.umami;
          if (tracker && typeof tracker.track === "function") {{
            tracker.track({event_name}, {payload});
          }}
        }} catch (_) {{}}
        </script>""",
        height=0,
        width=0,
    )
    st.session_state[session_key] = True


@st.cache_data(ttl=30, show_spinner=False)
def _paid_access(user_id: str) -> bool:
    try:
        record = get_access_record(user_id)
        if paid_from_record(record):
            return True
        if record and record.get("stripe_customer_id"):
            return refresh_live_subscription(user_id)
        return False
    except Exception:
        return False


def _redirect(url: str) -> None:
    components.html(
        f"<script>window.top.location.href={json.dumps(url)};</script>",
        height=0,
        width=0,
    )


def _trusted_header(name: str) -> str | None:
    value = st.context.headers.get(name)
    return value.strip() if value and value.strip() else None


def render_access_control() -> tuple[AccessState, bool]:
    """Render account controls and return gateway-verified access."""
    user_id = _trusted_header("X-Soxlpro-User-Id")
    visitor_id = _trusted_header("X-Soxlpro-Anonymous-Id")
    authenticated = bool(user_id and user_id.startswith("google_"))

    persisted_actions = 0
    anonymous_actions = 0
    elapsed_seconds = 0
    if authenticated:
        try:
            persisted_actions = signed_in_actions(user_id)
        except Exception:
            persisted_actions = SIGNED_IN_FREE_ACTIONS
    elif visitor_id:
        try:
            anonymous_actions, elapsed_seconds = anonymous_usage(visitor_id)
        except Exception:
            anonymous_actions = ANONYMOUS_ACTIONS

    state = AccessState(
        authenticated=authenticated,
        user_id=user_id if authenticated else None,
        visitor_id=visitor_id,
        anonymous_actions=anonymous_actions,
        signed_in_actions=persisted_actions,
        elapsed_seconds=elapsed_seconds,
    )
    paid = _paid_access(state.user_id) if state.authenticated else False
    st.session_state._access_user_id = state.user_id
    st.session_state._access_visitor_id = state.visitor_id
    st.session_state._access_paid = paid

    remaining_actions = max(
        0,
        (
            SIGNED_IN_FREE_ACTIONS - state.signed_in_actions
            if state.authenticated
            else ANONYMOUS_ACTIONS - state.anonymous_actions
        ),
    )
    raw = _auth_component(
        authenticated=state.authenticated,
        google_configured=google_oauth_configured(),
        stripe_configured=stripe_live_configured(),
        paid=paid,
        remaining_actions=remaining_actions,
        login_url="/auth/google/start",
        logout_url="/auth/logout",
        key="soxlpro_access_control",
        default={},
    ) or {}

    if st.query_params.get("auth") == "complete":
        _track_event(
            "google_login_completed",
            {"method": "google_oauth"},
            "google_login_completed",
        )
        st.query_params.pop("auth", None)
    elif st.query_params.get("auth") == "logged_out":
        _track_event("logout_completed", {}, "logout_completed")
        st.query_params.pop("auth", None)
    elif st.query_params.get("auth") == "failed":
        st.error("Google sign-in could not be completed. Please try again.")
        st.query_params.pop("auth", None)

    if state.authenticated and st.query_params.get("subscribe") == "1":
        st.query_params.pop("subscribe", None)
        try:
            _track_event(
                "subscription_checkout_started",
                {"billing_mode": "live"},
            )
            _redirect(create_checkout_url(state.user_id, _base_url()))
        except Exception:
            st.error("Live billing is temporarily unavailable.")

    session_id = st.query_params.get("session_id")
    if (
        state.authenticated
        and st.query_params.get("checkout") == "success"
        and session_id
    ):
        try:
            paid = verify_checkout_return(state.user_id, session_id)
        except Exception:
            paid = False
        st.query_params.clear()
        _paid_access.clear()
        if paid:
            st.session_state._access_paid = True
            _track_event(
                "subscription_activated",
                {"billing_mode": "live"},
                "subscription_activated",
            )
            st.success("Your SOXLPRO membership is active.")

    action_id = raw.get("action_id")
    action = (
        raw.get("action")
        if action_id and action_id != st.session_state.get("_last_access_action_id")
        else None
    )
    if action:
        st.session_state._last_access_action_id = action_id
    if action in {"checkout", "portal"} and state.authenticated:
        try:
            url = (
                create_portal_url(state.user_id, _base_url())
                if action == "portal"
                else create_checkout_url(state.user_id, _base_url())
            )
            _track_event(
                "billing_portal_opened"
                if action == "portal"
                else "subscription_checkout_started",
                {"billing_mode": "live"},
            )
            _redirect(url)
        except Exception:
            st.error("Live billing is temporarily unavailable.")

    if st.query_params.get("checkout") == "cancelled":
        st.query_params.clear()
        _track_event(
            "subscription_checkout_cancelled",
            {"billing_mode": "live"},
            "subscription_checkout_cancelled",
        )
    return state, paid


def record_meaningful_action(action_name: str) -> None:
    """Atomically reserve one free action before protected work executes."""
    if st.session_state.get("_access_paid"):
        return
    allowed, count = consume_usage_action(
        user_id=st.session_state.get("_access_user_id"),
        visitor_id=st.session_state.get("_access_visitor_id"),
        user_limit=SIGNED_IN_FREE_ACTIONS,
        visitor_limit=ANONYMOUS_ACTIONS,
    )
    if not allowed:
        st.rerun()
    _track_event(
        "free_usage_action",
        {"action": action_name, "count": count},
        f"free_usage_action_{action_name}_{count}",
    )


def enforce_staged_access(state: AccessState, paid: bool) -> None:
    """Stop premium rendering after each free allowance is exhausted."""
    if paid:
        return
    if not google_oauth_configured():
        st.error("Google sign-in is temporarily unavailable.")
        st.stop()
    anonymous_limit_reached = (
        state.elapsed_seconds >= ANONYMOUS_SECONDS
        or state.anonymous_actions >= ANONYMOUS_ACTIONS
    )
    if not state.authenticated and anonymous_limit_reached:
        _track_event(
            "login_prompt_shown",
            {"gate": "anonymous_allowance"},
            "login_prompt_shown",
        )
        st.warning(
            "Your initial preview is complete. "
            "Sign in with Google above to continue."
        )
        st.stop()
    if state.authenticated and state.signed_in_actions >= SIGNED_IN_FREE_ACTIONS:
        _track_event(
            "paywall_shown",
            {"gate": "signed_in_allowance"},
            "paywall_shown",
        )
        st.warning(
            "Your signed-in free allowance is complete. "
            "Subscribe above to continue using SOXLPRO."
        )
        st.stop()