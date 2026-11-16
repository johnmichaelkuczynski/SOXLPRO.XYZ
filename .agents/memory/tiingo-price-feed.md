---
name: Tiingo price-feed choice
description: Active SOXL quote provider and the account's reference-price entitlement.
---

Use the owner's Tiingo key for the current SOXL quote in the headline, chart
and market summary. Do not silently replace a failed quote with a daily close.
Existing historical-data and options providers remain separate.

**Why:** The user explicitly requested immediate use of Tiingo after removing
the prior stock-quote provider's credentials.

**How to apply:** Keep the quote's actual provider and observation timestamp
throughout the display and background-update paths.

Tiingo IEX can return null `last` and `lastSaleTimestamp` while `tngoLast` and
`timestamp` contain a valid current reference price.

**Why:** This account returned precisely that successful response; Tiingo's
documentation distinguishes entitlement-only exchange trades from reference prices.

**How to apply:** Accept the documented timestamped reference price, retain its
reference classification, and never describe it as an executed exchange trade.
