from datetime import datetime, timezone

import billing
from access_control import AccessState


def test_valid_clerk_user_id():
    assert billing.valid_clerk_user_id("user_2abcDEF123")
    assert not billing.valid_clerk_user_id("not-a-clerk-user")
    assert not billing.valid_clerk_user_id(None)


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