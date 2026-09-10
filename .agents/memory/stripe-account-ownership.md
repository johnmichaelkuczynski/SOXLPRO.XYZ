---
name: Stripe account ownership
description: Use the owner's Stripe keys directly without changing account settings, products, or prices.
---

Use only the owner's Stripe credentials stored in project Secrets. Do not
attach a Replit-managed Stripe connection, provision another account, or
substitute sandbox credentials.

**Why:** The user explicitly rejected the managed connection and required
their own Stripe keys. Provider readiness must be checked with real requests,
not inferred from the presence of environment variables.

**How to apply:** Keep credentials server-side and use existing account
configuration. Do not create or modify Stripe products, prices, portal settings,
or account settings. If required configuration is missing, report the exact
blocker instead of proposing to create it. App-initiated checkout/payment
operations must use the owner's credentials, never a managed connection.