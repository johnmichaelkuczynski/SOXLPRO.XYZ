---
name: SOXLPRO authentication
description: Authentication provider and environment boundary for the public SOXLPRO app.
---

Use direct Google OAuth through the localhost-bound Streamlit gateway. Require
authentication on published deployments and use a development identity only in
workspace previews.

**Why:** The project's Google client approves `/auth/google/callback` on both
public domains but rejects Streamlit's native `/oauth2callback`. The gateway
validates Google ID tokens and signed HTTP-only sessions before forwarding
identity to Streamlit. A workspace-only bypass keeps development possible.

**How to apply:** Keep `/auth/google/callback` as the OAuth callback. Bind the
internal Streamlit process to localhost, trust only gateway-injected identity,
and use `REPLIT_DEPLOYMENT=1` to enforce the production boundary.