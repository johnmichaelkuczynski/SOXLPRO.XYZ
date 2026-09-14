"""Direct one-time Stripe billing with the owner's environment keys.

Only the official Stripe Python SDK is used here.  Checkout state is kept in
``purchase_store`` so access survives a customer closing the return page.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlsplit

import stripe

import purchase_store


class BillingError(RuntimeError):
    """A safe, user-facing billing configuration or provider failure."""


def stripe_client():
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise BillingError("STRIPE_SECRET_KEY is missing from the server configuration.")
    try:
        return stripe.StripeClient(key, max_network_retries=2)
    except Exception as exc:
        raise BillingError("Stripe billing is temporarily unavailable.") from exc


def configured_price_id():
    price_id = os.environ.get("STRIPE_PRICE_ID", "")
    if not price_id.startswith("price_"):
        raise BillingError("STRIPE_PRICE_ID must identify an existing price in your Stripe account.")
    return price_id


def plain(resource):
    """Convert a Stripe resource (or test double) to a shallow plain mapping."""
    if resource is None:
        return {}
    if isinstance(resource, Mapping):
        return dict(resource)
    if hasattr(resource, "to_dict"):
        try:
            converted = resource.to_dict()
            return dict(converted) if isinstance(converted, Mapping) else converted
        except Exception:
            pass
    try:
        return dict(resource)
    except (TypeError, ValueError):
        return dict(getattr(resource, "__dict__", {}))


def _field(resource: Any, name: str, default=None):
    if isinstance(resource, Mapping):
        return resource.get(name, default)
    return getattr(resource, name, default)


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _data(resource: Any) -> list:
    value = _field(resource, "data", resource)
    if value is None:
        return []
    return list(value) if not isinstance(value, Mapping) else []


def _provider_call(call: Callable[[], Any], message: str):
    """Call Stripe without allowing provider exception text into the UI."""
    try:
        return call()
    except BillingError:
        raise
    except Exception as exc:
        raise BillingError(message) from exc


def _store_call(call: Callable[[], Any]):
    try:
        return call()
    except BillingError:
        raise
    except Exception as exc:
        raise BillingError("The purchase database is temporarily unavailable.") from exc


def get_plan():
    """Return the configured active live/ test price as a payment plan.

    This app intentionally supports one-time prices only.  A recurring price
    is rejected rather than being silently treated as a one-time purchase.
    ``livemode`` is exposed so callers can fail closed before creating a
    Checkout session.
    """
    price_id = configured_price_id()
    price = _provider_call(
        lambda: stripe_client().v1.prices.retrieve(
            price_id, {"expand": ["product"]}
        ),
        "The configured Stripe price could not be read.",
    )
    price = plain(price)
    product = _field(price, "product", {})
    product = plain(product) if product else {}
    if not _field(price, "active", False) or not _field(product, "active", False):
        raise BillingError("The configured Stripe price or product is inactive.")

    recurring = _field(price, "recurring")
    if _field(price, "type") == "recurring" or recurring:
        raise BillingError(
            "Recurring Stripe prices are not supported; configure an active one-time price."
        )
    amount = _as_int(_field(price, "unit_amount"))
    if amount is None or amount < 0:
        raise BillingError("The configured Stripe price must have a fixed amount.")
    raw_currency = _field(price, "currency", "")
    currency = str(raw_currency).lower()
    if not raw_currency:
        raise BillingError("The configured Stripe price has no currency.")
    if _field(price, "billing_scheme", "per_unit") != "per_unit":
        raise BillingError("The configured Stripe price must use per-unit billing.")

    return {
        "name": _field(product, "name", "SOXL Pro"),
        "amount": amount,
        "currency": currency,
        # Kept in the public contract for callers that display plan details.
        # One-time prices intentionally have no interval.
        "interval": None,
        "interval_count": None,
        "livemode": bool(_field(price, "livemode", False)),
        "price_id": price_id,
        "mode": "payment",
    }


def configuration_report():
    """Read-only provider check; returned fields contain no keys/customer data."""
    account = plain(
        _provider_call(
            lambda: stripe_client().v1.accounts.retrieve_current(),
            "Stripe account information is temporarily unavailable.",
        )
    )
    balance = plain(
        _provider_call(
            lambda: stripe_client().v1.balance.retrieve(),
            "Stripe balance information is temporarily unavailable.",
        )
    )
    try:
        plan = get_plan()
    except BillingError as exc:
        plan = {"error": getattr(exc, "code", None) or "invalid_price"}

    def available_prices():
        return _provider_call(
            lambda: stripe_client().v1.prices.list(
                {"active": True, "limit": 10, "expand": ["data.product"]}
            ),
            "Stripe prices are temporarily unavailable.",
        )

    prices = available_prices()
    available_plans = []
    for item in _data(prices):
        p = plain(item)
        product = plain(_field(p, "product", {}))
        available_plans.append(
            {
                "name": _field(product, "name", "SOXL Pro"),
                "amount": _field(p, "unit_amount"),
                "currency": _field(p, "currency"),
                "recurring": plain(_field(p, "recurring")) if _field(p, "recurring") else None,
                "livemode": bool(_field(p, "livemode", False)),
                "price_id": _field(p, "id"),
                "mode": "subscription" if _field(p, "recurring") else "payment",
            }
        )

    # Reading existing portal configuration preserves the old report shape.
    # This code never creates or changes portal/webhook resources.
    try:
        portals = _provider_call(
            lambda: stripe_client().v1.billing_portal.configurations.list(
                {"active": True, "limit": 1}
            ),
            "Stripe portal information is temporarily unavailable.",
        )
        portal_configured = bool(_data(portals))
    except BillingError:
        portal_configured = False

    return {
        "plan": plan,
        "livemode": bool(_field(balance, "livemode", False)),
        "charges_enabled": _field(account, "charges_enabled"),
        "portal_configured": portal_configured,
        "available_plans": available_plans,
    }


def public_origin():
    origin = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise BillingError("PUBLIC_APP_URL must be the published HTTPS app origin.")
    return origin


def user_identity(user):
    """Return a non-reversible identity key for a real Google user."""
    user = user if isinstance(user, Mapping) else {}
    # Preview access is not a Google identity and must never create live
    # charges, even if a caller supplies a synthetic-looking user mapping.
    try:
        from auth import is_development_preview

        preview = is_development_preview()
    except Exception as exc:
        raise BillingError("Google sign-in could not be verified.") from exc
    provider = str(user.get("auth_provider", "")).lower()
    if (
        preview
        or provider in {"development", "preview", "synthetic"}
        or (provider and provider not in {"google", "google_oidc"})
        or str(user.get("sub", "")).lower() in {"development-preview", "preview"}
    ):
        raise BillingError(
            "Checkout is disabled in development preview. Development access remains unrestricted."
        )
    if (
        not user.get("is_logged_in")
        or not user.get("sub")
        or not user.get("email")
        or user.get("email_verified") is not True
    ):
        raise BillingError("Sign in with a verified Google account before opening billing.")
    return hashlib.sha256(("google:" + str(user["sub"])).encode()).hexdigest()


def _live_plan(plan: dict) -> None:
    if plan.get("mode") != "payment":
        raise BillingError("Only one-time Stripe payments are supported.")
    if not plan.get("livemode"):
        raise BillingError("The configured Stripe price is not live; no checkout was created.")


def _session_map(session: Any) -> dict:
    value = plain(session)
    return value if isinstance(value, Mapping) else {}


def _session_status(session: Mapping) -> str:
    return str(_field(session, "status", "") or "").lower()


def _session_owner_matches(session: Mapping, identity: str) -> bool:
    metadata = plain(_field(session, "metadata", {}))
    return (
        _field(session, "client_reference_id") == identity
        and _field(metadata, "app") == "soxlpro"
        and _field(metadata, "user_identity") == identity
    )


_PENDING_INTENT_STATUSES = {
    "processing",
    "requires_action",
    "requires_confirmation",
}


def _session_needs_confirmation(session: Mapping, identity: str) -> bool:
    """Whether a completed Checkout is still waiting on card confirmation."""
    if (
        not session
        or _session_status(session) != "complete"
        or not _session_owner_matches(session, identity)
        or _field(session, "mode") != "payment"
        or _field(session, "livemode") is not True
    ):
        return False
    if _field(session, "payment_status") != "paid":
        return True
    # A paid session that failed our local checks must be reconciled, never
    # discarded in favor of asking the customer to pay a second time.
    return True


def _mark_status(identity: str, session_id: str, status: str) -> None:
    _store_call(lambda: purchase_store.mark_status(identity, session_id, status))


def _is_resource_missing(exc: Exception) -> bool:
    """Only a Stripe 404-style resource_missing is a normal false result."""
    return getattr(exc, "code", None) == "resource_missing"


def _retrieve_session(session_id: str) -> dict | None:
    try:
        session = stripe_client().v1.checkout.sessions.retrieve(
            session_id,
            {
                "expand": [
                    "line_items.data.price",
                    "payment_intent.latest_charge",
                    "total_details.breakdown",
                ]
            },
        )
        return _session_map(session)
    except stripe.InvalidRequestError as exc:
        if _is_resource_missing(exc):
            # A missing return URL is an unpaid checkout, not access.
            return None
        raise BillingError("The Stripe checkout status could not be verified.") from exc
    except BillingError:
        raise
    except Exception as exc:
        raise BillingError("The Stripe checkout status could not be verified.") from exc


def _retrieve_payment_intent(value: Any) -> dict | None:
    if isinstance(value, str):
        try:
            value = stripe_client().v1.payment_intents.retrieve(
                value, {"expand": ["latest_charge"]}
            )
        except stripe.InvalidRequestError as exc:
            if _is_resource_missing(exc):
                return None
            raise BillingError("The Stripe payment could not be verified.") from exc
        except Exception as exc:
            raise BillingError("The Stripe payment could not be verified.") from exc
    result = plain(value)
    return result if isinstance(result, Mapping) else None


def _retrieve_charge(value: Any) -> dict | None:
    if isinstance(value, str):
        try:
            value = stripe_client().v1.charges.retrieve(value)
        except stripe.InvalidRequestError as exc:
            if _is_resource_missing(exc):
                return None
            raise BillingError("The Stripe charge could not be verified.") from exc
        except Exception as exc:
            raise BillingError("The Stripe charge could not be verified.") from exc
    result = plain(value)
    return result if isinstance(result, Mapping) else None


def _line_items(session: Mapping, session_id: str) -> list:
    existing = _field(session, "line_items")
    if existing is not None:
        items = _data(existing)
        if items:
            return items
    try:
        sessions = stripe_client().v1.checkout.sessions
        params = {"limit": 100, "expand": ["data.price"]}
        if hasattr(sessions, "line_items"):
            response = sessions.line_items.list(session_id, params)
        else:
            # Compatibility for older/newer generated SDK resource layouts.
            response = sessions.list_line_items(session_id, params)
    except stripe.InvalidRequestError as exc:
        if _is_resource_missing(exc):
            return []
        raise BillingError("The Stripe checkout items could not be verified.") from exc
    except Exception as exc:
        raise BillingError("The Stripe checkout items could not be verified.") from exc
    return _data(response)


def _line_item_matches(items: list, plan: dict) -> bool:
    if len(items) != 1:
        return False
    item = plain(items[0])
    quantity = _field(item, "quantity")
    if _as_int(quantity) != 1:
        return False
    actual_price = _field(item, "price")
    actual_id = actual_price if isinstance(actual_price, str) else _field(actual_price, "id")
    if actual_id != plan["price_id"]:
        return False
    actual_price = plain(actual_price)
    unit_amount = _field(actual_price, "unit_amount")
    if unit_amount is not None and _as_int(unit_amount) != plan["amount"]:
        return False
    currency = _field(actual_price, "currency")
    if currency is not None and str(currency).lower() != plan["currency"]:
        return False
    actual_subtotal = _field(item, "amount_subtotal")
    if actual_subtotal is not None and _as_int(actual_subtotal) != plan["amount"]:
        return False
    return True


def _tax_is_inclusive(items: list, details: Mapping) -> bool:
    """Find an explicit inclusive-tax signal in Stripe's expanded totals."""
    for item in items:
        price = plain(_field(plain(item), "price", {}))
        if _field(price, "tax_behavior") == "inclusive":
            return True
    breakdown = plain(_field(details, "breakdown", {}))
    for tax in _data(_field(breakdown, "taxes")):
        tax = plain(tax)
        if _field(tax, "inclusive") is True:
            return True
        rate = plain(_field(tax, "rate", {}))
        if (
            _field(rate, "inclusive") is True
            or _field(rate, "tax_behavior") == "inclusive"
        ):
            return True
    return False


