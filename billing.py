"""Live Stripe billing and durable SOXLPRO access records."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import psycopg2


ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
_AUTH_USER_ID = re.compile(r"^google_[0-9]{8,64}$")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _connect():
    database_url = _database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for access control")
    if "sslmode=" not in database_url:
        database_url += ("&" if "?" in database_url else "?") + "sslmode=require"
    return psycopg2.connect(database_url, connect_timeout=8)


def valid_auth_user_id(user_id: str | None) -> bool:
    return bool(user_id and _AUTH_USER_ID.fullmatch(user_id))


def stripe_live_configured() -> bool:
    return (
        os.environ.get("STRIPE_PUBLISHABLE_KEY", "").startswith("pk_live_")
        and os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_")
        and os.environ.get("STRIPE_WEBHOOK_SECRET", "").startswith("whsec_")
        and os.environ.get("STRIPE_PRICE_ID", "").startswith("price_")
    )


def _stripe_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return converter()
    raise TypeError("Unexpected Stripe response type")


def signed_in_actions(user_id: str) -> int:
    """Return the server-maintained free-action count for a Google user."""
    if not valid_auth_user_id(user_id):
        raise ValueError("Invalid Google user ID")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_access (clerk_user_id)
                VALUES (%s)
                ON CONFLICT (clerk_user_id) DO UPDATE
                SET updated_at = user_access.updated_at
                RETURNING signed_in_free_actions
                """,
                (user_id,),
            )
            return int(cursor.fetchone()[0])


def anonymous_usage(visitor_id: str) -> tuple[int, int]:
    """Return server-maintained (actions, elapsed_seconds) for a visitor."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anonymous_access (visitor_id)
                VALUES (%s)
                ON CONFLICT (visitor_id) DO UPDATE
                SET updated_at = anonymous_access.updated_at
                RETURNING free_actions,
                    GREATEST(
                        0,
                        EXTRACT(EPOCH FROM (NOW() - first_seen))::INTEGER
                    )
                """,
                (visitor_id,),
            )
            row = cursor.fetchone()
    return int(row[0]), int(row[1])


def consume_usage_action(
    *,
    user_id: str | None = None,
    visitor_id: str | None = None,
    user_limit: int,
    visitor_limit: int,
) -> tuple[bool, int]:
    """Atomically reserve one free action if the principal is below its limit."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            if user_id:
                if not valid_auth_user_id(user_id):
                    raise ValueError("Invalid Google user ID")
                cursor.execute(
                    """
                    INSERT INTO user_access (clerk_user_id)
                    VALUES (%s)
                    ON CONFLICT (clerk_user_id) DO NOTHING
                    """,
                    (user_id,),
                )
                cursor.execute(
                    """
                    UPDATE user_access
                    SET signed_in_free_actions = signed_in_free_actions + 1,
                        updated_at = NOW()
                    WHERE clerk_user_id = %s
                      AND signed_in_free_actions < %s
                    RETURNING signed_in_free_actions
                    """,
                    (user_id, user_limit),
                )
            elif visitor_id:
                cursor.execute(
                    """
                    INSERT INTO anonymous_access (visitor_id)
                    VALUES (%s)
                    ON CONFLICT (visitor_id) DO NOTHING
                    """,
                    (visitor_id,),
                )
                cursor.execute(
                    """
                    UPDATE anonymous_access
                    SET free_actions = free_actions + 1,
                        updated_at = NOW()
                    WHERE visitor_id = %s
                      AND free_actions < %s
                    RETURNING free_actions
                    """,
                    (visitor_id, visitor_limit),
                )
            else:
                raise ValueError("A usage principal is required")
            row = cursor.fetchone()
            if row:
                return True, int(row[0])
            if user_id:
                cursor.execute(
                    "SELECT signed_in_free_actions FROM user_access "
                    "WHERE clerk_user_id = %s",
                    (user_id,),
                )
            else:
                cursor.execute(
                    "SELECT free_actions FROM anonymous_access WHERE visitor_id = %s",
                    (visitor_id,),
                )
            return False, int(cursor.fetchone()[0])


def _subscription_price_id(subscription: Any) -> str | None:
    subscription = _stripe_dict(subscription)
    items = subscription.get("items", {}).get("data", [])
    for item in items:
        price = item.get("price") or {}
        price_id = price.get("id")
        if price_id == os.environ.get("STRIPE_PRICE_ID"):
            return price_id
    return None


def _period_end(subscription: Any) -> datetime | None:
    subscription = _stripe_dict(subscription)
    value = subscription.get("current_period_end")
    if value:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    return None


def persist_subscription(
    user_id: str,
    *,
    customer_id: str | None,
    subscription_id: str | None,
    status: str | None,
    price_id: str | None,
    current_period_end: datetime | None = None,
    event_created: int | None = None,
) -> None:
    if not valid_auth_user_id(user_id):
        raise ValueError("Invalid Google user ID")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_access (
                    clerk_user_id, stripe_customer_id, stripe_subscription_id,
                    subscription_status, subscription_price_id,
                    current_period_end, last_stripe_event_created, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (clerk_user_id) DO UPDATE
                SET stripe_customer_id = COALESCE(
                        EXCLUDED.stripe_customer_id,
                        user_access.stripe_customer_id
                    ),
                    stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                    subscription_status = EXCLUDED.subscription_status,
                    subscription_price_id = EXCLUDED.subscription_price_id,
                    current_period_end = EXCLUDED.current_period_end,
                    last_stripe_event_created = COALESCE(
                        EXCLUDED.last_stripe_event_created,
                        user_access.last_stripe_event_created
                    ),
                    updated_at = NOW()
                WHERE EXCLUDED.last_stripe_event_created IS NULL
                   OR user_access.last_stripe_event_created IS NULL
                   OR EXCLUDED.last_stripe_event_created >=
                        user_access.last_stripe_event_created
                """,
                (
                    user_id,
                    customer_id,
                    subscription_id,
                    status,
                    price_id,
                    current_period_end,
                    event_created,
                ),
            )


