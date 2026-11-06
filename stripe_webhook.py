"""Raw-body Stripe receiver and durable, retryable event processor.

No provider requests run in the receiver. A 200 means the signed event is
committed to PostgreSQL, not merely placed in process memory.
"""
import asyncio
import json
import logging
import os
import re
import time

import stripe
import tornado.web
from psycopg2.extras import RealDictCursor

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS billing_webhook_events (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS billing_webhook_accounts (
    customer_id TEXT PRIMARY KEY,
    user_identity_hash TEXT,
    payment_failed BOOLEAN NOT NULL DEFAULT false,
    failure_event_created BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS billing_webhook_identity_idx
ON billing_webhook_accounts(user_identity_hash);
CREATE TABLE IF NOT EXISTS billing_webhook_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    event_created BIGINT NOT NULL,
    deleted BOOLEAN NOT NULL DEFAULT false,
    checkout_verified BOOLEAN NOT NULL DEFAULT false
);
"""
EVENTS = {
    "checkout.session.completed", "customer.subscription.updated",
    "customer.subscription.deleted", "invoice.payment_failed",
}


def persist_event(event):
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '2000ms'")
            cur.execute(
                "INSERT INTO billing_webhook_events(id,payload) VALUES (%s,%s::jsonb) "
                "ON CONFLICT(id) DO NOTHING", (event["id"], json.dumps(event)),
            )
    finally:
        conn.close()


class StripeWebhook(tornado.web.RequestHandler):
    def check_xsrf_cookie(self):
        # Authentication is Stripe's timestamped signature, not a browser cookie.
        pass

    async def post(self):
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not secret:
            self.set_status(503)
            self.finish({"error": "Webhook signing is not configured"})
            return
        try:
            event = stripe.Webhook.construct_event(
                self.request.body, self.request.headers.get("Stripe-Signature", ""),
                secret, tolerance=300,
            )
        except (ValueError, stripe.SignatureVerificationError):
            self.set_status(400)
            self.finish({"error": "Invalid Stripe signature or payload"})
            return
        if event["type"] not in EVENTS:
            self.finish({"received": True})
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(persist_event, event.to_dict()), 3)
        except Exception as exc:
            # Stripe retries non-2xx deliveries. Never acknowledge lost events.
            logging.error("Stripe webhook persistence unavailable (%s)", type(exc).__name__)
            self.set_status(503)
            self.finish({"error": "Please retry delivery"})
            return
        self.finish({"received": True})


def object_id(value):
    return value.get("id") if isinstance(value, dict) else value


def plain(value):
    return value.to_dict() if hasattr(value, "to_dict") else value


def sync_subscription(cur, obj, created, deleted=False):
    cur.execute(
        """INSERT INTO billing_webhook_subscriptions
        (subscription_id,customer_id,status,event_created,deleted)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(subscription_id) DO UPDATE SET
        status=EXCLUDED.status,event_created=EXCLUDED.event_created,
        deleted=EXCLUDED.deleted
        WHERE NOT billing_webhook_subscriptions.deleted
        AND (EXCLUDED.deleted OR
             EXCLUDED.event_created >= billing_webhook_subscriptions.event_created)""",
        (obj["id"], object_id(obj["customer"]),
         "canceled" if deleted else obj["status"], created, deleted),
    )


def process_event(cur, event, client):
    obj = event["data"]["object"]
    kind, created = event["type"], event["created"]
    # Test-mode deliveries must never grant/revoke real app entitlements.
    if event.get("livemode") is not True:
        return
    if kind == "checkout.session.completed":
        session = plain(client.v1.checkout.sessions.retrieve(
            obj["id"], {"expand": ["line_items", "subscription"]}
        ))
        meta = session.get("metadata") or {}
        identity = meta.get("user_identity")
        if meta.get("app") != "soxlpro":
            return
        if not identity or not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("Missing app identity")
        if session.get("client_reference_id") != identity:
            raise ValueError("Checkout identity mismatch")
        if session.get("livemode") is not True:
            raise ValueError("Checkout is not live")
        items = (session.get("line_items") or {}).get("data", [])
        if not any(object_id(i.get("price")) == os.environ.get("STRIPE_PRICE_ID")
                   for i in items):
            raise ValueError("Checkout price mismatch")
        customer = object_id(session.get("customer"))
        if session.get("status") != "complete":
            raise ValueError("Checkout incomplete")
        if session.get("mode") == "payment":
            # Preserve the existing, stricter one-time purchase verifier.
            if session.get("payment_status") != "paid":
                raise ValueError("Checkout unpaid")
            cur.execute(
                "UPDATE purchase_checkouts SET status='paid', paid_at=now(),updated_at=now() "
                "WHERE stripe_session_id=%s AND user_identity_hash=%s",
                (session["id"], identity),
            )
        elif session.get("mode") != "subscription":
            return
        if not customer:
            if session.get("mode") == "subscription":
                raise ValueError("Missing customer")
            return
        cur.execute(
            """INSERT INTO billing_webhook_accounts(customer_id,user_identity_hash)
            VALUES (%s,%s) ON CONFLICT(customer_id) DO UPDATE
            SET user_identity_hash=EXCLUDED.user_identity_hash
            WHERE billing_webhook_accounts.user_identity_hash IS NULL
            OR billing_webhook_accounts.user_identity_hash=EXCLUDED.user_identity_hash
            RETURNING customer_id""", (customer, identity),
        )
        if not cur.fetchone():
            raise ValueError("Customer identity conflict")
        subscription = session.get("subscription")
        if subscription:
            if isinstance(subscription, str):
                subscription = plain(client.v1.subscriptions.retrieve(subscription))
            sync_subscription(cur, subscription, created)
            cur.execute(
                "UPDATE billing_webhook_subscriptions SET checkout_verified=true "
                "WHERE subscription_id=%s AND customer_id=%s",
                (subscription["id"], customer),
            )
    elif kind in {"customer.subscription.updated", "customer.subscription.deleted"}:
        deleted = kind.endswith(".deleted")
        # Read canonical state, so delayed deliveries don't restore obsolete access.
        subscription = obj if deleted else plain(client.v1.subscriptions.retrieve(obj["id"]))
        sync_subscription(cur, subscription, created, deleted)
    elif kind == "invoice.payment_failed":
        customer = object_id(obj.get("customer"))
        if not customer:
            raise ValueError("Missing invoice customer")
        cur.execute(
            """INSERT INTO billing_webhook_accounts
            (customer_id,payment_failed,failure_event_created) VALUES (%s,true,%s)
            ON CONFLICT(customer_id) DO UPDATE SET payment_failed=true,
            failure_event_created=EXCLUDED.failure_event_created
            WHERE EXCLUDED.failure_event_created >=
            billing_webhook_accounts.failure_event_created""", (customer, created),
        )


def subscription_access(identity):
    """True only for linked, active subscriptions; never inferred from email."""
    conn = db.get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT EXISTS (
                SELECT 1 FROM billing_webhook_accounts a
                JOIN billing_webhook_subscriptions s USING(customer_id)
                WHERE a.user_identity_hash=%s AND NOT s.deleted
                AND s.checkout_verified
                AND s.status IN ('active','trialing'))""", (identity,),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def process_one(client):
    conn = db.get_conn()
    event_id = None
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id,payload FROM billing_webhook_events
                WHERE processed_at IS NULL AND next_attempt_at <= now()
                ORDER BY received_at FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            row = cur.fetchone()
            if not row:
                return False
            event_id = row["id"]
            process_event(cur, row["payload"], client)
            cur.execute(
                "UPDATE billing_webhook_events SET processed_at=now(),last_error=NULL "
                "WHERE id=%s", (event_id,),
            )
        return True
    except Exception as exc:
        conn.rollback()
        if event_id:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE billing_webhook_events SET attempts=attempts+1,
                    last_error=%s,next_attempt_at=now()+interval '60 seconds'
                    WHERE id=%s""", (type(exc).__name__, event_id),
                )
        logging.error("Stripe event processing failed (%s)", type(exc).__name__)
        return False
    finally:
        conn.close()


def main():
    api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not api_key:
        print("Stripe event worker disabled: STRIPE_SECRET_KEY is not configured.", flush=True)
        return
    if not os.environ.get("DATABASE_URL"):
        print("Stripe event worker disabled: DATABASE_URL is not configured.", flush=True)
        return
    client = stripe.StripeClient(
        api_key, max_network_retries=2,
        http_client=stripe.RequestsClient(timeout=10),
    )
    print("Stripe webhook event worker started", flush=True)
    while True:
        try:
            if process_one(client):
                continue
        except Exception as exc:
            logging.error("Stripe event worker unavailable (%s)", type(exc).__name__)
        time.sleep(2)


if __name__ == "__main__":
    main()