def _session_total(session: Mapping, items: list, plan: dict) -> int | None:
    """Validate base subtotal, zero extras, and Managed Payments tax totals."""
    if _as_int(_field(session, "amount_subtotal", -1)) != plan["amount"]:
        return None
    details = plain(_field(session, "total_details", {}))
    if not details:
        return None
    discount = _as_int(_field(details, "amount_discount", 0), -1)
    shipping = _as_int(_field(details, "amount_shipping", 0), -1)
    tax = _as_int(_field(details, "amount_tax", -1), -1)
    if discount != 0 or shipping != 0 or tax < 0:
        return None

    # If Stripe provides a tax breakdown, its sum must be the authoritative
    # session amount_tax.  This also avoids accidentally adding an inclusive
    # tax twice.
    breakdown = plain(_field(details, "breakdown", {}))
    tax_rows = _field(breakdown, "taxes")
    if tax_rows is not None:
        rows = _data(tax_rows)
        tax_sum = 0
        for row in rows:
            row_amount = _as_int(_field(plain(row), "amount"), -1)
            if row_amount < 0:
                return None
            tax_sum += row_amount
        if tax_sum != tax:
            return None

    expected_total = plan["amount"] if _tax_is_inclusive(items, details) else plan["amount"] + tax
    actual_total = _as_int(_field(session, "amount_total", -1))
    return expected_total if actual_total == expected_total else None


