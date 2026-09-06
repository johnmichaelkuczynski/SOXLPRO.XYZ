---
name: SOXLPRO authentication provider
description: The confirmed authentication provider and identity boundary for SOXLPRO.
---

SOXLPRO must use direct Google OAuth with the project's Google web-client
credentials. Do not introduce Clerk or Replit login.

**Why:** The user explicitly rejected those substitutes and configured Google
OAuth origins and callbacks for both the Replit app domain and soxlpro.xyz.

**How to apply:** Keep OAuth code, signed sessions, and identity verification in
the public gateway. Stripe checkout must require the gateway-verified Google
identity, while the Subscribe control remains visible to signed-out visitors.