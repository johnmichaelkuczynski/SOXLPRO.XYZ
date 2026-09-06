"""Clerk Google authentication, staged free access, and live Stripe controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
import streamlit as st
import streamlit.components.v1 as components

from billing import (
    anonymous_usage,
    increment_usage_action,
    create_checkout_url,
    create_portal_url,
    get_access_record,
    paid_from_record,
    refresh_live_subscription,
    stripe_live_configured,
    signed_in_actions,
    verify_checkout_return,
)
from visitor_counter import anonymous_visitor_id


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


def _clerk_configured() -> bool:
    return bool(
        os.environ.get("CLERK_PUBLISHABLE_KEY")
        and os.environ.get("CLERK_FRONTEND_API_URL")
        and os.environ.get("CLERK_ACCOUNT_PORTAL_URL")
    )


def clerk_production_ready() -> bool:
    return _clerk_configured() and os.environ.get(
        "CLERK_PUBLISHABLE_KEY", ""
    ).startswith("pk_live_")


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
        f"""
        <script>
        try {{
          const tracker = window.parent.umami;
          if (tracker && typeof tracker.track === "function") {{
            tracker.track({event_name}, {payload});
          }}
        }} catch (_) {{}}
        </script>
        """,
        height=0,
        width=0,
    )
    st.session_state[session_key] = True


@st.cache_resource
def _clerk_jwk_client(frontend_api_url: str):
    return jwt.PyJWKClient(
        f"{frontend_api_url.rstrip('/')}/.well-known/jwks.json",
        cache_keys=True,
        lifespan=300,
    )


def _verify_clerk_token(token: str | None) -> dict | None:
    if not token or not _clerk_configured():
        return None
    issuer = os.environ["CLERK_FRONTEND_API_URL"].rstrip("/")
    try:
        signing_key = _clerk_jwk_client(issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
        authorized_party = claims.get("azp")
        if not authorized_party or authorized_party.rstrip("/") != _base_url():
            return None
    except Exception:
        return None
    if not claims.get("sub") or not claims.get("sid"):
        return None
    return claims


@st.cache_data(ttl=30, show_spinner=False)
def _paid_access(user_id: str) -> bool:
    try:
        if paid_from_record(get_access_record(user_id)):
            return True
        return refresh_live_subscription(user_id)
    except Exception:
        return False


def _redirect(url: str) -> None:
    components.html(
        f"<script>window.top.location.href={json.dumps(url)};</script>",
        height=0,
        width=0,
    )


def render_access_control() -> tuple[AccessState, bool]:
    """Render top-right account controls and return server-verified access."""
    try:
        visitor_id = anonymous_visitor_id(st.context.headers)
    except Exception:
        visitor_id = None

    raw = _auth_component(
        publishable_key=os.environ.get("CLERK_PUBLISHABLE_KEY", ""),
        account_portal_url=os.environ.get("CLERK_ACCOUNT_PORTAL_URL", ""),
        clerk_configured=_clerk_configured(),
        clerk_production_ready=clerk_production_ready(),
        stripe_configured=stripe_live_configured(),
        paid=bool(st.session_state.get("_paid_access")),
        remaining_actions=int(
            st.session_state.get("_access_remaining_actions", ANONYMOUS_ACTIONS)
        ),
        key="soxlpro_access_control",
        default={},
    ) or {}

    claims = _verify_clerk_token(raw.get("token"))
    persisted_actions = 0
    anonymous_actions = 0
    elapsed_seconds = 0
    if claims:
        try:
            persisted_actions = signed_in_actions(claims["sub"])
        except Exception:
            persisted_actions = SIGNED_IN_FREE_ACTIONS
    elif visitor_id:
        try:
            anonymous_actions, elapsed_seconds = anonymous_usage(visitor_id)
        except Exception:
            anonymous_actions = ANONYMOUS_ACTIONS

    state = AccessState(
        authenticated=claims is not None,
        user_id=claims.get("sub") if claims else None,
        visitor_id=visitor_id,
        anonymous_actions=anonymous_actions,
        signed_in_actions=persisted_actions,
        elapsed_seconds=elapsed_seconds,
    )
    st.session_state._access_user_id = state.user_id
    st.session_state._access_visitor_id = state.visitor_id

    paid = _paid_access(state.user_id) if state.authenticated else False
    st.session_state._access_paid = paid
    if paid:
        st.session_state._paid_access = True

    remaining_actions = max(
        0,
        (
            SIGNED_IN_FREE_ACTIONS - state.signed_in_actions
            if state.authenticated
            else ANONYMOUS_ACTIONS - state.anonymous_actions
        ),
    )
    if st.session_state.get("_access_remaining_actions") != remaining_actions:
        st.session_state._access_remaining_actions = remaining_actions
        st.rerun()

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
            st.session_state._paid_access = True
            _track_event(
                "subscription_activated",
                {"billing_mode": "live"},
                "subscription_activated",
            )
            st.success("Your SOXLPRO membership is active.")

    action_id = raw.get("action_id")
    action = (
        raw.get("action")
        if action_id
        and action_id != st.session_state.get("_last_access_action_id")
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
            st.error(
                "Live billing is temporarily unavailable. "
                "Please contact contact@zhisystems.ai."
            )
    elif action == "clerk_configuration_missing":
        st.error(
            "Google sign-in is awaiting production Clerk configuration. "
            "Checkout is disabled until Google authentication is active."
        )

    if st.query_params.get("checkout") == "cancelled":
        st.query_params.clear()
        _track_event(
            "subscription_checkout_cancelled",
            {"billing_mode": "live"},
            "subscription_checkout_cancelled",
        )

    return state, paid


def record_meaningful_action(action_name: str) -> None:
    """Count a premium action from trusted Streamlit code, never the browser."""
    if st.session_state.get("_access_paid"):
        return
    try:
        count = increment_usage_action(
            user_id=st.session_state.get("_access_user_id"),
            visitor_id=st.session_state.get("_access_visitor_id"),
        )
        _track_event(
            "free_usage_action",
            {"action": action_name, "count": count},
            f"free_usage_action_{action_name}_{count}",
        )
    except Exception:
        # Fail closed on the next access check if persistence is unavailable.
        st.session_state._usage_persistence_failed = True


def enforce_staged_access(state: AccessState, paid: bool) -> None:
    """Stop premium rendering after each free allowance is exhausted."""
    if paid:
        return
    # Never trap a visitor behind an authentication control that cannot work.
    if not _clerk_configured():
        return
    if st.session_state.get("_usage_persistence_failed"):
        st.error(
            "Access verification is temporarily unavailable. "
            "Please refresh or contact contact@zhisystems.ai."
        )
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
        if _is_deployment() and not clerk_production_ready():
            st.error(
                "Google sign-in is temporarily unavailable. "
                "Please contact contact@zhisystems.ai."
            )
        else:
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