def _charge_is_valid(charge: Mapping, expected_amount: int, currency: str) -> bool:
    # Fail closed: the current charge must explicitly be a live, paid charge
    # with complete amount/currency and clean refund/dispute state.
    if _field(charge, "livemode") is not True:
        return False
    if _field(charge, "paid") is not True:
        return False
    amount_refunded = _field(charge, "amount_refunded", 0)
    refunded_amount = _as_int(amount_refunded, -1)
    if (
        _field(charge, "refunded") is not False
        or _field(charge, "disputed") is not False
        or refunded_amount != 0
    ):
        return False
    if _as_int(_field(charge, "amount")) != expected_amount:
        return False
    return str(_field(charge, "currency", "")).lower() == currency


def verify_checkout(user, session_id) -> bool:
    """Verify one complete paid session and durably record it.

    Every ownership, amount, mode, line-item, and payment check is performed
    against Stripe.  Invalid or unpaid sessions return ``False``; provider or
    database failures raise :class:`BillingError`.
    """
    identity = user_identity(user)
    if not isinstance(session_id, str) or not session_id:
        return False
    plan = get_plan()
    record = _store_call(lambda: purchase_store.find_checkout(identity, session_id))
    if not record:
        return False
    if (
        record.get("user_identity_hash") != identity
        or record.get("price_id") != plan["price_id"]
        or _as_int(record.get("expected_amount", -1)) != plan["amount"]
        or str(record.get("expected_currency", "")).lower() != plan["currency"]
        or record.get("status") in {"cancelled", "failed", "revoked", "expired"}
    ):
        return False
    if not plan.get("livemode"):
        _mark_status(identity, session_id, "revoked")
        return False

    session = _retrieve_session(session_id)
    if not session:
        return False
    status = _session_status(session)
    if (
        not _session_owner_matches(session, identity)
        or _field(session, "mode") != "payment"
        or _field(session, "livemode") is not True
    ):
        _mark_status(identity, session_id, "revoked")
        return False
    if status != "complete":
        _mark_status(
            identity,
            session_id,
            "expired" if status == "expired" else "open" if status == "open" else "failed",
        )
        return False
    if _field(session, "payment_status") != "paid":
        # Checkout can be complete while a card confirmation is still
        # propagating.  Keep the durable attempt retryable so a later login
        # can observe the eventual succeeded PaymentIntent.
        _mark_status(identity, session_id, "pending")
        return False
    items = _line_items(session, session_id)
    expected_total = _session_total(session, items, plan)
    if (
        str(_field(session, "currency", "")).lower() != plan["currency"]
        or not _line_item_matches(items, plan)
        or expected_total is None
    ):
        _mark_status(identity, session_id, "review")
        return False

    payment_intent = _retrieve_payment_intent(_field(session, "payment_intent"))
    if not payment_intent:
        _mark_status(identity, session_id, "pending")
        return False
    payment_status = _field(payment_intent, "status")
    if payment_status != "succeeded":
        _mark_status(identity, session_id, "pending")
        return False
    if (
        _field(payment_intent, "livemode") is not True
        or _as_int(_field(payment_intent, "amount", -1)) != expected_total
        or str(_field(payment_intent, "currency", "")).lower() != plan["currency"]
    ):
        _mark_status(identity, session_id, "review")
        return False
    charge = _field(payment_intent, "latest_charge")
    if not charge:
        charges = _data(_field(payment_intent, "charges"))
        charge = charges[-1] if charges else None
    charge = _retrieve_charge(charge)
    if not charge or not _charge_is_valid(charge, expected_total, plan["currency"]):
        reversed_payment = bool(charge) and (
            _field(charge, "refunded") is True
            or _field(charge, "disputed") is True
            or _as_int(_field(charge, "amount_refunded"), 0) > 0
        )
        _mark_status(identity, session_id, "revoked" if reversed_payment else "review")
        return False

    _store_call(lambda: purchase_store.mark_paid(identity, session_id))
    return True


