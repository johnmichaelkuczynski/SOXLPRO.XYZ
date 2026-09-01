---
name: Transformed proxy responses
description: Cache and compression rules for safely rewriting HTML in a reverse proxy.
---

When a proxy rewrites an upstream HTML body, force the upstream response to use identity encoding and remove stale validators such as ETag and Last-Modified from the rewritten response.

**Why:** Decoding compressed bytes as HTML corrupts the document, while forwarding validators computed for the original body can make browsers reuse a previously corrupted or stale transformed document.

**How to apply:** For any body-transforming route, suppress upstream conditional request headers, request `Accept-Encoding: identity`, recalculate `Content-Length`, and issue cache headers appropriate for the generated body. Byte-for-byte tunnel routes can preserve upstream compression and validators.