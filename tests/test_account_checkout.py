"""UI tests with explicit fake billing responses; never contacts Stripe."""
import unittest

from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
import account_header as h

def user():
    return {
        "is_logged_in": st.session_state.get("test_signed_in", True),
        "sub": "unit-test-only", "email_verified": True,
    }

def create(user):
    st.session_state["checkout_calls"] = st.session_state.get("checkout_calls", 0) + 1
    if st.session_state.get("test_failure"):
        raise RuntimeError("DO_NOT_DISPLAY_PROVIDER_DETAILS")
    return {"url": "https://checkout.stripe.com/c/pay/unit_test", "session_id": "cs_unit_test"}

def verify(user, session_id):
    st.session_state["verified_session"] = session_id
    return st.session_state.get("test_confirmed", False)

def track(name, properties=None, once_key=None):
    events = st.session_state.get("analytics_events", [])
    events.append({"name": name, "properties": properties})
    st.session_state["analytics_events"] = events

h.get_current_user = user
h.is_development_preview = lambda: st.session_state.get("test_preview", False)
h.user_identity = lambda u: u["sub"]
h.get_paid_access = lambda u: st.session_state.get("test_paid", False)
h.get_plan = lambda: {"name": "Soxl Pro", "amount": 99, "currency": "usd", "mode": "payment"}
h.create_checkout = create
h.verify_checkout = verify
h.public_origin = lambda: "https://example.com"
h.render_google_login = lambda: st.button("Test account")
h.track_event = track
h.flush_analytics = lambda: None
h.render_account_header()
'''


class AccountCheckoutTests(unittest.TestCase):
    def app(self, **state):
        app = AppTest.from_string(SCRIPT)
        for key, value in state.items():
            app.session_state[key] = value
        return app.run()

    def test_buy_opens_actual_payment_link(self):
        app = self.app()
        app.button(key="buy_access").click().run()
        self.assertFalse(app.exception)
        links = app.get("link_button")
        self.assertTrue(any("Pay $0.99 USD with Stripe" == x.proto.label for x in links))
        self.assertEqual(app.session_state["checkout_calls"], 1)
        self.assertTrue(any(e["name"] == "checkout_ready"
                            for e in app.session_state["analytics_events"]))
        self.assertFalse(any("not available yet" in x.value for x in app.markdown))

    def test_guest_is_invited_to_sign_in_without_creating_checkout(self):
        app = self.app(test_signed_in=False)
        app.button(key="buy_access").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="checkout_google_login").label, "Sign in to buy")
        self.assertNotIn("checkout_calls", app.session_state)

    def test_preview_uses_published_site_not_live_checkout_creation(self):
        app = self.app(test_preview=True)
        app.button(key="buy_access").click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("checkout_calls", app.session_state)
        self.assertTrue(any(x.proto.url == "https://example.com/?checkout=buy"
                            for x in app.get("link_button")))

    def test_paid_account_cannot_accidentally_buy_again(self):
        app = self.app(test_paid=True)
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="paid_access_active").disabled)
        self.assertNotIn("checkout_calls", app.session_state)
        self.assertTrue(app.session_state["_paid_access_verified"])

    def test_checkout_failure_never_leaks_provider_message(self):
        app = self.app(test_failure=True)
        app.button(key="buy_access").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("couldn't open checkout" in x.value for x in app.info))
        self.assertFalse(any("DO_NOT_DISPLAY" in x.value for x in app.info))

    def test_success_query_alone_does_not_grant_access(self):
        app = self.app()
        app.query_params["checkout"] = "success"
        app.query_params["session_id"] = "cs_not_paid"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.success)
        self.assertFalse(app.session_state["_paid_access_verified"])
        self.assertEqual(app.session_state["verified_session"], "cs_not_paid")
        self.assertFalse(any(e["name"] == "payment_confirmed"
                             for e in app.session_state["analytics_events"]))

    def test_confirmed_return_clears_payment_query(self):
        app = self.app(test_confirmed=True, test_paid=True)
        app.query_params["checkout"] = "success"
        app.query_params["session_id"] = "cs_paid"
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Payment confirmed" in x.value for x in app.success))
        self.assertNotIn("checkout", app.query_params)
        self.assertNotIn("session_id", app.query_params)
        payment_events = [e for e in app.session_state["analytics_events"]
                          if e["name"] == "payment_confirmed"]
        self.assertEqual(payment_events, [
            {"name": "payment_confirmed", "properties": {"plan": "full_access"}}
        ])

    def test_cancel_is_not_payment_success(self):
        app = self.app()
        app.query_params["checkout"] = "cancelled"
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.success)
        self.assertTrue(any("cancelled" in x.value for x in app.info))


if __name__ == "__main__":
    unittest.main()