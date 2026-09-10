"""Focused Stripe billing tests; every provider and database call is mocked."""

from types import SimpleNamespace

import pytest

import billing


PRICE = {
    "id": "price_live_soxl",
    "active": True,
    "livemode": True,
    "type": "one_time",
    "unit_amount": 99,
    "currency": "usd",
    "billing_scheme": "per_unit",
    "product": {"id": "prod_soxl", "active": True, "name": "SOXL Pro"},
}
USER = {
    "is_logged_in": True,
    "sub": "google-sub-123",
    "email": "buyer@example.com",
    "email_verified": True,
}
IDENTITY = billing.hashlib.sha256(b"google:google-sub-123").hexdigest()


def _client(session=None, payment_intent=None, line_items=None):
    prices = SimpleNamespace(
        retrieve=lambda *_args, **_kwargs: PRICE,
        list=lambda *_args, **_kwargs: SimpleNamespace(data=[]),
    )
    sessions = SimpleNamespace(
        retrieve=lambda *_args, **_kwargs: session,
        create=lambda *_args, **_kwargs: session,
        line_items=SimpleNamespace(
            list=lambda *_args, **_kwargs: SimpleNamespace(data=line_items or [])
        ),
    )
    payment_intents = SimpleNamespace(
        retrieve=lambda *_args, **_kwargs: payment_intent
    )
    charges = SimpleNamespace(retrieve=lambda *_args, **_kwargs: {})
    return SimpleNamespace(
        v1=SimpleNamespace(
            prices=prices,
            checkout=SimpleNamespace(sessions=sessions),
            payment_intents=payment_intents,
            charges=charges,
        )
    )


@pytest.fixture(autouse=True)
def billing_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_test_only_mock")
    monkeypatch.setenv("STRIPE_PRICE_ID", PRICE["id"])
    monkeypatch.setenv("PUBLIC_APP_URL", "https://soxlpro.example")
    monkeypatch.setattr("auth.is_development_preview", lambda: False)


def test_get_plan_accepts_active_one_time_price(monkeypatch):
    monkeypatch.setattr(billing, "stripe_client", lambda: _client())

    plan = billing.get_plan()

    assert plan == {
        "name": "SOXL Pro",
        "amount": 99,
        "currency": "usd",
        "interval": None,
        "interval_count": None,
        "livemode": True,
        "price_id": PRICE["id"],
        "mode": "payment",
    }


def test_get_plan_rejects_recurring_price(monkeypatch):
    recurring = dict(PRICE, type="recurring", recurring={"interval": "month"})
    client = _client()
    client.v1.prices.retrieve = lambda *_args, **_kwargs: recurring
    monkeypatch.setattr(billing, "stripe_client", lambda: client)

    with pytest.raises(billing.BillingError, match="Recurring"):
        billing.get_plan()


def test_preview_and_unverified_users_cannot_checkout(monkeypatch):
    monkeypatch.setattr("auth.is_development_preview", lambda: True)
    with pytest.raises(billing.BillingError):
        billing.user_identity(USER)

    monkeypatch.setattr("auth.is_development_preview", lambda: False)
    with pytest.raises(billing.BillingError):
        billing.user_identity(dict(USER, email_verified=False))


def test_create_checkout_persists_attempt_and_uses_card_payment(monkeypatch):
    session = {
        "id": "cs_live_123",
        "url": "https://checkout.stripe.com/cs_live_123",
        "livemode": True,
        "mode": "payment",
        "client_reference_id": IDENTITY,
        "metadata": {
            "app": "soxlpro",
            "user_identity": IDENTITY,
            "price_id": PRICE["id"],
            "attempt_id": "soxlpro-attempt",
        },
    }
    calls = []
    created = []
    attempt = {
        "attempt_id": "soxlpro-attempt",
        "user_identity_hash": IDENTITY,
        "price_id": PRICE["id"],
        "expected_amount": 99,
        "expected_currency": "usd",
        "status": "pending",
    }
    client = _client(session=session)
    client.v1.checkout.sessions.create = (
        lambda params, options: (created.append((params, options)) or session)
    )
    monkeypatch.setattr(billing, "stripe_client", lambda: client)
    monkeypatch.setattr(billing.purchase_store, "reserve_checkout",
                        lambda *_args: (calls.append("reserve") or attempt))
    monkeypatch.setattr(
        billing.purchase_store,
        "attach_session",
        lambda *_args: (calls.append("attach") or dict(
            attempt, stripe_session_id="cs_live_123",
            checkout_url=session["url"], status="open",
        )),
    )

    result = billing.create_checkout(USER)

    assert result == {"url": session["url"], "session_id": "cs_live_123"}
    assert calls == ["reserve", "attach"]
    assert "payment_method_types" not in created[0][0]


