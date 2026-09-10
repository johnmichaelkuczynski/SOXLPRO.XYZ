---
name: Deployment environment detection
description: Reliable distinction between Replit workspace previews and published deployments.
---

Use `REPLIT_DEPLOYMENT=1` as the authoritative signal that code is running in a published Replit deployment. Do not infer production from `REPLIT_CONTAINER`.

**Why:** A published VM can report `REPLIT_CONTAINER=repl`, which caused a development authentication bypass to activate on the public site.

**How to apply:** Any security boundary or production-only behavior must check `REPLIT_DEPLOYMENT`. A workspace-only bypass may additionally require `REPLIT_DEV_DOMAIN` when the deployment flag is absent.

Google sign-in must return to the same origin where login starts. Preview and
published origins need separate authorized OAuth callback entries.

**Why:** A real browser sign-in reached Google's `redirect_uri_mismatch` because
the preview callback was not authorized. Substituting the production callback
would not fix preview login: OAuth state and cookies belong to the initiating
origin. Do not claim a real Google session to hide this error.

**How to apply:** Verify provider authorization in addition to the local button.
Report missing Google Cloud allowlist entries as owner configuration blockers;
never store or expose credentials while diagnosing them.

Automatically sign in with a clearly identified development-only identity in
the workspace preview; never require Google login there.

**Why:** The user explicitly requires uninterrupted access while developing
and authorized preview-only automatic sign-in. This is not a Google identity.

**How to apply:** Keep the bypass server-controlled and disabled on published
deployments even if workspace markers remain. Preserve real Google login on
the published site; do not infer a production login requirement from this
preview-only request.