def _new_session_params(identity: str, attempt: dict, plan: dict) -> dict:
    origin = public_origin()
    return {
        "mode": "payment",
        "line_items": [{"price": plan["price_id"], "quantity": 1}],
        "success_url": origin + "/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": origin + "/?checkout=cancelled",
        "client_reference_id": identity,
        "metadata": {
            "app": "soxlpro",
            "user_identity": identity,
            "price_id": plan["price_id"],
            "attempt_id": attempt["attempt_id"],
        },
    }


def _reusable_open_session(identity: str, record: dict, plan: dict) -> bool:
    session_id = record.get("stripe_session_id")
    if not session_id:
        return False
    session = _retrieve_session(session_id)
    if not session:
        return False
    return (
        _session_status(session) == "open"
        and _field(session, "mode") == "payment"
        and _field(session, "livemode") is True
        and _session_owner_matches(session, identity)
        and record.get("price_id") == plan["price_id"]
        and record.get("checkout_url")
    )


def create_checkout(user) -> dict:
    """Create or reuse a card-only one-time Checkout session."""
    from auth import is_owner
    if is_owner(user):
        raise BillingError("Permanent owner access is already active. No payment is required.")
    identity = user_identity(user)
    plan = get_plan()
    _live_plan(plan)

    for _attempt_number in range(3):
        attempt = _store_call(
            lambda: purchase_store.reserve_checkout(
                identity, plan["price_id"], plan["amount"], plan["currency"]
            )
        )
        existing_id = attempt.get("stripe_session_id")
        if existing_id:
            if verify_checkout(user, existing_id):
                # A paid attempt is durably recognized; never create another
                # charge simply because the customer clicked Buy again.
                return {
                    "url": attempt.get("checkout_url", ""),
                    "session_id": existing_id,
                }
            existing_session = _retrieve_session(existing_id)
            if _session_needs_confirmation(existing_session, identity):
                _mark_status(
                    identity, existing_id,
                    "review" if _field(existing_session, "payment_status") == "paid" else "pending",
                )
                raise BillingError(
                    "Payment is still being confirmed. Please check again shortly; "
                    "do not pay again."
                )
            if _reusable_open_session(identity, attempt, plan):
                return {
                    "url": attempt["checkout_url"],
                    "session_id": existing_id,
                }
            _store_call(
                lambda: purchase_store.mark_status(identity, existing_id, "revoked")
            )
            continue

        params = _new_session_params(identity, attempt, plan)
        session = _provider_call(
            lambda: stripe_client().v1.checkout.sessions.create(
                params, {"idempotency_key": attempt["attempt_id"]}
            ),
            "The Stripe checkout could not be created.",
        )
        session = _session_map(session)
        session_id = _field(session, "id")
        checkout_url = _field(session, "url")
        if (
            not session_id
            or not checkout_url
            or _field(session, "mode") != "payment"
            or _field(session, "livemode") is not True
            or not _session_owner_matches(session, identity)
        ):
            raise BillingError("Stripe returned an invalid checkout session.")
        attached = _store_call(
            lambda: purchase_store.attach_session(
                attempt["attempt_id"], session_id, checkout_url
            )
        )
        return {
            "url": attached.get("checkout_url") or checkout_url,
            "session_id": attached.get("stripe_session_id") or session_id,
        }
    raise BillingError(
        "Checkout could not be prepared safely. Please retry shortly; no payment was taken."
    )


def get_paid_access(user) -> bool:
    """Refresh this user's stored one-time purchases and return access state."""
    from auth import is_owner
    if is_owner(user):
        return True
    identity = user_identity(user)
    plan = get_plan()
    if not plan.get("livemode"):
        return False
    records = _store_call(
        lambda: purchase_store.list_checkouts(identity, plan["price_id"])
    )
    for record in records:
        if (
            record.get("user_identity_hash") != identity
            or record.get("price_id") != plan["price_id"]
            or record.get("status") in {"cancelled", "failed", "revoked", "expired"}
            or not record.get("stripe_session_id")
        ):
            continue
        if verify_checkout(user, record["stripe_session_id"]):
            return True
    return False


if __name__ == "__main__":
    import json

    try:
        print(json.dumps(configuration_report()))
    except Exception as exc:
        # Do not echo provider exception strings: some include credentials.
        print(json.dumps({"error": type(exc).__name__, "code": getattr(exc, "code", None)}))