def test_verify_checkout_requires_paid_live_charge(monkeypatch):
    session = {
        "id": "cs_live_123",
        "livemode": True,
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "amount_subtotal": 99,
        "amount_total": 99,
        "currency": "usd",
        "total_details": {
            "amount_discount": 0, "amount_shipping": 0, "amount_tax": 0,
        },
        "client_reference_id": IDENTITY,
        "metadata": {"app": "soxlpro", "user_identity": IDENTITY},
        "payment_intent": {
            "status": "succeeded",
            "livemode": True,
            "amount": 99,
            "currency": "usd",
            "latest_charge": {
                "livemode": True,
                "paid": True,
                "amount": 99,
                "currency": "usd",
                "refunded": False,
                "amount_refunded": 0,
                "disputed": False,
            },
        },
        "line_items": {
            "data": [{"quantity": 1, "price": dict(PRICE)}],
        },
    }
    record = {
        "user_identity_hash": IDENTITY,
        "price_id": PRICE["id"],
        "expected_amount": 99,
        "expected_currency": "usd",
        "status": "open",
    }
    marked = []
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(billing.purchase_store, "mark_paid",
                        lambda *_args: marked.append(True))
    monkeypatch.setattr(billing.purchase_store, "mark_status",
                        lambda *_args: pytest.fail("valid payment was rejected"))

    assert billing.verify_checkout(USER, "cs_live_123") is True
    assert marked == [True]


def test_refunded_payment_never_grants_access(monkeypatch):
    session = {
        "id": "cs_live_123",
        "livemode": True,
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "amount_subtotal": 99,
        "amount_total": 99,
        "currency": "usd",
        "total_details": {
            "amount_discount": 0, "amount_shipping": 0, "amount_tax": 0,
        },
        "client_reference_id": IDENTITY,
        "metadata": {"app": "soxlpro", "user_identity": IDENTITY},
        "payment_intent": {
            "status": "succeeded",
            "livemode": True,
            "amount": 99,
            "currency": "usd",
            "latest_charge": {
                "livemode": True,
                "paid": True,
                "amount": 99,
                "currency": "usd",
                "refunded": True,
                "amount_refunded": 99,
                "disputed": False,
            },
        },
        "line_items": {"data": [{"quantity": 1, "price": dict(PRICE)}]},
    }
    record = dict(
        user_identity_hash=IDENTITY,
        price_id=PRICE["id"],
        expected_amount=99,
        expected_currency="usd",
        status="paid",
        stripe_session_id="cs_live_123",
    )
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "list_checkouts",
                        lambda *_args: [record])
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    statuses = []
    monkeypatch.setattr(billing.purchase_store, "mark_status",
                        lambda *_args: statuses.append(True))

    assert billing.get_paid_access(USER) is False
    assert statuses == [True]


def _verification_session(payment_status="paid", intent_status="succeeded"):
    return {
        "id": "cs_live_123",
        "livemode": True,
        "mode": "payment",
        "status": "complete",
        "payment_status": payment_status,
        "amount_subtotal": 99,
        "amount_total": 99,
        "currency": "usd",
        "total_details": {
            "amount_discount": 0, "amount_shipping": 0, "amount_tax": 0,
        },
        "client_reference_id": IDENTITY,
        "metadata": {"app": "soxlpro", "user_identity": IDENTITY},
        "payment_intent": {
            "status": intent_status,
            "livemode": True,
            "amount": 99,
            "currency": "usd",
            "latest_charge": {
                "livemode": True,
                "paid": True,
                "amount": 99,
                "currency": "usd",
                "refunded": False,
                "amount_refunded": 0,
                "disputed": False,
            },
        },
        "line_items": {"data": [{"quantity": 1, "price": dict(PRICE)}]},
    }


