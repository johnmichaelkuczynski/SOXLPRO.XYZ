"""Webhook HTTP security and real PostgreSQL transaction tests using synthetic IDs."""
import hashlib
import hmac
import json
import os
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

import stripe_webhook as wh


class ReceiverTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r"/api/stripe/webhook", wh.StripeWebhook)])

    def send(self, body, signature=None):
        return self.fetch("/api/stripe/webhook", method="POST", body=body,
                          headers={"Stripe-Signature": signature or ""})

    def signature(self, body, timestamp=None):
        stamp = str(timestamp or int(time.time()))
        sig = hmac.new(b"whsec_unit_test", stamp.encode() + b"." + body,
                       hashlib.sha256).hexdigest()
        return f"t={stamp},v1={sig}"

    @patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_unit_test"})
    def test_raw_signature_duplicates_invalid_and_expired(self):
        body = b'{ "id":"evt_test", "type":"checkout.session.completed", "data":{} }'
        with patch.object(wh, "persist_event") as save:
            self.assertEqual(self.send(body, self.signature(body)).code, 200)
            self.assertEqual(self.send(body, self.signature(body)).code, 200)
            self.assertEqual(save.call_count, 2)
            self.assertEqual(self.send(body + b" ", self.signature(body)).code, 400)
            self.assertEqual(self.send(body).code, 400)
            self.assertEqual(self.send(body, self.signature(body, int(time.time())-600)).code, 400)

    @patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_unit_test"})
    def test_persistence_failure_is_retryable(self):
        body = b'{"id":"evt_test","type":"invoice.payment_failed","data":{}}'
        with patch.object(wh, "persist_event", side_effect=RuntimeError):
            self.assertEqual(self.send(body, self.signature(body)).code, 503)

    @patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_unit_test"})
    def test_unhandled_acknowledged_and_get_rejected(self):
        body = b'{"id":"evt_test","type":"unhandled","data":{}}'
        with patch.object(wh, "persist_event") as save:
            self.assertEqual(self.send(body, self.signature(body)).code, 200)
            save.assert_not_called()
        self.assertEqual(self.fetch("/api/stripe/webhook").code, 405)


@unittest.skipUnless(os.environ.get("WEBHOOK_DB_TEST") == "1", "explicit dev DB test only")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tag = "webhook_test_" + uuid.uuid4().hex
        self.identity = hashlib.sha256(self.tag.encode()).hexdigest()
        self.customer, self.sub = self.tag + "_cus", self.tag + "_sub"
        self.subscription = {"id": self.sub, "customer": self.customer, "status": "active"}
        self.session = {
            "id": self.tag + "_cs", "customer": self.customer, "mode": "subscription",
            "livemode": True,
            "status": "complete", "client_reference_id": self.identity,
            "metadata": {"app": "soxlpro", "user_identity": self.identity},
            "line_items": {"data": [{"price": {"id": "price_unit_test"}}]},
            "subscription": self.subscription,
        }
        self.client = SimpleNamespace(v1=SimpleNamespace(
            checkout=SimpleNamespace(sessions=SimpleNamespace(retrieve=lambda *a: self.session)),
            subscriptions=SimpleNamespace(retrieve=lambda *a: self.subscription),
        ))
        self.conn = wh.db.get_conn()
        self.env = patch.dict(os.environ, {"STRIPE_PRICE_ID": "price_unit_test"})
        self.env.start()

    def tearDown(self):
        self.conn.rollback()
        with self.conn, self.conn.cursor() as cur:
            cur.execute("DELETE FROM billing_webhook_accounts WHERE customer_id=%s", (self.customer,))
            cur.execute("DELETE FROM billing_webhook_subscriptions WHERE customer_id=%s", (self.customer,))
            cur.execute("DELETE FROM billing_webhook_events WHERE id=%s", (self.tag,))
        self.conn.close()
        self.env.stop()

    def event(self, kind, obj, created=100):
        return {"id": self.tag, "type": kind, "created": created,
                "livemode": True, "data": {"object": obj}}

    def apply(self, kind, obj=None, created=100):
        with self.conn, self.conn.cursor() as cur:
            wh.process_event(cur, self.event(kind, obj or self.session, created), self.client)

    def test_checkout_grants_status_revokes_failure_flags_and_deletion_sticks(self):
        self.apply("checkout.session.completed")
        self.assertTrue(wh.subscription_access(self.identity))
        self.subscription["status"] = "past_due"
        self.apply("customer.subscription.updated", self.subscription, 110)
        self.assertFalse(wh.subscription_access(self.identity))
        self.apply("invoice.payment_failed", {"customer": self.customer}, 111)
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SELECT payment_failed FROM billing_webhook_accounts WHERE customer_id=%s",
                        (self.customer,))
            self.assertTrue(cur.fetchone()[0])
        self.subscription["status"] = "active"
        self.apply("customer.subscription.updated", self.subscription, 120)
        self.assertTrue(wh.subscription_access(self.identity))
        self.apply("customer.subscription.deleted", self.subscription, 130)
        self.apply("customer.subscription.updated", self.subscription, 125)
        self.apply("checkout.session.completed", created=100)
        self.assertFalse(wh.subscription_access(self.identity))

    def test_out_of_order_and_duplicate_delivery(self):
        self.apply("customer.subscription.deleted", self.subscription, 130)
        self.apply("checkout.session.completed")
        self.assertFalse(wh.subscription_access(self.identity))
        event = self.event("invoice.payment_failed", {"customer": self.customer})
        wh.persist_event(event)
        wh.persist_event(event)
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM billing_webhook_events WHERE id=%s", (self.tag,))
            self.assertEqual(cur.fetchone()[0], 1)

    def test_unsigned_identity_and_unrelated_subscription_cannot_grant(self):
        self.apply("customer.subscription.updated", self.subscription)
        self.assertFalse(wh.subscription_access(self.identity))
        self.session["client_reference_id"] = "wrong"
        with self.assertRaises(ValueError):
            self.apply("checkout.session.completed")
        self.assertFalse(wh.subscription_access(self.identity))

    def test_test_mode_cannot_grant(self):
        event = self.event("checkout.session.completed", self.session)
        event["livemode"] = False
        with self.conn, self.conn.cursor() as cur:
            wh.process_event(cur, event, self.client)
        self.assertFalse(wh.subscription_access(self.identity))

    def test_queue_worker_commits_access_and_records_completion(self):
        wh.persist_event(self.event("checkout.session.completed", self.session))
        self.assertTrue(wh.process_one(self.client))
        self.assertTrue(wh.subscription_access(self.identity))
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SELECT processed_at FROM billing_webhook_events WHERE id=%s",
                        (self.tag,))
            self.assertIsNotNone(cur.fetchone()[0])

    def test_queue_failure_rolls_back_and_retains_event_for_retry(self):
        self.session["client_reference_id"] = "wrong"
        wh.persist_event(self.event("checkout.session.completed", self.session))
        self.assertFalse(wh.process_one(self.client))
        self.assertFalse(wh.subscription_access(self.identity))
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SELECT processed_at,attempts,last_error FROM billing_webhook_events WHERE id=%s",
                        (self.tag,))
            self.assertEqual(cur.fetchone(), (None, 1, "ValueError"))
