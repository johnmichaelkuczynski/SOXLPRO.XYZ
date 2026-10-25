---
name: Options projection assumptions
description: Reuse the SOXL model, but distinguish conditional scenarios from validated options probabilities.
---

Options projections reuse the chart's historical log-return model. They are
conditional pricing scenarios, not a proven extension of SOXL signal accuracy.

**Why:** Correct SOXL forecasts alone do not determine pre-expiry option prices;
future implied volatility and execution spreads remain uncertain. The user
requested a selectable-contract popup showing value/P&L through expiration.

**How to apply:** Keep model limitations explicit. Never label simulated
percentiles guaranteed maximum/minimum prices or validated odds. Do not
silently replace missing bid/ask, IV or underlying observations with invented
data. Validate account entitlements with real responses, not just secret metadata.
