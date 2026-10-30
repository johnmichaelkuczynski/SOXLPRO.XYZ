---
name: Options projection assumptions
description: Reuse the SOXL model, but distinguish conditional scenarios from validated options probabilities.
---

Options projections reuse the chart's historical log-return model. They are
conditional pricing scenarios, not a proven extension of SOXL signal accuracy.

The user is not willing to pay for Options Advanced now and wants to hone the
existing functionality instead.

**Why:** The user explicitly declined the paid upgrade.

**How to apply:** Do not resume upgrade requests or paid-data acquisition unless
the user changes that decision; keep historical accuracy claims unvalidated.

**Why:** Correct SOXL forecasts alone do not determine pre-expiry option prices;
future implied volatility and execution spreads remain uncertain. The user
requested a selectable-contract popup showing value/P&L through expiration.

**How to apply:** Keep model limitations explicit. Never label simulated
percentiles guaranteed maximum/minimum prices or validated odds. Do not
silently replace missing bid/ask, IV or underlying observations with invented
data. Validate account entitlements with real responses, not just secret metadata.

Treat American-versus-European comparisons using provider IV as pricing
sensitivity, not independent validation.

**Why:** Provider IV may already be inverted from European prices, making
midpoint residual comparisons circular. Continuous dividend yield also misses
discrete ex-dividend exercise incentives.

**How to apply:** Retain unvalidated labels until historical execution outcomes
and independently specified American/dividend assumptions have been assessed;
passing software tests is not empirical accuracy evidence.

Do not infer historical quote access from an empty contract catalog response.

**Why:** Combining a historical `as_of` with `expired=true` returned no
contracts, while the same historical lookup without the expired filter found a
contract. Only the subsequent historical quotes request established denial.

**How to apply:** Discover a real contract as of the study date, then probe its
historical bid/ask endpoint. Distinguish empty results from explicit access denial;
recheck access rather than assuming a past subscription status is permanent.
