"""Clerk authentication, staged free access, and Stripe checkout controls."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
import requests
import streamlit as st
import streamlit.components.v1 as components


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
    session_id: str | None = None
    anonymous_actions: int = 0
    signed_in_actions: int = 0
    elapsed_seconds: int = 0


def _clerk_configured() -> bool:
    return bool(
        os.environ.get("CLERK_PUBLISHABLE_KEY")
        and os.environ.get("CLERK_FRONTEND_API_URL")
    )


def stripe_live_configured() -> bool:
    return (
        os.environ.get("STRIPE_PUBLISHABLE_KEY", "").startswith("pk_live_")
        and os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_")
        and os.environ.get("STRIPE_WEBHOOK_SECRET", "").startswith("whsec_")
        and os.environ.get("STRIPE_PRICE_ID", "").startswith("price_")
    )


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
    except Exception:
        return None
    if not claims.get("sub") or not claims.get("sid"):
        return None
    return claims


def _checkout_url(user_id: str) -> str | None:
    if not stripe_live_configured():
        return None
    try:
        import stripe

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        host = st.context.headers.get("host", "")
        scheme = st.context.headers.get("x-forwarded-proto", "https")
        base_url = f"{scheme}://{host}" if host else "https://soxlpro.xyz"
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
            client_reference_id=user_id,
            metadata={"clerk_user_id": user_id},
            subscription_data={"metadata": {"clerk_user_id": user_id}},
            success_url=f"{base_url}/?{urlencode({'checkout': 'success'})}"
            + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=f"{base_url}/?checkout=cancelled",
            allow_promotion_codes=True,
        )
        return session.url
    except Exception:
        return None


def _checkout_paid(user_id: str) -> bool:
    session_id = st.query_params.get("session_id")
    if not session_id or not stripe_live_configured():
        return bool(st.session_state.get("_paid_access"))
    try:
        import stripe

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        session = stripe.checkout.Session.retrieve(session_id)
        paid = (
            session.get("livemode") is True
            and session.get("client_reference_id") == user_id
            and session.get("payment_status") in {"paid", "no_payment_required"}
            and session.get("status") == "complete"
        )
        if paid:
            st.session_state._paid_access = True
            st.query_params.clear()
        return paid
    except Exception:
        return False


def render_access_control() -> tuple[AccessState, bool]:
    """Render fixed auth/payment controls and return verified access state."""
    raw = _auth_component(
        publishable_key=os.environ.get("CLERK_PUBLISHABLE_KEY", ""),
        clerk_configured=_clerk_configured(),
        stripe_configured=stripe_live_configured(),
        anonymous_seconds=ANONYMOUS_SECONDS,
        anonymous_actions=ANONYMOUS_ACTIONS,
        signed_in_actions=SIGNED_IN_FREE_ACTIONS,
        key="soxlpro_access_control",
        default={},
    ) or {}
    claims = _verify_clerk_token(raw.get("token"))
    state = AccessState(
        authenticated=claims is not None,
        user_id=claims.get("sub") if claims else None,
        session_id=claims.get("sid") if claims else None,
        anonymous_actions=max(0, int(raw.get("anonymous_actions", 0) or 0)),
        signed_in_actions=max(0, int(raw.get("signed_in_actions", 0) or 0)),
        elapsed_seconds=max(0, int(raw.get("elapsed_seconds", 0) or 0)),
    )

    checkout_requested = raw.get("action") == "checkout"
    if checkout_requested:
        if not state.authenticated:
            st.session_state._checkout_after_login = True
        else:
            checkout_url = _checkout_url(state.user_id)
            if checkout_url:
                st.markdown(
                    f'<meta http-equiv="refresh" content="0;url={checkout_url}">',
                    unsafe_allow_html=True,
                )
            else:
                st.error(
                    "Live checkout is not available yet. Contact contact@zhisystems.ai."
                )

    paid = _checkout_paid(state.user_id) if state.authenticated else False
    return state, paid


def enforce_staged_access(state: AccessState, paid: bool) -> None:
    """Stop the page only after the configured preview allowance is exhausted."""
    if paid or not _clerk_configured() or not stripe_live_configured():
        return
    anonymous_limit_reached = (
        state.elapsed_seconds >= ANONYMOUS_SECONDS
        or state.anonymous_actions >= ANONYMOUS_ACTIONS
    )
    if not state.authenticated and anonymous_limit_reached:
        st.warning(
            "Continue with Google to keep using SOXLPRO. "
            "Your initial preview is complete."
        )
        st.stop()
    if state.authenticated and state.signed_in_actions >= SIGNED_IN_FREE_ACTIONS:
        st.warning(
            "Your signed-in free access is complete. Subscribe to continue using SOXLPRO."
        )
        st.stop()