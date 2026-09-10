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

Put sign-in/sign-out and Buy at the top of the page in normal document flow,
not in a fixed, floating, or sticky bar.

**Why:** The user explicitly said these controls are used rarely and should
not clutter the screen while scrolling.

**How to apply:** Keep them above the market snapshot and let them scroll away
normally. Do not interpret "at the top" as "always visible."

Respect the owner's existing Stripe Managed Payments configuration.

**Why:** Real Checkout requests revealed that Managed Payments is enabled by
default. It rejects explicit payment_method_types and requires an eligible tax
category on the existing product; a valid API key and price alone do not prove
checkout readiness.

**How to apply:** Verify actual session creation without submitting payment.
Do not disable Managed Payments, even per-session, or edit product tax settings
without permission. Preserve Stripe's tax calculation when validating totals;
base price and final charge can differ because of tax.