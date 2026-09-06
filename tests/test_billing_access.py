from datetime import datetime, timezone
from types import SimpleNamespace

import billing
from access_control import AccessState


def test_valid_google_user_id():
    assert billing.valid_auth_user_id("google_975456524083123456789")
    assert not billing.valid_auth_user_id("user_2abcDEF123")
    assert not billing.valid_auth_user_id(None)


def test_paid_record_requires_active_matching_live_price(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_live_expected")
    base = {
        "subscription_status": "active",
        "subscription_price_id": "price_live_expected",
        "current_period_end": datetime.now(timezone.utc),
    }
    assert billing.paid_from_record(base)
    assert not billing.paid_from_record({**base, "subscription_status": "canceled"})
    assert not billing.paid_from_record(
        {**base, "subscription_price_id": "price_other"}
    )


def test_access_state_defaults_are_unprivileged():
    state = AccessState()
    assert not state.authenticated
    assert state.user_id is None
    assert state.anonymous_actions == 0


def test_live_checkout_returns_url_from_converted_stripe_session(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_live_expected")
    fake_stripe = SimpleNamespace(
        checkout=SimpleNamespace(
            Session=SimpleNamespace(
                create=lambda **_: {
                    "livemode": True,
                    "url": "https://checkout.stripe.com/live-session",
                }
            )
        )
    )
    monkeypatch.setattr(billing, "_stripe", lambda: fake_stripe)
    monkeypatch.setattr(
        billing, "_customer_for_user", lambda _stripe, _user_id: "cus_live"
    )

    assert billing.create_checkout_url(
        "google_975456524083123456789",
        "https://soxlpro.xyz",
    ) == "https://checkout.stripe.com/live-session"