def _stored_record(status="open"):
    return {
        "user_identity_hash": IDENTITY,
        "price_id": PRICE["id"],
        "expected_amount": 99,
        "expected_currency": "usd",
        "status": status,
        "stripe_session_id": "cs_live_123",
    }


def test_wrong_owner_and_test_mode_never_grant_access(monkeypatch):
    session = _verification_session()
    session["client_reference_id"] = "different-user"
    session["metadata"]["user_identity"] = "different-user"
    record = _stored_record()
    statuses = []
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(billing.purchase_store, "mark_status",
                        lambda *_args: statuses.append(True))

    assert billing.verify_checkout(USER, "cs_live_123") is False

    session["client_reference_id"] = IDENTITY
    session["metadata"]["user_identity"] = IDENTITY
    session["livemode"] = False
    assert billing.verify_checkout(USER, "cs_live_123") is False
    assert statuses == [True, True]


def test_unpaid_card_stays_pending_then_can_be_confirmed(monkeypatch):
    session = _verification_session(payment_status="unpaid", intent_status="processing")
    record = _stored_record()
    statuses = []
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(
        billing.purchase_store, "mark_status",
        lambda _identity, _session, status: (statuses.append(status),
                                               record.update(status=status)),
    )
    monkeypatch.setattr(
        billing.purchase_store, "mark_paid",
        lambda *_args: record.update(status="paid"),
    )

    assert billing.verify_checkout(USER, "cs_live_123") is False
    assert statuses == ["pending"]
    session["payment_status"] = "paid"
    session["payment_intent"]["status"] = "succeeded"
    assert billing.verify_checkout(USER, "cs_live_123") is True
    assert record["status"] == "paid"


def test_managed_payment_tax_is_added_to_base_before_payment_checks(monkeypatch):
    session = _verification_session()
    session["total_details"] = {
        "amount_discount": 0,
        "amount_shipping": 0,
        "amount_tax": 20,
        "breakdown": {"taxes": [{"amount": 20}]},
    }
    session["amount_total"] = 119
    session["payment_intent"]["amount"] = 119
    session["payment_intent"]["latest_charge"]["amount"] = 119
    record = _stored_record()
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(billing.purchase_store, "mark_paid",
                        lambda *_args: record.update(status="paid"))
    monkeypatch.setattr(billing.purchase_store, "mark_status",
                        lambda *_args: pytest.fail("valid tax total was rejected"))

    assert billing.verify_checkout(USER, "cs_live_123") is True


def test_inclusive_tax_is_not_added_twice(monkeypatch):
    session = _verification_session()
    session["total_details"] = {
        "amount_discount": 0,
        "amount_shipping": 0,
        "amount_tax": 20,
        "breakdown": {
            "taxes": [{"amount": 20, "rate": {"inclusive": True}}],
        },
    }
    session["line_items"]["data"][0]["price"] = dict(PRICE, tax_behavior="unspecified")
    record = _stored_record()
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(billing.purchase_store, "mark_paid",
                        lambda *_args: record.update(status="paid"))
    monkeypatch.setattr(billing.purchase_store, "mark_status",
                        lambda *_args: pytest.fail("inclusive tax was double-counted"))

    assert billing.verify_checkout(USER, "cs_live_123") is True


