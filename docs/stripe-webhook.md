# Stripe webhook

Endpoint: `POST /api/stripe/webhook`

The public Tornado gateway registers this before its proxy/catch-all route.
It verifies `Stripe-Signature` with `STRIPE_WEBHOOK_SECRET` against untouched
request bytes (five-minute signature tolerance). There is no JSON middleware.
Missing/invalid signatures receive 400; missing configuration or failed durable
storage receive 503. Accepted events receive 200 after the database commit.

Subscribe the Stripe endpoint to:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

The supervised `stripe_webhook.py` worker handles queued events separately.
Event IDs deduplicate deliveries; processing and completion are transactional.
Failures remain queued with a 60-second retry and a non-sensitive error class.
The worker uses row locks to avoid processing the same event concurrently.

## Account linkage and access

Checkout must carry `metadata.app=soxlpro`, `metadata.user_identity` equal to
the existing server-generated Google identity hash, and a matching
`client_reference_id`. Its line items must contain `STRIPE_PRICE_ID`.
Never use email matching or accept a caller-supplied identity without signing in.
The worker retrieves the Checkout Session directly from Stripe to validate it.
Unlinked events never grant access. Test-mode events are acknowledged but cannot
change live access.

Subscription IDs and customer IDs are persisted. Only subscriptions linked by
a verified app checkout can grant access, with `active` or `trialing` status.
Other statuses remove subscription access. Deleted subscriptions cannot be
reactivated by delayed events. Updates fetch current Stripe subscription state.
Unlinked subscription events can arrive before checkout and are retained.
Failed invoices set `payment_failed` on the customer account for review; this
flag does not independently revoke access or automatically clear.

Existing verified one-time purchases and the owner's permanent access remain
valid independently. The account header caches access for up to 60 seconds.
Existing sessions refresh that status on their next app rerun, or via Refresh.

## Publishing

The new tables are defined in `stripe_webhook.SCHEMA` and applied to the
development database. Publish must include the corresponding database schema
changes. No schema creation runs at app startup.

The current checkout still uses the existing one-time price and payment mode.
Switching the purchase offer to subscriptions is separate work: checkout mode,
recurring price validation, purchase-return verification and labels must change
together. Merely changing a price in Stripe does not make that transition safe.

After publishing, an unsigned POST should return 400, not 200. Use Stripe's
signed delivery tooling to verify accepted events. Do not fabricate signed
live purchase events against real customer records.

## Checks

`WEBHOOK_DB_TEST=1 python -m pytest tests/test_stripe_webhook.py`

Database tests use synthetic identities and IDs, mocked provider responses, and
clean up their rows. Run only against the development database.
