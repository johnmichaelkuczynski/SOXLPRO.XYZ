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
