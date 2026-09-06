---
name: SOXLPRO authentication
description: Authentication provider and environment boundary for the public SOXLPRO app.
---

Use Streamlit's native Google OIDC with the project's Google web-client
credentials. Require authentication on published deployments and use a
development identity only in workspace previews.

**Why:** Direct Google OIDC satisfies the requested login with the credentials
already configured, while a workspace-only bypass keeps development possible.
The deployment flag must remain authoritative so the public site can never
inherit the bypass.

**How to apply:** Keep the public callback at
`https://soxlpro.xyz/oauth2callback`, derive app identity from the verified OIDC
session, and use `REPLIT_DEPLOYMENT=1` to enforce the production boundary.