def _persist_subscription_cursor(
    cursor,
    user_id: str,
    *,
    customer_id: str | None,
    subscription_id: str | None,
    status: str | None,
    price_id: str | None,
    current_period_end: datetime | None,
    event_created: int,
) -> None:
    if not valid_auth_user_id(user_id):
        raise ValueError("Invalid Google user ID")
    cursor.execute(
        """
        INSERT INTO user_access (
            clerk_user_id, stripe_customer_id, stripe_subscription_id,
            subscription_status, subscription_price_id, current_period_end,
            last_stripe_event_created, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (clerk_user_id) DO UPDATE
        SET stripe_customer_id = COALESCE(
                EXCLUDED.stripe_customer_id, user_access.stripe_customer_id
            ),
            stripe_subscription_id = EXCLUDED.stripe_subscription_id,
            subscription_status = EXCLUDED.subscription_status,
            subscription_price_id = EXCLUDED.subscription_price_id,
            current_period_end = EXCLUDED.current_period_end,
            last_stripe_event_created = EXCLUDED.last_stripe_event_created,
            updated_at = NOW()
        WHERE user_access.last_stripe_event_created IS NULL
           OR EXCLUDED.last_stripe_event_created >=
                user_access.last_stripe_event_created
        """,
        (
            user_id,
            customer_id,
            subscription_id,
            status,
            price_id,
            current_period_end,
            event_created,
        ),
    )


def get_access_record(user_id: str) -> dict | None:
    if not valid_auth_user_id(user_id):
        return None
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT signed_in_free_actions, stripe_customer_id,
                       stripe_subscription_id, subscription_status,
                       subscription_price_id, current_period_end
                FROM user_access
                WHERE clerk_user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return {
        "signed_in_free_actions": int(row[0]),
        "stripe_customer_id": row[1],
        "stripe_subscription_id": row[2],
        "subscription_status": row[3],
        "subscription_price_id": row[4],
        "current_period_end": row[5],
    }


def paid_from_record(record: dict | None) -> bool:
    return bool(
        record
        and record.get("subscription_status") in ACTIVE_SUBSCRIPTION_STATUSES
        and record.get("subscription_price_id") == os.environ.get("STRIPE_PRICE_ID")
    )


def _stripe():
    if not stripe_live_configured():
        raise RuntimeError("Live Stripe is not configured")
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def _customer_for_user(stripe, user_id: str) -> str:
    record = get_access_record(user_id)
    if record and record.get("stripe_customer_id"):
        return record["stripe_customer_id"]

    matches = stripe.Customer.search(
        query=f"metadata['auth_user_id']:'{user_id}'",
        limit=1,
    )
    customer_id = (
        matches.data[0].id
        if matches.data
        else stripe.Customer.create(metadata={"auth_user_id": user_id}).id
    )
    persist_subscription(
        user_id,
        customer_id=customer_id,
        subscription_id=None,
        status=None,
        price_id=None,
    )
    return customer_id


def create_checkout_url(user_id: str, base_url: str) -> str:
    if not valid_auth_user_id(user_id):
        raise ValueError("Invalid Google user ID")
    stripe = _stripe()
    customer_id = _customer_for_user(stripe, user_id)
    session = _stripe_dict(stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        customer=customer_id,
        client_reference_id=user_id,
        metadata={"auth_user_id": user_id},
        subscription_data={"metadata": {"auth_user_id": user_id}},
        success_url=f"{base_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/?checkout=cancelled",
        allow_promotion_codes=True,
    ))
    if not session.get("livemode"):
        raise RuntimeError("Stripe returned a non-live Checkout session")
    return session["url"]


