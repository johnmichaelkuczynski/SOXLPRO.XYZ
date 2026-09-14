"""Normal, non-sticky page header. Account actions precede market content."""
import base64
import logging
import time
from decimal import Decimal
from pathlib import Path

import streamlit as st

from auth import (
    configure_google_auth, get_current_user, is_development_preview,
    render_google_login, is_owner,
)
from billing import (
    create_checkout, get_paid_access, get_plan, public_origin,
    user_identity, verify_checkout,
)
from app_analytics import flush_analytics, track_event

logger = logging.getLogger(__name__)


def _billing_failure(operation, exc):
    # Provider exception strings can include sensitive data. Only log categories.
    logger.warning("Billing %s failed (%s)", operation, type(exc).__name__)


def _price_label(plan):
    # This app's configured USD price is returned by Stripe in cents.
    return f"${Decimal(plan['amount']) / 100:.2f} {plan['currency'].upper()}"


def paid_access_for_current_user(force=False):
    user = get_current_user()
    if is_owner(user):
        return True
    if is_development_preview() or not user.get("is_logged_in"):
        return False
    identity = user_identity(user)
    cached = st.session_state.get("_billing_access")
    if not force and cached and cached["identity"] == identity:
        if time.monotonic() - cached["checked_at"] < 60:
            return cached["paid"]
    paid = get_paid_access(user)
    st.session_state["_billing_access"] = {
        "identity": identity, "checked_at": time.monotonic(), "paid": paid,
    }
    return paid


def _purchase_sign_in():
    st.write("Sign in with Google so your purchase stays connected to your account.")
    if st.button("Sign in to buy", key="checkout_google_login", type="primary",
                 width="stretch"):
        try:
            configure_google_auth()
            st.login("google")
        except Exception as exc:
            _billing_failure("sign-in", exc)
            st.info("Sign-in could not open. Please try again. No payment was taken.")

@st.dialog("Buy full access")
def show_purchase_options():
    try:
        if is_owner(get_current_user()):
            st.success("Permanent owner access is active. Unlimited app credits. No payment or renewal is required.")
            return
        plan = get_plan()
        price = _price_label(plan)
        st.write(f"{plan['name']} · {price} one-time payment")
        st.caption("No recurring subscription. Stripe handles payment and calculates any applicable tax at checkout.")
        if is_development_preview():
            st.info("The preview does not take payments. Use the published site and sign in with Google to purchase.")
            st.link_button("Open published site to buy", public_origin() + "/?checkout=buy",
                           type="primary", width="stretch")
            return
        user = get_current_user()
        if not user.get("is_logged_in"):
            _purchase_sign_in()
            return
        if paid_access_for_current_user(force=True):
            st.success("Your full access is active. You do not need to pay again.")
            return
        with st.spinner("Opening secure checkout…"):
            checkout = create_checkout(user)
        track_event("checkout_ready", {"location": "buy_dialog"},
                    once_key=checkout["session_id"])
        st.link_button(f"Pay {price} with Stripe", checkout["url"],
                       type="primary", width="stretch")
        st.caption("After payment, return here with the same Google account. Your purchase will also be recognized on your next visit.")
    except Exception as exc:
        _billing_failure("checkout", exc)
        track_event("checkout_error", {"stage": "checkout"})
        st.info("We couldn't open checkout. If you already paid, do not pay again—use Refresh to check your access. Otherwise, please try again.")
        if st.button("Try again", key="retry_checkout", width="stretch"):
            st.rerun(scope="fragment")
    finally:
        flush_analytics()


def _handle_checkout_return():
    if is_owner(get_current_user()):
        # Owner access is not a purchase and must not emit payment-confirmed events.
        return
    action = st.query_params.get("checkout")
    if action == "cancelled":
        track_event("checkout_cancelled", {"location": "return"})
        st.info("Checkout was cancelled. You can continue using the app.")
        del st.query_params["checkout"]
        return
    if action != "success":
        return
    user = get_current_user()
    if is_development_preview():
        st.info("Payment confirmation is available on the published site.")
        return
    if not user.get("is_logged_in"):
        st.info("Sign in with the same Google account to confirm your purchase.")
        return
    session_id = st.query_params.get("session_id", "")
    try:
        if not session_id.startswith("cs_") or len(session_id) > 255:
            st.info("This payment confirmation link is incomplete. Your account can still recover a completed purchase.")
            return
        with st.spinner("Confirming payment with Stripe…"):
            confirmed = verify_checkout(user, session_id)
        st.session_state.pop("_billing_access", None)
        if confirmed:
            track_event("payment_confirmed", {"plan": "full_access"},
                        once_key=session_id)
            st.success("Payment confirmed. Your full access is active.")
            del st.query_params["checkout"]
            del st.query_params["session_id"]
        else:
            st.info("Stripe has not confirmed a completed payment for this account. If you just paid, check again before starting another purchase.")
            if st.button("Check payment again", key="check_payment"):
                st.rerun()
    except Exception as exc:
        _billing_failure("confirmation", exc)
        track_event("checkout_error", {"stage": "confirmation"})
        st.info("We couldn't confirm payment yet. If you paid, do not pay again—retry confirmation or sign back in later.")
        if st.button("Retry confirmation", key="retry_payment"):
            st.rerun()


def render_account_header():
    flush_analytics()
    _handle_checkout_return()
    paid = False
    st.session_state["_paid_access_verified"] = False
    try:
        paid = paid_access_for_current_user()
        st.session_state["_paid_access_verified"] = paid
    except Exception as exc:
        _billing_failure("access-check", exc)
        st.info("Purchase status is temporarily unavailable. If you have paid, please refresh before trying to buy again.")
    user = get_current_user()
    if user.get("is_logged_in") and not is_development_preview():
        track_event("signed_in_session", {"tier": "paid" if paid else "signed_in"},
                    once_key=user.get("sub", "signed-in"))
    logo = Path("attached_assets/zhi_logoc_1787826573212.png")
    logo_uri = "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode("ascii")
    with st.container(key="account_header"):
        title, login, buy, contact, refresh = st.columns([3.3, 1.65, 0.8, 1.15, 0.85])
        with title:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:12px;min-height:44px;">'
                f'<a href="https://zhisystems.ai/" target="_blank" rel="noopener noreferrer" '
                f'title="Visit ZHI Systems"><img src="{logo_uri}" alt="ZHI Systems" '
                f'style="display:block;width:38px;height:38px;border-radius:8px;"></a>'
                f'<h1 style="font-size:1.35rem;font-weight:700;color:#111827;margin:0;">'
                f'SOXL Analysis</h1></div>',
                unsafe_allow_html=True,
            )
        with login:
            render_google_login()
        with buy:
            if is_owner(user):
                st.button("Owner", key="owner_access_active", disabled=True,
                          help="Permanent highest-tier access with unlimited app credits. No payment or renewal required.",
                          width="stretch")
            elif paid:
                st.button("Full access", key="paid_access_active", disabled=True,
                          help="Your payment has been verified with Stripe.", width="stretch")
            elif st.button("Buy", key="buy_access", type="primary", width="stretch"):
                show_purchase_options()
        with contact:
            st.link_button("Contact Us", "mailto:contact@zhisystems.ai", width="stretch")
        with refresh:
            if st.button("Refresh", help="Refresh data"):
                st.session_state.pop("_billing_access", None)
                st.cache_data.clear()
                st.rerun()
    if st.query_params.get("checkout") == "buy":
        del st.query_params["checkout"]
        show_purchase_options()
    flush_analytics()