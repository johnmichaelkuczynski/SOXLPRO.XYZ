"""Normal, non-sticky page header. Account actions precede market content."""
import base64
from pathlib import Path

import streamlit as st

from auth import get_current_user, render_google_login


@st.dialog("Buy full access")
def show_purchase_options():
    st.write("Full-access subscriptions")
    st.write(
        "Subscription checkout is not available yet. "
        "You can continue using your current app access."
    )
    st.link_button(
        "Contact us about a subscription",
        "mailto:contact@zhisystems.ai?subject=SOXL%20subscription",
        width="stretch",
    )
    if not get_current_user().get("is_logged_in"):
        st.caption("You can sign in using the account button at the top of the page.")


def render_account_header():
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
            if st.button("Buy", key="buy_access", type="primary", width="stretch"):
                show_purchase_options()
        with contact:
            st.link_button("Contact Us", "mailto:contact@zhisystems.ai", width="stretch")
        with refresh:
            if st.button("Refresh", help="Refresh data"):
                st.cache_data.clear()
                st.rerun()