def create_portal_url(user_id: str, base_url: str) -> str:
    if not valid_auth_user_id(user_id):
        raise ValueError("Invalid Google user ID")
    stripe = _stripe()
    customer_id = _customer_for_user(stripe, user_id)
    session = _stripe_dict(stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base_url}/",
    ))
    return session["url"]


def refresh_live_subscription(user_id: str) -> bool:
    """Refresh durable entitlement directly from live Stripe."""
    if not valid_auth_user_id(user_id):
        return False
    stripe = _stripe()
    customer_id = _customer_for_user(stripe, user_id)
    subscriptions = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=100,
        expand=["data.items.data.price"],
    )
    matching = None
    for subscription in subscriptions.auto_paging_iter():
        subscription = _stripe_dict(subscription)
        if not subscription.get("livemode"):
            continue
        if _subscription_price_id(subscription):
            matching = subscription
            if subscription.get("status") in ACTIVE_SUBSCRIPTION_STATUSES:
                break

    if matching is None:
        persist_subscription(
            user_id,
            customer_id=customer_id,
            subscription_id=None,
            status=None,
            price_id=None,
        )
        return False

    persist_subscription(
        user_id,
        customer_id=customer_id,
        subscription_id=matching.get("id"),
        status=matching.get("status"),
        price_id=_subscription_price_id(matching),
        current_period_end=_period_end(matching),
    )
    return matching.get("status") in ACTIVE_SUBSCRIPTION_STATUSES


def verify_checkout_return(user_id: str, session_id: str) -> bool:
    if not valid_auth_user_id(user_id) or not session_id.startswith("cs_live_"):
        return False
    stripe = _stripe()
    session = _stripe_dict(stripe.checkout.Session.retrieve(session_id))
    valid = (
        session.get("livemode") is True
        and session.get("client_reference_id") == user_id
        and session.get("status") == "complete"
        and session.get("payment_status") in {"paid", "no_payment_required"}
    )
    return refresh_live_subscription(user_id) if valid else False


def process_stripe_webhook(payload: bytes, signature: str) -> str:
    """Verify and persist one live Stripe webhook event. Returns its event ID."""
    stripe = _stripe()
    event = _stripe_dict(stripe.Webhook.construct_event(
        payload,
        signature,
        os.environ["STRIPE_WEBHOOK_SECRET"],
    ))
    if not event.get("livemode"):
        raise ValueError("Test-mode Stripe events are not accepted")

    event_id = event["id"]
    event_created = int(event["created"])
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO stripe_webhook_events (
                    event_id, event_type, event_created
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (event_id, event["type"], event_created),
            )
            if cursor.fetchone() is None:
                return event_id

            event_type = event["type"]
            obj = event["data"]["object"]
            if event_type == "checkout.session.completed":
                user_id = obj.get("client_reference_id") or obj.get(
                    "metadata", {}
                ).get("auth_user_id")
                subscription_id = obj.get("subscription")
                if valid_auth_user_id(user_id) and subscription_id:
                    subscription = _stripe_dict(stripe.Subscription.retrieve(
                        subscription_id,
                        expand=["items.data.price"],
                    ))
                    _persist_subscription_cursor(
                        cursor,
                        user_id,
                        customer_id=obj.get("customer"),
                        subscription_id=subscription.get("id"),
                        status=subscription.get("status"),
                        price_id=_subscription_price_id(subscription),
                        current_period_end=_period_end(subscription),
                        event_created=event_created,
                    )
            elif event_type.startswith("customer.subscription."):
                # Stripe event timestamps are second-resolution and deliveries
                # can be out of order. Persist Stripe's current resource state,
                # not the potentially stale event snapshot.
                try:
                    current_subscription = _stripe_dict(stripe.Subscription.retrieve(
                        obj.get("id"),
                        expand=["items.data.price"],
                    ))
                except Exception:
                    if event_type == "customer.subscription.deleted":
                        current_subscription = obj
                    else:
                        raise
                user_id = (
                    current_subscription.get("metadata", {}).get("auth_user_id")
                    or current_subscription.get("metadata", {}).get("clerk_user_id")
                )
                if not valid_auth_user_id(user_id):
                    cursor.execute(
                        "SELECT clerk_user_id FROM user_access "
                        "WHERE stripe_customer_id = %s",
                        (obj.get("customer"),),
                    )
                    row = cursor.fetchone()
                    user_id = row[0] if row else None
                if valid_auth_user_id(user_id):
                    _persist_subscription_cursor(
                        cursor,
                        user_id,
                        customer_id=current_subscription.get("customer"),
                        subscription_id=current_subscription.get("id"),
                        status=current_subscription.get("status"),
                        price_id=_subscription_price_id(current_subscription),
                        current_period_end=_period_end(current_subscription),
                        event_created=event_created,
                    )
    return event_id