from unittest.mock import patch

import unittest

import access
import auth
import billing
import account_header


OWNER = {
    "is_logged_in": True,
    "email_verified": True,
    "sub": "verified-google-subject",
    "email": "johnmichaelkuczynski@gmail.com",
}


INVALID_IDENTITIES = [
    {"is_logged_in": False},
    {"is_logged_in": "true"},
    {"email_verified": False},
    {"email_verified": "true"},
    {"sub": ""},
    {"email": "someone-else@gmail.com"},
    {"email": "johnmichaelkuczynski+other@gmail.com"},
    {"email": "johnmichaelkuczynski@gmail.com.evil.test"},
    {"auth_provider": "development"},
]


def test_owner_requires_exact_verified_authenticated_identity():
    for change in INVALID_IDENTITIES:
        assert not auth.is_owner(dict(OWNER, **change))
        assert not access.has_unlimited_credits(dict(OWNER, **change))


def test_owner_gets_highest_tier_even_when_billing_is_false():
    assert auth.is_owner(dict(OWNER, email=OWNER["email"].upper()))
    assert access.access_tier(OWNER, paid_verified=False, preview=False) == access.OWNER
    assert access.has_unlimited_credits(OWNER)
    for feature in access.PAID_FEATURES:
        assert access.can_access(feature, OWNER, paid_verified=False, preview=False)


def test_owner_access_makes_no_stripe_or_purchase_database_requests():
    with patch.object(billing, "stripe_client", side_effect=AssertionError("Stripe called")), \
         patch.object(billing, "get_plan", side_effect=AssertionError("Price checked")), \
         patch.object(billing, "user_identity", side_effect=AssertionError("Billing identity checked")):
        assert billing.get_paid_access(OWNER)
        with unittest.TestCase().assertRaisesRegex(billing.BillingError, "No payment"):
            billing.create_checkout(OWNER)


def test_header_skips_all_billing_and_checkout_return_for_owner():
    with patch.object(account_header, "get_current_user", return_value=OWNER), \
         patch.object(account_header, "get_paid_access", side_effect=AssertionError("Billing checked")), \
         patch.object(account_header, "verify_checkout", side_effect=AssertionError("Checkout checked")):
        assert account_header.paid_access_for_current_user(force=True)
        account_header._handle_checkout_return()


def test_owner_does_not_grant_access_to_next_user():
    other = dict(OWNER, email="another-user@example.com", sub="another-subject")
    with patch.object(auth, "get_current_user", return_value=OWNER):
        assert access.has_unlimited_credits()
    with patch.object(auth, "get_current_user", return_value=other):
        assert not access.has_unlimited_credits()
    assert access.access_tier(other, paid_verified=False, preview=False) == access.SIGNED_IN
    assert not access.has_paid_access(other, paid_verified=False, preview=False)
    assert access.has_paid_access(other, paid_verified=True, preview=False)
    assert access.access_tier({"is_logged_in": False}, preview=False) == access.GUEST


def test_owner_dialog_does_not_read_price_or_create_checkout():
    from streamlit.testing.v1 import AppTest
    script = """
import streamlit as st
import account_header as h
h.get_current_user = lambda: {
    "is_logged_in": True, "email_verified": True,
    "sub": "verified-google-subject", "email": "johnmichaelkuczynski@gmail.com"
}
def forbidden(*args, **kwargs):
    raise AssertionError("Owner should never enter billing")
h.get_plan = forbidden
h.create_checkout = forbidden
h.flush_analytics = lambda: None
h.show_purchase_options()
"""
    # AppTest executes imported modules in-process: restore every override.
    with patch.object(account_header, "get_current_user"), \
         patch.object(account_header, "get_plan"), \
         patch.object(account_header, "create_checkout"), \
         patch.object(account_header, "flush_analytics"):
        app = AppTest.from_string(script).run()
        assert not app.exception
        assert any("Permanent owner access" in x.value for x in app.success)
        assert not app.get("link_button")


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(
        unittest.FunctionTestCase(fn)
        for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    )