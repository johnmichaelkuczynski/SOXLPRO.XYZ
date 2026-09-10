"""Direct Stripe billing with the owner's environment keys; no connector."""
import hashlib
import os
from urllib.parse import urlsplit

import stripe


class BillingError(RuntimeError):
    pass


def stripe_client():
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise BillingError("STRIPE_SECRET_KEY is missing from the server configuration.")
    return stripe.StripeClient(key, max_network_retries=2)


def configured_price_id():
    price_id = os.environ.get("STRIPE_PRICE_ID", "")
    if not price_id.startswith("price_"):
        raise BillingError("STRIPE_PRICE_ID must identify an existing price in your Stripe account.")
    return price_id


def plain(resource):
    return resource.to_dict() if hasattr(resource, "to_dict") else dict(resource)


def get_plan():
    price = plain(stripe_client().v1.prices.retrieve(
        configured_price_id(), {"expand": ["product"]}
    ))
    product = price.get("product", {})
    if not price.get("active") or not product.get("active"):
        raise BillingError("The configured Stripe price or product is inactive.")
    if not price.get("recurring") or price.get("unit_amount") is None:
        raise BillingError("The configured price must be a fixed recurring subscription price.")
    if price.get("billing_scheme") != "per_unit" or price["recurring"].get("usage_type") != "licensed":
        raise BillingError("This checkout requires a fixed, non-metered subscription price.")
    return {
        "name": product.get("name", "SOXL subscription"),
        "amount": price["unit_amount"],
        "currency": price["currency"],
        "interval": price["recurring"]["interval"],
        "interval_count": price["recurring"]["interval_count"],
        "livemode": price["livemode"],
    }


def configuration_report():
    """Read-only provider check; returned fields contain no keys/customer data."""
    account = plain(stripe_client().v1.accounts.retrieve_current())
    balance = plain(stripe_client().v1.balance.retrieve())
    try:
        plan = get_plan()
    except stripe.InvalidRequestError as exc:
        plan = {"error": exc.code}
    prices = stripe_client().v1.prices.list({"active": True, "type": "recurring", "limit": 10, "expand": ["data.product"]})
    portals = stripe_client().v1.billing_portal.configurations.list({"active": True, "limit": 1})
    return {"plan": plan, "livemode": balance["livemode"], "charges_enabled": account.get("charges_enabled"),
            "portal_configured": bool(portals.data),
            "available_plans": [
                {"name": p.product.name, "amount": p.unit_amount, "currency": p.currency,
                 "recurring": plain(p.recurring), "livemode": p.livemode}
                for p in prices.data
            ]}


def public_origin():
    origin = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise BillingError("PUBLIC_APP_URL must be the published HTTPS app origin.")
    return origin


def user_identity(user):
    # Preview access is not a Google identity and must never create live charges.
    from auth import is_development_preview
    if is_development_preview() or user.get("auth_provider") == "development":
        raise BillingError("Checkout is disabled in development preview. Development access remains unrestricted.")
    if not user.get("is_logged_in") or not user.get("sub") or not user.get("email_verified"):
        raise BillingError("Sign in with Google before opening billing.")
    return hashlib.sha256(("google:" + str(user["sub"])).encode()).hexdigest()


if __name__ == "__main__":
    import json
    try:
        print(json.dumps(configuration_report()))
    except Exception as exc:
        # Do not echo provider exception strings: some include credentials.
        print(json.dumps({"error": type(exc).__name__, "code": getattr(exc, "code", None)}))