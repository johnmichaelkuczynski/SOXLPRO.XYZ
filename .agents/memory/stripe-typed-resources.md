---
name: Stripe typed resources
description: Compatibility rule for the installed stripe-python SDK.
---

Treat responses from live Stripe API resource methods as typed Stripe objects,
not dictionaries. Convert at the response boundary before dictionary-style
access.

**Why:** The installed SDK deliberately raises AttributeError for `.get()` on
typed resources, which can silently break checkout or webhook paths missed by
dict-based unit fixtures.

**How to apply:** Convert API resources through their supported dictionary
conversion method, and keep a regression test around Checkout URL extraction.