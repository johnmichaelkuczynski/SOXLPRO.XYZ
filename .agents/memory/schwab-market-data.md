---
name: Schwab market-data ownership
description: Owner's Schwab app configuration and portability constraints
---

Use the owner's Schwab developer app credentials directly for market data,
without making the Coolify deployment depend on a Replit connector. Do not add
trading or account-changing behavior as part of this integration.

**Why:** The user supplied their own Schwab keys and is moving the app to
Coolify. Market-data access does not authorize placing trades.

**How to apply:** Keep owner authorization separate from public app access.
The user confirmed the developer app's registered callback is
`https://soxl.ai/auth/schwab/callback`; do not substitute a preview callback.
Account authorization must be completed by the owner on that domain, after
the integration is deployed there. Saved client keys alone are not proof of
working market-data access.

SOXL's current price must use Schwab only, via
`GET /marketdata/v1/quotes?symbols=SOXL&fields=quote,extended`.
During extended hours use `extended.lastPrice` with `extended.tradeTime`;
otherwise use `quote.lastPrice` with `quote.tradeTime`. Label it “Schwab” with
Schwab's own observation timestamp. On request failure show an error, never
another provider or a historical-price substitute.

**Why:** The user explicitly rejected Yahoo Finance and all fallback sources for
SOXL's current price.

**How to apply:** Preserve historical analysis and benchmark functionality, but
never reuse an old saved quote to conceal a failed current Schwab request.
