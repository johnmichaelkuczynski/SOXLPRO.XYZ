---
name: Deployment environment detection
description: Reliable distinction between Replit workspace previews and published deployments.
---

Use `REPLIT_DEPLOYMENT=1` as the authoritative signal that code is running in a published Replit deployment. Do not infer production from `REPLIT_CONTAINER`.

**Why:** A published VM can report `REPLIT_CONTAINER=repl`, which caused a development authentication bypass to activate on the public site.

**How to apply:** Any security boundary or production-only behavior must check `REPLIT_DEPLOYMENT`. A workspace-only bypass may additionally require `REPLIT_DEV_DOMAIN` when the deployment flag is absent.