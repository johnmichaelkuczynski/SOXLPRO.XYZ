"""Small, server-backed access policy for the SOXL app.

The account header is the only place that verifies billing.  This module only
interprets that result for rendering; it never reads query parameters, asks
the billing provider for access, or treats a client-controlled value as an
identity.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

import streamlit as st

from auth import get_current_user, is_development_preview, is_owner


PAID_ACCESS_SESSION_KEY = "_paid_access_verified"

GUEST = "guest"
SIGNED_IN = "signed_in"
PAID = "paid"
OWNER = "owner"


def has_unlimited_credits(user=None) -> bool:
    """Permanent exemption from application credit quotas, not provider billing."""
    return is_owner(user)

# These are the paid entry points.  Chart/probability/snapshot rendering and
# diagnostics intentionally do not appear here and remain available under
# their existing rules.
PAID_FEATURES = frozenset(
    {
        "Vol Surface",
        "Call Risk/Reward",
        "Dislocation",
        "Backtest",
        "Strategy Builder",
    }
)


def _logged_in(user: Mapping[str, Any] | None) -> bool:
    """Return the server-authenticated login state without guessing identity."""
    return bool(user and user.get("is_logged_in"))


def access_tier(
    user: Mapping[str, Any] | None = None,
    *,
    paid_verified: bool | None = None,
    preview: bool | None = None,
) -> str:
    """Resolve to ``guest``, ``signed_in``, ``paid``, or permanent ``owner``.

    ``paid_verified`` is deliberately an explicit server result.  When it is
    omitted, the value written by ``render_account_header`` is used.  Preview
    is full access only while the preview's authenticated user is logged in;
    the preview sign-out control therefore correctly returns to guest access.
    """
    if user is None:
        user = get_current_user()

    if not _logged_in(user):
        return GUEST

    if is_owner(user):
        return OWNER

    if preview is None:
        preview = is_development_preview()
    if preview:
        return PAID

    if paid_verified is None:
        paid_verified = st.session_state.get(PAID_ACCESS_SESSION_KEY, False)
    return PAID if paid_verified is True else SIGNED_IN


def has_paid_access(
    user: Mapping[str, Any] | None = None,
    *,
    paid_verified: bool | None = None,
    preview: bool | None = None,
) -> bool:
    """Whether the authenticated session may enter a paid feature."""
    return access_tier(
        user, paid_verified=paid_verified, preview=preview
    ) in (PAID, OWNER)


def can_use_market_chat(
    user: Mapping[str, Any] | None = None,
    *,
    paid_verified: bool | None = None,
    preview: bool | None = None,
) -> bool:
    """Market chat is available to every signed-in user, not just paid users."""
    return access_tier(
        user, paid_verified=paid_verified, preview=preview
    ) != GUEST


def can_access(
    feature: str,
    user: Mapping[str, Any] | None = None,
    *,
    paid_verified: bool | None = None,
    preview: bool | None = None,
) -> bool:
    """Return whether a session can access a named feature.

    Unknown features are not silently made paid.  Existing app surfaces that
    are intentionally outside the paid list remain unaffected by this helper.
    """
    if feature in PAID_FEATURES:
        return has_paid_access(
            user, paid_verified=paid_verified, preview=preview
        )
    if feature == "Talk with SOXL Pro":
        return can_use_market_chat(
            user, paid_verified=paid_verified, preview=preview
        )
    return True


def _button_key(feature: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", feature.lower()).strip("_")
    return f"buy_full_access_{slug or 'feature'}"


def render_paid_gate(
    feature: str,
    purchase_dialog: Callable[[], Any],
) -> None:
    """Render a friendly paid-feature invitation and open real checkout.

    The callback is supplied by ``app.py`` so this module does not duplicate
    checkout logic or create a second purchase path.
    """
    st.markdown(f"### {feature}")
    st.info(
        f"{feature} is part of SOXL Pro full access. "
        "Buy full access to unlock it."
    )
    if st.button(
        "Buy full access",
        key=_button_key(feature),
        type="primary",
        width="stretch",
    ):
        purchase_dialog()


def require_paid_access(
    feature: str,
    user: Mapping[str, Any] | None,
    purchase_dialog: Callable[[], Any],
    *,
    paid_verified: bool | None = None,
    preview: bool | None = None,
) -> bool:
    """Render a gate when needed and return whether feature code may run."""
    if has_paid_access(
        user, paid_verified=paid_verified, preview=preview
    ):
        return True
    render_paid_gate(feature, purchase_dialog)
    return False