def test_create_checkout_does_not_start_second_payment_while_pending(monkeypatch):
    session = _verification_session(payment_status="unpaid", intent_status="processing")
    record = _stored_record()
    monkeypatch.setattr(billing, "stripe_client", lambda: _client(session=session))
    monkeypatch.setattr(billing.purchase_store, "reserve_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: record)
    monkeypatch.setattr(
        billing.purchase_store, "mark_status",
        lambda _identity, _session, status: record.update(status=status),
    )

    with pytest.raises(billing.BillingError, match="still being confirmed"):
        billing.create_checkout(USER)


@pytest.mark.parametrize("field", ["session", "intent", "charge"])
def test_paid_amount_mismatch_blocks_second_checkout_and_can_reconcile(monkeypatch, field):
    session = _verification_session()
    target = {
        "session": (session, "amount_total"),
        "intent": (session["payment_intent"], "amount"),
        "charge": (session["payment_intent"]["latest_charge"], "amount"),
    }[field]
    target[0][target[1]] = 199  # Locally unverifiable, but Stripe says paid.
    record = _stored_record()
    client = _client(session=session)
    client.v1.checkout.sessions.create = lambda *_args: pytest.fail("second checkout created")
    monkeypatch.setattr(billing, "stripe_client", lambda: client)
    monkeypatch.setattr(billing.purchase_store, "find_checkout", lambda *_: record)
    monkeypatch.setattr(billing.purchase_store, "reserve_checkout", lambda *_: record)
    monkeypatch.setattr(
        billing.purchase_store, "mark_status",
        lambda _identity, _session, status: record.update(status=status),
    )
    monkeypatch.setattr(
        billing.purchase_store, "mark_paid",
        lambda *_: record.update(status="paid"),
    )
    assert billing.verify_checkout(USER, "cs_live_123") is False
    assert record["status"] == "review"
    with pytest.raises(billing.BillingError, match="do not pay again"):
        billing.create_checkout(USER)
    assert record["status"] == "review"
    target[0][target[1]] = 99
    assert billing.verify_checkout(USER, "cs_live_123") is True
    assert record["status"] == "paid"


def test_provider_invalid_request_is_not_silently_treated_as_unpaid(monkeypatch):
    class InvalidRequest(Exception):
        code = "invalid_request_error"

    monkeypatch.setattr(billing.stripe, "InvalidRequestError", InvalidRequest)
    client = _client(session=None)
    client.v1.checkout.sessions.retrieve = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(InvalidRequest())
    )
    monkeypatch.setattr(billing, "stripe_client", lambda: client)
    monkeypatch.setattr(billing.purchase_store, "find_checkout",
                        lambda *_args: _stored_record())

    with pytest.raises(billing.BillingError, match="checkout"):
        billing.verify_checkout(USER, "cs_live_123")


def test_reservation_advisory_lock_prevents_duplicate_insert(monkeypatch):
    import purchase_store

    class Cursor:
        def __init__(self, state):
            self.state = state
            self.result = None
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            self.state["queries"].append(sql)
            if sql.startswith("SELECT pg_advisory"):
                self.result = None
            elif sql.startswith("SELECT"):
                self.result = self.state["rows"][0] if self.state["rows"] else None
            elif sql.startswith("INSERT"):
                row = {
                    "attempt_id": "soxlpro-test",
                    "user_identity_hash": IDENTITY,
                    "price_id": PRICE["id"],
                    "expected_amount": 99,
                    "expected_currency": "usd",
                    "status": "pending",
                }
                self.state["rows"].append(row)
                self.result = row
                self.rowcount = 1

        def fetchone(self):
            return self.result

    class Connection:
        def __init__(self, state):
            self.state = state

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self, **_kwargs):
            return Cursor(self.state)

        def close(self):
            pass

    state = {"queries": [], "rows": []}
    monkeypatch.setattr(purchase_store, "_initialized", True)
    monkeypatch.setattr(purchase_store.db, "get_conn",
                        lambda: Connection(state))

    first = purchase_store.reserve_checkout(IDENTITY, PRICE["id"], 99, "usd")
    second = purchase_store.reserve_checkout(IDENTITY, PRICE["id"], 99, "usd")

    assert first["attempt_id"] == second["attempt_id"]
    assert sum(query.startswith("INSERT") for query in state["queries"]) == 1
    assert sum(query.startswith("SELECT pg_advisory") for query in state["queries"]) == 2